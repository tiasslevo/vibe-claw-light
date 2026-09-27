"""Relais de connexion : faux CLI uniquement, aucun fournisseur contacté."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shlex
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vibe_claw_light import auth
from vibe_claw_light.storage import atomic_write, read_json, write_json


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-login-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_pipe_without_desktop_uses_manual_fallback_without_launching_cli(self):
        with patch.object(auth, "interactive_terminal", return_value=False), \
                patch.object(auth.sys, "platform", "linux"), \
                patch.object(auth, "os", SimpleNamespace(name="posix", environ={})), \
                patch.object(auth, "child_environment", return_value={}), \
                patch.object(auth.subprocess, "Popen") as popen:
            self.assertIsNone(auth.start_login(self.root, "claude", "claude"))
        popen.assert_not_called()
        self.assertEqual(list((self.root / "data" / "auth").iterdir()), [])

    def test_existing_terminal_inherits_input_and_keeps_calling_instance(self):
        process = Mock()
        process.poll.return_value = 1
        with patch.object(auth, "interactive_terminal", return_value=True), \
                patch.dict(os.environ, {"VIBE_CLAW_ROOT": "/private/source-instance"}), \
                patch.object(auth.subprocess, "Popen", return_value=process) as popen:
            attempt = auth.start_login(self.root, "claude", "test-cli")
        self.assertEqual(popen.call_args.kwargs["env"]["VIBE_CLAW_ROOT"], "/private/source-instance")
        for key in ("stdin", "stdout", "stderr", "start_new_session", "creationflags"):
            self.assertNotIn(key, popen.call_args.kwargs)
        self.assertEqual(read_json(attempt.directory / "request.json")["provider"], "claude")
        self.assertNotIn("TELEGRAM_TOKEN", (attempt.directory / "request.json").read_text())
        attempt.close()

    def test_agent_pseudoterminal_is_not_assumed_to_be_a_human_terminal(self):
        with patch.object(auth.sys, "stdin") as stdin, patch.object(auth.sys, "stdout") as stdout, \
                patch.dict(os.environ, {"CODEX_THREAD_ID": "fake-thread"}):
            stdin.isatty.return_value = stdout.isatty.return_value = True
            self.assertFalse(auth.interactive_terminal())

    def test_windows_noninteractive_setup_opens_a_real_console_without_pipe_handles(self):
        process = Mock()
        process.poll.return_value = 1
        with patch.object(auth, "interactive_terminal", return_value=False), \
                patch.object(auth, "os", SimpleNamespace(name="nt", environ=os.environ)), \
                patch.object(auth.subprocess, "CREATE_NEW_CONSOLE", 0x10, create=True), \
                patch.object(auth.subprocess, "Popen", return_value=process) as popen:
            attempt = auth.start_login(self.root, "codex", "codex.exe")
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x10)
        self.assertNotIn("stdin", popen.call_args.kwargs)
        self.assertNotIn("stdout", popen.call_args.kwargs)
        self.assertNotIn("stderr", popen.call_args.kwargs)
        attempt.close()

    def test_linux_terminal_receives_literal_arguments_and_waits(self):
        command = ["/python path/python", "/source $(do-not-run)/auth.py", "/tmp/control"]
        with patch.object(auth.sys, "platform", "linux"), \
                patch.object(auth.shutil, "which", side_effect=lambda name: "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None):
            result = auth.terminal_command(command, {"DISPLAY": ":0"})
        self.assertEqual(result, (["/usr/bin/gnome-terminal", "--wait", "--", *command], True))

    def test_macos_terminal_escapes_shell_and_applescript_separately(self):
        command = ["/path with spaces/python", '/path "quote"/`nope`/auth.py', "/tmp/été ' $test"]
        with patch.object(auth.sys, "platform", "darwin"):
            result, waits = auth.terminal_command(command, {})
        literal = result[-1].split("do script ", 1)[1].rsplit("\nend tell", 1)[0]
        self.assertEqual(shlex.split(json.loads(literal)), command)
        self.assertFalse(waits)

    def test_manual_powershell_command_escapes_single_quotes(self):
        with patch.object(auth, "os", SimpleNamespace(name="nt")):
            self.assertEqual(auth.manual_command("claude", "C:\\O'Brien\\claude.exe"),
                             "& 'C:\\O''Brien\\claude.exe' auth login")

    def test_launcher_failure_cleans_control_files(self):
        with patch.object(auth, "interactive_terminal", return_value=True), \
                patch.object(auth.subprocess, "Popen", side_effect=OSError("not available")):
            with self.assertRaises(OSError):
                auth.start_login(self.root, "codex", "test-cli")
        self.assertEqual(list((self.root / "data" / "auth").iterdir()), [])

    def test_gui_launcher_exit_does_not_end_a_still_open_terminal(self):
        directory = self.root / "control"
        directory.mkdir()
        process = Mock()
        process.poll.return_value = 0
        attempt = auth.LoginAttempt(directory, process, waits=False)
        self.assertIsNone(attempt.poll())
        write_json(directory / "result.json", {"exit_code": 0})
        self.assertEqual(attempt.poll(), 0)
        attempt.close()


@unittest.skipUnless(os.name == "nt", "Vérifie une vraie console Windows sans fournisseur.")
class WindowsConsoleTests(unittest.TestCase):
    def test_noninteractive_setup_gives_cli_a_console_and_can_cancel_input(self):
        with tempfile.TemporaryDirectory(prefix="vibe-auth-console-") as temporary:
            root = Path(temporary).resolve()
            # python.exe login joue le rôle du CLI natif sans utiliser de compte.
            atomic_write(root / "login", "import json, sys\n"
                         "from pathlib import Path\n"
                         "Path('terminal.json').write_text(json.dumps([sys.stdin.isatty(), sys.stdout.isatty()]))\n"
                         "input('SIMULATED_LOGIN: ')\n")
            with patch.object(auth, "interactive_terminal", return_value=False):
                attempt = auth.start_login(root, "codex", sys.executable)
            try:
                deadline = time.monotonic() + 10
                while not (root / "terminal.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(read_json(root / "terminal.json"), [True, True])
                attempt.cancel()
                deadline = time.monotonic() + 5
                while attempt.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(attempt.poll(), 130)
            finally:
                attempt.close()


@unittest.skipUnless(os.name == "posix", "Le test PTY réel est POSIX ; le lancement Windows est testé séparément.")
class RealTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-auth-pty-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.control = self.root / "control"
        self.control.mkdir()
        self.cli = self.root / "fake-cli"
        self.pid = self.fd = None
        self.terminal_tail = b""
        self.addCleanup(self.close_terminal)

    def close_terminal(self):
        # Fermer d'abord le maître vide le terminal et envoie le hangup à son
        # groupe. Sur BSD, un enfant sorti peut sinon rester en attente de drain.
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Un enfant déjà sorti peut être non signalable sur macOS.
                # Le waitpid borné ci-dessous vérifie tout de même sa fin.
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    pid, _ = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    pid = self.pid
                if pid:
                    self.pid = None
                    break
                time.sleep(0.02)
            self.assertIsNone(self.pid, "Le processus PTY de test n'a pas été nettoyé.")

    def start_terminal(self, provider="claude", timeout=10):
        import pty
        atomic_write(self.cli, f"#!{sys.executable}\n" +
                     "import os, sys\n"
                     "with open('/dev/tty') as tty:\n"
                     "    assert tty.isatty() and sys.stdin.isatty()\n"
                     "print('NATIVE_ARGS=' + ' '.join(sys.argv[1:]), flush=True)\n"
                     "print('INSTANCE=' + os.environ.get('VIBE_CLAW_ROOT', ''), flush=True)\n"
                     "code = input('RETURN_CODE: ')\n"
                     # Une sortie plus grande que le buffer PTY rend le besoin
                     # de drainage observable aussi sur Linux, pas seulement BSD.
                     "print('X' * 131072 + '\\nLOGIN_FINISHED', flush=True)\n"
                     "raise SystemExit(0 if code == 'simulated-code' else 3)\n")
        self.cli.chmod(0o700)
        write_json(self.control / "request.json", {
            "root": str(self.root), "provider": provider, "executable": str(self.cli),
            "expires_at": time.time() + timeout, "instance_root": "/calling-instance",
        })
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execv(sys.executable, [sys.executable, str(Path(auth.__file__).resolve()), str(self.control)])
        return self.read_until(b"RETURN_CODE: ")

    def read_until(self, marker):
        output = b""
        deadline = time.monotonic() + 5
        while marker not in output and time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], 0.1)
            if ready:
                try:
                    block = os.read(self.fd, 4096)
                except OSError:
                    break
                if not block:
                    break
                output += block
        self.assertIn(marker, output, output)
        return output

    def wait_result(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            # Un terminal réel lit continuellement la sortie. Le test doit
            # aussi vider l'écho du code et les derniers messages : attendre
            # seulement waitpid peut bloquer la fermeture du PTY sous macOS.
            ready, _, _ = select.select([self.fd], [], [], 0.02)
            if ready:
                try:
                    block = os.read(self.fd, 16384)
                except OSError:
                    block = b""
                self.terminal_tail = (self.terminal_tail + block)[-4096:]
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.pid = None
                return os.waitstatus_to_exitcode(status)
        self.fail(f"Le relais n'a pas quitté son terminal. Dernière sortie : {self.terminal_tail!r}")

    def test_native_cli_receives_a_pasted_code_in_a_real_controlling_terminal(self):
        output = self.start_terminal()
        self.assertIn(b"NATIVE_ARGS=auth login", output)
        self.assertIn(b"INSTANCE=/calling-instance", output)
        os.write(self.fd, b"simulated-code\n")
        self.assertEqual(self.wait_result(), 0)
        self.assertEqual(read_json(self.control / "result.json"), {"exit_code": 0})
        self.assertNotIn("simulated-code", "".join(p.read_text() for p in self.control.iterdir()))

    def test_cancellation_stops_a_cli_waiting_for_input(self):
        self.start_terminal(provider="codex")
        atomic_write(self.control / "cancel", "cancel\n")
        self.assertEqual(self.wait_result(), 130)
        self.assertEqual(read_json(self.control / "result.json"), {"exit_code": 130})

    def test_timeout_stops_a_cli_waiting_for_input(self):
        self.start_terminal(timeout=0.5)
        self.assertEqual(self.wait_result(), 130)


if __name__ == "__main__":
    unittest.main()
