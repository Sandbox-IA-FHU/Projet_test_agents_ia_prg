"""Interface web : déposer un document Word, demander une modification,
valider l'écriture, télécharger la copie.

Bibliothèque standard uniquement (`http.server`) : une page, un formulaire et
quatre adresses ne justifient pas un framework web, ni une dépendance de plus.

Le parcours d'une demande :

    1. GET  /                        formulaire : document + demande
    2. POST /taches                  dépôt ; l'agent démarre dans un fil à part
    3. GET  /taches/<id>             page de suivi, rechargée toutes les 2 s
    4. POST /taches/<id>/validation  « Valider » ou « Refuser » l'écriture
    5. GET  /taches/<id>/copie/<nom> téléchargement de la copie modifiée

Les règles de l'agent ne changent pas : il ne dispose que des trois outils
Word, l'écriture passe par la validation (ici, les boutons de la page), et
l'original déposé n'est jamais modifié. Chaque demande a son propre dossier
(`entree/` et `sortie/`), sous un dossier de travail ignoré par Git.
"""

import html
import json
import logging
import threading
import uuid
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from agent.approval import PendingApproval
from agent.client import AgentClient
from agent.documents import DOCUMENT_SUFFIX, DocumentFolder, buildDocumentTools
from agent.errors import ModelCallError, UploadError
from agent.loop import runAgent
from agent.models import STOP_ITERATION_LIMIT, ToolCall
from agent.tools import ToolRegistry

# Au-delà, le dépôt est refusé avant d'être lu en entier.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

STATUS_RUNNING = "en cours"
STATUS_DONE = "terminé"
STATUS_FAILED = "échec"

COPY_SUFFIX = "-modifie"

# La tâche transmise au modèle. Le nom de la copie est fixé ici plutôt que
# laissé au modèle : la personne sait d'avance quel fichier elle récupérera.
TASK_TEMPLATE = (
    "Document à modifier : {nom}.\nDemande : {demande}\nNomme la copie {copie}."
)

logger = logging.getLogger(__name__)


class WebTask:
    """Une demande déposée : son dossier, sa validation, son résultat.

    Écrite par le fil de l'agent, lue par les fils du serveur web : seuls
    des champs simples, remplacés d'un bloc, jamais modifiés en place.
    """

    def __init__(self, taskId: str, workDir: Path, documentName: str) -> None:
        self.taskId = taskId
        self.documentName = documentName
        # Le dossier d'entrée doit exister avant de construire `DocumentFolder`.
        # Pas de `exist_ok` : un identifiant déjà pris est une erreur.
        (workDir / "entree").mkdir(parents=True)
        self.folder = DocumentFolder(workDir / "entree", workDir / "sortie")
        self.approval = PendingApproval()
        self.status = STATUS_RUNNING
        self.answer = ""

    def copies(self) -> list[str]:
        """Copies écrites par l'agent, prêtes à télécharger."""
        if not self.folder.outputDir.is_dir():
            return []
        return sorted(
            path.name
            for path in self.folder.outputDir.iterdir()
            if path.suffix == DOCUMENT_SUFFIX
        )


def safeDocumentName(filename: str) -> str:
    """Nom de fichier déposé, ramené à un simple nom .docx sans dossier.

    Le nom vient du navigateur : il peut contenir un chemin (« C:\\…\\a.docx »)
    ou viser autre chose qu'un document Word. On ne garde que la fin.
    """
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name.lower().endswith(DOCUMENT_SUFFIX) or name.startswith((".", "~$")):
        raise UploadError("Seuls les documents Word (.docx) sont acceptés.")
    # Extension remise en minuscules : les outils Word ne voient que « .docx ».
    return name[: -len(DOCUMENT_SUFFIX)] + DOCUMENT_SUFFIX


def parseUpload(contentType: str, body: bytes) -> tuple[str, bytes, str]:
    """Lit le formulaire envoyé : (nom du document, contenu, demande).

    Le formulaire est au format `multipart/form-data`, celui de tout envoi de
    fichier. Ce format a la même structure qu'un courriel à pièces jointes :
    le module `email` de la bibliothèque standard sait le découper.
    """
    if not contentType.startswith("multipart/form-data"):
        raise UploadError("Formulaire attendu en multipart/form-data.")
    # On recolle l'en-tête Content-Type devant le corps pour que le parseur
    # retrouve la frontière qui sépare les champs.
    message = BytesParser(policy=policy.HTTP).parsebytes(
        f"Content-Type: {contentType}\r\n\r\n".encode("latin-1") + body
    )
    fields = {
        part.get_param("name", header="content-disposition"): part
        for part in message.iter_parts()
    }

    documentPart = fields.get("document")
    if documentPart is None or not documentPart.get_filename():
        raise UploadError("Aucun document déposé.")
    data = documentPart.get_payload(decode=True) or b""
    if not data:
        raise UploadError("Le document déposé est vide.")

    instructionPart = fields.get("demande")
    instruction = ""
    if instructionPart is not None:
        raw = instructionPart.get_payload(decode=True) or b""
        instruction = raw.decode("utf-8", errors="replace").strip()
    if not instruction:
        raise UploadError("Décris la modification à faire.")

    return safeDocumentName(documentPart.get_filename()), data, instruction


def copyNameFor(documentName: str) -> str:
    """Nom de la copie : « rapport.docx » donne « rapport-modifie.docx »."""
    return documentName[: -len(DOCUMENT_SUFFIX)] + COPY_SUFFIX + DOCUMENT_SUFFIX


def runTask(
    task: WebTask, client: AgentClient, systemPrompt: str, instruction: str
) -> None:
    """Fait tourner l'agent sur une demande. Exécuté dans un fil à part."""
    # Seuls les outils Word : pas de notes, pas de suppression. Moins
    # l'agent a d'outils, moins un document piégé peut lui faire faire.
    registry = ToolRegistry(buildDocumentTools(task.folder))
    try:
        trace = runAgent(
            client=client,
            registry=registry,
            approval=task.approval,
            systemPrompt=systemPrompt,
            task=TASK_TEMPLATE.format(
                nom=task.documentName,
                demande=instruction,
                copie=copyNameFor(task.documentName),
            ),
        )
    except ModelCallError as error:
        task.answer = f"Appel au modèle impossible : {error}"
        task.status = STATUS_FAILED
        return
    # Journal : des compteurs et des noms d'outils, jamais le contenu.
    logger.info(
        "tache %s : %d tour(s), outils %s",
        task.taskId,
        trace.stepCount,
        trace.toolNames(),
    )
    task.answer = trace.finalText
    task.status = (
        STATUS_FAILED if trace.stoppedReason == STOP_ITERATION_LIMIT else STATUS_DONE
    )


class WebApp:
    """L'état de l'interface : les demandes en cours, et de quoi les lancer."""

    def __init__(self, client: AgentClient, systemPrompt: str, workRoot: Path):
        self.client = client
        self.systemPrompt = systemPrompt
        self.workRoot = workRoot
        self.tasks: dict[str, WebTask] = {}

    def submit(self, documentName: str, data: bytes, instruction: str) -> WebTask:
        """Range le document déposé et lance l'agent en arrière-plan."""
        # Identifiant aléatoire : il sert de nom de dossier et d'adresse, il
        # ne doit pas se deviner d'une demande à l'autre.
        taskId = uuid.uuid4().hex
        task = WebTask(taskId, self.workRoot / taskId, documentName)
        (task.folder.inputDir / documentName).write_bytes(data)
        self.tasks[taskId] = task
        threading.Thread(
            target=runTask,
            args=(task, self.client, self.systemPrompt, instruction),
            daemon=True,
        ).start()
        return task


# --- Pages HTML -------------------------------------------------------------
# Tout ce qui vient de l'extérieur (nom de fichier, demande, réponse et
# arguments du modèle) passe par `html.escape` avant d'entrer dans la page.

STYLE = """
body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; color: #1f2328; background: #fff; }
textarea, input[type=file] { width: 100%; box-sizing: border-box; }
textarea { min-height: 7rem; font: inherit; padding: .5rem; }
button { font: inherit; padding: .4rem 1rem; margin-right: .5rem; cursor: pointer; }
.box { border: 1px solid #d0d7de; border-radius: 6px; padding: 1rem; margin: 1rem 0; }
.attente { border-color: #bf8700; background: #fff8c5; }
.erreur { color: #cf222e; }
pre { white-space: pre-wrap; }
"""


def page(title: str, body: str, refresh: bool = False) -> str:
    """Enveloppe HTML commune. `refresh` recharge la page toutes les 2 s."""
    meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{meta}<title>{html.escape(title)}</title><style>{STYLE}</style>"
        f"</head><body>{body}</body></html>"
    )


def formPage(error: str = "") -> str:
    """Page d'accueil : le formulaire de dépôt."""
    message = f'<p class="erreur">{html.escape(error)}</p>' if error else ""
    return page(
        "Modifier un document Word",
        "<h1>Modifier un document Word</h1>"
        "<p>Dépose un document, décris la modification. L'agent propose les "
        "changements ; rien n'est écrit sans ta validation, et l'original "
        "n'est jamais modifié.</p>"
        f"{message}"
        '<form method="post" action="/taches" enctype="multipart/form-data">'
        '<p><label>Document (.docx)<br><input type="file" name="document" '
        'accept=".docx" required></label></p>'
        '<p><label>Modification demandée<br><textarea name="demande" required '
        'placeholder="Ex. : remplace « jeudi » par « vendredi » et ajoute une '
        'section « Points divers »."></textarea></label></p>'
        "<button>Envoyer</button></form>",
    )


def describeCall(call: ToolCall) -> str:
    """Ce que l'agent veut écrire, en clair, pour la personne qui valide."""
    arguments = call.arguments
    if call.toolName != "writeDocumentCopy":
        return f"<pre>{html.escape(json.dumps(arguments, ensure_ascii=False))}</pre>"
    items = []
    for item in arguments.get("remplacements") or []:
        if isinstance(item, dict):
            items.append(
                f"<li>Remplacer « {html.escape(str(item.get('ancien', '')))} » "
                f"par « {html.escape(str(item.get('nouveau', '')))} »</li>"
            )
    for item in arguments.get("sections") or []:
        if isinstance(item, dict):
            texts = item.get("paragraphes") or []
            paragraphs = "".join(
                f"<li>{html.escape(str(text))}</li>"
                for text in (texts if isinstance(texts, list) else [texts])
            )
            items.append(
                f"<li>Ajouter la section « {html.escape(str(item.get('titre', '')))}"
                f" »<ul>{paragraphs}</ul></li>"
            )
    copyName = html.escape(str(arguments.get("nomCopie", "")))
    return f"<p>Copie : <strong>{copyName}</strong></p><ul>{''.join(items)}</ul>"


def taskPage(task: WebTask) -> str:
    """Page de suivi : en cours, en attente de validation, ou terminé."""
    parts = [
        "<h1>Modifier un document Word</h1>",
        f"<p>Document : <strong>{html.escape(task.documentName)}</strong> — "
        f"état : {html.escape(task.status)}</p>",
    ]
    pending = task.approval.pendingCall
    if pending is not None:
        # L'agent est bloqué sur `approve` : on montre ce qu'il veut faire.
        parts.append(
            '<div class="box attente"><h2>Validation demandée</h2>'
            f"{describeCall(pending)}"
            f'<form method="post" action="/taches/{task.taskId}/validation">'
            '<button name="decision" value="oui">Valider</button>'
            '<button name="decision" value="non">Refuser</button></form></div>'
        )
    elif task.status == STATUS_RUNNING:
        parts.append("<p>L'agent travaille…</p>")

    if task.answer:
        parts.append(
            f'<div class="box"><h2>Réponse de l\'agent</h2>'
            f"<pre>{html.escape(task.answer)}</pre></div>"
        )
    links = "".join(
        f'<li><a href="/taches/{task.taskId}/copie/{quote(name)}">'
        f"{html.escape(name)}</a></li>"
        for name in task.copies()
    )
    if links:
        parts.append(f"<h2>Copie à télécharger</h2><ul>{links}</ul>")
    if task.status != STATUS_RUNNING:
        parts.append('<p><a href="/">Modifier un autre document</a></p>')
    # Rechargement automatique tant que l'agent travaille, mais pas pendant
    # une validation : la page changerait sous le clic.
    refresh = task.status == STATUS_RUNNING and pending is None
    return page("Suivi de la demande", "".join(parts), refresh=refresh)


# --- Serveur ----------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    """Répond aux requêtes du navigateur. Une instance par requête."""

    # Renseigné par `serve` : l'état partagé entre toutes les requêtes.
    app: WebApp

    def do_GET(self) -> None:
        """Pages et téléchargement."""
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == [""]:
            self._sendHtml(formPage())
        elif len(parts) == 2 and parts[0] == "taches":
            task = self._task(parts[1])
            if task:
                self._sendHtml(taskPage(task))
        elif len(parts) == 4 and parts[0] == "taches" and parts[2] == "copie":
            task = self._task(parts[1])
            if task:
                self._sendCopy(task, parts[3])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        """Dépôt d'un document, ou décision de validation."""
        parts = self.path.strip("/").split("/")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            self._sendHtml(formPage("Document trop volumineux (10 Mo au plus)."))
            return
        body = self.rfile.read(length)

        if parts == ["taches"]:
            try:
                name, data, instruction = parseUpload(
                    self.headers.get("Content-Type", ""), body
                )
            except UploadError as error:
                self._sendHtml(formPage(str(error)))
                return
            task = self.app.submit(name, data, instruction)
            self._redirect(f"/taches/{task.taskId}")
        elif len(parts) == 3 and parts[0] == "taches" and parts[2] == "validation":
            task = self._task(parts[1])
            if task:
                decision = parse_qs(body.decode("utf-8")).get("decision", [""])[0]
                # Seul « oui » vaut accord, comme en ligne de commande.
                task.approval.decide(decision == "oui")
                self._redirect(f"/taches/{task.taskId}")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _task(self, taskId: str) -> WebTask | None:
        """La demande, ou une erreur 404 si l'identifiant est inconnu."""
        task = self.app.tasks.get(taskId)
        if task is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Demande inconnue")
        return task

    def _sendCopy(self, task: WebTask, quotedName: str) -> None:
        """Envoie une copie. Seuls les noms réellement présents sont servis."""
        name = unquote(quotedName)
        # Comparer à la liste des copies interdit tout chemin fabriqué
        # (« ../entree/… ») : on ne sert que ce que l'agent a écrit.
        if name not in task.copies():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = (task.folder.outputDir / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.send_header(
            "Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}"
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sendHtml(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        # 303 : après un envoi de formulaire, le navigateur recharge la page
        # de suivi en GET, sans renvoyer le document au rechargement.
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Journal du serveur web : la ligne de requête seulement (méthode,
        # adresse, code), par le module logging plutôt que sur stderr.
        logger.info("%s", format % args)


def serve(app: WebApp, host: str, port: int) -> None:
    """Lance le serveur jusqu'à Ctrl+C. Un fil par requête."""
    Handler.app = app
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
