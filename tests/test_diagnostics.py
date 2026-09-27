from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from vibe_claw_light.cli import doctor
from vibe_claw_light.config import save_config
from vibe_claw_light.diagnostics import MODEL_CACHE_SECONDS, run_diagnostics
from vibe_claw_light.providers import Result
from vibe_claw_light.storage import FileLock
from vibe_claw_light.telegram import TelegramError


TOKEN = "111111111:" + "x" * 35


class FastEvent(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.executable = self.root / "fake-cli"
        self.executable.write_text("test binary placeholder", encoding="utf-8")
        save_config(self.root, {
            "PROVIDER": "claude", "TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42",
            "TELEGRAM_CHAT_ID": "42", "WORKSPACE": str(self.root / "documents"),
            "ACCESS_MODE": "workspace", "ALLOW_SHELL": "0",
        })
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "auth")}))
        self.stack.enter_context(patch("vibe_claw_light.diagnostics.find_cli", return_value=str(self.executable)))
        self.version = self.stack.enter_context(patch("vibe_claw_light.diagnostics.subprocess.run", return_value=
            subprocess.CompletedProcess([], 0, "claude 2.1.283", "")))
        self.auth = self.stack.enter_context(patch("vibe_claw_light.diagnostics.auth_status", return_value=(True, "connected")))
        self.telegram = Mock()
        self.telegram.request.side_effect = self.telegram_response
        self.stack.enter_context(patch("vibe_claw_light.diagnostics.Telegram", return_value=self.telegram))
        self.runner = Mock()
        self.runner.run.side_effect = self.model_success
        self.runner_factory = self.stack.enter_context(patch("vibe_claw_light.diagnostics.ProviderRunner", return_value=self.runner))

    def telegram_response(self, method, **kwargs):
        if method == "getMe":
            return {"id": 17, "is_bot": True, "username": "example_test_bot"}
        if method == "getWebhookInfo":
            return {"url": ""}
        raise AssertionError("unexpected Telegram mutation")

    def model_success(self, prompt, **kwargs):
        match = re.search(r'fichier ("(?:\\.|[^"\\])*?")', prompt)
        self.assertIsNotNone(match)
        Path(json.loads(match.group(1))).write_text("VIBE_LIGHT_OK", encoding="utf-8")
        return Result("VIBE_LIGHT_OK")

    def run_checks(self, **kwargs):
        return run_diagnostics(self.root, cancel=kwargs.pop("cancel", FastEvent()), **kwargs)

    def check(self, result, identifier):
        return next(check for check in result.checks if check.id == identifier)

    def test_live_success_reports_distinct_steps_and_removes_temporary_probe(self):
        reports = []
        result = self.run_checks(report=reports.append)
        self.assertTrue(result.ok)
        self.assertEqual(self.check(result, "pairing").status, "ok")
        self.assertEqual(self.check(result, "telegram").status, "ok")
        self.assertEqual(self.check(result, "model").code, "model.ok")
        self.assertEqual([check.status for check in reports if check.id == "model"], ["running", "ok"])
        self.assertEqual(list((self.root / "data" / "diagnostics").iterdir()), [])
        self.assertFalse((self.root / "documents" / "bienvenue.txt").exists())
        self.assertNotIn(TOKEN, repr(result))
        self.assertEqual(self.runner.run.call_count, 1)

    def test_cached_success_does_not_repeat_quota_but_rechecks_auth_and_telegram(self):
        self.assertTrue(self.run_checks().ok)
        second = self.run_checks()
        self.assertTrue(second.ok)
        self.assertTrue(self.check(second, "model").cached)
        self.assertEqual(self.runner.run.call_count, 1)
        self.assertEqual(self.auth.call_count, 2)
        self.assertEqual(self.telegram.request.call_count, 4)
        raw = (self.root / "data" / "diagnostic-success.json").read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, raw)
        self.assertNotIn(str(self.root), raw)

    def test_network_failure_blocks_model_then_recovery_reuses_previous_success(self):
        self.assertTrue(self.run_checks().ok)
        self.telegram.request.side_effect = TelegramError(0, category="timeout")
        failed = self.run_checks()
        self.assertFalse(failed.ok)
        self.assertEqual(self.check(failed, "telegram").code, "telegram.timeout")
        self.assertEqual(self.check(failed, "telegram").attempt, 3)
        self.assertEqual(self.check(failed, "model").code, "model.blocked")
        self.assertEqual(self.runner.run.call_count, 1)
        self.telegram.request.side_effect = self.telegram_response
        self.assertTrue(self.check(self.run_checks(), "model").cached)
        self.assertEqual(self.runner.run.call_count, 1)

    def test_transient_network_error_recovers_before_first_model_call(self):
        replies = [TelegramError(0, category="dns"), {"id": 17, "is_bot": True}, {"url": ""}]
        self.telegram.request.side_effect = replies
        result = self.run_checks()
        self.assertTrue(result.ok)
        self.assertEqual(self.check(result, "telegram").attempt, 2)
        self.assertEqual(self.runner.run.call_count, 1)

    def test_invalid_telegram_token_is_not_retried_and_never_calls_model(self):
        self.telegram.request.side_effect = TelegramError(401, "https://api.telegram.org/bot" + TOKEN)
        result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "telegram").code, "telegram.unauthorized")
        self.assertEqual(self.telegram.request.call_count, 1)
        self.runner.run.assert_not_called()
        self.assertNotIn(TOKEN, repr(result))

    def test_webhook_blocks_model_and_does_not_mutate_telegram(self):
        self.telegram.request.side_effect = [{"id": 17, "is_bot": True}, {"url": "https://secret.invalid/" + TOKEN}]
        result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "telegram").code, "telegram.webhook")
        self.assertNotIn("secret.invalid", repr(result))
        self.runner.run.assert_not_called()

    def test_auth_failure_invalidates_cache_and_prevents_model_call(self):
        self.assertTrue(self.run_checks().ok)
        self.auth.return_value = False, "https://private.invalid/" + TOKEN
        failed = self.run_checks()
        self.assertFalse(failed.ok)
        self.assertEqual(self.check(failed, "auth").code, "auth.required")
        self.assertEqual(self.runner.run.call_count, 1)
        self.assertNotIn(TOKEN, repr(failed))
        self.auth.return_value = True, "connected"
        self.assertTrue(self.run_checks().ok)
        self.assertEqual(self.runner.run.call_count, 2)

    def test_relevant_config_change_invalidates_success(self):
        self.assertTrue(self.run_checks().ok)
        for change in ({"CLAUDE_MODEL": "different-model"}, {"ACCESS_MODE": "personal"},
                       {"WORKSPACE": str(self.root / "other-workspace")}):
            save_config(self.root, change)
            result = self.run_checks()
            self.assertTrue(result.ok)
            self.assertFalse(self.check(result, "model").cached)
        self.assertEqual(self.runner.run.call_count, 4)

    def test_agent_name_and_telegram_token_do_not_invalidate_model_test(self):
        self.assertTrue(self.run_checks().ok)
        save_config(self.root, {"AGENT_NAME": "Autre nom", "TELEGRAM_TOKEN": "222222222:" + "y" * 35})
        result = self.run_checks()
        self.assertTrue(result.ok)
        self.assertTrue(self.check(result, "model").cached)
        self.assertEqual(self.runner.run.call_count, 1)

    def test_provider_successes_are_independent_and_can_be_reused_after_switch(self):
        self.assertTrue(self.run_checks().ok)
        save_config(self.root, {"PROVIDER": "codex"})
        self.assertTrue(self.run_checks().ok)
        save_config(self.root, {"PROVIDER": "claude"})
        self.assertTrue(self.check(self.run_checks(), "model").cached)
        self.assertEqual(self.runner.run.call_count, 2)

    def test_cache_expires_and_binary_version_change_invalidates_it(self):
        self.assertTrue(self.run_checks().ok)
        with patch("vibe_claw_light.diagnostics.time.time", return_value=time.time() + MODEL_CACHE_SECONDS + 1):
            self.assertFalse(self.check(self.run_checks(), "model").cached)
        self.version.return_value.stdout = "claude 2.1.284"
        self.assertFalse(self.check(self.run_checks(), "model").cached)
        self.assertEqual(self.runner.run.call_count, 3)

    def test_auth_file_metadata_change_invalidates_cache_without_reading_secret(self):
        directory = self.root / "auth"
        directory.mkdir()
        credential = directory / ".credentials.json"
        credential.write_text("private fixture content", encoding="utf-8")
        self.assertTrue(self.run_checks().ok)
        credential.write_text("replacement private fixture content", encoding="utf-8")
        self.assertFalse(self.check(self.run_checks(), "model").cached)
        self.assertEqual(self.runner.run.call_count, 2)
        self.assertNotIn("private fixture", (self.root / "data" / "diagnostic-success.json").read_text(encoding="utf-8"))

    def test_auth_refresh_during_success_uses_the_new_metadata_for_cache(self):
        directory = self.root / "auth"
        directory.mkdir()
        credential = directory / ".credentials.json"
        credential.write_text("initial fixture", encoding="utf-8")
        def refresh(prompt, **kwargs):
            credential.write_text("refreshed private fixture", encoding="utf-8")
            return self.model_success(prompt, **kwargs)
        self.runner.run.side_effect = refresh
        self.assertTrue(self.run_checks().ok)
        self.assertTrue(self.check(self.run_checks(), "model").cached)
        self.assertEqual(self.runner.run.call_count, 1)

    def test_busy_model_lock_prevents_duplicate_calls(self):
        with FileLock(self.root / "data" / "diagnostic-model.lock"):
            result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "model").code, "model.busy")
        self.runner.run.assert_not_called()

    def test_corrupt_cache_is_replaced_only_after_a_successful_test(self):
        self.assertTrue(self.run_checks().ok)
        path = self.root / "data" / "diagnostic-success.json"
        path.write_text("{broken", encoding="utf-8")
        self.assertTrue(self.run_checks().ok)
        self.assertEqual(self.runner.run.call_count, 2)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)

    def test_auth_and_memory_internal_errors_cannot_consume_model_quota(self):
        self.auth.side_effect = RuntimeError(TOKEN)
        result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "auth").code, "auth.internal")
        self.auth.side_effect = None
        with patch("vibe_claw_light.diagnostics.MemoryStore.health", side_effect=OSError(TOKEN)):
            result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "memory").code, "memory.invalid")
        self.runner.run.assert_not_called()

    def test_live_false_never_calls_model(self):
        result = self.run_checks(live=False)
        self.assertTrue(result.ok)
        self.assertEqual(self.check(result, "model").code, "model.not_requested")
        self.runner.run.assert_not_called()

    def test_cancellation_before_and_during_model_never_caches_success(self):
        event = FastEvent()
        event.set()
        result = self.run_checks(cancel=event)
        self.assertFalse(result.ok)
        self.assertTrue(result.cancelled)
        self.runner.run.assert_not_called()
        event.clear()
        self.runner.run.side_effect = lambda *args, **kwargs: Result("", cancelled=True)
        result = self.run_checks(cancel=event)
        self.assertFalse(result.ok)
        self.assertTrue(result.cancelled)
        self.assertFalse((self.root / "data" / "diagnostic-success.json").exists())

    def test_provider_error_is_classified_and_never_echoes_raw_output(self):
        self.runner.run.side_effect = None
        self.runner.run.return_value = Result("", error="429 quota exceeded https://private.invalid/" + TOKEN)
        result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "model").code, "model.quota")
        self.assertFalse(self.check(result, "model").retryable)
        self.assertNotIn(TOKEN, repr(result))
        self.assertNotIn("private.invalid", repr(result))

    def test_internal_telegram_exception_and_corrupt_memory_block_quota(self):
        self.telegram.request.side_effect = RuntimeError(TOKEN)
        result = self.run_checks()
        self.assertEqual(self.check(result, "telegram").code, "telegram.internal")
        self.assertNotIn(TOKEN, repr(result))
        self.telegram.request.side_effect = self.telegram_response
        memory = self.root / "memory"
        memory.mkdir()
        (memory / "memory.json").write_text("{broken", encoding="utf-8")
        result = self.run_checks()
        self.assertFalse(result.ok)
        self.assertEqual(self.check(result, "memory").code, "memory.invalid")
        self.runner.run.assert_not_called()

    def test_doctor_wrapper_keeps_exit_codes_and_uses_same_reporter(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor(self.root, live=False), 0)
        self.assertIn("démarrage du service est une étape distincte", output.getvalue())
        self.telegram.request.side_effect = TelegramError(401)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor(self.root, live=True), 1)
        self.assertIn("401", output.getvalue())
        self.assertNotIn(TOKEN, output.getvalue())
        self.runner.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
