"""Lance l'évaluation de l'agent et écrit un fichier de run daté.

    uv run --env-file .env python scripts/evaluate.py --limite 3
    uv run --env-file .env python scripts/evaluate.py --etiquette prompt-v1

Le LLM est partagé entre plusieurs projets : un run complet occupe le serveur
pour tout le monde. Toujours commencer par `--limite 3`.

Trois points sur lesquels ce script ne transige pas :

- **La validation est toujours en mode refus.** Un jeu d'évaluation ne doit
  jamais pouvoir déclencher une action réelle, et un run qui attend une réponse
  humaine ne se termine pas.
- **Chaque cas repart d'un magasin de notes neuf.** Un cas qui modifie l'état
  fausserait tous les suivants, et le score dépendrait de l'ordre des cas.
- **Le modèle est consigné en entier** : nom exposé, modèle réel déclaré par
  le serveur, révision et niveau de réflexion. Le nom exposé est stable alors
  que le modèle derrière peut changer.
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from agent.approval import DenyAll
from agent.client import (
    MAX_OUTPUT_TOKENS,
    REASONING_EFFORT,
    REASONING_EFFORTS,
    OpenAICompatibleClient,
)
from agent.config import loadConfig
from agent.errors import ConfigError, ModelCallError, NoteStoreError
from agent.evaluation import gradeCase, loadTaskSet, summarize
from agent.loop import MAX_ITERATIONS, runAgent
from agent.toolbox import NoteStore, buildToolbox
from agent.tools import ToolRegistry

DEFAULT_NOTES = Path("evaluations/jeux/notes_demo.jsonl")
DEFAULT_TASK_SET = Path("evaluations/jeux/taches_demo.jsonl")
DEFAULT_PROMPT = Path("prompts/agent_v1.md")
RUNS_DIR = Path("evaluations/runs")


def buildParser() -> argparse.ArgumentParser:
    """Décrit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Évalue l'agent.")
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--jeu", type=Path, default=DEFAULT_TASK_SET)
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
        cases = loadTaskSet(args.jeu)
        NoteStore.fromFile(args.notes)  # échoue tout de suite si illisible
    except NoteStoreError as error:
        print(f"Données : {error}", file=sys.stderr)
        return 1

    if args.limite is not None:
        cases = cases[: args.limite]

    client = OpenAICompatibleClient(
        baseUrl=config.baseUrl,
        model=config.model,
        apiKey=config.apiKey,
        reasoningEffort=args.reflexion,
    )
    try:
        servedModel = client.servedModel()
    except ModelCallError as error:
        print(f"Modèle : {error}", file=sys.stderr)
        return 1
    systemPrompt = DEFAULT_PROMPT.read_text(encoding="utf-8")

    print(
        f"{len(cases)} cas, modèle {config.model} ({servedModel}), "
        f"réflexion {args.reflexion}, prompt {DEFAULT_PROMPT.name}."
    )
    print(
        f"Jusqu'à {args.maxIterations * len(cases)} appels au LLM partagé. "
        "Validation : refus."
    )

    results = []
    for case in cases:
        # Magasin neuf pour chaque cas : aucun cas n'influence le suivant.
        registry = ToolRegistry(buildToolbox(NoteStore.fromFile(args.notes)))
        try:
            trace = runAgent(
                client=client,
                registry=registry,
                approval=DenyAll(),
                systemPrompt=systemPrompt,
                task=case.task,
                maxIterations=args.maxIterations,
            )
        except ModelCallError as error:
            print(f"{case.caseId} : appel modèle échoué — {error}", file=sys.stderr)
            return 1

        result = gradeCase(case, trace)
        results.append(result)
        flags = []
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
        "nb_cas": len(results),
        "parametres": {
            "max_iterations": args.maxIterations,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reflexion": args.reflexion,
            "approbation": "refus",
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
    print(f"Outil interdit appelé : {summary['outil_interdit_appele']}")
    print(f"Plafond atteint       : {summary['limite_iterations_atteinte']}")
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
