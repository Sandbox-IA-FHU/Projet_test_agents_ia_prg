"""Accès au LLM local, par son API compatible OpenAI.

Seul module qui connaît le SDK. La boucle ne manipule que le protocole
`AgentClient` — c'est ce qui permet aux tests de rejouer des scénarios
d'agent complets, avec plusieurs tours et des appels d'outils, sans réseau et
sans serveur.

La réflexion du modèle (`reasoning_content`) n'entre jamais dans un
`ModelTurn` : ni dans le texte, ni dans le message renvoyé au tour suivant, ni
donc dans la trace. Elle n'est pas la réponse, et elle contient tout ce que le
modèle a lu.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

import openai
from openai.types.chat import ChatCompletion

from agent.errors import ModelCallError
from agent.models import ToolCall, Usage

# Avec la réflexion, le serveur recommande au moins 4 000 jetons de sortie :
# en dessous, la réponse peut être coupée pendant la réflexion, avec un
# contenu vide.
MAX_OUTPUT_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 120.0
MAX_RETRIES = 2

# Niveau de réflexion. `low` est le défaut du serveur et le meilleur réglage
# mesuré à ce jour sur un autre usage du même modèle ; pour un agent, `off`
# contre `low` reste à mesurer sur le jeu d'évaluation
# (scripts/evaluate.py --reflexion).
REASONING_OFF = "off"
REASONING_EFFORTS = (REASONING_OFF, "low", "medium", "xhigh")
REASONING_EFFORT = "low"

# Sans réflexion, échantillonnage recommandé pour ce modèle. Avec réflexion,
# on garde les réglages par défaut du serveur.
NO_REASONING_SAMPLING = {"temperature": 0.7, "top_p": 0.8}

# Le LLM local n'a pas de clé aujourd'hui. Le SDK en exige une non vide : on
# envoie une valeur factice, qui n'est pas un secret.
PLACEHOLDER_API_KEY = "aucune-cle"

FINISH_STOP = "stop"
FINISH_TOOL_CALLS = "tool_calls"
FINISH_LENGTH = "length"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelTurn:
    """Un tour de modèle, réduit à ce dont la boucle a besoin.

    `assistantMessage` est ajouté tel quel à l'historique du tour suivant. Il
    reprend les arguments d'outils tels que le modèle les a écrits, sans les
    réécrire, et ne contient jamais la réflexion.
    """

    text: str
    toolCalls: tuple[ToolCall, ...]
    assistantMessage: dict[str, object]
    usage: Usage
    finishReason: str


class AgentClient(Protocol):
    """Ce que la boucle attend d'un client. Rien de plus."""

    def respond(
        self,
        system: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ModelTurn:
        """Un tour : consignes, historique, outils disponibles."""
        ...


def buildRequestOptions(reasoningEffort: str) -> dict[str, object]:
    """Paramètres de requête qui dépendent du niveau de réflexion.

    Le serveur lit la réflexion dans `chat_template_kwargs`. Le paramètre
    `reasoning_effort` de premier niveau du SDK est celui d'un autre
    fournisseur : le serveur local l'ignorerait.
    """
    if reasoningEffort not in REASONING_EFFORTS:
        raise ModelCallError(
            f"Niveau de réflexion {reasoningEffort!r} inconnu, "
            f"attendu l'un de {REASONING_EFFORTS}."
        )
    if reasoningEffort == REASONING_OFF:
        return {
            **NO_REASONING_SAMPLING,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
    return {
        "extra_body": {"chat_template_kwargs": {"reasoning_effort": reasoningEffort}}
    }


def _parseArguments(rawArguments: str, toolName: str) -> dict[str, object]:
    """Décode les arguments d'un appel d'outil.

    Des arguments illisibles ne tuent pas la boucle : l'outil reçoit un
    dictionnaire vide et son message d'erreur dira au modèle quoi corriger.
    """
    try:
        arguments = json.loads(rawArguments or "{}")
    except json.JSONDecodeError:
        logger.warning("arguments illisibles pour l'outil %s", toolName)
        return {}
    return arguments if isinstance(arguments, dict) else {}


def turnFromResponse(response: ChatCompletion) -> ModelTurn:
    """Réduit une réponse de l'API à un `ModelTurn`, sans la réflexion."""
    choice = response.choices[0]
    message = choice.message
    finishReason = choice.finish_reason or FINISH_STOP

    if finishReason == FINISH_LENGTH:
        raise ModelCallError(
            "Réponse coupée par la limite de jetons de sortie, probablement "
            "pendant la réflexion. Augmenter MAX_OUTPUT_TOKENS ou baisser le "
            "niveau de réflexion."
        )
    if response.usage is None:
        raise ModelCallError("Le serveur n'a pas renvoyé de compte de jetons.")

    text = message.content or ""
    rawCalls = [call for call in message.tool_calls or [] if call.type == "function"]
    toolCalls = tuple(
        ToolCall(
            callId=call.id,
            toolName=call.function.name,
            arguments=_parseArguments(call.function.arguments, call.function.name),
        )
        for call in rawCalls
    )

    assistantMessage: dict[str, object] = {"role": "assistant", "content": text}
    if rawCalls:
        assistantMessage["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in rawCalls
        ]

    return ModelTurn(
        text=text,
        toolCalls=toolCalls,
        assistantMessage=assistantMessage,
        usage=Usage(
            inputTokens=response.usage.prompt_tokens,
            outputTokens=response.usage.completion_tokens,
        ),
        finishReason=finishReason,
    )


@contextmanager
def _translateErrors() -> Iterator[None]:
    """Transforme les erreurs du SDK en `ModelCallError` qui disent quoi faire.

    Les messages ne reprennent jamais le corps de la réponse du serveur : il
    peut contenir des morceaux de la requête.
    """
    try:
        yield
    except openai.AuthenticationError as error:
        raise ModelCallError(
            "Authentification refusée. Vérifier LLM_API_KEY."
        ) from error
    except openai.NotFoundError as error:
        raise ModelCallError(
            "Adresse ou modèle inconnu (HTTP 404). Vérifier LLM_MODEL, et que "
            "LLM_BASE_URL se termine par /v1."
        ) from error
    except openai.RateLimitError as error:
        raise ModelCallError(
            "Serveur LLM saturé (HTTP 429). Il est partagé : réessayer plus tard."
        ) from error
    except openai.APIStatusError as error:
        raise ModelCallError(
            f"Appel au LLM refusé (HTTP {error.status_code})."
        ) from error
    except openai.APIConnectionError as error:
        raise ModelCallError(
            "LLM injoignable ou trop lent à répondre. Vérifier LLM_BASE_URL."
        ) from error


class OpenAICompatibleClient:
    """Implémentation réelle, pour le LLM local compatible OpenAI."""

    def __init__(
        self,
        baseUrl: str,
        model: str,
        apiKey: str = "",
        reasoningEffort: str = REASONING_EFFORT,
        maxOutputTokens: int = MAX_OUTPUT_TOKENS,
        timeoutSeconds: float = REQUEST_TIMEOUT_SECONDS,
        maxRetries: int = MAX_RETRIES,
    ) -> None:
        # Délai et réessais explicites. Le SDK réessaie déjà : on ne rajoute
        # jamais une boucle de réessai maison par-dessus, elles se multiplient.
        self._client = openai.OpenAI(
            base_url=baseUrl,
            api_key=apiKey or PLACEHOLDER_API_KEY,
            timeout=timeoutSeconds,
            max_retries=maxRetries,
        )
        self._requestOptions = buildRequestOptions(reasoningEffort)
        self.model = model
        self.reasoningEffort = reasoningEffort
        self.maxOutputTokens = maxOutputTokens

    def respond(
        self,
        system: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ModelTurn:
        """Appelle le modèle et rend le tour normalisé."""
        with _translateErrors():
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                tools=tools,
                max_tokens=self.maxOutputTokens,
                **self._requestOptions,
            )
        turn = turnFromResponse(response)

        logger.info(
            "tour modele model=%s reflexion=%s arret=%s outils=%d "
            "jetons_entree=%d jetons_sortie=%d",
            self.model,
            self.reasoningEffort,
            turn.finishReason,
            len(turn.toolCalls),
            turn.usage.inputTokens,
            turn.usage.outputTokens,
        )
        return turn

    def servedModel(self) -> str:
        """Modèle réel derrière le nom exposé, tel que le serveur le déclare.

        Le nom exposé est stable alors que le modèle peut changer : un fichier
        de run consigne les deux, sinon deux runs sur deux modèles différents
        auraient l'air comparables.
        """
        with _translateErrors():
            models = list(self._client.models.list())
        for served in models:
            if served.id == self.model:
                return str(getattr(served, "root", None) or served.id)
        raise ModelCallError(
            f"Le serveur n'expose pas {self.model!r}. Vérifier LLM_MODEL."
        )
