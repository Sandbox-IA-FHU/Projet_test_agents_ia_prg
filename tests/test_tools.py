"""Tests du registre d'outils."""

import pytest

from agent.errors import UnknownToolError
from agent.models import ToolSpec
from agent.tools import ToolRegistry

SCHEMA = {"type": "object", "properties": {}, "required": []}


def buildSpec(name: str, sensitive: bool = False) -> ToolSpec:
    """Outil minimal pour les tests."""
    return ToolSpec(
        name=name,
        description="Outil de test.",
        inputSchema=SCHEMA,
        handler=lambda arguments: "ok",
        isSensitive=sensitive,
    )


def test_registryExposesSchemas(registry: ToolRegistry) -> None:
    schemas = registry.schemas()
    functions = [schema["function"] for schema in schemas]

    assert all(schema["type"] == "function" for schema in schemas)
    assert [function["name"] for function in functions] == registry.names()
    # Le schéma envoyé au modèle et la fonction exécutée viennent du même
    # objet : c'est ce qui les empêche de diverger.
    assert all("parameters" in function for function in functions)
    assert all("description" in function for function in functions)


def test_sensitiveToolsAreListed(registry: ToolRegistry) -> None:
    assert registry.sensitiveNames() == ["deleteNote"]


def test_unknownToolIsNamedInTheError(registry: ToolRegistry) -> None:
    with pytest.raises(UnknownToolError, match="sendEmail"):
        registry.get("sendEmail")


def test_duplicateToolsAreRefused() -> None:
    with pytest.raises(ValueError, match="double"):
        ToolRegistry([buildSpec("listNotes"), buildSpec("listNotes")])


def test_sensitiveToolDescriptionWarnsTheModel(registry: ToolRegistry) -> None:
    # Le modèle doit pouvoir tenir compte du caractère irréversible AVANT de
    # demander l'action, pas seulement après un refus.
    description = registry.get("deleteNote").description.lower()

    assert "irréversible" in description
    assert "validation" in description
