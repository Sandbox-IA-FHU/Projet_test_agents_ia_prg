"""Évalue l'agent de relecture sur le jeu d'actes fictifs et écrit un run daté.

    uv run --env-file .env python scripts/evaluate.py --limite 3
    uv run --env-file .env python scripts/evaluate.py --etiquette relecture-v1

Le LLM est partagé entre plusieurs projets : un run complet occupe le serveur
pour tout le monde. Toujours commencer par `--limite 3`.

Trois points sur lesquels ce script ne transige pas :

- **Chaque cas repart de zéro**, dans un dossier temporaire : l'acte fictif y
  est fabriqué, relu, et la copie commentée y est écrite puis effacée. Aucun
  fichier d'évaluation ne reste sur le disque, et aucun cas n'influence le
  suivant.
- **Le modèle est consigné en entier** : nom exposé, modèle réel déclaré par
  le serveur, révision et niveau de réflexion. Le nom exposé est stable alors
  que le modèle derrière peut changer.
- **La liste de contrôles et le prompt sont consignés** : modifier l'un ou
  l'autre change ce que l'agent reçoit, et invalide la comparaison avec les
  runs passés.
"""

import argparse
import json
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

from agent.client import (
    KEEP_REASONING_IN_HISTORY,
    MAX_OUTPUT_TOKENS,
    REASONING_EFFORT,
    REASONING_EFFORTS,
    OpenAICompatibleClient,
)
from agent.config import loadConfig
from agent.errors import ActeError, ConfigError, ModelCallError, ReviewInputError
from agent.evaluation import gradeCase, loadReviewSet, summarize, writeCaseActe
from agent.loop import MAX_ITERATIONS
from agent.relecture import (
    KIND_JUDGEMENT,
    OUT_OF_LIST,
    companySheetFromDict,
    loadChecks,
    reviewActe,
)

DEFAULT_SET = Path("evaluations/jeux/relecture_demo.jsonl")
DEFAULT_CHECKS = Path("controles/controles.toml")
DEFAULT_PROMPT = Path("prompts/relecture_v1.md")
RUNS_DIR = Path("evaluations/runs")


def buildParser() -> argparse.ArgumentParser:
    """Décrit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Évalue l'agent de relecture.")
    parser.add_argument("--jeu", type=Path, default=DEFAULT_SET)
    parser.add_argument("--controles", type=Path, default=DEFAULT_CHECKS)
    parser.add_argument(
        "--etiquette", default="run", help="Suffixe du nom de fichier de run."
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        dest="maxIterations",
    )
    parser.add_argument(
        "--reflexion",
        choices=REASONING_EFFORTS,
        default=REASONING_EFFORT,
        help=f"Niveau de réflexion du modèle (défaut : {REASONING_EFFORT}).",
    )
    parser.add_argument(
        "--garder-reflexion",
        action=argparse.BooleanOptionalAction,
        default=KEEP_REASONING_IN_HISTORY,
        dest="garderReflexion",
        help=(
            "Renvoie au modèle, dans l'historique, la réflexion de son tour "
            "précédent. Jamais écrite dans la trace ni dans le run."
        ),
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="N'évalue que les N premiers cas. À utiliser avant un run complet.",
    )
    return parser


def main() -> int:
    """Point d'entrée. Rend 0 en succès, 1 sur une erreur attendue."""
    args = buildParser().parse_args()

    try:
        config = loadConfig()
    except ConfigError as error:
        print(f"Configuration : {error}", file=sys.stderr)
        return 1

    if not config.modelRevision:
        print(
            "Configuration : LLM_MODEL_REVISION est vide. Un run doit consigner "
            "la révision du modèle ; la demander à Florian (responsable).",
            file=sys.stderr,
        )
        return 1

    logging.basicConfig(level=config.logLevel, format="%(levelname)s %(message)s")

    try:
        cases = loadReviewSet(args.jeu)
        checks = loadChecks(args.controles)
    except ReviewInputError as error:
        print(f"Données : {error}", file=sys.stderr)
        return 1

    if args.limite is not None:
        cases = cases[: args.limite]

    # Contrôles confiés à l'agent (et « hors liste ») : leur rappel se mesure
    # à part, celui des contrôles du code est garanti par les tests.
    judgementIds = {c.checkId for c in checks if c.kind == KIND_JUDGEMENT}
    judgementIds.add(OUT_OF_LIST)

    client = OpenAICompatibleClient(
        baseUrl=config.baseUrl,
        model=config.model,
        apiKey=config.apiKey,
        reasoningEffort=args.reflexion,
        keepReasoning=args.garderReflexion,
    )
    try:
        servedModel = client.servedModel()
    except ModelCallError as error:
        print(f"Modèle : {error}", file=sys.stderr)
        return 1
    systemPrompt = DEFAULT_PROMPT.read_text(encoding="utf-8")

    print(
        f"{len(cases)} cas, modèle {config.model} ({servedModel}), "
        f"réflexion {args.reflexion} (gardée dans l'historique : "
        f"{'oui' if args.garderReflexion else 'non'}), "
        f"prompt {DEFAULT_PROMPT.name}."
    )
    print(f"Jusqu'à {args.maxIterations * len(cases)} appels au LLM partagé.")

    results = []
    for case in cases:
        try:
            with tempfile.TemporaryDirectory() as workDir:
                actePath = writeCaseActe(case, Path(workDir) / "entree")
                review = reviewActe(
                    client=client,
                    actePath=actePath,
                    sheet=companySheetFromDict(case.sheet, case.caseId),
                    checks=checks,
                    acteType=case.acteType,
                    systemPrompt=systemPrompt,
                    outputDir=Path(workDir) / "sortie",
                    today=date.today().isoformat(),
                    maxIterations=args.maxIterations,
                )
        except ModelCallError as error:
            print(f"{case.caseId} : appel modèle échoué — {error}", file=sys.stderr)
            return 1
        except (ReviewInputError, ActeError) as error:
            print(f"{case.caseId} : {error}", file=sys.stderr)
            return 1

        result = gradeCase(case, review.trace, review.findings, judgementIds)
        results.append(result)
        flags = []
        if result.missedChecks:
            flags.append(f"manqués {list(result.missedChecks)}")
        if result.falseChecks:
            flags.append(f"à tort {list(result.falseChecks)}")
        if result.forbiddenToolCalled:
            flags.append("OUTIL INTERDIT")
        if result.hitIterationLimit:
            flags.append("PLAFOND")
        print(
            f"  {case.caseId} [{case.caseType}] "
            f"{'ok' if result.succeeded else 'ECHEC'} "
            f"{result.stepCount} tour(s) {' '.join(flags)}"
        )

    summary = summarize(results)
    run = {
        "date": date.today().isoformat(),
        "modele": {
            "nom_expose": config.model,
            "modele_reel": servedModel,
            "revision": config.modelRevision,
        },
        "prompt": f"prompts/{DEFAULT_PROMPT.name}",
        "jeu": str(args.jeu).replace("\\", "/"),
        "controles": str(args.controles).replace("\\", "/"),
        "nb_cas": len(results),
        "parametres": {
            "max_iterations": args.maxIterations,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reflexion": args.reflexion,
            "garder_reflexion": args.garderReflexion,
        },
        "resultats": summary,
        "commentaire": "",
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runPath = RUNS_DIR / f"{run['date']}-{args.etiquette}.json"
    runPath.write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print(f"Tâches réussies       : {summary['tache_reussie']}")
    print(f"Plafond atteint       : {summary['limite_iterations_atteinte']}")
    print(
        f"Rappel (jugement)     : {summary['rappel_jugement']} sur "
        f"{summary['points_jugement_attendus']} point(s) attendu(s)"
    )
    print(f"Faux signalements     : {summary['faux_signalements']}")
    print(
        f"Étapes médianes / max : {summary['etapes_medianes']} / "
        f"{summary['etapes_max']}"
    )
    print(f"Jetons par tâche      : {summary['jetons_par_tache']}")
    print(
        f"Latence médiane / p95 : {summary['latence_mediane_s']} s / "
        f"{summary['latence_p95_s']} s"
    )
    print()
    print(f"Run écrit dans {runPath}")
    print("Remplir le champ « commentaire » avant de commiter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
