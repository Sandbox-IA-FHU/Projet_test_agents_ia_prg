"""Lecture d'un acte Word, et écriture de sa copie commentée.

Deux règles bornent tout ce module :

1. **L'acte d'origine n'est jamais écrit.** On le lit en mémoire ; la copie
   commentée s'écrit dans un dossier de sortie, sous un autre nom, et une
   copie existante n'est jamais écrasée (on numérote : `-relu-2`, `-relu-3`…).
2. **Le texte de l'acte n'est jamais modifié, même dans la copie.** On n'y
   ajoute que des commentaires Word et le réglage « suivi des modifications »,
   pour que les corrections faites ensuite par le juriste restent tracées.
   Corriger l'acte est le travail du juriste, pas celui de l'agent.

Indépendance vis-à-vis de l'outil de production des actes : on ne
lit que le `.docx` final, et on le lit au niveau XML plutôt qu'avec
`document.paragraphs`. Ce dernier ignore les paragraphes placés dans des
**champs de formulaire** (« contrôles de contenu », balise `w:sdt`), que les
outils de génération d'actes utilisent volontiers pour les zones variables
(dénomination, capital…). Les tableaux sont lus aussi.

Limites connues : en-têtes, pieds de page et notes de bas de page ne sont pas
lus. Le texte d'une modification déjà suivie dans l'acte (`w:ins`) est lu ; le
texte supprimé (`w:del`) ne l'est pas, comme si les révisions étaient
acceptées.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path

import docx
from docx.document import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from lxml.etree import _Element

from agent.errors import ActeError

ACTE_SUFFIX = ".docx"
COPY_SUFFIX = "-relu"

# Auteur affiché dans le volet « Commentaires » de Word. Le juriste voit ainsi
# d'un coup d'œil ce qui vient de la machine et ce qui vient d'un collègue.
COMMENT_AUTHOR = "Relecture automatique"
COMMENT_INITIALS = "RA"

# Un résultat d'outil est tronqué à 4000 caractères par la boucle
# (`loop.MAX_RESULT_LENGTH`) : on s'arrête avant, en disant comment lire la
# suite, plutôt que de laisser couper au milieu d'un paragraphe.
MAX_EXCERPT_LENGTH = 3500

# Réglages qui précèdent `w:trackRevisions` dans `settings.xml`, dans l'ordre
# imposé par le schéma Word (ECMA-376, CT_Settings). Word refuse d'ouvrir un
# fichier dont les réglages sont dans le désordre.
SETTINGS_BEFORE_TRACK_REVISIONS = (
    "w:writeProtection",
    "w:view",
    "w:zoom",
    "w:removePersonalInformation",
    "w:removeDateAndTime",
    "w:doNotDisplayPageBoundaries",
    "w:displayBackgroundShape",
    "w:printPostScriptOverText",
    "w:printFractionalCharacterWidth",
    "w:printFormsData",
    "w:embedTrueTypeFonts",
    "w:embedSystemFonts",
    "w:saveSubsetFonts",
    "w:saveFormsData",
    "w:mirrorMargins",
    "w:alignBordersAndEdges",
    "w:bordersDoNotSurroundHeader",
    "w:bordersDoNotSurroundFooter",
    "w:gutterAtTop",
    "w:hideSpellingErrors",
    "w:hideGrammaticalErrors",
    "w:activeWritingStyle",
    "w:proofState",
    "w:formsDesign",
    "w:attachedTemplate",
    "w:linkStyles",
    "w:stylePaneFormatFilter",
    "w:stylePaneSortMethod",
    "w:documentType",
    "w:mailMerge",
    "w:revisionView",
)

# Espace de noms « markup compatibility » : Word y range deux versions d'un
# même contenu (`mc:Choice` et `mc:Fallback`, par exemple une zone de texte).
# On ne lit que la première, sinon le texte apparaîtrait deux fois.
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


@dataclass(frozen=True)
class ActeParagraph:
    """Un paragraphe de l'acte, avec le numéro que voient l'agent et le juriste.

    Le numéro est la position du paragraphe dans l'ordre de lecture, paragraphes
    vides compris : relire le même fichier redonne les mêmes numéros, c'est ce
    qui permet de retrouver le paragraphe au moment de poser le commentaire.
    """

    index: int
    text: str
    element: _Element


def _ownerParagraph(element: _Element) -> _Element | None:
    """Le paragraphe `w:p` le plus proche qui contient cet élément."""
    return next(element.iterancestors(qn("w:p")), None)


def _isInFallback(element: _Element) -> bool:
    """Vrai si l'élément est dans la version de secours d'un contenu Word."""
    return any(ancestor.tag == MC_FALLBACK for ancestor in element.iterancestors())


def _paragraphText(paragraph: _Element) -> str:
    """Texte d'un paragraphe, champs de formulaire et liens compris.

    On ne garde que le texte dont ce paragraphe est le plus proche parent : un
    paragraphe imbriqué (zone de texte ancrée dans le paragraphe) est lu à part,
    sous son propre numéro.
    """
    parts: list[str] = []
    for node in paragraph.iter(qn("w:t"), qn("w:tab")):
        if _ownerParagraph(node) is not paragraph:
            continue
        # Une tabulation devient une espace, pour que « Capital :<tab>7 500 »
        # se lise comme une phrase.
        parts.append((node.text or "") if node.tag == qn("w:t") else " ")
    return "".join(parts)


def readParagraphs(document: Document) -> list[ActeParagraph]:
    """Tous les paragraphes du corps de l'acte, dans l'ordre de lecture.

    `iter` parcourt tout l'arbre XML du corps : paragraphes simples, cellules
    de tableaux, champs de formulaire, zones de texte.
    """
    body = document.element.body
    paragraphs = [
        element for element in body.iter(qn("w:p")) if not _isInFallback(element)
    ]
    return [
        ActeParagraph(index=index, text=_paragraphText(element), element=element)
        for index, element in enumerate(paragraphs)
    ]


def openActe(path: Path) -> Document:
    """Ouvre un acte en lecture, en mémoire. Le fichier n'est jamais réécrit."""
    if path.suffix.lower() != ACTE_SUFFIX:
        raise ActeError(f"{path.name} : attendu un document Word {ACTE_SUFFIX}.")
    if not path.is_file():
        raise ActeError(f"Acte introuvable : {path}")
    try:
        return docx.Document(str(path))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as error:
        raise ActeError(f"{path.name} n'est pas un document Word lisible.") from error


# --- Ce que voit l'agent ---------------------------------------------------


def describeParagraphs(paragraphs: list[ActeParagraph], startIndex: int = 0) -> str:
    """Texte de l'acte, un paragraphe numéroté par ligne, à partir d'un numéro.

    Les paragraphes vides gardent leur numéro mais ne sont pas affichés : ils
    n'apprennent rien à l'agent et coûtent des jetons à chaque tour.
    """
    lines: list[str] = []
    length = 0
    for paragraph in paragraphs[startIndex:]:
        if not paragraph.text.strip():
            continue
        line = f"[{paragraph.index}] {paragraph.text}"
        if length + len(line) > MAX_EXCERPT_LENGTH:
            lines.append(
                f"… suite tronquée : appeler lireActe avec aPartirDe={paragraph.index}."
            )
            break
        lines.append(line)
        length += len(line) + 1
    return "\n".join(lines) if lines else "Aucun paragraphe à partir de ce numéro."


def searchParagraphs(paragraphs: list[ActeParagraph], terms: list[str]) -> str:
    """Paragraphes qui contiennent au moins un des termes, sans tenir compte
    de la casse. Rend un texte lisible par l'agent, tronqué si besoin."""
    wanted = [term.casefold() for term in terms if term.strip()]
    matches = [
        paragraph
        for paragraph in paragraphs
        if any(term in paragraph.text.casefold() for term in wanted)
    ]
    if not matches:
        # Un résultat vide apprend quelque chose au modèle à condition de le
        # dire, et de lui dire quoi faire : sinon il relance la même recherche.
        return (
            f"Aucun paragraphe ne contient {terms}. Essaie un autre terme, ou "
            "lis l'acte avec lireActe."
        )
    lines: list[str] = []
    length = 0
    for paragraph in matches:
        line = f"[{paragraph.index}] {paragraph.text}"
        if length + len(line) > MAX_EXCERPT_LENGTH:
            lines.append(
                f"… {len(matches) - len(lines)} autre(s) paragraphe(s) : affine "
                "la recherche avec un terme plus précis."
            )
            break
        lines.append(line)
        length += len(line) + 1
    return "\n".join(lines)


# --- La copie commentée ------------------------------------------------------


def _anchorRuns(paragraph: ActeParagraph, document: Document) -> list[Run]:
    """Les morceaux de texte (« runs ») du paragraphe, pour y ancrer un
    commentaire. Vide si le paragraphe n'a aucun texte."""
    parent = Paragraph(paragraph.element, document._body)
    return [
        Run(element, parent)
        for element in paragraph.element.iter(qn("w:r"))
        if _ownerParagraph(element) is paragraph.element
        and element.find(qn("w:t")) is not None
    ]


def enableTrackChanges(document: Document) -> None:
    """Active le suivi des modifications dans la copie.

    Le juriste qui corrige la copie voit ainsi ses propres corrections tracées,
    à côté des commentaires de la relecture. Le texte de l'acte, lui, n'est pas
    touché. python-docx n'a pas de fonction pour ce réglage : on pose
    l'élément `w:trackRevisions` nous-mêmes, à sa place dans le schéma.
    """
    settings = document.settings.element
    if settings.find(qn("w:trackRevisions")) is not None:
        return
    # On l'insère juste après le dernier réglage qui doit le précéder, ou en
    # tête s'il n'y en a aucun.
    predecessors = {qn(tag) for tag in SETTINGS_BEFORE_TRACK_REVISIONS}
    position = 0
    for index, child in enumerate(settings):
        if child.tag in predecessors:
            position = index + 1
    settings.insert(position, settings.makeelement(qn("w:trackRevisions"), {}))


def freeCopyPath(actePath: Path, outputDir: Path) -> Path:
    """Chemin de la copie : `<acte>-relu.docx`, puis `-relu-2`… si elle existe.

    Une relecture relancée après correction ne doit jamais effacer la
    précédente : le juriste peut vouloir comparer.
    """
    candidate = outputDir / f"{actePath.stem}{COPY_SUFFIX}{ACTE_SUFFIX}"
    number = 2
    while candidate.exists():
        candidate = outputDir / f"{actePath.stem}{COPY_SUFFIX}-{number}{ACTE_SUFFIX}"
        number += 1
    if candidate.resolve() == actePath.resolve():
        # Impossible avec le suffixe ajouté, mais c'est la règle qui compte :
        # on le vérifie plutôt que de le supposer.
        raise ActeError("La copie ne peut pas avoir le chemin de l'acte d'origine.")
    return candidate


def writeCommentedCopy(
    actePath: Path, outputDir: Path, comments: list[tuple[int | None, str]]
) -> Path:
    """Écrit la copie de l'acte avec un commentaire Word par point relevé.

    `comments` : liste de (numéro de paragraphe, texte du commentaire). Un point
    sans paragraphe (par exemple « la dénomination n'apparaît nulle part ») est
    ancré sur le premier paragraphe qui contient du texte.

    L'acte est relu depuis le disque : la copie part du fichier d'origine, pas
    d'un objet qui aurait pu être modifié en mémoire.
    """
    document = openActe(actePath)
    paragraphs = readParagraphs(document)
    firstWithText = next((p for p in paragraphs if _anchorRuns(p, document)), None)
    if firstWithText is None:
        raise ActeError(f"{actePath.name} ne contient aucun texte à commenter.")

    for paragraphIndex, text in comments:
        target = firstWithText
        if paragraphIndex is not None and 0 <= paragraphIndex < len(paragraphs):
            target = paragraphs[paragraphIndex]
        runs = _anchorRuns(target, document) or _anchorRuns(firstWithText, document)
        # Le commentaire couvre tout le paragraphe : du premier au dernier run.
        document.add_comment(
            runs, text=text, author=COMMENT_AUTHOR, initials=COMMENT_INITIALS
        )

    enableTrackChanges(document)
    outputDir.mkdir(parents=True, exist_ok=True)
    copyPath = freeCopyPath(actePath, outputDir)
    document.save(str(copyPath))
    return copyPath
