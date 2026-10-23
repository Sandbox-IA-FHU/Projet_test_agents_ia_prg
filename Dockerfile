# Image de l'agent : Python 3.13 et uv, dépendances figées par uv.lock.
# Pas de GPU, pas de bibliothèque de modèle : l'agent appelle le LLM par API.
#
# Tag exact + empreinte : la même image partout, même si le tag est republié.
# Pour monter de version, relever le tag ET l'empreinte réellement publiés.
FROM python:3.13.17-slim-trixie@sha256:fe14fd57a4c0361110eaa0c284112b189750bcb43fb04bb5d1ee7b7744027ccf

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /bin/

# L'environnement virtuel vit hors de /app : compose monte le dépôt sur /app
# pour les tests et le lint, et ce montage ne doit pas le masquer.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances d'abord : cette couche ne se reconstruit que si uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY . .
RUN uv sync --locked

# Utilisateur non root par défaut. compose.yaml le remplace par AGENT_UID et
# AGENT_GID pour pouvoir écrire dans le dépôt monté (voir son commentaire).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin agent
USER agent

CMD ["python", "scripts/run_agent.py", "--help"]
