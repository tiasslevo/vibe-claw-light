"""Configuration dans le navigateur local ; aucun secret dans le chat du CLI."""
from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .auth import LoginAttempt, start_login
from .config import read_values, save_config
from .providers import auth_status, executable_command, find_cli
from .setup_ui import WATCH_CSP, page
from .storage import FileLock, atomic_write, is_locked, write_json
from .telegram import Telegram, TelegramError, retry_telegram


SETUP_TIMEOUT = 20 * 60
AUTH_TIMEOUT = 5 * 60
PAIR_TIMEOUT = 5 * 60
MAX_FORM_BYTES = 8192
# Même un formulaire rejeté doit être consommé avant de fermer la connexion :
# Windows peut sinon remplacer la réponse HTTP par un reset TCP. La limite
# distincte borne la lecture des corps trop grands, qui restent invalides.
MAX_DISCARD_BYTES = 65536


def paired_owner(message: dict, code: str) -> int | None:
    """N'accepter que le code de cette session envoyé par son compte privé."""
    if not isinstance(message, dict) or message.get("text") != "/start " + code:
        return None
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    owner = sender.get("id")
    if (type(owner) is not int or owner <= 0 or sender.get("is_bot") is not False
            or chat.get("type") != "private" or type(chat.get("id")) is not int
            or chat["id"] != owner):
        return None
    return owner


class Wizard:
    """État testable indépendamment du serveur HTTP et des appels réels."""

    def __init__(self, root: Path, provider: str, executable: str,
                 authenticated: bool, telegram_factory=Telegram, *,
                 diagnostic_runner=None, service_start=None, service_status=None):
        self.root, self.provider, self.executable = root, provider, executable
        self.initial = read_values(root)
        self.telegram_factory = telegram_factory
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.done = threading.Event()
        self.phase = "configure" if authenticated else "auth"
        self.error = ""
        self.csrf = secrets.token_urlsafe(32)
        self.path = "/" + secrets.token_urlsafe(24) + "/"
        self.name = self.initial["AGENT_NAME"]
        self.workspace = self.initial["WORKSPACE"]
        self.access_mode = self.initial["ACCESS_MODE"]
        self.allow_shell = self.initial["ALLOW_SHELL"].lower() in {"1", "true", "yes", "oui"}
        self.bot_username = ""
        self.pair_code = ""
        self.pair_link = ""
        self.generation = 0
        self.threads: list[threading.Thread] = []
        self.auth_attempt: LoginAttempt | None = None
        self.auth_generation = 0
        self.checking_login = False
        self.result = 1
        self.diagnostic_runner = diagnostic_runner
        self.service_start = service_start
        self.service_status = service_status
        self.checks = {}
        self.service_state = "pending"
        self.auth_watch_deadline = 0.0
        self.auth_next_check = 0.0

    def enable_login_watch(self):
        self.auth_watch_deadline = time.monotonic() + AUTH_TIMEOUT

    def refresh_login(self):
        """Lecture bornée de l'état du CLI, y compris après un login manuel."""
        with self.lock:
            now = time.monotonic()
            if (self.phase not in {"auth", "authenticating"} or self.checking_login
                    or not now < self.auth_watch_deadline or now < self.auth_next_check):
                return
            self.auth_next_check = now + 5
            self.check_login(automatic=True)

    def _thread(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def login(self):
        with self.lock:
            if self.phase != "auth" or self.auth_attempt is not None:
                return
            self.phase, self.error = "authenticating", ""
            self.enable_login_watch()
            self.auth_generation += 1
            self._thread(self._login, self.auth_generation)

    def _login(self, generation: int):
        attempt = None
        try:
            print(f"Connexion {self.provider} : terminez la connexion dans le terminal et le navigateur officiels.", flush=True)
            with self.lock:
                if self.stop.is_set() or generation != self.auth_generation:
                    return
                attempt = start_login(self.root, self.provider, self.executable, AUTH_TIMEOUT)
                if attempt is None:
                    self.phase, self.error = "auth", (
                        "Aucun terminal interactif n'a pu être ouvert. "
                        "Ouvrez un terminal sur ce PC, lancez la commande ci-dessous, puis cliquez sur Vérifier."
                    )
                    return
                self.auth_attempt = attempt
            deadline = time.monotonic() + AUTH_TIMEOUT
            while attempt.poll() is None and not self.stop.wait(0.2):
                if time.monotonic() >= deadline or generation != self.auth_generation:
                    break
            if self.stop.is_set() or generation != self.auth_generation:
                return
            valid, _ = auth_status(self.provider, self.executable)
            with self.lock:
                if self.stop.is_set() or generation != self.auth_generation:
                    return
                self.phase = "configure" if valid else "auth"
                self.error = "" if valid else (
                    "Connexion non terminée. Vous pouvez réessayer ci-dessous. "
                    "Si un code est demandé, saisissez-le dans le terminal de connexion, jamais dans cette page."
                )
                if valid:
                    self.auth_generation += 1
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                if generation == self.auth_generation and not self.stop.is_set():
                    self.phase = "auth"
                    self.error = "Impossible de lancer la connexion. Réessayez ou utilisez la commande affichée dans un terminal."
        finally:
            if attempt is not None:
                attempt.close()
            with self.lock:
                if self.auth_attempt is attempt:
                    self.auth_attempt = None

    def check_login(self, automatic=False):
        with self.lock:
            if self.phase not in {"auth", "authenticating"} or self.checking_login:
                return
            self.checking_login = True
            if not automatic:
                self.phase, self.error = "authenticating", ""
                self.enable_login_watch()
            self._thread(self._check_login, self.auth_generation, automatic)

    def _check_login(self, generation: int, automatic=False):
        valid, _ = auth_status(self.provider, self.executable)
        with self.lock:
            self.checking_login = False
            if self.stop.is_set() or generation != self.auth_generation:
                return
            self.phase = "configure" if valid else ("authenticating" if self.auth_attempt else "auth")
            if valid:
                self.error = ""
            elif not automatic:
                self.error = "Connexion non détectée. Terminez la connexion puis réessayez."
            if valid:
                self.auth_generation += 1
                if self.auth_attempt:
                    self.auth_attempt.cancel()

    def cancel_login(self):
        with self.lock:
            if self.phase != "authenticating":
                return
            self.auth_generation += 1
            self.auth_watch_deadline = 0
            self.phase, self.error = "auth", "Connexion annulée. Vous pourrez la relancer ou la vérifier."
            if self.auth_attempt:
                self.auth_attempt.cancel()

    def configure(self, fields: dict[str, str]):
        with self.lock:
            if self.phase != "configure":
                return
            name = fields.get("name", "").strip()
            workspace_text = fields.get("workspace", "").strip()
            access_mode = fields.get("access_mode", self.access_mode)
            token = fields.get("token", "").strip() or self.initial["TELEGRAM_TOKEN"]
            if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
                self.error = "Choisissez un nom entre 1 et 80 caractères."
                return
            if not workspace_text or len(workspace_text) > 2000 or any(ord(char) < 32 for char in workspace_text):
                self.error = "Indiquez un dossier de travail valide."
                return
            if access_mode not in {"personal", "workspace"}:
                self.error = "Choisissez un mode d'accès valide."
                return
            if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,200}", token):
                self.error = "Le token Telegram est incomplet. Copiez celui fourni par BotFather."
                return
            try:
                workspace = Path(workspace_text).expanduser()
                if not workspace.is_absolute():
                    workspace = self.root / workspace
                workspace = workspace.resolve()
                if workspace.exists() and not workspace.is_dir():
                    self.error = "Le chemin choisi désigne un fichier. Choisissez un dossier."
                    return
            except (OSError, ValueError, RuntimeError):
                self.error = "Ce dossier n'est pas accessible. Vérifiez son chemin."
                return
            self.name, self.workspace = name, workspace_text
            self.access_mode = access_mode
            if self.provider == "claude":
                self.allow_shell = fields.get("allow_shell") == "1"
            self.phase, self.error = "validating", ""
            self.generation += 1
            generation = self.generation
            updates = {
                "PROVIDER": self.provider, "AGENT_NAME": name,
                "WORKSPACE": str(workspace), "TELEGRAM_TOKEN": token,
                "ALLOW_SHELL": "1" if self.allow_shell else "0",
                "ACCESS_MODE": access_mode,
                "CODEX_BIN" if self.provider == "codex" else "CLAUDE_BIN": self.executable,
            }
            self._thread(self._validate_and_pair, updates, fields.get("keep_owner") == "1", generation)

    def _current(self, generation: int) -> bool:
        return generation == self.generation and not self.stop.is_set()

    def _fail(self, generation: int, message: str):
        with self.lock:
            if self._current(generation):
                self.phase, self.error = "configure", message
                self.pair_code = self.pair_link = ""

    def _validate_and_pair(self, updates: dict[str, str], keep_owner: bool, generation: int):
        try:
            telegram = self.telegram_factory(updates["TELEGRAM_TOKEN"])
            me = retry_telegram(telegram.get_me, cancel=self.stop)
            username = me.get("username", "")
            if not me.get("is_bot") or not re.fullmatch(r"[A-Za-z0-9_]{5,64}", username):
                self._fail(generation, "Ce token ne correspond pas à un bot Telegram utilisable.")
                return
            webhook = retry_telegram(lambda: telegram.request("getWebhookInfo", timeout=8), cancel=self.stop)
            if webhook.get("url"):
                self._fail(generation, "Ce bot est déjà relié à un autre service par un webhook. Créez un bot dédié avec BotFather ; l'association existante a été conservée.")
                return
            with self.lock:
                if not self._current(generation):
                    return
                self.bot_username = username
                owner = self.initial["TELEGRAM_OWNER_ID"]
                chat = self.initial["TELEGRAM_CHAT_ID"]
                if (keep_owner and updates["TELEGRAM_TOKEN"] == self.initial["TELEGRAM_TOKEN"]
                        and owner.isdecimal() and int(owner) > 0 and owner == chat):
                    self._save(updates, int(owner), generation)
                    return
                self.pair_code = secrets.token_urlsafe(24)
                self.pair_link = f"https://t.me/{username}?start={self.pair_code}"
                code = self.pair_code
                self.phase = "pairing"
            deadline, offset = time.monotonic() + PAIR_TIMEOUT, None
            while self._current(generation) and time.monotonic() < deadline:
                try:
                    batch = telegram.updates(offset=offset, timeout=5)
                except TelegramError as exc:
                    remaining = deadline - time.monotonic()
                    if exc.retryable and max(exc.retry_after, 1) < remaining:
                        with self.lock:
                            if self._current(generation):
                                self.error = str(exc) + " Nouvelle tentative en cours."
                        self.stop.wait(max(exc.retry_after, 1))
                        continue
                    raise
                with self.lock:
                    if self._current(generation):
                        self.error = ""
                for update in batch:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if type(update_id) is not int or update_id < 0:
                        continue
                    offset = max(offset or 0, update_id + 1)
                    owner_id = paired_owner(update.get("message", {}), code)
                    if owner_id is not None:
                        self._save(updates, owner_id, generation, update_id + 1)
                        return
                if not batch:
                    self.stop.wait(0.2)
            self._fail(generation, "Le lien d'association a expiré. Validez à nouveau le formulaire pour en créer un nouveau.")
        except TelegramError as exc:
            messages = {
                401: "Telegram a refusé ce token. Copiez à nouveau celui de BotFather.",
                409: "Un autre programme utilise déjà ce bot. Arrêtez cet autre programme ou créez un bot dédié.",
            }
            self._fail(generation, messages.get(exc.code, str(exc)))
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            # Ne jamais afficher une exception contenant une URL API et son token.
            self._fail(generation, "L'association n'a pas pu être enregistrée. Vérifiez les droits d'accès au dossier puis réessayez.")

    def _save(self, updates: dict[str, str], owner_id: int, generation: int,
              next_offset: int | None = None):
        with self.lock:
            if not self._current(generation):
                return
            previous_owner = self.initial["TELEGRAM_OWNER_ID"]
            if previous_owner and previous_owner != str(owner_id):
                self._fail(generation, "Ce dossier appartient déjà à un autre compte Telegram. Installez le starter dans un nouveau dossier pour préserver la mémoire privée de ce compte.")
                return
            if is_locked(self.root / "data" / "service.lock"):
                self._fail(generation, "L'agent a été démarré entre-temps. Arrêtez-le avec python run.py stop, puis réessayez.")
                return
            # Le verrou protège aussi la fenêtre entre le dernier contrôle et
            # l'écriture contre un démarrage simultané du superviseur.
            with FileLock(self.root / "data" / "service.lock"):
                workspace = Path(updates["WORKSPACE"])
                workspace.mkdir(parents=True, exist_ok=True)
                (self.root / "data" / "files").mkdir(parents=True, exist_ok=True)
                soul = self.root / "identity" / "SOUL.md"
                if not soul.exists():
                    atomic_write(soul, "# Voix de l'assistant\n\n"
                                 "Parle simplement, en français par défaut. Adapte la longueur à la demande.\n"
                                 "Sois honnête sur ce qui est vérifié, les limites et les erreurs.\n"
                                 "Range les livrables dans le projet concerné et conserve une mémoire courte, utile et vérifiée.\n")
                updates.update({"TELEGRAM_OWNER_ID": str(owner_id), "TELEGRAM_CHAT_ID": str(owner_id)})
                if next_offset is not None:
                    write_json(self.root / "data" / "state.json", {
                        "offset": next_offset, "sessions": {}, "queue": [], "active": None, "paused": False,
                    })
                save_config(self.root, updates)
            self.initial = read_values(self.root)
            self.phase, self.error = "diagnostics", ""
            self.pair_code = self.pair_link = ""
            self._thread(self._prepare, generation)

    def _prepare(self, generation: int):
        from .diagnostics import run_diagnostics
        from . import service

        def report(check):
            with self.lock:
                if self._current(generation):
                    self.checks[check.id] = check

        try:
            runner = self.diagnostic_runner or run_diagnostics
            result = runner(self.root, live=True, report=report, cancel=self.stop)
            with self.lock:
                if not self._current(generation):
                    return
                if not result.ok:
                    self.phase = "blocked"
                    self.error = "Une étape reste à terminer. Corrigez le point indiqué, puis réessayez ici."
                    return
                self.phase, self.service_state = "starting", "running"
            start = self.service_start or service.start
            status = self.service_status or service.status
            started = start(self.root, cancel=self.stop)
            state = status(self.root)
            with self.lock:
                if not self._current(generation):
                    return
                if started != 0 or not (state.get("running") and state.get("ready")):
                    self.phase, self.service_state = "blocked", "error"
                    self.error = "Le service n’a pas démarré correctement. Les réglages sont enregistrés. Réessayez ; le test modèle déjà réussi sera réutilisé pendant quinze minutes."
                    return
                self.phase, self.service_state, self.result = "ready", "ok", 0
                self.done.set()
        except Exception:
            # Aucun détail brut : une exception réseau peut contenir un token.
            with self.lock:
                if self._current(generation):
                    if self.phase == "starting":
                        self.service_state = "error"
                    self.phase = "blocked"
                    self.error = "La vérification a été interrompue. Vos réglages sont enregistrés ; vous pouvez réessayer."

    def retry(self):
        with self.lock:
            if self.phase != "blocked":
                return
            self.phase, self.error, self.service_state = "diagnostics", "", "pending"
            self.generation += 1
            self._thread(self._prepare, self.generation)

    def edit_config(self):
        with self.lock:
            if self.phase != "blocked":
                return
            if is_locked(self.root / "data" / "service.lock"):
                self.error = "Le service est déjà actif. Arrêtez cette instance avec python run.py stop avant de modifier sa configuration."
                return
            self.generation += 1
            self.phase, self.error = "configure", ""

    def cancel_pairing(self):
        with self.lock:
            if self.phase in {"validating", "pairing"}:
                self.generation += 1
                self.phase = "configure"
                self.pair_code = self.pair_link = ""
                self.error = "Association annulée. La configuration précédente est conservée."

    def close(self):
        self.stop.set()
        with self.lock:
            self.auth_generation += 1
            attempt = self.auth_attempt
        if attempt is not None:
            attempt.cancel()
        # Laisser les opérations annulées arrêter leurs propres enfants avant
        # la sortie de Python, notamment pendant le lancement du service.
        deadline = time.monotonic() + 35
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))

    def render(self) -> bytes:
        from .setup_ui import render_wizard
        with self.lock:
            return render_wizard(self)


class WizardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, wizard: Wizard):
        self.wizard = wizard
        super().__init__(("127.0.0.1", 0), WizardHandler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = "http://" + self.host
        self.url = self.origin + wizard.path

    def handle_error(self, request, client_address):
        # Pas de traceback HTTP : un formulaire pourrait contenir un secret.
        pass


class WizardHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        pass

    def _send(self, code: int, data: bytes = b"", location: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", f"default-src 'none'; script-src {WATCH_CSP}; connect-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _error(self, code: int, message: str):
        # Le nouveau chemin privé ne doit jamais être révélé à un ancien onglet
        # ou à une requête venue d'une autre origine.
        trusted = (self.headers.get("Host") == self.server.host
                   and self.headers.get("Origin") in {None, self.server.origin}
                   and self.headers.get("Sec-Fetch-Site") != "cross-site"
                   and self.path.startswith(self.server.wizard.path))
        body = f'<h1>Revenons à l’installation.</h1><p class="intro">{escape(message)}</p>'
        if trusted:
            body += f'<a class="button primary" href="{escape(self.server.wizard.path)}">Revenir à l’installation</a>'
        else:
            body += '<p>Utilisez la dernière page ouverte par l’installateur ou l’adresse affichée dans son terminal. Cet onglet peut appartenir à une installation précédente.</p>'
        self._send(code, page(body))

    def _allowed(self, post=False) -> bool:
        origin = self.headers.get("Origin")
        if (self.headers.get("Host") != self.server.host
                or (post and origin != self.server.origin)
                or (origin is not None and origin != self.server.origin)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self._error(403, "Cette demande n’a pas pu être validée. Aucun réglage n’a été modifié.")
            return False
        parts = urlsplit(self.path)
        if parts.scheme or parts.netloc or parts.query or parts.fragment:
            self._error(404, "Cette page d’installation n’est plus active.")
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        if self.path != self.server.wizard.path:
            self._error(404, "Cette page d’installation n’est plus active.")
            return
        self.server.wizard.refresh_login()
        self._send(200, self.server.wizard.render())

    def do_POST(self):
        # Lire sans interpréter le corps avant les rejets Host/Origin/chemin.
        # Les paquets d'un petit POST peuvent arriver après ses en-têtes ; une
        # fermeture immédiate laisse alors des données TCP non lues sous Windows.
        raw = None
        try:
            lengths = self.headers.get_all("Content-Length", [])
            length = int(lengths[0]) if len(lengths) == 1 else -1
            if 0 < length <= MAX_DISCARD_BYTES:
                received = self.rfile.read(length)
                if len(received) == length and length <= MAX_FORM_BYTES:
                    raw = received
        except (ValueError, OSError):
            pass
        if not self._allowed(post=True):
            return
        wizard = self.server.wizard
        actions = {"login", "check-login", "cancel-login", "configure", "cancel", "retry", "edit-config", "finish"}
        action = self.path[len(wizard.path):] if self.path.startswith(wizard.path) else ""
        if action not in actions:
            self._error(404, "Cette page d’installation n’est plus active.")
            return
        if (self.headers.get_content_type() != "application/x-www-form-urlencoded"
                or self.headers.get("Transfer-Encoding") or raw is None):
            self._error(400, "Le formulaire n’a pas pu être lu. Revenez à la page pour réessayer.")
            return
        try:
            fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=12)
            if any(len(value) != 1 for value in fields.values()):
                raise ValueError
            fields = {key: value[0] for key, value in fields.items()}
        except (UnicodeError, ValueError):
            self._error(400, "Le formulaire n’a pas pu être lu. Revenez à la page pour réessayer.")
            return
        if not secrets.compare_digest(fields.pop("csrf", "").encode("utf-8"), wizard.csrf.encode("utf-8")):
            self._error(403, "Ce formulaire a expiré ou appartient à une ancienne page. Aucun réglage n’a été modifié.")
            return
        if action == "login":
            wizard.login()
        elif action == "check-login":
            wizard.check_login()
        elif action == "cancel-login":
            wizard.cancel_login()
        elif action == "configure":
            wizard.configure(fields)
        elif action == "cancel":
            wizard.cancel_pairing()
        elif action == "retry":
            wizard.retry()
        elif action == "edit-config":
            wizard.edit_config()
        elif action == "finish" and wizard.phase == "ready":
            self._send(200, page('<h1>À vous de jouer.</h1><p class="intro">L’assistant tourne en arrière-plan. Vous pouvez fermer cet onglet et lui écrire dans Telegram.</p><p>Gardez le PC allumé et connecté.</p>'))
            wizard.stop.set()
            return
        self._send(303, location=wizard.path)


def setup(root: Path, provider: str | None = None) -> int:
    root = root.expanduser().resolve()
    wizard = server = None
    try:
        if is_locked(root / "data" / "service.lock"):
            print("L'agent fonctionne déjà. Arrêtez-le avec python run.py stop avant de relancer setup.")
            return 1
        with FileLock(root / "data" / "setup.lock"):
            values = read_values(root)
            provider = (provider or values["PROVIDER"]).lower()
            if provider not in {"codex", "claude"}:
                print("Choisissez un moteur : setup --provider codex ou setup --provider claude.")
                return 1
            executable = find_cli(provider, values["CODEX_BIN" if provider == "codex" else "CLAUDE_BIN"])
            if not executable:
                print(f"Le CLI {provider} est introuvable. Relancez l'installateur en choisissant ce moteur.")
                return 1
            executable_command(executable)
            authenticated, _ = auth_status(provider, executable)
            wizard = Wizard(root, provider, executable, authenticated)
            wizard.enable_login_watch()
            server = WizardServer(wizard)
            server.timeout = 0.25
            print("Configuration dans votre navigateur. Saisissez le token Telegram uniquement dans le formulaire local.", flush=True)
            print("Si le navigateur ne s'ouvre pas, ouvrez cette adresse sur ce PC :", flush=True)
            print(server.url, flush=True)
            try:
                webbrowser.open(server.url)
            except webbrowser.Error:
                pass
            deadline, completed_at = time.monotonic() + SETUP_TIMEOUT, None
            while not wizard.stop.is_set() and time.monotonic() < deadline:
                server.handle_request()
                if wizard.done.is_set():
                    if completed_at is None:
                        completed_at = time.monotonic()
                        print("Assistant prêt : Telegram associé, modèle testé, service démarré. Vous pouvez lui écrire dans Telegram.", flush=True)
                    # Garder le formulaire disponible pendant le premier essai
                    # Telegram, jusqu'à Terminer ou à la limite du setup.
            if not wizard.done.is_set():
                print("Configuration expirée. Relancez setup pour recommencer ; votre mémoire est conservée.")
            return wizard.result
    except KeyboardInterrupt:
        print("\nConfiguration interrompue. Votre configuration précédente est conservée si l'association n'était pas terminée.")
        return 130
    except (OSError, ValueError, RuntimeError):
        print("Impossible de démarrer la configuration. Vérifiez le dossier, le CLI natif et qu'aucun autre setup n'est ouvert.")
        return 1
    finally:
        if wizard:
            wizard.close()
        if server:
            server.server_close()
