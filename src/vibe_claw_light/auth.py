"""Connexion native dans un terminal : aucun code OAuth ne passe par le Web.

Le petit relais est aussi exécutable directement dans une nouvelle fenêtre.
Ses fichiers de contrôle ne contiennent que des chemins et des états de sortie.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

# Une fenêtre Terminal démarre ce fichier par son chemin absolu, y compris
# lorsque le starter a été extrait sans installation du paquet Python.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibe_claw_light.processes import child_environment
from vibe_claw_light.providers import executable_command
from vibe_claw_light.storage import atomic_write, read_json, write_json


def interactive_terminal() -> bool:
    """Un pipe (ou le pseudo-terminal d'un agent) n'est pas le clavier du PC."""
    if any(os.environ.get(key) for key in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CLAUDECODE")):
        return False
    return bool(sys.stdin and sys.stdout and sys.stdin.isatty() and sys.stdout.isatty())


def manual_command(provider: str, executable: str) -> str:
    args = ["login"] if provider == "codex" else ["auth", "login"]
    if os.name == "nt":
        # Commande à copier dans PowerShell, sans interpolation du chemin.
        return "& '" + executable.replace("'", "''") + "' " + " ".join(args)
    return shlex.join([executable, *args])


def terminal_command(command: list[str], environment: dict[str, str]) -> tuple[list[str], bool] | None:
    """Retourner le lanceur et s'il reste vivant avec sa fenêtre."""
    if sys.platform == "darwin":
        shell_command = shlex.join(command)
        script = 'tell application "Terminal"\nactivate\ndo script ' + json.dumps(shell_command, ensure_ascii=False) + '\nend tell'
        return ["/usr/bin/osascript", "-e", script], False
    if not (environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")):
        return None
    candidates = (
        ("gnome-terminal", ["--wait", "--"], True),
        ("konsole", ["--separate", "-e"], True),
        ("xfce4-terminal", ["--disable-server", "-x"], True),
        ("xterm", ["-e"], True),
        ("x-terminal-emulator", ["-e"], False),
    )
    for name, options, waits in candidates:
        executable = shutil.which(name)
        if executable:
            return [executable, *options, *command], waits
    return None


class LoginAttempt:
    def __init__(self, directory: Path, process: subprocess.Popen, waits: bool):
        self.directory, self.process, self.waits = directory, process, waits

    def poll(self) -> int | None:
        result = read_json(self.directory / "result.json", {})
        if type(result.get("exit_code")) is int:
            return result["exit_code"]
        code = self.process.poll()
        # Certains lanceurs GUI sortent dès l'ouverture du terminal.
        if code is not None and (self.waits or code != 0):
            return code or 1  # Un relais fermé sans résultat n'est pas un succès.
        return None

    def cancel(self) -> None:
        if self.directory.exists():
            atomic_write(self.directory / "cancel", "cancel\n")

    def close(self) -> None:
        self.cancel()
        deadline = time.monotonic() + 3
        while self.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.poll() is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
        # Ne pas supprimer le marqueur si Terminal ouvre sa fenêtre en retard :
        # le relais doit encore voir l'annulation et ne pas lancer une connexion.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)


def start_login(root: Path, provider: str, executable: str, timeout: float = 300) -> LoginAttempt | None:
    if provider not in {"codex", "claude"}:
        raise ValueError("Moteur de connexion inconnu.")
    executable_command(executable)
    environment = child_environment(root)
    attached = interactive_terminal()
    control_root = root / "data" / "auth"
    control_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="login-", dir=control_root))
    # VIBE_CLAW_ROOT doit survivre même si un serveur de terminal existant
    # n'hérite pas de notre environnement. Aucun autre secret n'est sérialisé.
    write_json(directory / "request.json", {
        "root": str(root), "provider": provider, "executable": executable,
        "expires_at": time.time() + timeout,
        "instance_root": os.environ.get("VIBE_CLAW_ROOT"),
    })
    command = [sys.executable, str(Path(__file__).resolve()), str(directory)]
    kwargs = {"cwd": root, "env": environment}
    waits = True
    try:
        if attached:
            # Pas de redirection, pas de nouvelle session : le clavier et le
            # terminal de contrôle sont ceux de l'installateur interactif.
            pass
        elif os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        else:
            launcher = terminal_command(command, environment)
            if launcher is None:
                shutil.rmtree(directory)
                return None
            command, waits = launcher
            # Seul le lanceur GUI est détaché des pipes de l'agent appelant.
            # Le relais et le CLI auront les vrais descripteurs du terminal.
            kwargs.update(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
        process = subprocess.Popen(command, **kwargs)
        return LoginAttempt(directory, process, waits)
    except (OSError, ValueError, subprocess.SubprocessError):
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _stop_login(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        # Le CLI partage volontairement le groupe de premier plan du terminal.
        # Un killpg viserait aussi l'installateur : terminer ce processus seul.
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def run_terminal(directory: Path) -> int:
    """Relais exécuté dans un vrai terminal, jamais un lecteur de credentials."""
    request = read_json(directory / "request.json", {})
    cancel = directory / "cancel"
    process, code = None, 1
    try:
        if cancel.exists() or time.time() >= request["expires_at"]:
            code = 130
            return code
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            code = 2
            return code
        root = Path(request["root"])
        provider = request["provider"]
        if provider not in {"claude", "codex"}:
            code = 2
            return code
        args = ["login"] if provider == "codex" else ["auth", "login"]
        environment = child_environment(root)
        if request.get("instance_root") is not None:
            environment["VIBE_CLAW_ROOT"] = request["instance_root"]
        print("Terminez la connexion officielle. Si un code est demandé, collez-le dans ce terminal.", flush=True)
        process = subprocess.Popen(executable_command(request["executable"]) + args,
                                   cwd=root, env=environment)
        while process.poll() is None:
            if cancel.exists() or time.time() >= request["expires_at"]:
                _stop_login(process)
                code = 130
                break
            time.sleep(0.1)
        else:
            code = process.returncode
        return code
    except KeyboardInterrupt:
        code = 130
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return 1
    finally:
        if process is not None:
            _stop_login(process)
        # Ce fichier ne contient jamais la sortie du CLI ni le code OAuth.
        write_json(directory / "result.json", {"exit_code": code})


if __name__ == "__main__":
    raise SystemExit(run_terminal(Path(sys.argv[1])))
