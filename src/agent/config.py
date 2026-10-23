"""Configuration du projet.

Seul module du dépôt qui lit `os.environ`. Partout ailleurs, la configuration
arrive en argument — c'est ce qui rend le reste testable sans serveur.
"""

import os
from dataclasses import dataclass

from agent.errors import ConfigError

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
DEFAULT_LOG_LEVEL = "INFO"

# Politiques de validation des outils sensibles. Le défaut est le refus :
# une valeur par défaut permissive finit par être utilisée sans y penser.
APPROVAL_DENY = "refus"
APPROVAL_CONSOLE = "console"
VALID_APPROVAL_MODES = (APPROVAL_DENY, APPROVAL_CONSOLE)
DEFAULT_APPROVAL_MODE = APPROVAL_DENY

ENV_FILE_HINT = (
    "Copier .env.example en .env, le renseigner, puis lancer avec "
    "uv run --env-file .env ... (ou docker compose run, qui lit .env)."
)


@dataclass(frozen=True)
class Config:
    """Configuration validée. Construite uniquement par `loadConfig`.

    `apiKey` peut être vide : le LLM local n'en demande pas aujourd'hui, mais
    une passerelle avec une clé par personne pourra venir sans toucher au code.
    `modelRevision` peut être vide pour un essai, jamais pour une évaluation.
    """

    baseUrl: str
    model: str
    apiKey: str
    modelRevision: str
    logLevel: str
    approvalMode: str


def _requireVariable(name: str, hint: str) -> str:
    """Lit une variable obligatoire, ou échoue en disant quoi faire."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} est absente ou vide. {hint} {ENV_FILE_HINT}")
    return value


def loadConfig() -> Config:
    """Lit la configuration depuis l'environnement et la valide.

    Échoue immédiatement si elle est incomplète, avec un message qui dit quoi
    faire.
    """
    baseUrl = _requireVariable(
        "LLM_BASE_URL", "L'adresse du LLM est fournie par Florian (responsable)."
    )
    if not baseUrl.startswith(("http://", "https://")):
        raise ConfigError(
            "LLM_BASE_URL doit commencer par http:// ou https:// et se terminer "
            "par /v1, par exemple http://<adresse-du-serveur-llm>:8000/v1."
        )

    model = _requireVariable("LLM_MODEL", "Valeur attendue : altoneo-llm.")

    logLevel = os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    if logLevel not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"LOG_LEVEL vaut {logLevel!r}, attendu l'un de {VALID_LOG_LEVELS}."
        )

    approvalMode = os.environ.get("APPROBATION", DEFAULT_APPROVAL_MODE).strip().lower()
    if approvalMode not in VALID_APPROVAL_MODES:
        raise ConfigError(
            f"APPROBATION vaut {approvalMode!r}, attendu l'un de "
            f"{VALID_APPROVAL_MODES}."
        )

    return Config(
        baseUrl=baseUrl,
        model=model,
        apiKey=os.environ.get("LLM_API_KEY", "").strip(),
        modelRevision=os.environ.get("LLM_MODEL_REVISION", "").strip(),
        logLevel=logLevel,
        approvalMode=approvalMode,
    )
