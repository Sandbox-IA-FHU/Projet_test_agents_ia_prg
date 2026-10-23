"""Tests du client, sans aucun appel réseau.

Le point central : la réflexion du modèle (`reasoning_content`) n'est jamais
prise pour la réponse, ne repart jamais dans l'historique et n'atteint jamais
la trace. Elle contient tout ce que le modèle a lu.
"""

import pytest

from agent.approval import DenyAll
from agent.client import (
    FINISH_LENGTH,
    NO_REASONING_SAMPLING,
    REASONING_EFFORT,
    buildRequestOptions,
    turnFromResponse,
)
from agent.errors import ModelCallError
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
