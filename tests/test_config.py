"""Tests de la configuration."""

import pytest

from agent.config import APPROVAL_DENY, loadConfig
from agent.errors import ConfigError

VARIABLES = (
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_MODEL_REVISION",
    "LOG_LEVEL",
    "APPROBATION",
)


def setValidConfig(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pose une configuration minimale valide et efface le reste."""
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://serveur-de-test:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "altoneo-llm")


def test_missingBaseUrlFailsImmediately(monkeypatch: pytest.MonkeyPatch) -> None:
    setValidConfig(monkeypatch)
    monkeypatch.delenv("LLM_BASE_URL")

    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        loadConfig()


def test_baseUrlWithoutSchemeIsRefused(monkeypatch: pytest.MonkeyPatch) -> None:
    setValidConfig(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "serveur-de-test:8000/v1")

    with pytest.raises(ConfigError, match="http"):
        loadConfig()


def test_missingModelFailsImmediately(monkeypatch: pytest.MonkeyPatch) -> None:
    setValidConfig(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "  ")

    with pytest.raises(ConfigError, match="LLM_MODEL"):
        loadConfig()


def test_emptyApiKeyIsAccepted(monkeypatch: pytest.MonkeyPatch) -> None:
    # Le LLM local n'a pas de clé aujourd'hui : une clé vide n'est pas une
    # erreur de configuration.
    setValidConfig(monkeypatch)

    config = loadConfig()

    assert config.apiKey == ""
    assert config.modelRevision == ""


def test_invalidLogLevelIsRefused(monkeypatch: pytest.MonkeyPatch) -> None:
    setValidConfig(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "BAVARD")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        loadConfig()


def test_invalidApprovalModeIsRefused(monkeypatch: pytest.MonkeyPatch) -> None:
    setValidConfig(monkeypatch)
    monkeypatch.setenv("APPROBATION", "toujours")

    with pytest.raises(ConfigError, match="APPROBATION"):
        loadConfig()


def test_approvalDefaultsToRefusal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Une valeur par défaut permissive finit par être utilisée sans y penser.
    setValidConfig(monkeypatch)

    assert loadConfig().approvalMode == APPROVAL_DENY
