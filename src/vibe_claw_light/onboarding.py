"""Configuration dans le navigateur local ; aucun secret dans le chat du CLI."""
from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .config import read_values, save_config
from .processes import child_environment, spawn_options, stop_tree
from .providers import auth_status, executable_command, find_cli
from .storage import FileLock, atomic_write, is_locked, write_json
from .telegram import Telegram, TelegramError


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
                 authenticated: bool, telegram_factory=Telegram):
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
        self.allow_shell = self.initial["ALLOW_SHELL"].lower() in {"1", "true", "yes", "oui"}
        self.bot_username = ""
        self.pair_code = ""
        self.pair_link = ""
        self.generation = 0
        self.threads: list[threading.Thread] = []
        self.auth_process: subprocess.Popen | None = None
        self.result = 1

    def _thread(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def login(self):
        with self.lock:
            if self.phase != "auth":
                return
            self.phase, self.error = "authenticating", ""
            self._thread(self._login)

    def _login(self):
        args = ["login"] if self.provider == "codex" else ["auth", "login"]
        process = None
        try:
            # Sortie directe du CLI pour son propre parcours OAuth. Aucun cache
            # d'authentification ni credential n'est lu par l'installateur.
            print(f"Connexion {self.provider} : terminez la connexion dans le navigateur.", flush=True)
            with self.lock:
                if self.stop.is_set():
                    return
                process = subprocess.Popen(
                    executable_command(self.executable) + args, cwd=self.root,
                    env=child_environment(self.root), stdin=subprocess.DEVNULL,
                    **spawn_options(),
                )
                self.auth_process = process
            deadline = time.monotonic() + AUTH_TIMEOUT
            while process.poll() is None and not self.stop.wait(0.2):
                if time.monotonic() >= deadline:
                    break
            if process.poll() is None:
                stop_tree(process)
            if self.stop.is_set():
                return
            valid, _ = auth_status(self.provider, self.executable)
            with self.lock:
                self.phase = "configure" if valid else "auth"
                self.error = "" if valid else (
                    "Connexion non terminée. Vous pouvez réessayer ci-dessous. "
                    "Si le navigateur ne s'ouvre pas, lancez la commande de connexion affichée sur cette page dans un terminal."
                )
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                self.phase = "auth"
                self.error = "Impossible de lancer la connexion. Réessayez ou utilisez la commande affichée dans un terminal."
        finally:
            if process is not None and process.poll() is None:
                stop_tree(process)
            self.auth_process = None

    def check_login(self):
        with self.lock:
            if self.phase != "auth":
                return
            self.phase, self.error = "authenticating", ""
            self._thread(self._check_login)

    def _check_login(self):
        valid, _ = auth_status(self.provider, self.executable)
        with self.lock:
            self.phase = "configure" if valid else "auth"
            self.error = "" if valid else "Connexion non détectée. Connectez-vous puis réessayez."

    def configure(self, fields: dict[str, str]):
        with self.lock:
            if self.phase != "configure":
                return
            name = fields.get("name", "").strip()
            workspace_text = fields.get("workspace", "").strip()
            token = fields.get("token", "").strip() or self.initial["TELEGRAM_TOKEN"]
            if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
                self.error = "Choisissez un nom entre 1 et 80 caractères."
                return
            if not workspace_text or len(workspace_text) > 2000 or any(ord(char) < 32 for char in workspace_text):
                self.error = "Indiquez un dossier de travail valide."
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
            self.allow_shell = self.provider == "claude" and fields.get("allow_shell") == "1"
            self.phase, self.error = "validating", ""
            self.generation += 1
            generation = self.generation
            updates = {
                "PROVIDER": self.provider, "AGENT_NAME": name,
                "WORKSPACE": str(workspace), "TELEGRAM_TOKEN": token,
                "ALLOW_SHELL": "1" if self.allow_shell else "0",
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
            me = telegram.get_me()
            username = me.get("username", "")
            if not me.get("is_bot") or not re.fullmatch(r"[A-Za-z0-9_]{5,64}", username):
                self._fail(generation, "Ce token ne correspond pas à un bot Telegram utilisable.")
                return
            webhook = telegram.request("getWebhookInfo")
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
                    if exc.code in {0, 429}:
                        self.stop.wait(min(max(exc.retry_after, 1), 5))
                        continue
                    raise
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
            self._fail(generation, messages.get(exc.code, "Telegram est indisponible pour le moment. Vérifiez votre connexion puis réessayez."))
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
            self.phase, self.result = "done", 0
            self.pair_code = self.pair_link = ""
            self.done.set()

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
            process = self.auth_process
        if process is not None and process.poll() is None:
            stop_tree(process)
        for thread in self.threads:
            thread.join(timeout=0.3)

    def render(self) -> bytes:
        with self.lock:
            e = escape
            hidden = f'<input type="hidden" name="csrf" value="{e(self.csrf)}">'
            def form(action, contents):
                return f'<form method="post" action="{e(self.path + action)}">{hidden}{contents}</form>'
            refresh = self.phase in {"authenticating", "validating", "pairing"}
            body = '<p class="eyebrow">Vibe Claw Light · Installation locale</p>'
            if self.error:
                body += f'<p role="alert" class="error">{e(self.error)}</p>'
            if self.phase == "auth":
                login_command = "codex login" if self.provider == "codex" else "claude auth login"
                body += f'<h1>Connectez {e(self.provider)}</h1><p>Utilisez le compte dont vous souhaitez employer l’abonnement. Seul ce moteur sera configuré.</p>'
                body += form("login", '<button>Ouvrir la connexion</button>')
                body += f'<p>Si la fenêtre de connexion ne s’ouvre pas, lancez <code>{login_command}</code> dans un terminal, puis revenez ici.</p>'
                body += form("check-login", '<button class="secondary">J’ai terminé la connexion, vérifier</button>')
            elif self.phase == "authenticating":
                body += '<h1>Connexion en cours</h1><p>Terminez la connexion dans l’onglet ouvert par le moteur. Cette page se met à jour automatiquement.</p><p>Après cinq minutes, vous pourrez recommencer si nécessaire.</p>'
            elif self.phase == "configure":
                existing = bool(self.initial["TELEGRAM_TOKEN"])
                body += '<h1>Votre assistant</h1><p>Ces informations restent sur ce PC. Le token est enregistré dans votre fichier privé <code>config.env</code>.</p>'
                fields = f'<label>Nom de l’assistant<input name="name" maxlength="80" required value="{e(self.name, quote=True)}"></label>'
                fields += f'<label>Dossier où travailler<input name="workspace" required value="{e(self.workspace, quote=True)}" spellcheck="false"></label><p class="hint">Un chemin complet est accepté. Un chemin relatif sera créé dans le dossier du starter.</p>'
                fields += '<p>Dans Telegram, ouvrez <a href="https://t.me/BotFather" target="_blank" rel="noreferrer noopener">BotFather</a>, choisissez <code>/newbot</code>, puis copiez le token fourni ci-dessous.</p>'
                fields += '<label>Token du bot Telegram<input type="password" name="token" autocomplete="new-password" spellcheck="false"' + ('' if existing else ' required') + '></label>'
                if existing:
                    fields += '<p class="hint">Un token est déjà enregistré. Laissez ce champ vide pour le conserver.</p>'
                owner, chat = self.initial["TELEGRAM_OWNER_ID"], self.initial["TELEGRAM_CHAT_ID"]
                if existing and owner.isdecimal() and int(owner) > 0 and owner == chat:
                    fields += '<label class="check"><input type="checkbox" name="keep_owner" value="1" checked>Conserver l’association Telegram existante si le token reste le même.</label>'
                if self.provider == "claude":
                    checked = ' checked' if self.allow_shell else ''
                    fields += f'<label class="check"><input type="checkbox" name="allow_shell" value="1"{checked}>Autoriser Claude à exécuter des commandes sur ce PC.</label><p class="hint">Les commandes utilisent les droits de votre compte. Claude Code ne fournit pas de sandbox système Windows ici. Laissez décoché pour commencer avec les outils de fichiers.</p>'
                else:
                    fields += '<p class="hint">Codex utilise son mode de travail limité au dossier du projet et au dossier choisi.</p>'
                fields += '<button>Vérifier et associer Telegram</button>'
                body += form("configure", fields)
            elif self.phase == "validating":
                body += '<h1>Vérification du bot</h1><p>Connexion à Telegram en cours. Aucun changement de configuration n’est encore enregistré.</p>'
                body += form("cancel", '<button class="secondary">Revenir au formulaire</button>')
            elif self.phase == "pairing":
                body += f'<h1>Associez votre Telegram</h1><p>Ouvrez ce lien avec votre compte personnel, puis appuyez sur <strong>Démarrer</strong> dans la conversation privée de votre bot.</p><p><a class="button" href="{e(self.pair_link, quote=True)}" target="_blank" rel="noreferrer noopener">Ouvrir @{e(self.bot_username)} dans Telegram</a></p><p>Sur un autre appareil, ouvrez ce même lien :</p><p class="link">{e(self.pair_link)}</p><p class="hint">Le lien expire après cinq minutes. Gardez-le pour vous : il associe votre compte à cet assistant. Cette page se met à jour automatiquement.</p>'
                body += form("cancel", '<button class="secondary">Revenir au formulaire</button>')
            else:
                body += f'<h1>{e(self.name)} est configuré</h1><p>Votre bot <a href="https://t.me/{e(self.bot_username)}" target="_blank" rel="noreferrer noopener">@{e(self.bot_username)}</a> est associé à votre compte.</p><p>Le service n’est pas encore démarré. Si vous avez utilisé l’installateur, il poursuit automatiquement avec la vérification puis le démarrage après ce formulaire. Le test réel utilise votre quota.</p>'
                body += form("finish", '<button>Terminer et continuer l’installation</button>')
                body += '<details><summary>J’ai lancé setup seul, sans l’installateur</summary><p>Retournez dans Codex ou Claude Code et demandez de continuer avec :</p><ol><li><code>python run.py doctor --live</code> pour vérifier une vraie action.</li><li><code>python run.py start</code> pour démarrer l’assistant en arrière-plan.</li></ol></details><p>Ensuite, écrivez-lui sur Telegram. Le PC doit rester allumé et connecté.</p>'
            html = '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            if refresh:
                html += '<meta http-equiv="refresh" content="2">'
            html += '<title>Configurer votre assistant</title><style>body{font:17px/1.55 system-ui,sans-serif;background:#f5f4f0;color:#232323;margin:0;padding:32px 16px}main{max-width:650px;margin:auto;background:white;padding:32px;border-radius:14px}h1{line-height:1.2;font-size:32px}.eyebrow,.hint{color:#60605d}.eyebrow{font-size:14px}label{display:block;margin:22px 0 8px;font-weight:600}input:not([type=checkbox]):not([type=hidden]){display:block;box-sizing:border-box;width:100%;font:inherit;padding:12px;border:1px solid #a5a5a0;border-radius:6px;margin-top:6px}button,.button{display:inline-block;background:#252b28;color:white;border:0;border-radius:6px;padding:12px 18px;font:inherit;cursor:pointer;text-decoration:none;margin-top:14px}.secondary{background:#eee;color:#222}.error{padding:14px;background:#fff0df;color:#7b3f00}.hint{font-size:14px}.check{font-weight:400}.check input{margin-right:8px}code{font-size:.9em;background:#f2f2ed;padding:2px 5px}.link{overflow-wrap:anywhere}a{color:#235942}li{margin:12px 0}</style></head><body><main>'
            return (html + body + '</main></body></html>').encode("utf-8")


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
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _allowed(self, post=False) -> bool:
        origin = self.headers.get("Origin")
        if (self.headers.get("Host") != self.server.host
                or (post and origin != self.server.origin)
                or (origin is not None and origin != self.server.origin)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self._send(403, b"Acces refuse.")
            return False
        parts = urlsplit(self.path)
        if parts.scheme or parts.netloc or parts.query or parts.fragment:
            self._send(404, b"Page introuvable.")
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        if self.path != self.server.wizard.path:
            self._send(404, b"Page introuvable.")
            return
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
        actions = {"login", "check-login", "configure", "cancel", "finish"}
        action = self.path[len(wizard.path):] if self.path.startswith(wizard.path) else ""
        if action not in actions:
            self._send(404, b"Page introuvable.")
            return
        if (self.headers.get_content_type() != "application/x-www-form-urlencoded"
                or self.headers.get("Transfer-Encoding") or raw is None):
            self._send(400, b"Formulaire invalide.")
            return
        try:
            fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=12)
            if any(len(value) != 1 for value in fields.values()):
                raise ValueError
            fields = {key: value[0] for key, value in fields.items()}
        except (UnicodeError, ValueError):
            self._send(400, b"Formulaire invalide.")
            return
        if not secrets.compare_digest(fields.pop("csrf", "").encode("utf-8"), wizard.csrf.encode("utf-8")):
            self._send(403, b"Acces refuse.")
            return
        if action == "login":
            wizard.login()
        elif action == "check-login":
            wizard.check_login()
        elif action == "configure":
            wizard.configure(fields)
        elif action == "cancel":
            wizard.cancel_pairing()
        elif action == "finish" and wizard.phase == "done":
            self._send(200, b"Configuration terminee. Vous pouvez fermer cet onglet et revenir a Codex ou Claude Code.")
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
                        print("Configuration enregistrée. Terminez dans le navigateur ; l'installateur poursuit automatiquement. Si setup a été lancé seul : python run.py doctor --live puis python run.py start.", flush=True)
                    # Laisser le navigateur charger la page finale sans garder
                    # le terminal occupé si l'utilisateur ferme son onglet.
                    if time.monotonic() - completed_at > 20:
                        break
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
