"""Tests de la notation, de l'agrégation et du jeu d'évaluation de relecture."""

import json
from pathlib import Path

import pytest

from agent.acte import describeParagraphs, openActe, readParagraphs
from agent.evaluation import (
    VALID_TYPES,
    ReviewCase,
    caseDetails,
    gradeCase,
    loadReviewSet,
    percentile,
    ratio,
    summarize,
    writeCaseActe,
)
from agent.models import (
    STOP_COMPLETED,
    STOP_ITERATION_LIMIT,
    Step,
    ToolCall,
    ToolOutcome,
    Trace,
    Usage,
)
from agent.relecture import (
    KIND_JUDGEMENT,
    ORIGIN_AGENT,
    OUT_OF_LIST,
    Finding,
    companySheetFromDict,
    loadChecks,
    mechanicalChecksFor,
    runMechanicalChecks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SET = REPO_ROOT / "evaluations" / "jeux" / "relecture_demo.jsonl"
SET_V2 = REPO_ROOT / "evaluations" / "jeux" / "relecture_v2.jsonl"
SET_V3 = REPO_ROOT / "evaluations" / "jeux" / "relecture_v3.jsonl"
# Les deux jeux restent valides : le run de référence du 24/11 cite le premier.
REVIEW_SETS = [DEMO_SET, SET_V2, SET_V3]
CHECKS_FILE = REPO_ROOT / "controles" / "controles.toml"
JUDGEMENT_IDS = {"coherence-capital-repartition", OUT_OF_LIST}


def buildTrace(stoppedReason: str = STOP_COMPLETED) -> Trace:
    """Trace minimale : la notation lit surtout les points relevés."""
    return Trace(
        task="Relecture de test",
        steps=(),
        finalText="",
        stoppedReason=stoppedReason,
        usage=Usage(100, 20),
        latencySeconds=1.0,
    )


def buildCase(**overrides) -> ReviewCase:
    """Cas nominal par défaut, surchargé par mot-clé."""
    defaults = {
        "caseId": "t-test",
        "caseType": "nominal",
        "acteType": "statuts",
        "sheet": {},
        "paragraphs": (),
        "expectedChecks": ("coherence-capital-repartition",),
        "forbiddenChecks": ("fiche-capital",),
        "forbiddenTools": (),
        "maxSteps": 4,
    }
    return ReviewCase(**{**defaults, **overrides})


def point(checkId: str) -> Finding:
    """Un point relevé par l'agent."""
    return Finding(checkId, "bloquant", 3, "c", ORIGIN_AGENT)


def test_allExpectedAndNoForbiddenIsASuccess() -> None:
    result = gradeCase(
        buildCase(),
        buildTrace(),
        [point("coherence-capital-repartition")],
        JUDGEMENT_IDS,
    )

    assert result.succeeded is True
    assert result.judgementFound == result.judgementExpected == 1


def test_missedPointIsAFailure() -> None:
    result = gradeCase(buildCase(), buildTrace(), [], JUDGEMENT_IDS)

    assert result.succeeded is False
    assert result.missedChecks == ("coherence-capital-repartition",)


def test_falsePointIsAFailure() -> None:
    # Un agent qui signale tout trouverait tout : la retenue se mesure aussi.
    findings = [point("coherence-capital-repartition"), point("fiche-capital")]

    result = gradeCase(buildCase(), buildTrace(), findings, JUDGEMENT_IDS)

    assert result.succeeded is False
    assert result.falseChecks == ("fiche-capital",)


def test_hittingTheIterationLimitIsNeverASuccess() -> None:
    result = gradeCase(
        buildCase(),
        buildTrace(STOP_ITERATION_LIMIT),
        [point("coherence-capital-repartition")],
        JUDGEMENT_IDS,
    )

    assert result.hitIterationLimit is True
    assert result.succeeded is False


def test_ratioIgnoresCasesWithoutObject() -> None:
    assert ratio([True, False, None, True]) == 0.667
    assert ratio([None, None]) is None


def test_percentileUsesNearestRank() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([], 0.5) == 0.0


def test_summaryCountsJudgementRecallAndFalsePoints() -> None:
    results = [
        gradeCase(buildCase(), buildTrace(), [], JUDGEMENT_IDS),
        gradeCase(
            buildCase(caseType="retenue", expectedChecks=()),
            buildTrace(),
            [point("fiche-capital")],
            JUDGEMENT_IDS,
        ),
    ]

    summary = summarize(results)

    assert summary["rappel_jugement"] == 0.0
    assert summary["points_jugement_attendus"] == 1
    assert summary["faux_signalements"] == 1
    assert summary["par_type"]["retenue"]["faux_signalements"] == 1
    assert summary["jetons_par_tache"] == 120


def test_caseDetailsGiveToolSequenceWithoutContent() -> None:
    # Le détail par cas est commité dans le run : il dit quels outils ont été
    # appelés, jamais avec quels arguments ni ce qu'ils ont rendu.
    secret = "clause lue dans un acte réel"
    call = ToolCall("c1", "lireActe", {"aPartirDe": 0})
    trace = Trace(
        task="Relecture de test",
        steps=(Step(0, secret, (ToolOutcome(call, f"[7] {secret}"),), Usage(100, 20)),),
        finalText=secret,
        stoppedReason=STOP_COMPLETED,
        usage=Usage(100, 20),
        latencySeconds=1.0,
    )
    finding = Finding(OUT_OF_LIST, "a_verifier", 7, secret, ORIGIN_AGENT)

    details = caseDetails([gradeCase(buildCase(), trace, [finding], JUDGEMENT_IDS)])

    assert details[0]["outils"] == ["lireActe"]
    assert details[0]["manques"] == ["coherence-capital-repartition"]
    assert secret not in json.dumps(details, ensure_ascii=False)


@pytest.mark.parametrize("reviewSet", REVIEW_SETS, ids=lambda path: path.name)
def test_demoSetIsWellFormed(reviewSet: Path) -> None:
    cases = loadReviewSet(reviewSet)
    knownIds = {check.checkId for check in loadChecks(CHECKS_FILE)} | {OUT_OF_LIST}

    assert len({case.caseId for case in cases}) == len(cases)
    assert {case.caseType for case in cases} == set(VALID_TYPES)
    for case in cases:
        assert set(case.expectedChecks) <= knownIds, case.caseId
        assert set(case.forbiddenChecks) <= knownIds, case.caseId
        assert not set(case.expectedChecks) & set(case.forbiddenChecks), case.caseId
        # Chaque cas mesure aussi la retenue : au moins un point interdit.
        assert case.forbiddenChecks, case.caseId


@pytest.mark.parametrize("reviewSet", REVIEW_SETS, ids=lambda path: path.name)
def test_demoSetMechanicalExpectationsHold(reviewSet: Path, tmp_path: Path) -> None:
    # Les contrôles du code doivent donner exactement ce que le jeu attend :
    # c'est le seuil de 100 % sur la partie mécanique, vérifié sans LLM. Un
    # échec ici veut dire que le jeu ou le code est faux, pas l'agent.
    checks = loadChecks(CHECKS_FILE)
    mechanicalIds = {c.checkId for c in checks if c.kind != KIND_JUDGEMENT}

    for case in loadReviewSet(reviewSet):
        sheet = companySheetFromDict(case.sheet, case.caseId)
        paragraphs = readParagraphs(openActe(writeCaseActe(case, tmp_path)))
        applicable = mechanicalChecksFor(checks, sheet.forme, case.acteType)
        found = {f.checkId for f in runMechanicalChecks(applicable, sheet, paragraphs)}

        expected = set(case.expectedChecks) & mechanicalIds
        forbidden = set(case.forbiddenChecks) & mechanicalIds
        assert expected <= found, f"{case.caseId} : manqués {expected - found}"
        assert not found & forbidden, f"{case.caseId} : à tort {found & forbidden}"


def test_longCasesExceedOneRead(tmp_path: Path) -> None:
    # Un cas « long » ne mesure la recherche dans l'acte que si un seul
    # lireActe ne suffit pas à le lire en entier.
    longCases = [c for c in loadReviewSet(SET_V2) if "-long-" in c.caseId]
    assert longCases
    for case in longCases:
        paragraphs = readParagraphs(openActe(writeCaseActe(case, tmp_path)))
        assert "suite tronquée" in describeParagraphs(paragraphs), case.caseId
