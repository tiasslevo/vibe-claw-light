"""Deux CLI natifs, entrée stdin UTF-8 et lecteur de pipes portable."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Callable

from .config import Config
from .processes import WindowsJob, child_environment, spawn_options, stop_tree


def find_cli(provider: str, configured: str = "") -> str | None:
    if provider not in {"codex", "claude"}:
        return None
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate.resolve()) if candidate.is_file() else shutil.which(configured)
    found = (shutil.which(provider + ".exe") if os.name == "nt" else None) or shutil.which(provider)
    if found:
        # Préférer le binaire natif au shim npm .cmd sur Windows.
        if os.name != "nt" or Path(found).suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            return found
    suffix = ".exe" if os.name == "nt" else ""
    candidates = [
        Path.home() / ".local" / "bin" / (provider + suffix),
        Path.home() / ".cargo" / "bin" / (provider + suffix),
    ]
    if os.name == "nt" and provider == "codex":
        candidates.append(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
    for path in candidates:
        if path.is_file():
            return str(path)
    return found


def executable_command(executable: str) -> list[str]:
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # Les shims npm ajoutent une couche shell. Installer le CLI natif évite
        # l'interprétation de caractères de prompt comme code PowerShell/CMD.
        raise ValueError("Installez le CLI natif avec scripts/install.ps1 ; un shim npm a été détecté.")
    return [executable]


def auth_status(provider: str, executable: str | None = None) -> tuple[bool, str]:
    executable = executable or find_cli(provider)
    if not executable:
        return False, f"{provider} n'est pas installé ou n'est pas détecté."
    args = ["login", "status"] if provider == "codex" else ["auth", "status"]
    try:
        result = subprocess.run(
            executable_command(executable) + args, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=25,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        if provider == "claude":
            try:
                valid = bool(json.loads(result.stdout).get("loggedIn"))
            except ValueError:
                valid = result.returncode == 0
        else:
            valid = result.returncode == 0
        return valid, f"{provider} : " + ("connexion enregistrée." if valid else "connectez-vous depuis le PC.")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False, f"Impossible de vérifier la connexion {provider}."


def build_command(config: Config, session_id: str | None = None, executable: str | None = None) -> list[str]:
    executable = executable or find_cli(config.provider, config.executable_hint)
    if not executable:
        raise ValueError(f"{config.provider} introuvable. Lancez l'installateur pour ce moteur.")
    cmd = executable_command(executable)
    if config.provider == "codex":
        # La politique est explicite à chaque invocation, y compris resume.
        cmd += ["-a", "never", "-c", 'sandbox_mode="workspace-write"']
        cmd += ["-c", "sandbox_workspace_write.network_access=false"]
        if session_id:
            cmd += ["exec", "resume", session_id, "--json", "--skip-git-repo-check"]
        else:
            cmd += ["exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", str(config.root)]
            if not config.workspace.is_relative_to(config.root):
                cmd += ["--add-dir", str(config.workspace)]
        if config.model:
            cmd += ["-m", config.model]
        cmd.append("-")
    else:
        allowed = ["Read", "Write", "Edit", "Glob", "Grep"]
        if config.allow_shell:
            allowed += ["Bash", "PowerShell"]
        cmd += ["-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "dontAsk", "--allowedTools", ",".join(allowed),
                "--tools", ",".join(allowed), "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}']
        if session_id:
            cmd += ["--resume", session_id]
        if not config.workspace.is_relative_to(config.root):
            cmd += ["--add-dir", str(config.workspace)]
        if config.model:
            cmd += ["--model", config.model]
    return cmd


def redact_secrets(text: str, config: Config) -> str:
    if config.telegram_token:
        text = text.replace(config.telegram_token, "[secret masqué]")
    return re.sub(r"(?:sk-[\w-]{12,}|gh[pousr]_[\w]{12,}|github_pat_[\w]{12,}|[0-9]{6,}:[A-Za-z0-9_-]{20,})", "[secret masqué]", text)


def safe_error(text: str, config: Config) -> str:
    text = redact_secrets(text, config)
    text = re.sub(r"https?://[^\s]+", "[adresse masquée]", text)
    return text[:1200]


@dataclass
class Result:
    text: str
    session_id: str | None = None
    error: str | None = None
    cancelled: bool = False


class ProviderRunner:
    def __init__(self, config: Config):
        self.config = config
        self.process: subprocess.Popen | None = None

    def run(
        self, prompt: str, session_id: str | None = None,
        cancel: threading.Event | None = None,
        on_session: Callable[[str], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> Result:
        cancel = cancel or threading.Event()
        command = build_command(self.config, session_id)
        proc = subprocess.Popen(
            command, cwd=self.config.root, env=child_environment(self.config.root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **spawn_options(),
        )
        self.process = proc
        job = None
        if os.name == "nt":
            try:
                job = WindowsJob(proc)
            except OSError:
                stop_tree(proc)
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    stream.close()
                self.process = None
                return Result("", session_id, "Windows n'a pas pu préparer l'arrêt des sous-processus. Consultez doctor.")
        events: queue.Queue = queue.Queue()
        stderr_tail: list[str] = []
        def reader(stream, label):
            try:
                for line in stream:
                    events.put((label, line))
            finally:
                events.put((label, None))
        threads = [threading.Thread(target=reader, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=reader, args=(proc.stderr, "err"), daemon=True)]
        for thread in threads:
            thread.start()
        def writer():
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        threading.Thread(target=writer, daemon=True).start()
        final_text = ""
        error = None
        closed = set()
        deadline = time.monotonic() + self.config.timeout_seconds
        try:
            while len(closed) < 2:
                if cancel.is_set():
                    stop_tree(proc)
                    return Result("", session_id, cancelled=True)
                if time.monotonic() >= deadline:
                    stop_tree(proc)
                    return Result(final_text, session_id, "Temps limite atteint. Réduisez la tâche ou réessayez.")
                try:
                    label, line = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    closed.add(label)
                    continue
                if label == "err":
                    stderr_tail.append(line.strip())
                    stderr_tail = stderr_tail[-8:]
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                event_type = event.get("type")
                sid = event.get("thread_id") if event_type == "thread.started" else event.get("session_id")
                if sid and re.fullmatch(r"[A-Za-z0-9_-]{8,128}", sid):
                    session_id = sid
                    if on_session:
                        on_session(sid)
                if self.config.provider == "codex":
                    item = event.get("item") or {}
                    if item.get("type") == "agent_message" and event_type == "item.completed":
                        final_text = item.get("text", "")
                    if event_type == "item.started" and on_progress:
                        names = {"command_execution": "Je travaille dans les fichiers.",
                                 "file_change": "Je prépare les modifications.",
                                 "web_search": "Je vérifie les informations."}
                        if item.get("type") in names:
                            on_progress(names[item["type"]])
                    if event_type == "turn.failed":
                        error = str(event.get("error", {}).get("message", "Codex a interrompu la tâche."))
                    if event_type == "error":
                        error = str(event.get("message", "Erreur Codex."))
                    if event_type == "turn.completed":
                        error = None
                else:
                    if event_type == "assistant":
                        parts = []
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use" and on_progress:
                                on_progress("Je travaille dans les fichiers.")
                        if parts:
                            final_text = "\n".join(parts)
                    if event_type == "result":
                        final_text = event.get("result") or final_text
                        if event.get("is_error"):
                            error = "; ".join(event.get("errors") or [final_text or "Claude a interrompu la tâche."])
                        elif event.get("permission_denials") and not final_text:
                            error = "Cette action demande une permission locale. Vérifiez la configuration depuis le PC."
            code = proc.wait(timeout=5)
            if code and not error:
                error = "\n".join(stderr_tail) or f"{self.config.provider} s'est arrêté (code {code}). Vérifiez la connexion et le quota."
            if not final_text and not error:
                error = "Le moteur n'a renvoyé aucune réponse. Lancez doctor --live depuis le PC."
            return Result(final_text, session_id, safe_error(error, self.config) if error else None)
        finally:
            if job:
                job.close()
            if proc.poll() is None or os.name != "nt":
                stop_tree(proc)
            for thread in threads:
                thread.join(timeout=1)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            self.process = None
