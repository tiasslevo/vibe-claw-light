"""Both CLI protocols are simulated; no provider process or account is used."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from vibe_claw_light.config import Config
from vibe_claw_light.providers import ProviderRunner, auth_status, build_command, find_cli, safe_error


class CaptureInput(io.StringIO):
    def __init__(self):
        super().__init__()
        self.sent = ""
        self.complete = threading.Event()

    def close(self):
        if not self.closed:
            self.sent = self.getvalue()
        super().close()
        self.complete.set()


class ResponseAfterInput(io.StringIO):
    def __init__(self, text, ready):
        super().__init__(text)
        self.ready = ready

    def __iter__(self):
        self.ready.wait(2)
        return super().__iter__()


class FakeProcess:
    def __init__(self, events, stderr="", code=0):
        self.stdin = CaptureInput()
        self.stdout = ResponseAfterInput("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", self.stdin.complete)
        self.stderr = io.StringIO(stderr)
        self.returncode = code
        self.pid = 2147483000

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.config = Config(self.root, "codex", "Démo", "dummy-known-token", 123, 123, self.root / "workspace")

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "nt", "Résolution PATH native Windows")
    def test_native_executable_is_found_after_an_earlier_npm_shim(self):
        npm, native = self.root / "npm", self.root / "native"
        npm.mkdir()
        native.mkdir()
        (npm / "codex.cmd").write_text("@echo fixture", encoding="utf-8")
        exe = native / "codex.exe"
        exe.write_text("fixture, never executed", encoding="utf-8")
        with patch.dict(os.environ, {"PATH": str(npm) + os.pathsep + str(native)}):
            self.assertEqual(find_cli("codex"), str(exe))

    def run_fake(self, events, *, provider="codex", stderr="", code=0, prompt="Lis le résumé de Zoé 📚", cancel=None):
        proc = FakeProcess(events, stderr, code)
        seen = []
        runner = ProviderRunner(replace(self.config, provider=provider))
        with patch("vibe_claw_light.providers.build_command", return_value=["fake-provider"]), \
             patch("vibe_claw_light.providers.subprocess.Popen", return_value=proc) as popen, \
             patch("vibe_claw_light.providers.stop_tree") as stop, \
             patch("vibe_claw_light.providers.WindowsJob"):
            result = runner.run(prompt, cancel=cancel, on_session=seen.append)
        self.assertIsNone(runner.process)
        return result, proc, popen, stop, seen

    def test_codex_fresh_and_resume_keep_stdin_and_explicit_permissions(self):
        executable = str(self.root / "Program Files" / "codex.exe")
        config = replace(self.config, codex_model="model-test")
        for sid in (None, "session_123456"):
            command = build_command(config, sid, executable)
            self.assertEqual(command[0], executable)
            self.assertEqual(command[-1], "-")
            self.assertIn('sandbox_mode="workspace-write"', command)
            self.assertIn("sandbox_workspace_write.network_access=false", command)
            self.assertEqual(command[command.index("-a") + 1], "never")
            self.assertIn("model-test", command)
            if sid:
                self.assertEqual(command[command.index("resume") + 1], sid)
            else:
                self.assertEqual(command[command.index("-C") + 1], str(self.root))

    def test_claude_resume_is_explicit_and_shell_tools_require_opt_in(self):
        config = replace(self.config, provider="claude", workspace=self.root.parent / "external")
        command = build_command(config, "session_123456", "claude-native")
        self.assertEqual(command[command.index("--resume") + 1], "session_123456")
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(command[command.index("--add-dir") + 1], str(config.workspace))
        self.assertNotIn("Bash", command[command.index("--allowedTools") + 1])
        allowed = build_command(replace(config, allow_shell=True), executable="claude-native")
        self.assertIn("Bash", allowed[allowed.index("--allowedTools") + 1])

    def test_codex_json_stream_ignores_tool_output_and_saves_session_early(self):
        events = [
            {"type": "thread.started", "thread_id": "session_123456"},
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "SECRET_TOOL_OUTPUT"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Résumé prêt 📚"}},
            {"type": "turn.completed"},
        ]
        result, proc, popen, stop, sessions = self.run_fake(events)
        self.assertEqual(result.text, "Résumé prêt 📚")
        self.assertEqual(sessions, ["session_123456"])
        self.assertIsNone(result.error)
        self.assertEqual(proc.stdin.sent, "Lis le résumé de Zoé 📚")
        self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
        self.assertFalse(popen.call_args.kwargs.get("shell", False))
        self.assertEqual(popen.call_args.args[0], ["fake-provider"])

    def test_prompt_metacharacters_stay_on_stdin(self):
        prompt = "$(touch file); `echo danger` & | > < Résumé"
        result, proc, popen, _, _ = self.run_fake([
            {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
        ], prompt=prompt)
        self.assertEqual(proc.stdin.sent, prompt)
        self.assertNotIn(prompt, popen.call_args.args[0])
        self.assertFalse(popen.call_args.kwargs.get("shell", False))

    def test_claude_stream_extracts_final_result_without_tool_data(self):
        events = [
            {"type": "system", "session_id": "session_claude"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {"token": "SECRET_TOOL_INPUT"}}, {"type": "text", "text": "Intermédiaire"}]}},
            {"type": "result", "result": "Terminé, Zoé.", "is_error": False},
        ]
        result, _, _, _, sessions = self.run_fake(events, provider="claude")
        self.assertEqual(result.text, "Terminé, Zoé.")
        self.assertEqual(sessions, ["session_claude"])
        self.assertIsNone(result.error)

    def test_stderr_and_protocol_errors_mask_credentials(self):
        secret = "sk-proj-" + "a" * 30
        message = f"Error {self.config.telegram_token} {secret} https://api.example.com/private"
        for events, code in (([{"type": "turn.failed", "error": {"message": message}}], 0), ([], 1)):
            result, *_ = self.run_fake(events, stderr=message, code=code)
            self.assertTrue(result.error)
            self.assertNotIn(self.config.telegram_token, result.error)
            self.assertNotIn(secret, result.error)
            self.assertNotIn("https://", result.error)
        self.assertLessEqual(len(safe_error("x" * 3000, self.config)), 1200)

    def test_cancellation_does_not_return_partial_answer(self):
        cancel = threading.Event()
        cancel.set()
        result, _, _, stop, _ = self.run_fake([], cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.text, "")
        self.assertTrue(stop.called)

    def test_auth_probe_never_echoes_stdout_credentials(self):
        result = type("Completed", (), {"stdout": '{"loggedIn":false,"token":"private"}', "returncode": 0})()
        with patch("vibe_claw_light.providers.subprocess.run", return_value=result):
            ok, message = auth_status("claude", "fake-cli")
        self.assertFalse(ok)
        self.assertNotIn("private", message)


if __name__ == "__main__":
    unittest.main()
