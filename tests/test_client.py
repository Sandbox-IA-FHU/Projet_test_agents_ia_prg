"""Tests du client, sans aucun appel réseau.

Le point central : la réflexion du modèle n'est jamais prise pour la réponse
et n'atteint jamais la trace ni le fichier de run. Elle contient tout ce que
le modèle a lu. Par défaut, elle ne repart pas non plus dans l'historique ;
l'option qui l'y renvoie ne change rien à la trace.
"""

import pytest

from agent.approval import DenyAll
from agent.client import (
    FINISH_LENGTH,
    KEEP_REASONING_IN_HISTORY,
    NO_REASONING_SAMPLING,
    REASONING_EFFORT,
    buildRequestOptions,
    turnFromResponse,
)
from agent.errors import ModelCallError
from agent.evaluation import TaskCase, gradeCase, summarize
from agent.loop import runAgent, summarizeTrace
from agent.tools import ToolRegistry
from tests.conftest import ScriptedClient, completion, textTurn, toolTurn

SECRET_REASONING = "réflexion interne à ne jamais publier"


def test_reasoningIsNeverTakenForTheAnswer() -> None:
    turn = textTurn("Le tarif est de 95 euros.", reasoning=SECRET_REASONING)

    assert turn.text == "Le tarif est de 95 euros."
    assert SECRET_REASONING not in str(turn.assistantMessage)


def test_reasoningNeverReachesHistoryOrTrace(registry: ToolRegistry) -> None:
    client = ScriptedClient(
        [
            toolTurn(
                ("c1", "readNote", {"nom": "astreinte"}), reasoning=SECRET_REASONING
            ),
            textTurn("Le tarif est de 95 euros.", reasoning=SECRET_REASONING),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt="Consignes de test.",
        task="quel tarif ?",
    )

    assert SECRET_REASONING not in str(client.calls)
    assert SECRET_REASONING not in str(trace)
    assert SECRET_REASONING not in summarizeTrace(trace)


def test_toolCallsAreReadFromTheOpenAIFormat() -> None:
    turn = toolTurn(("c1", "readNote", {"nom": "astreinte"}))

    assert turn.toolCalls[0].callId == "c1"
    assert turn.toolCalls[0].toolName == "readNote"
    assert turn.toolCalls[0].arguments == {"nom": "astreinte"}
    # Les arguments repartent tels que le modèle les a écrits.
    assert turn.assistantMessage["tool_calls"][0]["function"]["arguments"] == (
        '{"nom": "astreinte"}'
    )


def test_unreadableArgumentsDoNotKillTheLoop() -> None:
    response = completion(
        None,
        [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "readNote", "arguments": "{pas du json"},
            }
        ],
        "tool_calls",
    )

    assert turnFromResponse(response).toolCalls[0].arguments == {}


def test_truncatedAnswerIsNotSilent() -> None:
    # Coupée pendant la réflexion, la réponse arrive vide : la prendre pour
    # une réponse serait pire qu'une erreur.
    with pytest.raises(ModelCallError, match="coupée"):
        turnFromResponse(completion("", finishReason=FINISH_LENGTH))


def test_reasoningEffortIsSentWhereTheServerReadsIt() -> None:
    options = buildRequestOptions(REASONING_EFFORT)

    assert options == {
        "extra_body": {"chat_template_kwargs": {"reasoning_effort": "low"}}
    }


def test_reasoningOffUsesTheRecommendedSampling() -> None:
    options = buildRequestOptions("off")

    assert options["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert {key: options[key] for key in NO_REASONING_SAMPLING} == (
        NO_REASONING_SAMPLING
    )


def test_unknownReasoningEffortIsRefused() -> None:
    with pytest.raises(ModelCallError, match="réflexion"):
        buildRequestOptions("maximum")


def test_reasoningIsDroppedFromHistoryByDefault() -> None:
    assert KEEP_REASONING_IN_HISTORY is False


def test_keptReasoningGoesBackToTheModelOnly(registry: ToolRegistry) -> None:
    # Option à mesurer : la réflexion repart dans l'historique, sous le champ
    # « reasoning », pour aider le modèle à garder le fil. Elle ne doit pour
    # autant jamais atteindre la trace, son résumé ni le fichier de run.
    client = ScriptedClient(
        [
            toolTurn(
                ("c1", "readNote", {"nom": "astreinte"}),
                reasoning=SECRET_REASONING,
                keepReasoning=True,
            ),
            textTurn(
                "Le tarif est de 95 euros.",
                reasoning=SECRET_REASONING,
                keepReasoning=True,
            ),
        ]
    )

    trace = runAgent(
        client=client,
        registry=registry,
        approval=DenyAll(),
        systemPrompt="Consignes de test.",
        task="quel tarif ?",
    )
    case = TaskCase(
        caseId="t-test",
        caseType="nominal",
        task="quel tarif ?",
        expectedKeywords=("95",),
        forbiddenKeywords=(),
        forbiddenTools=("deleteNote",),
        maxSteps=3,
    )
    runSummary = summarize([gradeCase(case, trace)])

    assistantMessage = client.calls[1][1]
    assert assistantMessage["reasoning"] == SECRET_REASONING
    assert trace.finalText == "Le tarif est de 95 euros."
    assert SECRET_REASONING not in str(trace)
    assert SECRET_REASONING not in summarizeTrace(trace)
    assert SECRET_REASONING not in str(runSummary)
