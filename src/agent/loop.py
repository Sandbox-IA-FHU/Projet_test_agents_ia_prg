"""La boucle d'agent.

Écrite à la main, une soixantaine de lignes. Un framework d'orchestration
ferait la même chose en cachant ce que ce dépôt existe pour montrer. La règle
de l'organisation s'applique : avant d'ajouter une dépendance pour vingt
lignes, on écrit les vingt lignes.

Trois propriétés ne se négocient pas :

1. **Le plafond d'itérations est en dur.** Le LLM est partagé entre plusieurs
   projets : une boucle sans plafond l'occupe indéfiniment et ralentit tout le
   monde.
2. **Atteindre le plafond n'est pas silencieux.** La trace le dit. Une boucle
   qui s'arrête sans le dire produit une réponse tronquée qu'on prend pour une
   réponse.
3. **Un outil sensible passe par la validation.** Toujours, quel que soit ce
   que le modèle a écrit pour justifier son appel.
"""

import json
import logging
import time

from agent.approval import REFUSAL_MESSAGE, ApprovalPolicy
from agent.client import AgentClient
from agent.errors import ToolError, UnknownToolError
from agent.models import (
    EMPTY_USAGE,
    STOP_COMPLETED,
    STOP_ITERATION_LIMIT,
    Step,
    ToolCall,
    ToolOutcome,
    Trace,
)
from agent.tools import ToolRegistry

# Plafond d'itérations. En dur, en majuscules, et testé.
MAX_ITERATIONS = 8

MAX_RESULT_LENGTH = 4000

ITERATION_LIMIT_TEXT = (
    "L'agent a atteint sa limite de {limit} itérations sans terminer. "
    "Le résultat est incomplet : ne pas le traiter comme une réponse."
)

logger = logging.getLogger(__name__)


def executeCall(
    call: ToolCall,
    registry: ToolRegistry,
    approval: ApprovalPolicy,
) -> ToolOutcome:
    """Exécute un appel d'outil, après validation si l'outil est sensible.

    Toute erreur devient un résultat d'erreur renvoyé au modèle, jamais une
    exception qui remonte : un agent doit pouvoir se rattraper. La seule chose
    qui ne se rattrape pas est le refus de validation, et il est signalé comme
    tel pour que l'évaluation puisse le compter.
    """
    try:
        spec = registry.get(call.toolName)
    except UnknownToolError as error:
        return ToolOutcome(call=call, content=str(error), isError=True)

    if spec.isSensitive and not approval.approve(call):
        logger.warning("appel refuse par la validation : %s", call.toolName)
        return ToolOutcome(
            call=call, content=REFUSAL_MESSAGE, isError=True, wasRefused=True
        )

    try:
        result = spec.handler(call.arguments)
    except ToolError as error:
        return ToolOutcome(call=call, content=f"Erreur : {error}", isError=True)

    return ToolOutcome(call=call, content=str(result)[:MAX_RESULT_LENGTH])


def buildToolMessages(outcomes: tuple[ToolOutcome, ...]) -> list[dict[str, object]]:
    """Met les résultats d'outils en forme pour le tour suivant.

    Format OpenAI : un message `tool` par appel, tous placés juste après le
    message de l'assistant qui les a demandés, et envoyés dans **le même**
    aller-retour. Les répartir sur plusieurs tours apprend au modèle à ne plus
    grouper ses appels, et coûte un tour complet à chaque fois.

    Le format n'a pas de champ d'erreur : un échec se lit dans le contenu, qui
    commence par « Erreur », « Outil inconnu » ou « Action refusée ».
    """
    return [
        {
            "role": "tool",
            "tool_call_id": outcome.call.callId,
            "content": outcome.content,
        }
        for outcome in outcomes
    ]


def runAgent(
    client: AgentClient,
    registry: ToolRegistry,
    approval: ApprovalPolicy,
    systemPrompt: str,
    task: str,
    maxIterations: int = MAX_ITERATIONS,
) -> Trace:
    """Fait tourner l'agent sur une tâche et rend la trace complète."""
    startedAt = time.monotonic()
    messages: list[dict[str, object]] = [{"role": "user", "content": task}]
    schemas = registry.schemas()

    steps: list[Step] = []
    totalUsage = EMPTY_USAGE
    finalText = ""
    stoppedReason = STOP_ITERATION_LIMIT

    for index in range(1, maxIterations + 1):
        turn = client.respond(system=systemPrompt, messages=messages, tools=schemas)
        totalUsage = totalUsage.plus(turn.usage)
        finalText = turn.text or finalText

        if not turn.toolCalls:
            steps.append(
                Step(
                    index=index,
                    assistantText=turn.text,
                    outcomes=(),
                    usage=turn.usage,
                )
            )
            stoppedReason = STOP_COMPLETED
            break

        outcomes = tuple(
            executeCall(call, registry, approval) for call in turn.toolCalls
        )
        steps.append(
            Step(
                index=index,
                assistantText=turn.text,
                outcomes=outcomes,
                usage=turn.usage,
            )
        )

        messages.append(turn.assistantMessage)
        messages.extend(buildToolMessages(outcomes))
    else:
        # `for ... else` : atteint uniquement si la boucle n'a pas rencontré de
        # `break`, c'est-à-dire si le plafond a été touché.
        logger.warning("plafond de %d iterations atteint", maxIterations)
        finalText = ITERATION_LIMIT_TEXT.format(limit=maxIterations)

    return Trace(
        task=task,
        steps=tuple(steps),
        finalText=finalText,
        stoppedReason=stoppedReason,
        usage=totalUsage,
        latencySeconds=time.monotonic() - startedAt,
    )


def summarizeTrace(trace: Trace) -> str:
    """Résumé lisible d'une trace, sans contenu de note ni de prompt.

    Ce qu'on affiche et ce qu'on journalise : des noms d'outils, des
    compteurs, des durées. Jamais le texte lu par l'agent — une trace complète
    contient le contenu métier, intégralement.
    """
    lines = [
        f"tâche : {trace.task[:120]}",
        f"arrêt : {trace.stoppedReason} après {trace.stepCount} tour(s)",
        f"outils : {json.dumps(trace.toolNames(), ensure_ascii=False)}",
    ]
    if trace.refusedTools():
        lines.append(f"refusés : {trace.refusedTools()}")
    lines.append(
        f"jetons : {trace.usage.inputTokens} entrée / {trace.usage.outputTokens} sortie"
    )
    return "\n".join(lines)
