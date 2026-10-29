"""Tests des politiques de validation.

Petit module, tests courts, mais c'est le seul endroit qui décide si une action
irréversible a lieu.
"""

import threading
import time

from agent.approval import AllowAll, ConsoleApproval, DenyAll, PendingApproval
from agent.models import ToolCall

CALL = ToolCall(callId="c1", toolName="deleteNote", arguments={"nom": "a"})


def test_denyAllRefuses() -> None:
    assert DenyAll().approve(CALL) is False


def test_allowAllAccepts() -> None:
    assert AllowAll().approve(CALL) is True


def test_consoleAcceptsOnlyAnExplicitYes() -> None:
    assert ConsoleApproval(ask=lambda _: "oui").approve(CALL) is True
    assert ConsoleApproval(ask=lambda _: "OUI  ").approve(CALL) is True


def test_consoleTreatsAnythingElseAsRefusal() -> None:
    # Sur une action irréversible, un appui sur Entrée ne doit pas valoir
    # accord. Ni « o », ni « y », ni « ok ».
    for answer in ["", " ", "o", "y", "ok", "non", "oui je crois"]:
        assert ConsoleApproval(ask=lambda _, a=answer: a).approve(CALL) is False


def test_consoleShowsToolAndArguments() -> None:
    # La personne qui valide doit voir ce qu'elle valide, pas seulement qu'on
    # lui demande quelque chose.
    seen: list[str] = []

    def capture(question: str) -> str:
        seen.append(question)
        return "non"

    ConsoleApproval(ask=capture).approve(CALL)

    assert "deleteNote" in seen[0]
    assert "nom" in seen[0]


def decideWhenPending(approval: PendingApproval, approved: bool) -> threading.Thread:
    """Joue la personne devant la page web : attend la demande, puis décide."""

    def click() -> None:
        while approval.pendingCall is None:
            time.sleep(0.01)
        approval.decide(approved)

    thread = threading.Thread(target=click)
    thread.start()
    return thread


def test_pendingApprovalWaitsForTheDecision() -> None:
    for approved in (True, False):
        approval = PendingApproval(timeoutSeconds=5)
        clicker = decideWhenPending(approval, approved)
        assert approval.approve(CALL) is approved
        clicker.join()
        assert approval.pendingCall is None


def test_pendingApprovalRefusesAfterTimeout() -> None:
    # Page fermée, personne ne répond : le silence ne vaut pas accord.
    assert PendingApproval(timeoutSeconds=0.05).approve(CALL) is False


def test_lateDecisionIsIgnored() -> None:
    # Un clic « Valider » arrivé hors attente ne doit pas valider la demande
    # suivante.
    approval = PendingApproval(timeoutSeconds=0.05)
    approval.decide(True)
    assert approval.approve(CALL) is False
