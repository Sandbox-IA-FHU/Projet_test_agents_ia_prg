"""Tests de la relecture : contrôles du code, outils de l'agent, relecture complète.

Aucun test n'appelle le LLM : les scénarios d'agent sont rejoués par
`ScriptedClient` (voir `conftest.py`).
"""

import hashlib
from pathlib import Path

import docx
import pytest

from agent.acte import openActe, readParagraphs
from agent.errors import ReviewInputError, ToolError
from agent.loop import MAX_ITERATIONS, summarizeTrace
from agent.relecture import (
    KIND_JUDGEMENT,
    ORIGIN_AGENT,
    Check,
    CompanySheet,
    Finding,
    buildReviewTools,
    companySheetFromDict,
    loadChecks,
    mechanicalChecksFor,
    reviewActe,
    runMechanicalChecks,
)
from agent.tools import ToolRegistry
from tests.conftest import LoopingClient, ScriptedClient, textTurn, toolTurn

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKS_FILE = REPO_ROOT / "controles" / "controles.toml"

SHEET = CompanySheet(
    denomination="EARL DU CHAMP FICTIF",
    forme="EARL",
    capital=7500,
    siege="1 chemin des Exemples 00000 Villefictive",
    dirigeants=("Camille Exemple",),
)

CORRECT_EARL = [
    "STATUTS — EARL DU CHAMP FICTIF",
    "Exploitation agricole à responsabilité limitée au capital de 7 500 euros.",
    "Siège social : 1 chemin des Exemples, 00000 Villefictive.",
    "Camille Exemple est nommé gérant.",
]

JUDGEMENT = Check(
    checkId="earl-gerant-associe-exploitant",
    kind=KIND_JUDGEMENT,
    severity="bloquant",
    forms=("EARL",),
    acteTypes=("statuts",),
    description="Gérance d'EARL.",
    instruction="Chaque gérant est-il un associé exploitant ?",
)


def buildActe(path: Path, texts: list[str]) -> Path:
    """Fabrique un petit acte, un paragraphe par texte."""
    document = docx.Document()
    for text in texts:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def mechanicalFindings(tmp_path: Path, texts: list[str], forme: str = "EARL"):
    """Contrôles du code du fichier de démonstration, sur un acte fabriqué."""
    paragraphs = readParagraphs(openActe(buildActe(tmp_path / "acte.docx", texts)))
    checks = mechanicalChecksFor(loadChecks(CHECKS_FILE), forme, "statuts")
    sheet = (
        SHEET if forme == "EARL" else CompanySheet(**{**SHEET.__dict__, "forme": forme})
    )
    return runMechanicalChecks(checks, sheet, paragraphs)


# --- Entrées -------------------------------------------------------------------


def test_demoChecksFileIsValid() -> None:
    checks = loadChecks(CHECKS_FILE)

    assert checks
    assert any(check.kind == KIND_JUDGEMENT for check in checks)


def test_invalidSeveritySaysWhatToFix(tmp_path: Path) -> None:
    path = tmp_path / "controles.toml"
    path.write_text(
        '[[controle]]\nid = "x"\ntype = "verification"\ngravite = "grave"\n'
        'formes = ["*"]\nactes = ["*"]\ndescription = "d"\nconsigne = "c"\n',
        encoding="utf-8",
    )

    with pytest.raises(ReviewInputError, match="gravité"):
        loadChecks(path)


def test_capitalMustBeAWholeNumber() -> None:
    record = {
        "denomination": "X",
        "forme": "SARL",
        "capital": "7 500 euros",
        "siege": "s",
        "dirigeants": [],
    }

    with pytest.raises(ReviewInputError, match="entier"):
        companySheetFromDict(record, "fiche.json")


# --- Contrôles du code -----------------------------------------------------------


def test_correctActeRaisesNoMechanicalPoint(tmp_path: Path) -> None:
    assert mechanicalFindings(tmp_path, CORRECT_EARL) == []


def test_forbiddenTermIsFoundInEveryParagraph(tmp_path: Path) -> None:
    # L'erreur connue de la bibliothèque de clauses : « entreprise » dans des
    # statuts d'EARL. Singulier et pluriel, majuscules indifférentes, mot
    # entier seulement (« entrepreneur » n'est pas visé).
    texts = [
        *CORRECT_EARL,
        "Une Entreprise agricole.",
        "Les entreprises.",
        "Un entrepreneur.",
    ]

    findings = mechanicalFindings(tmp_path, texts)

    assert [(f.checkId, f.paragraph) for f in findings] == [
        ("earl-terme-entreprise", 4),
        ("earl-terme-entreprise", 5),
    ]
    assert "exploitation" in findings[0].comment


def test_forbiddenTermOnlyAppliesToItsForm(tmp_path: Path) -> None:
    texts = [*CORRECT_EARL, "Une entreprise commerciale."]

    findings = mechanicalFindings(tmp_path, texts, forme="SARL")

    assert all(f.checkId != "earl-terme-entreprise" for f in findings)


@pytest.mark.parametrize(
    "written", ["7 500 euros", "7.500 euros", "7500,00 euros", "7 500 €"]
)
def test_capitalIsRecognisedWhateverItsFormatting(tmp_path: Path, written: str) -> None:
    texts = [CORRECT_EARL[0], f"Capital : {written}.", *CORRECT_EARL[2:]]

    assert mechanicalFindings(tmp_path, texts) == []


def test_differentCapitalIsReported(tmp_path: Path) -> None:
    # 17 500 contient 7 500 : il ne doit pas passer pour le bon capital.
    texts = [CORRECT_EARL[0], "Capital : 17 500 euros.", *CORRECT_EARL[2:]]

    findings = mechanicalFindings(tmp_path, texts)

    assert [(f.checkId, f.paragraph) for f in findings] == [("fiche-capital", None)]


def test_missingDirigeantIsReported(tmp_path: Path) -> None:
    texts = [*CORRECT_EARL[:3], "Alex Tiers est nommé gérant."]

    findings = mechanicalFindings(tmp_path, texts)

    assert [f.checkId for f in findings] == ["fiche-dirigeants"]
    assert "Camille Exemple" in findings[0].comment


# --- Outils de l'agent -------------------------------------------------------------


def buildTools(tmp_path: Path) -> tuple[ToolRegistry, list[Finding]]:
    """Registre de relecture autour d'un acte EARL correct."""
    paragraphs = readParagraphs(openActe(buildActe(tmp_path / "a.docx", CORRECT_EARL)))
    findings: list[Finding] = []
    return ToolRegistry(buildReviewTools(paragraphs, [JUDGEMENT], findings)), findings


def test_reviewAgentHasNoWriteTool(tmp_path: Path) -> None:
    # La garantie « l'agent ne modifie pas l'acte » repose sur cette liste, pas
    # sur le prompt. Ajouter un outil ici est une décision à justifier.
    registry, _ = buildTools(tmp_path)

    assert registry.names() == ["chercherDansActe", "lireActe", "signalerPoint"]
    assert registry.sensitiveNames() == []


def test_reportedPointIsRecorded(tmp_path: Path) -> None:
    registry, findings = buildTools(tmp_path)

    result = registry.get("signalerPoint").handler(
        {"controle": JUDGEMENT.checkId, "paragraphe": 3, "commentaire": "Non associé."}
    )

    assert "enregistré" in result
    assert findings == [
        Finding(
            checkId=JUDGEMENT.checkId,
            severity="bloquant",  # gravité par défaut du contrôle
            paragraph=3,
            comment="Non associé.",
            origin=ORIGIN_AGENT,
        )
    ]


def test_samePointTwiceIsRecordedOnce(tmp_path: Path) -> None:
    registry, findings = buildTools(tmp_path)
    arguments = {"controle": JUDGEMENT.checkId, "paragraphe": 3, "commentaire": "c"}

    registry.get("signalerPoint").handler(arguments)
    registry.get("signalerPoint").handler(arguments)

    assert len(findings) == 1


@pytest.mark.parametrize(
    ("arguments", "hint"),
    [
        ({"controle": "inexistant", "commentaire": "c"}, "Identifiants"),
        ({"controle": "hors_liste", "commentaire": "c", "paragraphe": 99}, "0 à 3"),
        (
            {"controle": "hors_liste", "commentaire": "c", "gravite": "grave"},
            "bloquant",
        ),
        ({"controle": "hors_liste", "commentaire": " "}, "commentaire"),
    ],
)
def test_badPointTellsTheModelHowToFixIt(
    tmp_path: Path, arguments: dict[str, object], hint: str
) -> None:
    registry, findings = buildTools(tmp_path)

    with pytest.raises(ToolError, match=hint):
        registry.get("signalerPoint").handler(arguments)
    assert findings == []


# --- Relecture complète --------------------------------------------------------------


def runReview(tmp_path: Path, client, texts: list[str]):
    """Relecture complète d'un acte fabriqué, avec un client rejoué."""
    acte = buildActe(tmp_path / "statuts.docx", texts)
    before = hashlib.sha256(acte.read_bytes()).hexdigest()
    result = reviewActe(
        client=client,
        actePath=acte,
        sheet=SHEET,
        checks=loadChecks(CHECKS_FILE),
        acteType="statuts",
        systemPrompt="Consignes de test.",
        outputDir=tmp_path / "sortie",
        today="2026-11-23",
    )
    assert hashlib.sha256(acte.read_bytes()).hexdigest() == before, (
        "L'acte d'origine a été modifié."
    )
    return result


def test_fullReviewWritesCommentedCopyAndSortedReport(tmp_path: Path) -> None:
    texts = [
        *CORRECT_EARL[:3],
        "Alex Tiers, non associé, est nommé gérant.",
        "Une entreprise.",
    ]
    client = ScriptedClient(
        [
            toolTurn(("c1", "chercherDansActe", {"termes": ["gérant"]})),
            toolTurn(
                (
                    "c2",
                    "signalerPoint",
                    {
                        "controle": "earl-gerant-associe-exploitant",
                        "paragraphe": 3,
                        "commentaire": "Le gérant n'est pas associé.",
                    },
                )
            ),
            textTurn("Un point signalé."),
        ]
    )

    result = runReview(tmp_path, client, texts)

    # Points du code (terme, dirigeant absent) et de l'agent, du plus grave
    # au moins grave.
    assert [(f.checkId, f.severity) for f in result.findings] == [
        ("earl-gerant-associe-exploitant", "bloquant"),
        ("fiche-dirigeants", "majeur"),
        ("earl-terme-entreprise", "majeur"),
    ]
    assert len(list(openActe(result.copyPath).comments)) == 3
    report = result.reportPath.read_text(encoding="utf-8")
    assert report.index("### BLOQUANT") < report.index("### MAJEUR")
    assert "complète" in report


def test_requestedWriteToolDoesNotExist(tmp_path: Path) -> None:
    # Si un contenu de l'acte pousse le modèle à demander une écriture, il n'y
    # a rien à appeler : l'outil n'existe pas dans le registre de relecture.
    client = ScriptedClient(
        [
            toolTurn(("c1", "writeDocumentCopy", {"nom": "statuts.docx"})),
            textTurn("Fini."),
        ]
    )

    result = runReview(tmp_path, client, CORRECT_EARL)

    outcome = result.trace.steps[0].outcomes[0]
    assert outcome.isError
    assert "Outil inconnu" in outcome.content


def test_iterationLimitMarksTheReportIncomplete(tmp_path: Path) -> None:
    result = runReview(tmp_path, LoopingClient(), CORRECT_EARL)

    assert result.trace.stepCount == MAX_ITERATIONS
    assert "INCOMPLÈTE" in result.reportPath.read_text(encoding="utf-8")


def test_traceSummaryShowsNoCompanyData(tmp_path: Path) -> None:
    # La tâche contient la fiche société ; le résumé affiché n'en montre rien.
    result = runReview(tmp_path, ScriptedClient([textTurn("Rien.")]), CORRECT_EARL)

    summary = summarizeTrace(result.trace)

    assert SHEET.denomination not in summary
    assert "Camille Exemple" not in summary
