"""Lance l'interface web : déposer un document Word, récupérer une copie modifiée.

Sur un poste :

    uv run --env-file .env python scripts/interface_web.py
    # puis ouvrir http://127.0.0.1:8080

Sur le serveur de staging, le port n'est publié que le temps de la session,
et seulement sur 127.0.0.1 (VS Code le redirige vers votre navigateur) :

    docker compose run --rm -p 127.0.0.1:8080:8080 \\
      agent-projet_test_agents_ia_prg python scripts/interface_web.py --hote 0.0.0.0

Ici la validation se fait sur la page (boutons Valider / Refuser) : la
variable APPROBATION ne s'applique pas. Les documents déposés et leurs copies
restent dans `data/interface/` (ignoré par Git) jusqu'à ce qu'on l'efface.
"""

import argparse
import logging
import sys
from pathlib import Path

from agent.client import OpenAICompatibleClient
from agent.config import loadConfig
from agent.errors import ConfigError
from agent.web import WebApp, serve

DEFAULT_PROMPT = Path("prompts/agent_v2.md")
DEFAULT_WORK_ROOT = Path("data/interface")
DEFAULT_PORT = 8080


def buildParser() -> argparse.ArgumentParser:
    """Décrit les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Lance l'interface web.")
    parser.add_argument(
        "--hote",
        default="127.0.0.1",
        help=(
            "Adresse d'écoute (défaut : 127.0.0.1, ce poste seulement). "
            "0.0.0.0 uniquement dans un conteneur dont le port est publié "
            "sur 127.0.0.1."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main() -> int:
    """Point d'entrée. Rend 0 à l'arrêt normal (Ctrl+C), 1 sur une erreur."""
    args = buildParser().parse_args()

    # 1. Configuration : seule l'adresse du LLM est utile ici. Les dossiers
    #    de documents sont créés par l'interface, un par demande.
    try:
        config = loadConfig()
    except ConfigError as error:
        print(f"Configuration : {error}", file=sys.stderr)
        return 1
    logging.basicConfig(level=config.logLevel, format="%(levelname)s %(message)s")

    # 2. L'état de l'interface : le client du LLM, le prompt, et le dossier
    #    où ranger les documents déposés.
    app = WebApp(
        client=OpenAICompatibleClient(
            baseUrl=config.baseUrl, model=config.model, apiKey=config.apiKey
        ),
        systemPrompt=DEFAULT_PROMPT.read_text(encoding="utf-8"),
        workRoot=DEFAULT_WORK_ROOT,
    )

    # 3. Le serveur, jusqu'à Ctrl+C.
    print(f"Interface sur http://127.0.0.1:{args.port} — Ctrl+C pour arrêter.")
    try:
        serve(app, args.hote, args.port)
    except KeyboardInterrupt:
        print("\nInterface arrêtée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
