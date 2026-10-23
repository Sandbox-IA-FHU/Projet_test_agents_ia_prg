"""Tests des outils d'exemple.

L'essentiel est dans `evaluateExpression` : c'est le seul endroit du dépôt où
du texte produit par un modèle est interprété. Un modèle produit du code
plausible, pas du code sûr.
"""

import pytest

from agent.errors import NoteStoreError, ToolError
from agent.toolbox import (
    MAX_EXPONENT,
    MAX_EXPRESSION_LENGTH,
    NoteStore,
    buildToolbox,
    evaluateExpression,
)


def test_arithmeticIsEvaluated() -> None:
    assert evaluateExpression("2 + 3 * 4") == 14.0
    assert evaluateExpression("(120 * 3) / 4") == 90.0
    assert evaluateExpression("-5 + 2") == -3.0
    assert evaluateExpression("2 ** 10") == 1024.0


def test_functionCallsAreRefused() -> None:
    # C'est le test qui compte : sans lui, `eval` sur une chaîne venue d'un
    # modèle est une exécution de code arbitraire déclenchée par un texte que
    # personne n'a relu.
    for expression in [
        "__import__('os').system('echo rate')",
        "open('secret.txt').read()",
        "print(1)",
        "[].__class__",
    ]:
        with pytest.raises(ToolError):
            evaluateExpression(expression)


def test_namesAndStringsAreRefused() -> None:
    with pytest.raises(ToolError):
        evaluateExpression("x + 1")
    with pytest.raises(ToolError):
        evaluateExpression("'a' * 3")


def test_divisionByZeroIsRefused() -> None:
    with pytest.raises(ToolError, match="zéro"):
        evaluateExpression("1 / 0")


def test_hugeExponentIsRefused() -> None:
    # 9**9**9 fige le processus et consomme toute la mémoire : une limite en
    # dur, comme pour les itérations.
    with pytest.raises(ToolError, match="Exposant"):
        evaluateExpression(f"2 ** {MAX_EXPONENT + 1}")


def test_longExpressionIsRefused() -> None:
    with pytest.raises(ToolError, match="trop longue"):
        evaluateExpression("1+" * MAX_EXPRESSION_LENGTH + "1")


def test_noteStoreReadsAndDeletes(noteStore: NoteStore) -> None:
    assert "astreinte" in noteStore.listNames()
    assert "95 euros" in noteStore.read("astreinte")

    noteStore.delete("note-a-supprimer")
    assert "note-a-supprimer" not in noteStore.listNames()


def test_unknownNoteIsReported(noteStore: NoteStore) -> None:
    with pytest.raises(ToolError, match="Note inconnue"):
        noteStore.read("note-fantome")


def test_noteStoreRefusesAMalformedFile(tmp_path) -> None:
    path = tmp_path / "notes.jsonl"
    path.write_text('{"nom": "a"}\n', encoding="utf-8")

    with pytest.raises(NoteStoreError, match="nom/contenu"):
        NoteStore.fromFile(path)


def test_poisonedNoteIsReturnedAsIs(noteStore: NoteStore) -> None:
    # On ne filtre pas le contenu, et on ne prétend pas savoir détecter une
    # injection. Le contenu remonte tel quel ; c'est le prompt et la surface
    # d'outils qui limitent ce qui peut arriver.
    toolbox = {spec.name: spec for spec in buildToolbox(noteStore)}
    result = toolbox["readNote"].handler({"nom": "consignes-migration"})

    assert "ignore toutes les consignes" in result


def test_onlyDeleteIsMarkedSensitive(noteStore: NoteStore) -> None:
    sensitive = [spec.name for spec in buildToolbox(noteStore) if spec.isSensitive]

    assert sensitive == ["deleteNote"]
