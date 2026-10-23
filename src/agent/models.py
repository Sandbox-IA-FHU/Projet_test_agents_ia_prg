"""Structures de données de la boucle d'agent.

Aucune logique, aucun effet de bord. La `Trace` est la structure centrale :
c'est elle qu'on relit pour comprendre ce que l'agent a fait, et elle qu'on
mesure.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Usage:
    """Jetons consommés. Entrée et sortie comptées séparément."""

    inputTokens: int
    outputTokens: int

    def plus(self, other: "Usage") -> "Usage":
        """Additionne deux consommations."""
        return Usage(
            inputTokens=self.inputTokens + other.inputTokens,
            outputTokens=self.outputTokens + other.outputTokens,
        )


EMPTY_USAGE = Usage(inputTokens=0, outputTokens=0)


@dataclass(frozen=True)
class ToolCall:
    """Un appel d'outil demandé par le modèle."""

    callId: str
    toolName: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolOutcome:
    """Le résultat d'un appel d'outil, tel qu'il est renvoyé au modèle.

    `isError` remonte au modèle : un outil qui échoue doit le dire plutôt que
    de rendre une chaîne vide, sinon le modèle réessaie à l'identique.

    `wasRefused` distingue l'échec technique du **refus de validation**. Les
    deux produisent un résultat d'erreur pour le modèle, mais seul le second
    est une décision humaine, et c'est celui qu'on compte en évaluation.
    """

    call: ToolCall
    content: str
    isError: bool = False
    wasRefused: bool = False


@dataclass(frozen=True)
class Step:
    """Un tour de boucle : ce que le modèle a dit, ce qu'il a appelé."""

    index: int
    assistantText: str
    outcomes: tuple[ToolOutcome, ...]
    usage: Usage


# Raisons d'arrêt possibles. `limite_iterations` n'est pas une réussite :
# c'est une réponse tronquée qu'on prendrait pour une réponse.
STOP_COMPLETED = "termine"
STOP_ITERATION_LIMIT = "limite_iterations"
STOP_TOOL_ERROR = "erreur_outil"


@dataclass(frozen=True)
class Trace:
    """Le déroulé complet d'une exécution.

    Une trace ne contient jamais le contenu des documents lus ni le texte des
    prompts : elle contient des noms d'outils, des compteurs et des extraits
    courts destinés à l'humain qui relit. Les traces ne sont pas commitées.
    """

    task: str
    steps: tuple[Step, ...]
    finalText: str
    stoppedReason: str
    usage: Usage
    latencySeconds: float

    @property
    def stepCount(self) -> int:
        """Nombre de tours de boucle effectués."""
        return len(self.steps)

    def toolNames(self) -> list[str]:
        """Noms des outils appelés, dans l'ordre, doublons compris."""
        return [
            outcome.call.toolName for step in self.steps for outcome in step.outcomes
        ]

    def refusedTools(self) -> list[str]:
        """Outils dont l'exécution a été refusée par la politique de validation."""
        return [
            outcome.call.toolName
            for step in self.steps
            for outcome in step.outcomes
            if outcome.wasRefused
        ]


@dataclass
class ToolSpec:
    """Définition d'un outil exposé au modèle.

    `isSensitive` marque une action irréversible ou coûteuse. Un outil sensible
    ne s'exécute jamais sans passer par la politique de validation.
    """

    name: str
    description: str
    inputSchema: dict[str, object]
    handler: object
    isSensitive: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
