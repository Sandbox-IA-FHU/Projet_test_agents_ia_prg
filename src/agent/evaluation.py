"""Évaluation de l'agent de relecture.

Un cas du jeu d'évaluation est un acte fictif, décrit en texte (pas de `.docx`
dans le dépôt), sa fiche société, et deux listes :

- `points_attendus` : les contrôles que la relecture **doit** signaler ;
- `points_interdits` : des contrôles que l'acte respecte, et que la relecture
  ne doit **pas** signaler. Sans eux, on ne mesurerait que la capacité à
  trouver, jamais la retenue : un agent qui signale tout aurait 100 %.

Ce qu'on mesure, et pourquoi c'est séparé :

- **la tâche est-elle réussie** — tous les attendus trouvés, aucun interdit ;
- **le rappel sur les contrôles de jugement** — ceux qu'a faits l'agent. Les
  contrôles mécaniques sont faits par le code et couverts par les tests : les
  mélanger au rappel de l'agent gonflerait son score ;
- **les faux signalements** — le coût pour le juriste, qui lit chaque point ;
- **combien de tours, combien de jetons** — la charge du LLM partagé ;
- **le plafond a-t-il été touché** — un cas tronqué est ininterprétable.

La notation est volontairement la plus bête qui réponde à la question : on
compare des identifiants de contrôles, pas le texte des commentaires.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import docx

from agent.errors import ReviewInputError
from agent.models import STOP_ITERATION_LIMIT, Trace
from agent.relecture import Finding

REQUIRED_FIELDS = ("cas_id", "type", "type_acte", "fiche", "acte", "points_attendus")
# retenue : un acte correct, où rien ne doit être signalé à tort.
# injection : l'acte contient une phrase qui tente de piloter l'agent.
VALID_TYPES = ("nominal", "difficile", "retenue", "injection")


@dataclass(frozen=True)
class ReviewCase:
    """Un cas du jeu d'évaluation : un acte fictif et ce qu'on en attend."""

    caseId: str
    caseType: str
    acteType: str
    sheet: dict[str, object]
    paragraphs: tuple[tuple[str, str], ...]  # (style Word, texte)
    expectedChecks: tuple[str, ...]
    forbiddenChecks: tuple[str, ...]
    forbiddenTools: tuple[str, ...]
    maxSteps: int | None


@dataclass(frozen=True)
class CaseResult:
    """Ce qu'on a mesuré sur un cas."""

    case: ReviewCase
    succeeded: bool
    missedChecks: tuple[str, ...]
    falseChecks: tuple[str, ...]
    judgementExpected: int
    judgementFound: int
    forbiddenToolCalled: bool
    hitIterationLimit: bool
    withinStepBudget: bool | None
    stepCount: int
    inputTokens: int
    outputTokens: int
    latencySeconds: float
    toolNames: tuple[str, ...] = ()


def loadReviewSet(path: Path) -> list[ReviewCase]:
    """Lit le jeu d'évaluation JSONL, une ligne par cas."""
    if not path.is_file():
        raise ReviewInputError(f"Jeu d'évaluation introuvable : {path}")

    cases: list[ReviewCase] = []
    with path.open(encoding="utf-8") as handle:
        for lineNumber, rawLine in enumerate(handle, start=1):
            line = rawLine.strip()
            if not line:
                continue
            where = f"{path.name} ligne {lineNumber}"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ReviewInputError(f"{where} : JSON invalide.") from error
            missing = [name for name in REQUIRED_FIELDS if name not in record]
            if missing:
                raise ReviewInputError(f"{where} : champs manquants {missing}.")
            if record["type"] not in VALID_TYPES:
                raise ReviewInputError(
                    f"{where} : type {record['type']!r} inconnu, attendu {VALID_TYPES}."
                )
            cases.append(
                ReviewCase(
                    caseId=str(record["cas_id"]),
                    caseType=str(record["type"]),
                    acteType=str(record["type_acte"]),
                    sheet=dict(record["fiche"]),
                    paragraphs=tuple(
                        (str(item["style"]), str(item["texte"]))
                        for item in record["acte"]
                    ),
                    expectedChecks=tuple(record["points_attendus"]),
                    forbiddenChecks=tuple(record.get("points_interdits", [])),
                    forbiddenTools=tuple(record.get("outils_interdits", [])),
                    maxSteps=record.get("max_etapes"),
                )
            )
    return cases


def writeCaseActe(case: ReviewCase, directory: Path) -> Path:
    """Fabrique le `.docx` fictif d'un cas, à partir de sa description texte.

    Les actes de démonstration vivent dans le dépôt sous forme de texte
    relisible en revue ; le fichier Word est recréé à chaque évaluation, dans
    un dossier temporaire.
    """
    directory.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    for style, text in case.paragraphs:
        document.add_paragraph(text, style=style)
    path = directory / f"{case.caseId}.docx"
    document.save(str(path))
    return path


def gradeCase(
    case: ReviewCase,
    trace: Trace,
    findings: list[Finding],
    judgementIds: set[str],
) -> CaseResult:
    """Note un cas à partir des points relevés et de la trace.

    `judgementIds` : identifiants des contrôles confiés à l'agent, pour
    calculer son rappel à part de celui du code.
    """
    reported = {finding.checkId for finding in findings}
    missed = tuple(check for check in case.expectedChecks if check not in reported)
    false = tuple(check for check in case.forbiddenChecks if check in reported)
    expectedJudgement = [c for c in case.expectedChecks if c in judgementIds]
    forbiddenToolCalled = bool(set(trace.toolNames()) & set(case.forbiddenTools))
    hitIterationLimit = trace.stoppedReason == STOP_ITERATION_LIMIT

    withinStepBudget: bool | None = None
    if case.maxSteps is not None:
        withinStepBudget = trace.stepCount <= case.maxSteps

    return CaseResult(
        case=case,
        succeeded=not missed
        and not false
        and not forbiddenToolCalled
        and not hitIterationLimit,
        missedChecks=missed,
        falseChecks=false,
        judgementExpected=len(expectedJudgement),
        judgementFound=sum(check in reported for check in expectedJudgement),
        forbiddenToolCalled=forbiddenToolCalled,
        hitIterationLimit=hitIterationLimit,
        withinStepBudget=withinStepBudget,
        stepCount=trace.stepCount,
        inputTokens=trace.usage.inputTokens,
        outputTokens=trace.usage.outputTokens,
        latencySeconds=trace.latencySeconds,
        toolNames=tuple(trace.toolNames()),
    )


def ratio(values: list[bool | None]) -> float | None:
    """Proportion de vrais, en ignorant les cas sans objet."""
    considered = [value for value in values if value is not None]
    if not considered:
        return None
    return round(sum(considered) / len(considered), 3)


def percentile(values: list[float], fraction: float) -> float:
    """Centile par rang le plus proche, sans interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return round(ordered[rank], 3)


def summarize(results: list[CaseResult]) -> dict[str, object]:
    """Agrège les résultats, globalement et par type de cas.

    Les clés sont le contrat du fichier de run : en `snake_case` français,
    lues par des humains et par d'autres outils.
    """
    latencies = [result.latencySeconds for result in results]
    steps = [float(result.stepCount) for result in results]
    judgementExpected = sum(result.judgementExpected for result in results)
    byType: dict[str, object] = {}

    for caseType in VALID_TYPES:
        subset = [result for result in results if result.case.caseType == caseType]
        if not subset:
            continue
        byType[caseType] = {
            "nb_cas": len(subset),
            "tache_reussie": ratio([result.succeeded for result in subset]),
            "faux_signalements": sum(len(result.falseChecks) for result in subset),
        }

    return {
        "tache_reussie": ratio([result.succeeded for result in results]),
        "outil_interdit_appele": ratio(
            [result.forbiddenToolCalled for result in results]
        ),
        "limite_iterations_atteinte": ratio(
            [result.hitIterationLimit for result in results]
        ),
        # Rappel de l'agent seul : points de jugement attendus et trouvés.
        "rappel_jugement": (
            round(
                sum(result.judgementFound for result in results) / judgementExpected, 3
            )
            if judgementExpected
            else None
        ),
        "points_jugement_attendus": judgementExpected,
        "faux_signalements": sum(len(result.falseChecks) for result in results),
        "dans_le_budget_etapes": ratio([result.withinStepBudget for result in results]),
        "etapes_medianes": percentile(steps, 0.5),
        "etapes_max": max(steps) if steps else 0.0,
        "jetons_entree": sum(result.inputTokens for result in results),
        "jetons_sortie": sum(result.outputTokens for result in results),
        "jetons_par_tache": round(
            sum(result.inputTokens + result.outputTokens for result in results)
            / max(len(results), 1)
        ),
        "latence_mediane_s": percentile(latencies, 0.5),
        "latence_p95_s": percentile(latencies, 0.95),
        "par_type": byType,
    }


def caseDetails(results: list[CaseResult]) -> list[dict[str, object]]:
    """Le détail par cas, pour savoir *quels* cas ont échoué et comment.

    Seulement des identifiants, des compteurs et des noms d'outils : jamais un
    argument d'appel ni un commentaire, qui reprennent le texte de l'acte (même
    règle que `summarizeTrace`). La séquence d'outils suffit à distinguer un
    agent qui n'a pas lu le paragraphe fautif d'un agent qui l'a lu sans le
    juger faux.
    """
    return [
        {
            "cas_id": result.case.caseId,
            "type": result.case.caseType,
            "reussi": result.succeeded,
            "manques": list(result.missedChecks),
            "a_tort": list(result.falseChecks),
            "etapes": result.stepCount,
            "outils": list(result.toolNames),
        }
        for result in results
    ]
