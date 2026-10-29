"""Validation humaine des actions sensibles.

Un modèle produit une action plausible, pas une action sûre. La règle de
l'organisation est explicite : aucune action irréversible ne se déclenche à
partir d'un contenu récupéré sans validation humaine.

Ce module est petit exprès. Ce qui compte n'est pas son code, c'est que le
chemin d'exécution d'un outil sensible **passe forcément par lui** — voir
`loop.executeCall`, et le test `test_sensitiveToolNeedsApproval`.
"""

import logging
from typing import Protocol

from agent.models import ToolCall

logger = logging.getLogger(__name__)


class ApprovalPolicy(Protocol):
    """Décide si un appel d'outil sensible peut s'exécuter."""

    def approve(self, call: ToolCall) -> bool:
        """Rend True si l'action est autorisée."""
        ...


class DenyAll:
    """Refuse toute action sensible. Politique par défaut.

    C'est la politique de l'évaluation : un jeu d'évaluation ne doit jamais
    pouvoir déclencher une action réelle, et un run qui attend une réponse
    humaine ne se termine pas.
    """

    def approve(self, call: ToolCall) -> bool:
        """Refuse, et journalise le nom de l'outil."""
        logger.warning("action sensible refusee par defaut : %s", call.toolName)
        return False


class AllowAll:
    """Autorise tout. **Réservé aux tests.**

    Aucun script du dépôt ne la construit : elle n'existe que pour vérifier le
    chemin autorisé sans intervention humaine.
    """

    def approve(self, call: ToolCall) -> bool:
        """Autorise systématiquement."""
        return True


class ConsoleApproval:
    """Demande la validation en ligne de commande.

    Affiche l'outil et ses arguments, puis attend une réponse. Tout ce qui
    n'est pas exactement `oui` vaut refus : sur une action irréversible, un
    appui sur Entrée ne doit pas valoir accord.
    """

    def __init__(self, ask=input) -> None:
        self._ask = ask

    def approve(self, call: ToolCall) -> bool:
        """Interroge l'utilisateur et rend sa décision."""
        answer = self._ask(
            f"\nL'agent demande l'action sensible « {call.toolName} »\n"
            f"  arguments : {call.arguments}\n"
            f"Autoriser ? (oui / autre chose = non) : "
        )
        approved = answer.strip().lower() == "oui"
        logger.info(
            "action sensible %s : %s",
            call.toolName,
            "autorisee" if approved else "refusee",
        )
        return approved


REFUSAL_MESSAGE = (
    "Action refusée : cette opération est irréversible et n'a pas été validée "
    "par un humain. Ne la retente pas, propose une autre approche ou explique "
    "ce qu'il faudrait valider."
)
