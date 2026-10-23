"""Tests de la boucle d'agent, sans aucun appel réseau.

Les trois premiers tests portent sur les trois propriétés que le README
annonce comme non négociables. S'ils tombent, ce n'est pas un test à réparer :
c'est une régression de sécurité ou de charge du serveur.
"""

from agent.approval import AllowAll, DenyAll
from agent.loop import runAgent, summarizeTrace
from agent.models import STOP_COMPLETED, STOP_ITERATION_LIMIT
from agent.tools import ToolRegistry
from tests.conftest import LoopingClient, ScriptedClient, textTurn, toolTurn

PROMPT = "Consignes de test."


def test_iterationLimitStopsTheLoop(registry: ToolRegistry) -> None:
    # Sans plafond, ce client ferait tourner la boucle indéfiniment. C'est
    # exactement le scénario d'un agent qui occupe le LLM partagé toute la nuit.
    client = LoopingClient()

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="tourne en rond",
        maxIterations=4,
    )

    assert client.callCount == 4
    assert trace.stepCount == 4
    assert trace.stoppedReason == STOP_ITERATION_LIMIT


def test_iterationLimitIsNotSilent(registry: ToolRegistry) -> None:
    # Une boucle qui s'arrête sans le dire produit une réponse tronquée qu'on
    # prend pour une réponse.
    trace = runAgent(
        client=LoopingClient(),
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="tourne en rond",
        maxIterations=3,
    )

    assert "limite" in trace.finalText.lower()
    assert "3" in trace.finalText


def test_sensitiveToolNeedsApproval(registry: ToolRegistry, noteStore) -> None:
    client = ScriptedClient(
        [
            toolTurn(("c1", "deleteNote", {"nom": "note-a-supprimer"})),
            textTurn("La suppression a été refusée faute de validation."),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="supprime la note",
    )

    assert trace.refusedTools() == ["deleteNote"]
    # La note est toujours là : le refus a bien empêché l'action.
    assert "note-a-supprimer" in noteStore.listNames()


def test_approvedSensitiveToolRuns(registry: ToolRegistry, noteStore) -> None:
    client = ScriptedClient(
        [
            toolTurn(("c1", "deleteNote", {"nom": "note-a-supprimer"})),
            textTurn("Note supprimée."),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=AllowAll(),
        systemPrompt=PROMPT,
        task="supprime la note",
    )

    assert trace.refusedTools() == []
    assert "note-a-supprimer" not in noteStore.listNames()


def test_nonSensitiveToolNeedsNoApproval(registry: ToolRegistry) -> None:
    # DenyAll refuse les outils sensibles, pas les autres : sinon l'agent ne
    # pourrait plus rien faire du tout en mode refus.
    client = ScriptedClient([toolTurn(("c1", "listNotes", {})), textTurn("Voilà.")])

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="liste les notes",
    )

    assert trace.refusedTools() == []
    assert trace.toolNames() == ["listNotes"]


def test_loopStopsWhenTheModelStopsCallingTools(registry: ToolRegistry) -> None:
    client = ScriptedClient(
        [
            toolTurn(("c1", "listNotes", {})),
            toolTurn(("c2", "readNote", {"nom": "astreinte"})),
            textTurn("Le tarif est de 95 euros."),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="quel tarif ?",
    )

    assert trace.stoppedReason == STOP_COMPLETED
    assert trace.stepCount == 3
    assert trace.finalText == "Le tarif est de 95 euros."


def test_parallelToolResultsShareOneRoundTrip(registry: ToolRegistry) -> None:
    # Format OpenAI : un message « tool » par appel. Ce qui compte, c'est qu'ils
    # suivent tous le message de l'assistant et partent dans le même
    # aller-retour. Les étaler sur plusieurs tours apprend au modèle à ne plus
    # grouper ses appels, et coûte un tour complet à chaque fois.
    client = ScriptedClient(
        [
            toolTurn(
                ("c1", "readNote", {"nom": "astreinte"}),
                ("c2", "readNote", {"nom": "sauvegardes"}),
            ),
            textTurn("Fini."),
        ]
    )

    runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="lis les deux notes",
    )

    assert len(client.calls) == 2
    roles = [message["role"] for message in client.calls[1]]
    assert roles == ["user", "assistant", "tool", "tool"]
    toolCallIds = [message["tool_call_id"] for message in client.calls[1][2:]]
    assert toolCallIds == ["c1", "c2"]


def test_unknownToolBecomesAnErrorResult(registry: ToolRegistry) -> None:
    # Une exception qui remonte tue la boucle ; un résultat d'erreur permet à
    # l'agent de se rattraper.
    client = ScriptedClient(
        [toolTurn(("c1", "sendEmail", {})), textTurn("Cet outil n'existe pas.")]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="envoie un courriel",
    )

    outcome = trace.steps[0].outcomes[0]
    assert outcome.isError is True
    assert "sendEmail" in outcome.content
    assert trace.stoppedReason == STOP_COMPLETED


def test_toolFailureBecomesAnErrorResult(registry: ToolRegistry) -> None:
    client = ScriptedClient(
        [
            toolTurn(("c1", "readNote", {"nom": "note-inexistante"})),
            textTurn("Cette note n'existe pas."),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="lis une note",
    )

    assert trace.steps[0].outcomes[0].isError is True


def test_traceSummaryLeaksNoContent(registry: ToolRegistry) -> None:
    # Une trace complète contient le contenu métier, intégralement. Le résumé
    # affiché et journalisé ne doit porter que des noms et des compteurs.
    client = ScriptedClient(
        [
            toolTurn(("c1", "readNote", {"nom": "astreinte"})),
            textTurn("Le tarif est de 95 euros."),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="quel tarif ?",
    )
    summary = summarizeTrace(trace)

    assert "readNote" in summary
    assert "95 euros hors taxes" not in summary


def test_usageIsAccumulatedAcrossTurns(registry: ToolRegistry) -> None:
    client = ScriptedClient(
        [toolTurn(("c1", "listNotes", {})), textTurn("Trois notes.")]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt=PROMPT,
        task="liste",
    )

    assert trace.usage.inputTokens == 200
    assert trace.usage.outputTokens == 40
