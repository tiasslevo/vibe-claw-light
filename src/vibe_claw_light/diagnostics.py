"""Reusable installation checks, bounded retries and a private model-test cache."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Callable

from . import __version__
from .config import Config, load_config
from .memory import MemoryStore
from .processes import child_environment
from .providers import ProviderRunner, auth_status, executable_command, find_cli
from .storage import FileLock, read_json, write_json
from .telegram import Telegram, TelegramError, retry_telegram


MODEL_CACHE_SECONDS = 15 * 60
MODEL_TIMEOUT_SECONDS = 90
NETWORK_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class DiagnosticCheck:
    id: str
    status: str
    message: str
    code: str = ""
    retryable: bool = False
    cached: bool = False
    attempt: int = 1


@dataclass(frozen=True)
class DiagnosticResult:
    ok: bool
    checks: tuple[DiagnosticCheck, ...]
    cancelled: bool = False


def _file_identity(path: Path) -> dict:
    """Use filesystem metadata, never read or serialize authentication secrets."""
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime": stat.st_mtime_ns, "inode": stat.st_ino}
    except OSError:
        return {"present": False}


def _fingerprint(config: Config, executable: str, version: str) -> str:
    auth_root = Path(os.environ.get(
        "CODEX_HOME" if config.provider == "codex" else "CLAUDE_CONFIG_DIR",
        str(Path.home() / (".codex" if config.provider == "codex" else ".claude")),
    )).expanduser()
    auth_file = auth_root / ("auth.json" if config.provider == "codex" else ".credentials.json")
    value = {
        "app": __version__, "provider": config.provider, "model": config.model,
        "executable": str(Path(executable).resolve()), "binary": _file_identity(Path(executable)),
        "version": version, "root": str(config.root), "workspace": str(config.workspace),
        "roots": [str(path) for path in config.allowed_roots], "access": config.access_mode,
        "shell": config.shell_enabled, "network": config.network_enabled,
        "auth_file": str(auth_file), "auth_identity": _file_identity(auth_file),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _cache_path(config: Config) -> Path:
    return config.data / "diagnostic-success.json"


def _read_cache(config: Config) -> dict:
    path = _cache_path(config)
    try:
        if path.is_symlink() or path.stat().st_size > 16384:
            return {}
        value = read_json(path, {})
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("models"), dict):
            return {}
        records = {}
        for provider in ("codex", "claude"):
            record = value["models"].get(provider)
            if not isinstance(record, dict):
                continue
            fingerprint, timestamp = record.get("fingerprint"), record.get("at")
            if (isinstance(fingerprint, str) and re.fullmatch(r"[a-f0-9]{64}", fingerprint)
                    and isinstance(timestamp, (float, int)) and math.isfinite(timestamp)):
                records[provider] = {"fingerprint": fingerprint, "at": timestamp}
        return records
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return {}


def _cached(config: Config, fingerprint: str) -> bool:
    record = _read_cache(config).get(config.provider)
    if not isinstance(record, dict) or record.get("fingerprint") != fingerprint:
        return False
    timestamp = record.get("at")
    if not isinstance(timestamp, (float, int)):
        return False
    age = time.time() - timestamp
    return 0 <= age < MODEL_CACHE_SECONDS


def _write_cache(config: Config, fingerprint: str | None) -> bool:
    records = _read_cache(config)
    # Only known providers and small success records survive a write.
    records = {key: value for key, value in records.items() if key in {"codex", "claude"}}
    if fingerprint is None:
        records.pop(config.provider, None)
    else:
        records[config.provider] = {"fingerprint": fingerprint, "at": time.time()}
    try:
        write_json(_cache_path(config), {"version": 1, "models": records})
        return True
    except OSError:
        return False


def _model_failure(error: str | None) -> tuple[str, str, bool]:
    """Categorize provider errors without returning arbitrary CLI output."""
    value = (error or "").lower()
    if re.search(r"\b(?:401|unauthori[sz]ed|authentication|not logged in|login required)\b", value):
        return "model.auth", "Le moteur a refusé l'authentification. Reconnectez le compte choisi.", False
    if re.search(r"\b(?:429|quota|rate.limit|usage.limit|credit|billing)\b", value):
        return "model.quota", "Le moteur a atteint une limite de quota ou d'abonnement. Vérifiez le compte choisi.", False
    if re.search(r"\b(?:403|forbidden|permission.denied|access.denied)\b", value):
        return "model.access", "Le moteur a refusé l'accès demandé. Vérifiez le modèle et les permissions locales.", False
    if "temps limite" in value or "timed out" in value or "timeout" in value:
        return "model.timeout", "Le test du moteur a dépassé son délai. Une nouvelle tentative est possible.", True
    if any(word in value for word in ("network", "connection", "connectivity", "dns", "réseau", "503", "502")):
        return "model.network", "La connexion au moteur a échoué pendant le test. Vérifiez le réseau puis réessayez.", True
    return "model.failed", "Le moteur n'a pas créé le fichier temporaire attendu. Vérifiez sa connexion et ses permissions.", True


def run_diagnostics(root: Path, live: bool = True,
                    report: Callable[[DiagnosticCheck], None] | None = None,
                    cancel: threading.Event | None = None) -> DiagnosticResult:
    """Check readiness without starting a service or sending Telegram messages.

    A report callback receives transitions; the result contains the latest state
    of each check. Only an explicit live run may consume model quota, and never
    after a failed prerequisite. Authentication is rechecked even on a cache hit.
    """
    cancel = cancel or threading.Event()
    checks: dict[str, DiagnosticCheck] = {}

    def emit(identifier: str, status: str, message: str, code: str = "", **details) -> None:
        check = DiagnosticCheck(identifier, status, message, code, **details)
        checks[identifier] = check
        if report:
            report(check)

    def finish() -> DiagnosticResult:
        cancelled = cancel.is_set() or any(check.code.endswith("cancelled") for check in checks.values())
        ok = bool(checks) and not cancelled and all(check.status in {"ok", "skipped"} for check in checks.values())
        return DiagnosticResult(ok, tuple(checks.values()), cancelled)

    def stopped() -> bool:
        if not cancel.is_set():
            return False
        emit("cancel", "error", "Vérification annulée. Aucun démarrage effectué.", "diagnostic.cancelled")
        return True

    if stopped():
        return finish()
    emit("config", "running", "Lecture de la configuration locale.")
    try:
        config = load_config(root, require_token=False)
    except (OSError, ValueError, TypeError):
        emit("config", "error", "La configuration locale est illisible ou incomplète. Reprenez le formulaire.", "config.invalid")
        return finish()
    emit("config", "ok", "Configuration locale lisible.")

    executable, version = None, "unknown"
    emit("engine", "running", f"Vérification du moteur {config.provider}.")
    try:
        executable = find_cli(config.provider, config.executable_hint)
        if not executable:
            emit("engine", "error", f"Le moteur {config.provider} n'est pas détecté. Relancez son installation.", "engine.missing")
        else:
            result = subprocess.run(
                executable_command(executable) + ["--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10, env=child_environment(config.root),
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
            )
            if result.returncode:
                emit("engine", "error", "Le moteur installé ne peut pas démarrer.", "engine.unusable")
            else:
                match = re.search(r"\b\d{1,4}\.\d{1,4}\.\d{1,6}\b", result.stdout or "")
                version = match.group(0) if match else "unknown"
                emit("engine", "ok", f"Moteur {config.provider} détecté" + (f" ({version})." if match else "."))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        emit("engine", "error", "L'exécutable du moteur est indisponible ou n'a pas répondu.", "engine.unusable")
    if stopped():
        return finish()

    if checks["engine"].status == "ok":
        emit("auth", "running", "Vérification de la connexion au compte du moteur.")
        try:
            authenticated, _ = auth_status(config.provider, executable)
            emit("auth", "ok" if authenticated else "error",
                 "Connexion au moteur enregistrée." if authenticated else "Connectez le compte du moteur dans le terminal puis réessayez.",
                 "auth.ok" if authenticated else "auth.required")
            if not authenticated:
                _write_cache(config, None)
        except Exception:
            emit("auth", "error", "Une erreur interne empêche de vérifier la connexion au moteur.", "auth.internal")
            _write_cache(config, None)
    else:
        emit("auth", "skipped", "Connexion non vérifiée : moteur indisponible.", "auth.blocked")
    if stopped():
        return finish()

    paired = bool(config.telegram_token and config.owner_id and config.chat_id == config.owner_id and config.owner_id > 0)
    emit("pairing", "ok" if paired else "error",
         "Telegram associé au compte privé." if paired else "L'association Telegram privée reste à terminer dans le formulaire.",
         "pairing.ok" if paired else "pairing.required")
    if config.telegram_token:
        emit("telegram", "running", "Vérification de la connexion à Telegram.")
        telegram = Telegram(config.telegram_token)
        attempt = 1

        def probe_telegram():
            me = telegram.request("getMe", timeout=NETWORK_TIMEOUT_SECONDS)
            if not isinstance(me, dict) or not isinstance(me.get("id"), int) or me.get("is_bot") is not True:
                raise TelegramError(0, category="internal")
            if cancel.is_set():
                raise TelegramError(0, category="cancelled")
            webhook = telegram.request("getWebhookInfo", timeout=NETWORK_TIMEOUT_SECONDS)
            if not isinstance(webhook, dict) or "url" not in webhook or not isinstance(webhook["url"], str):
                raise TelegramError(0, category="internal")
            if webhook["url"]:
                raise TelegramError(409, category="webhook")

        def retry_report(error: TelegramError, next_attempt: int, delay: float):
            nonlocal attempt
            attempt = next_attempt
            emit("telegram", "running", str(error) + f" Nouvelle tentative {next_attempt}/3 dans {delay:g} s.",
                 "telegram." + error.category, retryable=True, attempt=next_attempt)

        try:
            retry_telegram(probe_telegram, cancel=cancel, on_retry=retry_report)
            emit("telegram", "ok", "Telegram accessible ; aucun webhook actif.", "telegram.ok", attempt=attempt)
        except TelegramError as exc:
            emit("telegram", "error", str(exc), "telegram." + exc.category,
                 retryable=exc.retryable, attempt=attempt)
        except Exception:
            emit("telegram", "error", "Une erreur interne a interrompu la vérification Telegram.", "telegram.internal")
    else:
        emit("telegram", "skipped", "Connexion Telegram non vérifiée : association incomplète.", "telegram.blocked")
    if stopped():
        return finish()

    try:
        config.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=config.workspace) as probe:
            probe.write(b"ok")
        emit("workspace", "ok", "Le dossier de travail permet de créer des fichiers.")
    except OSError:
        emit("workspace", "error", "Le dossier de travail n'est pas accessible en écriture.", "workspace.access")
    try:
        healthy, _ = MemoryStore(root).health()
    except (OSError, ValueError, TypeError):
        healthy = False
    emit("memory", "ok" if healthy else "error",
         "Mémoire locale lisible." if healthy else "Mémoire illisible ; le fichier original est conservé.",
         "memory.ok" if healthy else "memory.invalid")
    try:
        from .runtime import validate_state
        state = read_json(config.data / "state.json", None)
        if state is not None:
            validate_state(state)
        emit("state", "ok", "État des conversations lisible.")
    except (OSError, ValueError, TypeError, RecursionError):
        emit("state", "error", "L'état des conversations est illisible ; le fichier original est conservé.", "state.invalid")
    if stopped():
        return finish()

    if not live:
        emit("model", "skipped", "Test réel du modèle non demandé ; aucun quota consommé.", "model.not_requested")
        return finish()
    if any(check.status == "error" for check in checks.values()):
        emit("model", "skipped", "Test du modèle différé : corrigez les étapes signalées. Aucun quota consommé.", "model.blocked")
        return finish()

    lock = FileLock(config.data / "diagnostic-model.lock")
    try:
        lock.acquire()
    except (OSError, RuntimeError):
        emit("model", "error", "Un autre test du moteur est en cours, ou son verrou est indisponible. Réessayez ensuite.",
             "model.busy", retryable=True)
        return finish()
    try:
        fingerprint = _fingerprint(config, executable, version)
        if _cached(config, fingerprint):
            emit("model", "ok", "Modèle déjà testé avec cette configuration depuis moins de 15 minutes ; aucun nouvel appel.",
                 "model.cached", cached=True)
            return finish()
        if stopped():
            return finish()
        emit("model", "running", "Test réel du moteur : création d'un fichier temporaire distinct de vos documents (utilise du quota).")
        if stopped():
            return finish()
        try:
            diagnostic_root = config.data / "diagnostics"
            diagnostic_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryDirectory(prefix="test-", dir=diagnostic_root) as directory:
                path = Path(directory) / "verification.txt"
                result = ProviderRunner(replace(config, timeout_seconds=MODEL_TIMEOUT_SECONDS)).run(
                    "Test de fonctionnement autorisé. Crée uniquement le fichier " + json.dumps(str(path), ensure_ascii=False)
                    + " avec le contenu exact VIBE_LIGHT_OK. Ce fichier de diagnostic sera supprimé. "
                    "Ne lis aucun autre fichier, n'utilise aucun plugin ni recherche. Réponds ensuite VIBE_LIGHT_OK.",
                    cancel=cancel,
                )
                if cancel.is_set() or result.cancelled:
                    emit("model", "error", "Test du modèle annulé ; aucun succès enregistré.", "model.cancelled")
                    return finish()
                worked = (not result.error and path.is_file() and not path.is_symlink()
                          and path.stat().st_size <= 100 and path.read_text(encoding="utf-8").strip() == "VIBE_LIGHT_OK")
                if not worked:
                    _write_cache(config, None)
                    code, message, retryable = _model_failure(result.error)
                    emit("model", "error", message, code, retryable=retryable)
                    return finish()
            # A successful invocation may refresh the CLI's credential metadata.
            cached = _write_cache(config, _fingerprint(config, executable, version))
            emit("model", "ok", "Le modèle a créé le fichier temporaire demandé ; test terminé."
                 + ("" if cached else " Le cache de succès n'a pas pu être enregistré."),
                 "model.ok" if cached else "model.ok_uncached")
        except (OSError, ValueError, RuntimeError, TypeError):
            emit("model", "error", "Le test du modèle a été interrompu par une erreur locale. Vérifiez les permissions puis réessayez.",
                 "model.local", retryable=True)
        return finish()
    finally:
        lock.release()
