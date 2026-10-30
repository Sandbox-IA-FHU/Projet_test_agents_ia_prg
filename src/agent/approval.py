"""Validation humaine des actions sensibles.

Un modèle produit une action plausible, pas une action sûre. La règle de
l'organisation est explicite : aucune action irréversible ne se déclenche à
partir d'un contenu récupéré sans validation humaine.

Ce module est petit exprès. Ce qui compte n'est pas son code, c'est que le
chemin d'exécution d'un outil sensible **passe forcément par lui** — voir
`loop.executeCall`, et le test `test_sensitiveToolNeedsApproval`.
"""

import logging
import threading
from typing import Protocol

from agent.models import ToolCall

# Sans réponse de la personne dans ce délai, l'action est refusée : une page
# web fermée ne doit pas bloquer l'agent indéfiniment, ni valoir accord.
PENDING_APPROVAL_TIMEOUT_SECONDS = 600.0

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


class PendingApproval:
    """Attend la décision d'un humain, donnée depuis un autre fil d'exécution.

    Sert à l'interface web : l'agent tourne dans un fil à part ; quand il
    demande une action sensible, `approve` met l'appel en attente et bloque
    ce fil. La page web affiche l'appel (`pendingCall`) et ses boutons
    appellent `decide`, depuis le fil du serveur web. Pas de réponse dans le
    délai : refus.
    """

    def __init__(
        self, timeoutSeconds: float = PENDING_APPROVAL_TIMEOUT_SECONDS
    ) -> None:
        self._timeoutSeconds = timeoutSeconds
        # Le verrou protège `pendingCall` et `_approved`, lus et écrits par
        # deux fils différents ; l'événement réveille le fil de l'agent.
        self._lock = threading.Lock()
        self._decided = threading.Event()
        self._approved = False
        self.pendingCall: ToolCall | None = None

    def approve(self, call: ToolCall) -> bool:
        """Met l'appel en attente et bloque jusqu'à la décision ou au délai."""
        with self._lock:
            self.pendingCall = call
            self._approved = False
            self._decided.clear()
        decided = self._decided.wait(self._timeoutSeconds)
        with self._lock:
            approved = decided and self._approved
            self.pendingCall = None
        logger.info(
            "action sensible %s : %s",
            call.toolName,
            "autorisee" if approved else "refusee",
        )
        return approved

    def decide(self, approved: bool) -> None:
        """Enregistre la décision. Sans appel en attente, elle est ignorée."""
        with self._lock:
            # Un clic arrivé trop tard (délai écoulé, page restée ouverte) ne
            # doit pas valoir accord pour la prochaine demande.
            if self.pendingCall is None:
                return
            self._approved = approved
            self._decided.set()


REFUSAL_MESSAGE = (
    "Action refusée : cette opération est irréversible et n'a pas été validée "
    "par un humain. Ne la retente pas, propose une autre approche ou explique "
    "ce qu'il faudrait valider."
)
