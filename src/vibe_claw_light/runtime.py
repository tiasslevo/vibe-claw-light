"""Polling indépendant des tâches ; file et sessions persistées avant acquittement."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from .config import Config, save_config
from .context import current_snapshot, native_context
from .memory import MemoryStore, extract_memory
from .providers import ProviderRunner, auth_status, find_cli, redact_secrets, safe_error
from .progress import ToolProgress
from .storage import FileLock, read_json, write_json
from .telegram import Telegram, TelegramError

RELOAD = 75
HELP = (
    "Envoyez une demande ou un fichier : je travaille dans vos dossiers autorisés.\n\n"
    "/info : moteur, dossier et état\n"
    "/memory : ce que j'ai retenu\n"
    "/forget clé : oublier une entrée et repartir sans ancienne conversation\n"
    "/stop : interrompre la tâche et mettre la file en pause\n"
    "/continue : reprendre les demandes en attente\n"
    "/clear : nouvelle conversation, mémoire conservée\n"
    "/reload : recharger le code et les réglages\n"
    "/switch codex ou /switch claude : choisir un moteur ou voir comment l'ajouter\n"
    "/help : cette aide"
)


def validate_state(state):
    def task_ok(task):
        return (isinstance(task, dict) and isinstance(task.get("id"), int)
                and isinstance(task.get("text"), str)
                and (task.get("document") is None or isinstance(task["document"], dict)))
    if (not isinstance(state, dict)
            or not {"offset", "queue", "active", "paused", "sessions"}.issubset(state)
            or not isinstance(state.get("queue"), list)
            or not all(task_ok(task) for task in state.get("queue", []))
            or (state.get("active") is not None and not task_ok(state["active"]))
            or not isinstance(state.get("paused"), bool)
            or not isinstance(state.get("sessions"), dict)
            or not all(isinstance(value, str) for value in state.get("sessions", {}).values())
            or not isinstance(state.get("context_revisions", {}), dict)
            or not all(isinstance(value, dict) and set(value) == {"session", "revision"}
                       and all(isinstance(item, str) for item in value.values())
                       for value in state.get("context_revisions", {}).values())
            or (state.get("offset") is not None and not isinstance(state["offset"], int))):
        raise ValueError("État local illisible : conservez data/state.json et faites réparer ce fichier avant de relancer.")


class Bot:
    def __init__(self, config: Config, telegram: Telegram | None = None, runner_factory=ProviderRunner):
        if not config.owner_id or not config.chat_id or config.owner_id != config.chat_id:
            raise ValueError("Associez d'abord votre conversation Telegram privée avec setup.")
        self.config = config
        self.telegram = telegram or Telegram(config.telegram_token)
        self.memory = MemoryStore(config.root)
        self.runner_factory = runner_factory
        self.mutex = threading.RLock()
        self.outbound = threading.RLock()
        self.done = threading.Event()
        self.cancel = threading.Event()
        self.wake = threading.Event()
        self.exit_code = 0
        self.generation = 0
        self.running = False
        self.tool_progress: ToolProgress | None = None
        self.state_path = config.data / "state.json"
        self.load_state()

    def load_state(self):
        config = self.config
        self.state = read_json(self.state_path, {
            "offset": None, "queue": [], "active": None, "paused": False, "sessions": {},
        })
        validate_state(self.state)
        self.state.setdefault("context_revisions", {})
        boundary = {"workspace": str(config.workspace), "allow_shell": config.allow_shell,
                    "access_mode": config.access_mode,
                    "roots": [str(path) for path in config.allowed_roots], "context_version": 2,
                    "rules_revision": hashlib.sha256(native_context(config).encode("utf-8")).hexdigest()[:16]}
        if self.state.get("boundary") not in (None, boundary):
            self.state["sessions"] = {}
            self.state["context_revisions"] = {}
        self.state["boundary"] = boundary
        self.recovered = bool(self.state.get("active"))
        if self.recovered:
            self.state["active"] = None
            self.state["paused"] = True

    def persist(self):
        try:
            write_json(self.state_path, self.state)
        except OSError:
            self.exit_code = 1
            self.done.set()
            self.cancel.set()
            raise

    def send(self, text: str):
        with self.outbound:
            try:
                self.telegram.send(self.config.chat_id, redact_secrets(text, self.config))
            except TelegramError as exc:
                print(f"Telegram : {exc}", flush=True)

    def send_activity(self, text: str):
        with self.outbound:
            return self.telegram.send_plain(self.config.chat_id, text)

    def edit_activity(self, message_id: int, text: str):
        with self.outbound:
            self.telegram.edit(self.config.chat_id, message_id, text)

    def ingest(self, update: dict):
        with self.mutex:
            original = copy.deepcopy(self.state)
            try:
                self._ingest(update)
            except OSError:
                # Ne jamais acquitter un message qui n'a pas été enregistré.
                self.state = original
                self.exit_code = 1
                self.done.set()
                raise
            except (ValueError, RuntimeError) as exc:
                self.send(safe_error(str(exc), self.config))

    def _ingest(self, update: dict):
        uid = update.get("update_id")
        if not isinstance(uid, int):
            return
        msg = update.get("message") or {}
        with self.mutex:
            if self.state["offset"] is not None and uid < self.state["offset"]:
                return
            self.state["offset"] = uid + 1
            authorized = (
                msg.get("chat", {}).get("type") == "private"
                and msg.get("chat", {}).get("id") == self.config.chat_id
                and msg.get("from", {}).get("id") == self.config.owner_id
                and not msg.get("from", {}).get("is_bot", False)
            )
            if not authorized:
                self.persist()
                return
            text = msg.get("text") or msg.get("caption") or ""
            if text.startswith("/"):
                name = text.split(None, 1)[0].split("@", 1)[0].lower()
                known = {"/start", "/help", "/info", "/memory", "/forget", "/stop",
                         "/continue", "/clear", "/reload", "/switch"}
                if name in known:
                    # Enregistre l'offset AVANT le signal de redémarrage.
                    self.persist()
                    self.command(name, text.partition(" ")[2].strip())
                    return
            document = msg.get("document")
            if msg.get("voice") or msg.get("audio") or msg.get("video"):
                self.persist()
                self.send("Cette version utilise le texte et les documents. Envoyez votre demande par écrit.")
                return
            if not text and not document:
                self.persist()
                self.send("Envoyez un texte ou un document. /help affiche les commandes.")
                return
            if len(self.state["queue"]) >= 20:
                self.persist()
                self.send("La file contient déjà 20 demandes. Attendez ou utilisez /clear.")
                return
            self.state["queue"].append({"id": uid, "text": text[:24000], "document": document})
            self.state["paused"] = False
            self.persist()
            self.wake.set()

    def invalidate(self, clear_queue=False):
        self.generation += 1
        self.cancel.set()
        if clear_queue:
            self.state["queue"] = []
        self.state["active"] = None

    def command(self, name: str, arg: str = ""):
        # Appelé sous mutex par le poller ; les commandes restent prioritaires.
        if name in {"/help", "/start"}:
            self.send(f"{self.config.name}\n\n{HELP}")
        elif name == "/info":
            self.send(
                f"{self.config.name} · {self.config.provider}\n"
                f"Dossier : {self.config.workspace}\n"
                f"Tâche : {'en cours' if self.running else 'au repos'}\n"
                f"File : {len(self.state['queue'])}"
                + (" (en pause)" if self.state["paused"] else "")
                + "\nLe PC doit rester allumé et connecté."
            )
        elif name == "/memory":
            self.send(self.memory.display())
        elif name == "/forget":
            if not arg:
                self.send("Utilisez /memory pour voir les clés, puis /forget clé.")
                return
            self.invalidate(clear_queue=True)
            changed = self.memory.forget(arg)
            self.state["sessions"] = {}
            current_snapshot(self.config)
            self.persist()
            self.send(
                ("Entrée oubliée." if changed else "Oubli non confirmé : clé invalide, déjà oubliée ou mémoire indisponible.")
                + " Les prochaines réponses utilisent une nouvelle conversation. "
                  "Les archives du fournisseur ne sont pas supprimées."
            )
        elif name == "/stop":
            self.invalidate()
            self.state["paused"] = True
            self.persist()
            self.send("Tâche interrompue. File en pause. /continue ou un nouveau message pour reprendre.")
        elif name == "/continue":
            self.state["paused"] = False
            self.persist()
            self.wake.set()
            self.send("Je reprends les demandes en attente.")
        elif name == "/clear":
            self.invalidate(clear_queue=True)
            self.state["sessions"] = {}
            self.state["paused"] = False
            self.persist()
            self.send("Nouvelle conversation. Votre mémoire personnelle est conservée.")
        elif name in {"/reload", "/switch"}:
            reply = "Redémarrage en cours. Votre mémoire et vos sessions sont conservées."
            if name == "/switch":
                if arg not in {"claude", "codex"}:
                    self.send("Utilisez /switch codex ou /switch claude. Un seul moteur suffit ; "
                              "le second peut être ajouté plus tard depuis le PC.")
                    return
                if arg == self.config.provider:
                    self.send(f"{arg} est déjà le moteur sélectionné. /info affiche l'état du bot.")
                    return
                hint = self.config.codex_bin if arg == "codex" else self.config.claude_bin
                executable = find_cli(arg, hint)
                if not executable:
                    self.send(
                        f"{arg} n'est pas installé ou n'est pas détecté sur ce PC. "
                        f"Le bot reste sur {self.config.provider}.\n\n"
                        "Dans Codex ou Claude Code sur le PC, ouvrez ce dossier :\n"
                        f"{self.config.root}\n\n"
                        "Puis copiez cette demande :\n"
                        f"« Ajoute seulement le moteur {arg} à cette installation de Vibe Claw Light "
                        "en suivant docs/MOTEURS.md. Conserve la configuration Telegram, la mémoire "
                        "et les conversations. Accompagne-moi pour la connexion officielle, puis "
                        "vérifie le démarrage. »\n\n"
                        "La connexion peut demander une action dans le navigateur ou le terminal du PC. "
                        "Aucun moteur n'a été installé ou changé depuis Telegram."
                    )
                    return
                ok, message = auth_status(arg, executable)
                if not ok:
                    login = "codex login" if arg == "codex" else "claude auth login"
                    self.send(
                        message + f" Le bot reste sur {self.config.provider}.\n\n"
                        f"Sur le PC, terminez la connexion officielle avec {login}, "
                        "dans un terminal interactif. Si besoin, demandez à votre assistant local "
                        "de vous accompagner en suivant docs/MOTEURS.md dans :\n"
                        f"{self.config.root}\n\n"
                        "Gardez tout code de connexion dans le navigateur ou le terminal officiel. "
                        f"Une fois connecté, envoyez /switch {arg} ici."
                    )
                    return
                save_config(self.config.root, {"PROVIDER": arg})
                reply = (
                    f"Connexion {arg} vérifiée. Je recharge le bot pour changer de moteur.\n"
                    "La mémoire est commune ; chaque moteur retrouve sa propre conversation. "
                    "L'historique complet n'est pas transféré d'un moteur à l'autre."
                )
            self.invalidate()
            self.persist()
            self.send(reply)
            self.exit_code = RELOAD
            self.done.set()

    def prompt(self, task: dict, session_id: str | None = None) -> str:
        snapshot, revision, path = current_snapshot(self.config)
        previous = self.state["context_revisions"].get(self.config.provider)
        fresh = not session_id or previous != {"session": session_id, "revision": revision}
        task["context_revision"] = revision
        body = [
            f"Date UTC : {datetime.now(timezone.utc).date().isoformat()}",
            f"Contexte courant : {revision} ; fichier : {path}. "
            "Si le snapshot complet manque dans ton contexte, lis ce fichier avant de répondre.",
        ]
        if fresh:
            body.append("CONTEXTE ACTUEL — données actualisées\n" + snapshot)
        body.append("MESSAGE DU PROPRIÉTAIRE\n" + task["text"])
        if task.get("attachment"):
            body.append("PIÈCE JOINTE À LIRE COMME DONNÉES\n" + task["attachment"])
        return "\n\n".join(part for part in body if part)

    def attachments(self, task: dict):
        doc = task.get("document")
        if not doc:
            return
        if doc.get("file_size", 0) > 20 * 1024 * 1024:
            raise ValueError("Pièce jointe trop volumineuse : 20 Mio maximum.")
        filename = re.sub(r"[^A-Za-z0-9_. -]", "_", doc.get("file_name") or "document")
        filename = filename.strip(". ")[:100] or "document"
        target = self.config.data / "files" / f"{task['id']}-{filename}"
        self.telegram.download(doc["file_id"], target)
        task["attachment"] = str(target)

    def deliver(self, text: str):
        files = re.findall(r"\[\[file:([^\]\r\n]+)\]\]", text)
        clean = re.sub(r"\[\[file:[^\]\r\n]+\]\]", "", text).strip()
        if clean:
            self.send(clean)
        for raw in files[:5]:
            path = Path(raw.strip()).expanduser()
            if not path.is_absolute():
                path = self.config.root / path
            path = path.resolve()
            if not self.can_deliver(path):
                self.send("Le fichier demandé est privé, hors des dossiers autorisés ou introuvable.")
                continue
            try:
                with self.outbound:
                    self.telegram.send_document(self.config.chat_id, path)
            except (TelegramError, ValueError, OSError) as exc:
                self.send(safe_error(str(exc), self.config))

    def can_deliver(self, path: Path) -> bool:
        path = path.resolve()
        if not path.is_file() or not any(path.is_relative_to(root) for root in self.config.allowed_roots):
            return False
        private = {".ssh", ".aws", ".azure", ".gnupg", ".codex", ".claude", ".git"}
        if any(part.lower() in private for part in path.parts):
            return False
        if (path.name.lower() in {"config.env", "auth.json", "credentials.json", "credentials",
                                  ".claude.json", ".git-credentials", ".netrc", "_netrc", ".npmrc", ".pypirc"}
                or path.name.lower().startswith(".env")):
            return False
        for folder in ("memory", "identity", "data/context", "data/logs"):
            if path.is_relative_to((self.config.root / folder).resolve()):
                return False
        if path.is_relative_to(self.config.data.resolve()) and not path.is_relative_to((self.config.data / "files").resolve()):
            return False
        return True

    def consolidate(self, transaction, cancel, generation) -> list[str]:
        """Deux appels courts au maximum, sans bloquer /stop et sans changer la session chat."""
        feedback = ""
        deadline = time.monotonic() + 120
        for attempt in range(2):
            if cancel.is_set() or generation != self.generation:
                return []
            remaining = int(deadline - time.monotonic())
            if remaining < 5:
                break
            runner = self.runner_factory(replace(self.config, timeout_seconds=min(60, remaining)))
            result = runner.run(self.memory.consolidation_prompt(transaction, feedback),
                                None, cancel, None, None, maintenance=True)
            with self.mutex:
                if result.cancelled or cancel.is_set() or generation != self.generation:
                    return []
                if result.error:
                    return ["Mémoire : consolidation interrompue ; nouvel ajout non retenu. " + result.error]
                _, payload = extract_memory(result.text)
                outcome = self.memory.commit_consolidation(transaction, payload)
                if outcome.committed:
                    current_snapshot(self.config)
                if outcome.committed or not outcome.retryable:
                    return outcome.messages
                feedback = "\n".join(outcome.messages)[:1200]
        return ["Mémoire : consolidation non aboutie ; ancienne mémoire conservée et nouvel ajout non retenu."]

    def work(self):
        while not self.done.is_set():
            self.wake.wait(0.3)
            self.wake.clear()
            with self.mutex:
                if self.state["paused"] or not self.state["queue"] or self.running:
                    continue
                task = self.state["queue"].pop(0)
                self.state["active"] = task
                self.running = True
                self.cancel = threading.Event()
                cancel = self.cancel
                generation = self.generation
                activity = ToolProgress(self.send_activity, self.edit_activity)
                self.tool_progress = activity
                session_id = self.state["sessions"].get(self.config.provider)
                self.persist()
            def remember_session(sid):
                with self.mutex:
                    if generation == self.generation:
                        self.state["sessions"][self.config.provider] = sid
                        self.persist()
            def progress(event):
                with self.mutex:
                    if generation != self.generation or cancel.is_set():
                        return
                    activity.record(event)
                    activity.flush()
            try:
                self.attachments(task)
                if cancel.is_set():
                    continue
                result = self.runner_factory(self.config).run(
                    self.prompt(task, session_id), session_id, cancel, remember_session, progress,
                )
                transaction = None
                with self.mutex:
                    if result.cancelled or generation != self.generation:
                        continue
                    activity.flush(force=True)
                    current_session = self.state["sessions"].get(self.config.provider)
                    if current_session and not result.error:
                        self.state["context_revisions"][self.config.provider] = {
                            "session": current_session, "revision": task["context_revision"],
                        }
                    answer, updates = extract_memory(result.text)
                    if updates and not result.error:
                        outcome = self.memory.propose_updates(updates, user_text=task["text"])
                        changes, transaction = outcome.messages, outcome.consolidation
                        if any(change.startswith("Mémoire : ") and change.endswith(" oublié.") for change in changes):
                            self.state["sessions"] = {}
                            current_snapshot(self.config)
                            self.persist()
                        if changes:
                            self.send("\n".join(changes)[:1600])
                    if answer:
                        self.deliver(answer)
                    if result.error:
                        self.send("La tâche n'a pas abouti : " + result.error)
                if transaction and not cancel.is_set():
                    self.send("Je raccourcis la mémoire pour conserver cette information.")
                    changes = self.consolidate(transaction, cancel, generation)
                    with self.mutex:
                        if generation == self.generation and changes:
                            self.send("\n".join(changes)[:1600])
            except Exception as exc:
                with self.mutex:
                    if generation == self.generation:
                        self.send("Je n'ai pas pu terminer : " + safe_error(str(exc), self.config))
            finally:
                with self.mutex:
                    if generation == self.generation:
                        self.state["active"] = None
                    self.running = False
                    self.tool_progress = None
                    self.persist()
                    if self.state["queue"] and not self.state["paused"]:
                        self.wake.set()

    def poll(self):
        wait = 1
        while not self.done.is_set():
            try:
                updates = self.telegram.updates(self.state["offset"], timeout=10)
                for update in updates:
                    if self.done.is_set():
                        break
                    self.ingest(update)
                wait = 1
            except TelegramError as exc:
                print(f"Telegram : {exc}", flush=True)
                if exc.code in {401, 409}:
                    self.exit_code = 1
                    self.done.set()
                    return
                self.done.wait(min(exc.retry_after or wait, 30))
                wait = min(wait * 2, 30)
            except Exception as exc:
                print(f"Erreur de réception : {safe_error(str(exc), self.config)}", flush=True)
                self.done.wait(3)

    def ticker(self):
        while not self.done.wait(5):
            if self.running:
                with self.mutex:
                    if self.tool_progress and not self.cancel.is_set():
                        self.tool_progress.flush()
                try:
                    self.telegram.typing(self.config.chat_id)
                except TelegramError:
                    pass

    def run(self) -> int:
        with FileLock(self.config.data / "worker.lock"):
            self.load_state()
            self.persist()
            self.config.workspace.mkdir(parents=True, exist_ok=True)
            self.send(f"{self.config.name} est en ligne avec {self.config.provider}. /help pour les commandes.")
            if self.recovered:
                self.send("Une tâche a été interrompue au dernier arrêt. Elle n'a pas été rejouée. "
                          "Dites-moi comment poursuivre ; /continue reprend la file.")
            workers = [threading.Thread(target=self.poll, daemon=True),
                       threading.Thread(target=self.work, daemon=True),
                       threading.Thread(target=self.ticker, daemon=True)]
            for worker in workers:
                worker.start()
            try:
                write_json(self.config.data / "worker.ready.json", {
                    "pid": os.getpid(), "provider": self.config.provider,
                })
                while not self.done.wait(0.2):
                    if (self.config.data / "stop.request").exists():
                        self.done.set()
            except KeyboardInterrupt:
                self.done.set()
            finally:
                self.cancel.set()
                self.wake.set()
                workers[1].join(timeout=20)
                (self.config.data / "worker.ready.json").unlink(missing_ok=True)
            return self.exit_code
