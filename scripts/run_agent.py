"""Relit un acte Word et produit une copie commentée et un rapport.

    uv run --env-file .env python scripts/run_agent.py \\
        --acte data/relecture/entree/statuts.docx \\
        --fiche data/relecture/entree/fiche.json --type-acte statuts

    # Essai sur un acte fictif du jeu d'évaluation, sans aucun fichier réel :
    uv run --env-file .env python scripts/run_agent.py --demo earl-entreprise

Entrées : l'acte (.docx, quel que soit l'outil qui l'a produit), la fiche
société (JSON : denomination, forme, capital, siege, dirigeants) et la liste
de contrôles (TOML, `controles/controles.toml` par défaut).

Sorties, dans `RELECTURE_SORTIE` : `<acte>-relu.docx`, copie de l'acte avec
un commentaire Word par point et le suivi des modifications activé, et
`<acte>-relu-rapport.md`, le rapport trié par gravité. **L'acte d'origine
n'est jamais modifié**, et rien n'est jamais écrasé.

Ce script affiche des compteurs, des identifiants de contrôles et des numéros
de paragraphe ; jamais le texte de l'acte ni la réflexion du modèle. Le
contenu est dans le rapport, qui reste dans `data/`, ignoré par Git.
"""

import argparse
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

from agent.client import REASONING_EFFORT, OpenAICompatibleClient
from agent.config import loadConfig
from agent.errors import ActeError, ConfigError, ModelCallError, ReviewInputError
from agent.evaluation import loadReviewSet, writeCaseActe
from agent.loop import MAX_ITERATIONS, summarizeTrace
from agent.models import STOP_ITERATION_LIMIT
from agent.relecture import (
    SEVERITIES,
    SEVERITY_LABELS,
    companySheetFromDict,
    loadChecks,
    loadCompanySheet,
    reviewActe,
)

DEFAULT_CHECKS = Path("controles/controles.toml")
DEFAULT_PROMPT = Path("prompts/relecture_v1.md")
DEMO_SET = Path("evaluations/jeux/relecture_demo.jsonl")


def buildParser() -> argparse.ArgumentParser:
    """Décrit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Relit un acte Word.")
    parser.add_argument("--acte", type=Path, help="Acte à relire (.docx).")
    parser.add_argument("--fiche", type=Path, help="Fiche société (.json).")
    parser.add_argument(
        "--type-acte",
        dest="acteType",
        default="statuts",
        help="Type d'acte, nommé comme dans la liste de contrôles (défaut : statuts).",
    )
    parser.add_argument(
        "--controles",
        type=Path,
        default=DEFAULT_CHECKS,
        help=f"Liste de contrôles TOML (défaut : {DEFAULT_CHECKS}).",
    )
    parser.add_argument(
        "--demo",
        metavar="CAS_ID",
        help="Relit l'acte fictif d'un cas du jeu d'évaluation, au lieu de --acte.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        dest="maxIterations",
        help=f"Plafond d'itérations (défaut : {MAX_ITERATIONS}).",
    )
    return parser


def main() -> int:
    """Point d'entrée. Rend 0 en succès, 1 sur une erreur attendue."""
    args = buildParser().parse_args()
    if not args.demo and not (args.acte and args.fiche):
        print("Indiquer --acte et --fiche, ou --demo CAS_ID.", file=sys.stderr)
        return 1

    # 1. Configuration : adresse du LLM, dossier de sortie (fichier .env).
    try:
        config = loadConfig()
    except ConfigError as error:
        print(f"Configuration : {error}", file=sys.stderr)
        return 1
    if not config.reviewOutputDir:
        print(
            "Configuration : RELECTURE_SORTIE est vide. Y mettre le dossier où "
            "écrire la copie commentée et le rapport, par exemple "
            "data/relecture/sortie (voir .env.example).",
            file=sys.stderr,
        )
        return 1

    logging.basicConfig(level=config.logLevel, format="%(levelname)s %(message)s")

    client = OpenAICompatibleClient(
        baseUrl=config.baseUrl, model=config.model, apiKey=config.apiKey
    )
    # Le dossier temporaire ne sert qu'à --demo, pour y fabriquer l'acte
    # fictif ; il disparaît à la fin. La copie et le rapport, eux, vont dans
    # RELECTURE_SORTIE.
    with tempfile.TemporaryDirectory() as workDir:
        try:
            # 2. Les entrées : l'acte, la fiche société, la liste de contrôles.
            checks = loadChecks(args.controles)
            if args.demo:
                cases = {case.caseId: case for case in loadReviewSet(DEMO_SET)}
                if args.demo not in cases:
                    print(
                        f"Cas inconnu. Cas disponibles : {sorted(cases)}",
                        file=sys.stderr,
                    )
                    return 1
                case = cases[args.demo]
                actePath = writeCaseActe(case, Path(workDir))
                sheet = companySheetFromDict(case.sheet, args.demo)
                acteType = case.acteType
            else:
                actePath = args.acte
                sheet = loadCompanySheet(args.fiche)
                acteType = args.acteType

            print(
                f"Modèle {config.model}, réflexion {REASONING_EFFORT}, plafond "
                f"{args.maxIterations} itérations. Acte : {actePath.name}, "
                f"{acteType}, forme {sheet.forme}."
            )

            # 3. La relecture : contrôles du code, puis agent, puis écriture de
            #    la copie commentée et du rapport (relecture.reviewActe).
            result = reviewActe(
                client=client,
                actePath=actePath,
                sheet=sheet,
                checks=checks,
                acteType=acteType,
                systemPrompt=DEFAULT_PROMPT.read_text(encoding="utf-8"),
                outputDir=Path(config.reviewOutputDir),
                today=date.today().isoformat(),
                maxIterations=args.maxIterations,
            )
        except (ReviewInputError, ActeError) as error:
            print(f"Entrées : {error}", file=sys.stderr)
            return 1
        except ModelCallError as error:
            print(f"Appel modèle : {error}", file=sys.stderr)
            return 1

    # 4. Un résumé sans contenu : identifiants, gravités, numéros.
    print()
    for severity in SEVERITIES:
        points = [f for f in result.findings if f.severity == severity]
        if points:
            print(f"{SEVERITY_LABELS[severity]} ({len(points)})")
            for finding in points:
                where = "acte" if finding.paragraph is None else f"§{finding.paragraph}"
                print(f"  {where:>6}  {finding.checkId}  [{finding.origin}]")
    if not result.findings:
        print("Aucun point signalé.")
    print()
    print(f"Copie commentée : {result.copyPath}")
    print(f"Rapport         : {result.reportPath}")
    print()
    print(summarizeTrace(result.trace))
    print(f"latence : {result.trace.latencySeconds:.1f} s")

    if result.trace.stoppedReason == STOP_ITERATION_LIMIT:
        print()
        print("ATTENTION : plafond d'itérations atteint, relecture incomplète.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
