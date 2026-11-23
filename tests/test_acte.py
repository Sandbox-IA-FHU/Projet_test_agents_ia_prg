"""Tests de la lecture d'un acte Word et de sa copie commentée.

Le point central : l'acte d'origine n'est jamais modifié, et le texte de la
copie est identique à celui de l'acte. Seuls des commentaires et le réglage
« suivi des modifications » sont ajoutés.
"""

import hashlib
from pathlib import Path

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from agent.acte import (
    COMMENT_AUTHOR,
    MAX_EXCERPT_LENGTH,
    describeParagraphs,
    openActe,
    readParagraphs,
    searchParagraphs,
    writeCommentedCopy,
)
from agent.errors import ActeError


def buildActe(path: Path, texts: list[str]) -> Path:
    """Fabrique un petit acte, un paragraphe par texte."""
    document = docx.Document()
    for text in texts:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def fingerprint(path: Path) -> str:
    """Empreinte du fichier, pour prouver qu'il n'a pas changé d'un octet."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contentControlsAndTablesAreRead(tmp_path: Path) -> None:
    # Les outils de génération d'actes placent souvent les zones variables
    # dans des champs de formulaire (w:sdt), que document.paragraphs ignore.
    document = docx.Document()
    document.add_paragraph("Article 1 – Forme")
    blockControl = parse_xml(
        f"<w:sdt {nsdecls('w')}><w:sdtContent><w:p><w:r>"
        "<w:t>Dénomination : EARL DU CHAMP FICTIF</w:t>"
        "</w:r></w:p></w:sdtContent></w:sdt>"
    )
    document.element.body.insert(1, blockControl)
    inline = document.add_paragraph("Capital : ")
    inline._p.append(
        parse_xml(
            f"<w:sdt {nsdecls('w')}><w:sdtContent><w:r><w:t>7 500 euros</w:t>"
            "</w:r></w:sdtContent></w:sdt>"
        )
    )
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Gérant : Camille Exemple"
    path = tmp_path / "acte.docx"
    document.save(str(path))

    texts = [paragraph.text for paragraph in readParagraphs(openActe(path))]

    assert "Dénomination : EARL DU CHAMP FICTIF" in texts
    assert "Capital : 7 500 euros" in texts
    assert "Gérant : Camille Exemple" in texts


def test_notAWordFileIsRefusedClearly(tmp_path: Path) -> None:
    path = tmp_path / "acte.docx"
    path.write_text("pas un document Word", encoding="utf-8")

    with pytest.raises(ActeError, match="lisible"):
        openActe(path)


def test_searchIgnoresCaseAndNumbersParagraphs(tmp_path: Path) -> None:
    path = buildActe(tmp_path / "acte.docx", ["Préambule", "Le GÉRANT est nommé."])

    result = searchParagraphs(readParagraphs(openActe(path)), ["gérant"])

    assert result == "[1] Le GÉRANT est nommé."


def test_emptySearchTellsTheModelWhatToDo(tmp_path: Path) -> None:
    # Un résultat vide sans indication fait reboucler le modèle sur la même
    # recherche : l'outil doit dire quoi essayer ensuite.
    path = buildActe(tmp_path / "acte.docx", ["Préambule"])

    result = searchParagraphs(readParagraphs(openActe(path)), ["président"])

    assert "lireActe" in result


def test_longActeIsTruncatedWithAHint(tmp_path: Path) -> None:
    path = buildActe(tmp_path / "acte.docx", ["x" * 500] * 20)

    result = describeParagraphs(readParagraphs(openActe(path)))

    assert len(result) < MAX_EXCERPT_LENGTH + 200
    assert "aPartirDe=" in result


def test_originalIsNeverModified(tmp_path: Path) -> None:
    acte = buildActe(tmp_path / "acte.docx", ["Article 1", "Une entreprise agricole."])
    before = fingerprint(acte)

    writeCommentedCopy(acte, tmp_path / "sortie", [(1, "[MAJEUR] terme")])

    assert fingerprint(acte) == before


def test_copyKeepsTheTextAndAddsCommentsAndTrackChanges(tmp_path: Path) -> None:
    acte = buildActe(tmp_path / "acte.docx", ["Article 1", "Une entreprise agricole."])

    copy = writeCommentedCopy(
        acte, tmp_path / "sortie", [(1, "[MAJEUR] terme"), (None, "[BLOQUANT] fiche")]
    )

    original = [p.text for p in readParagraphs(openActe(acte))]
    copied = openActe(copy)
    assert [p.text for p in readParagraphs(copied)] == original
    comments = list(copied.comments)
    assert [comment.text for comment in comments] == [
        "[MAJEUR] terme",
        "[BLOQUANT] fiche",
    ]
    assert {comment.author for comment in comments} == {COMMENT_AUTHOR}
    assert copied.settings.element.find(qn("w:trackRevisions")) is not None


def test_copyIsNeverOverwritten(tmp_path: Path) -> None:
    acte = buildActe(tmp_path / "acte.docx", ["Article 1"])
    output = tmp_path / "sortie"

    first = writeCommentedCopy(acte, output, [(0, "a")])
    firstPrint = fingerprint(first)
    second = writeCommentedCopy(acte, output, [(0, "b")])

    assert first.name == "acte-relu.docx"
    assert second.name == "acte-relu-2.docx"
    assert fingerprint(first) == firstPrint
