"""HTTP local et Telegram simulé : aucun bot réel, aucun compte fournisseur."""
from __future__ import annotations

from contextlib import redirect_stdout
import http.client
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from itertools import count
from urllib.parse import urlencode

from vibe_claw_light.config import load_config, read_values, save_config
from vibe_claw_light.onboarding import Wizard, WizardServer, paired_owner, setup
from vibe_claw_light.storage import FileLock, atomic_write, read_json, write_json
from vibe_claw_light.telegram import TelegramError


# Faux tokens de forme valide, sans valeur réelle.
TOKEN = "123456:" + "a" * 32
OTHER_TOKEN = "654321:" + "b" * 32


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def message(code, owner=42, **extra):
    return {"text": "/start " + code, "chat": {"id": owner, "type": "private"},
            "from": {"id": owner, "is_bot": False}, **extra}


class FakeTelegram:
    def __init__(self):
        self.inbox = queue.Queue()
        self.webhook = ""
        self.update_calls = 0
        self.methods = []
        self.failure = None

    def get_me(self):
        if self.failure:
            raise self.failure
        return {"id": 123456, "is_bot": True, "username": "TestAssistantBot"}

    def request(self, method, **kwargs):
        self.methods.append(method)
        if method != "getWebhookInfo":
            raise AssertionError("Requête Telegram inattendue")
        return {"url": self.webhook}

    def updates(self, offset=None, timeout=5):
        self.update_calls += 1
        try:
            batch = self.inbox.get(timeout=0.03)
        except queue.Empty:
            return []
        if isinstance(batch, Exception):
            raise batch
        return batch

    def push(self, msg, update_id=1):
        self.inbox.put([{"update_id": update_id, "message": msg}])


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-onboarding-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fake = FakeTelegram()
        self.wizards = []
        self.addCleanup(self.close_wizards)

    def close_wizards(self):
        for wizard in self.wizards:
            wizard.close()

    def wizard(self, provider="codex", authenticated=True):
        wizard = Wizard(self.root, provider, "test-cli", authenticated,
                        telegram_factory=lambda token: self.fake,
                        diagnostic_runner=lambda *a, **kw: SimpleNamespace(ok=True, checks=()),
                        service_start=lambda root, **kw: 0,
                        service_status=lambda root: {"running": True, "ready": True})
        self.wizards.append(wizard)
        return wizard

    def configure(self, wizard, **fields):
        wizard.configure({"name": "Léa", "workspace": "mes projets", "token": TOKEN, **fields})

    def test_private_owner_requires_exact_nonce_and_identity(self):
        self.assertEqual(paired_owner(message("secret"), "secret"), 42)
        invalid = [
            message("wrong"), message("secret", text="/start"),
            message("secret", chat={"id": 42, "type": "group"}),
            message("secret", chat={"id": 99, "type": "private"}),
            message("secret", **{"from": {"id": 42, "is_bot": True}}),
            message("secret", **{"from": {"id": "42", "is_bot": False}}),
            message("secret", **{"from": {"id": 42}}),
            message("secret", owner=True), {}, None,
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                self.assertIsNone(paired_owner(candidate, "secret"))

    def test_only_matching_private_start_persists_configuration(self):
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        self.assertFalse((self.root / "config.env").exists())
        self.fake.push(message("unrelated"))
        self.fake.push(message(wizard.pair_code, chat={"id": 42, "type": "group"}), 2)
        self.assertFalse(wizard.done.wait(0.15))
        self.fake.push(message(wizard.pair_code), 3)
        self.assertTrue(wizard.done.wait(3))
        config = load_config(self.root)
        self.assertEqual((config.owner_id, config.chat_id), (42, 42))
        self.assertEqual(config.name, "Léa")
        self.assertEqual(config.codex_bin, "test-cli")
        self.assertEqual(config.workspace, self.root / "mes projets")
        self.assertTrue(config.workspace.is_dir())
        self.assertTrue((self.root / "data" / "files").is_dir())
        self.assertTrue((self.root / "identity" / "SOUL.md").exists())
        self.assertEqual(read_json(self.root / "data" / "state.json")["offset"], 4)

    def test_existing_same_bot_owner_keeps_identity_memory_without_polling(self):
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42", "TELEGRAM_CHAT_ID": "42"})
        soul = self.root / "identity" / "SOUL.md"
        memory = self.root / "memory" / "profile.json"
        atomic_write(soul, "Ma voix personnelle")
        atomic_write(memory, "Mémoire privée à garder")
        write_json(self.root / "data" / "state.json", {"offset": 200, "queue": [], "sessions": {"codex": "old"}})
        wizard = self.wizard()
        self.configure(wizard, token="", keep_owner="1")
        self.assertTrue(wizard.done.wait(3))
        self.assertEqual(self.fake.update_calls, 0)
        self.assertEqual(soul.read_text(encoding="utf-8"), "Ma voix personnelle")
        self.assertEqual(memory.read_text(encoding="utf-8"), "Mémoire privée à garder")
        self.assertEqual(read_json(self.root / "data" / "state.json")["offset"], 200)

    def test_changed_token_requires_pairing_and_clears_old_offsets_for_same_owner(self):
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42", "TELEGRAM_CHAT_ID": "42"})
        write_json(self.root / "data" / "state.json", {"offset": 99999999, "queue": [{"text": "old"}], "active": {}, "paused": True, "sessions": {"codex": "old"}})
        wizard = self.wizard()
        self.configure(wizard, token=OTHER_TOKEN, keep_owner="1")
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        self.fake.push(message(wizard.pair_code))
        self.assertTrue(wizard.done.wait(3))
        self.assertEqual(read_values(self.root)["TELEGRAM_TOKEN"], OTHER_TOKEN)
        self.assertEqual(read_json(self.root / "data" / "state.json"), {
            "offset": 2, "sessions": {}, "queue": [], "active": None, "paused": False,
        })

    def test_fresh_pairing_keeps_only_updates_after_the_private_start(self):
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42", "TELEGRAM_CHAT_ID": "42"})
        write_json(self.root / "data" / "state.json", {"offset": 3, "queue": [{"text": "old"}], "sessions": {"codex": "old"}})
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        self.fake.inbox.put([
            {"update_id": 90, "message": message("obsolete")},
            {"update_id": 91, "message": message(wizard.pair_code)},
            {"update_id": 92, "message": message("new-task")},
        ])
        self.assertTrue(wizard.done.wait(3))
        state = read_json(self.root / "data" / "state.json")
        self.assertEqual(state["offset"], 92)
        self.assertEqual(state["queue"], [])
        self.assertEqual(state["sessions"], {})

    def test_cannot_reassign_existing_private_memory_to_another_owner(self):
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42", "TELEGRAM_CHAT_ID": "42"})
        original = (self.root / "config.env").read_bytes()
        wizard = self.wizard()
        self.configure(wizard, token=OTHER_TOKEN)
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        self.fake.push(message(wizard.pair_code, owner=99))
        self.assertTrue(wait_until(lambda: wizard.phase == "configure"))
        self.assertIn("autre compte", wizard.error)
        self.assertEqual((self.root / "config.env").read_bytes(), original)
        self.assertFalse(wizard.done.is_set())

    def test_webhook_is_refused_without_modifying_it(self):
        self.fake.webhook = "https://example.invalid/hook"
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertIn("webhook", wizard.error)
        self.assertEqual(self.fake.methods, ["getWebhookInfo"])
        self.assertEqual(self.fake.update_calls, 0)
        self.assertFalse((self.root / "config.env").exists())

    def test_token_in_exception_is_never_echoed(self):
        self.fake.failure = TelegramError(401, "https://api.telegram.org/bot" + TOKEN)
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertNotIn(TOKEN, wizard.render().decode())
        self.assertNotIn("api.telegram", wizard.error)

    def test_poll_conflict_returns_to_form(self):
        self.fake.inbox.put(TelegramError(409, "conflict"))
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertIn("autre programme", wizard.error)
        self.assertFalse(wizard.done.is_set())

    def test_expired_nonce_does_not_write_configuration(self):
        wizard = self.wizard()
        with patch("vibe_claw_light.onboarding.PAIR_TIMEOUT", 0.01):
            self.configure(wizard)
            self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertIn("expiré", wizard.error)
        self.assertFalse((self.root / "config.env").exists())

    def test_cancelled_pairing_cannot_save_late_result(self):
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        code = wizard.pair_code
        wizard.cancel_pairing()
        self.fake.push(message(code))
        self.assertFalse(wizard.done.wait(0.15))
        self.assertFalse((self.root / "config.env").exists())

    def test_claude_shell_requires_checkbox(self):
        for allow in ("0", "1"):
            with self.subTest(allow=allow):
                wizard = self.wizard(provider="claude")
                self.configure(wizard, allow_shell=allow, access_mode="workspace")
                self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
                self.fake.push(message(wizard.pair_code))
                self.assertTrue(wizard.done.wait(3))
                self.assertEqual(load_config(self.root).allow_shell, allow == "1")

    def test_service_started_during_pairing_prevents_save(self):
        wizard = self.wizard()
        self.configure(wizard)
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        with FileLock(self.root / "data" / "service.lock"):
            self.fake.push(message(wizard.pair_code))
            self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertIn("python run.py stop", wizard.error)
        self.assertFalse((self.root / "config.env").exists())

    def test_login_launches_only_selected_cli(self):
        wizard = self.wizard(provider="claude", authenticated=False)
        attempt = Mock()
        attempt.poll.return_value = 0
        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt) as start, \
                patch("vibe_claw_light.onboarding.auth_status", return_value=(True, "connected")), \
                redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: wizard.phase == "configure"))
        self.assertEqual(start.call_args.args[:3], (self.root, "claude", "test-cli"))
        attempt.close.assert_called_once()

    def test_auth_failure_allows_retry(self):
        wizard = self.wizard(authenticated=False)
        attempt = Mock()
        attempt.poll.return_value = 1
        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt), \
                patch("vibe_claw_light.onboarding.auth_status", return_value=(False, "no")), \
                redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: bool(wizard.error)))
        self.assertEqual(wizard.phase, "auth")
        self.assertIn("réessayer", wizard.error)

    def test_headless_login_shows_manual_command_and_can_be_rechecked(self):
        wizard = self.wizard(provider="claude", authenticated=False)
        with patch("vibe_claw_light.onboarding.start_login", return_value=None), \
                patch("vibe_claw_light.onboarding.auth_status", return_value=(True, "connected")), \
                redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: bool(wizard.error)))
            self.assertEqual(wizard.phase, "auth")
            self.assertIn("terminal", wizard.error)
            self.assertIn("test-cli", wizard.render().decode())
            self.assertIn("auth login", wizard.render().decode())
            wizard.check_login()
            self.assertTrue(wait_until(lambda: wizard.phase == "configure"))

    def test_cancel_login_closes_attempt_without_starting_configuration(self):
        wizard = self.wizard(authenticated=False)
        attempt = Mock()
        attempt.poll.return_value = None
        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt), \
                patch("vibe_claw_light.onboarding.auth_status") as status, \
                redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: wizard.auth_attempt is attempt))
            wizard.cancel_login()
            self.assertTrue(wait_until(lambda: wizard.auth_attempt is None))
        self.assertEqual(wizard.phase, "auth")
        attempt.cancel.assert_called_once()
        attempt.close.assert_called_once()
        status.assert_not_called()

    def test_recheck_during_login_cannot_be_overwritten_by_late_failure(self):
        wizard = self.wizard(authenticated=False)
        attempt = Mock()
        attempt.poll.return_value = None
        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt), \
                patch("vibe_claw_light.onboarding.auth_status", return_value=(True, "connected")), \
                redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: wizard.auth_attempt is attempt))
            wizard.check_login()
            self.assertTrue(wait_until(lambda: wizard.phase == "configure"))
            self.assertTrue(wait_until(lambda: wizard.auth_attempt is None))
        self.assertEqual(wizard.phase, "configure")
        self.assertEqual(wizard.error, "")
        attempt.cancel.assert_called_once()

    def test_close_setup_cancels_an_interactive_login(self):
        wizard = self.wizard(authenticated=False)
        attempt = Mock()
        attempt.poll.return_value = None
        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt), redirect_stdout(io.StringIO()):
            wizard.login()
            self.assertTrue(wait_until(lambda: wizard.auth_attempt is attempt))
            wizard.close()
        self.assertTrue(wizard.stop.is_set())
        attempt.cancel.assert_called_once()
        attempt.close.assert_called_once()

    def test_late_negative_recheck_cannot_replace_a_successful_login(self):
        wizard = self.wizard(authenticated=False)
        attempt = Mock()
        finished = threading.Event()
        checking = threading.Event()
        release_check = threading.Event()
        attempt.poll.side_effect = lambda: 0 if finished.is_set() else None

        def check_status(*_):
            if not checking.is_set():
                checking.set()
                release_check.wait(3)
                return False, "previous status"
            return True, "connected"

        with patch("vibe_claw_light.onboarding.start_login", return_value=attempt), \
                patch("vibe_claw_light.onboarding.auth_status", side_effect=check_status), \
                redirect_stdout(io.StringIO()):
            try:
                wizard.login()
                self.assertTrue(wait_until(lambda: wizard.auth_attempt is attempt))
                wizard.check_login()
                self.assertTrue(checking.wait(1))
                finished.set()
                self.assertTrue(wait_until(lambda: wizard.phase == "configure"))
            finally:
                release_check.set()
            self.assertTrue(wait_until(lambda: not wizard.checking_login))
        self.assertEqual(wizard.phase, "configure")
        self.assertEqual(wizard.error, "")

    def test_existing_workspace_mode_and_extra_directories_are_not_silently_widened(self):
        extra = str(self.root / "archive")
        (self.root / "archive").mkdir()
        save_config(self.root, {"ACCESS_MODE": "workspace", "EXTRA_DIRS": json.dumps([extra]),
                               "TELEGRAM_TOKEN": TOKEN, "TELEGRAM_OWNER_ID": "42", "TELEGRAM_CHAT_ID": "42"})
        wizard = self.wizard()
        self.assertIn('value="workspace" selected', wizard.render().decode())
        self.configure(wizard, token="", keep_owner="1")
        self.assertTrue(wizard.done.wait(3))
        values = read_values(self.root)
        self.assertEqual(values["ACCESS_MODE"], "workspace")
        self.assertEqual(json.loads(values["EXTRA_DIRS"]), [extra])

    def test_first_install_can_choose_personal_or_workspace(self):
        wizard = self.wizard()
        self.assertEqual(wizard.access_mode, "personal")
        self.configure(wizard, access_mode="personal")
        self.assertTrue(wait_until(lambda: wizard.phase == "pairing"))
        self.fake.push(message(wizard.pair_code))
        self.assertTrue(wizard.done.wait(3))
        self.assertEqual(load_config(self.root).access_mode, "personal")

    def test_unknown_access_mode_does_not_start_pairing(self):
        wizard = self.wizard()
        self.configure(wizard, access_mode="administrator")
        self.assertEqual(wizard.phase, "configure")
        self.assertIn("mode d'accès", wizard.error)

    def test_setup_refuses_running_instance_before_auth(self):
        with FileLock(self.root / "data" / "service.lock"), \
                patch("vibe_claw_light.onboarding.auth_status") as auth, \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(setup(self.root, "codex"), 1)
        auth.assert_not_called()
        self.assertIn("python run.py stop", output.getvalue())

    def test_setup_missing_cli_fails_without_opening_browser(self):
        with patch("vibe_claw_light.onboarding.find_cli", return_value=None), \
                patch("vibe_claw_light.onboarding.webbrowser.open") as browser, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(setup(self.root, "claude"), 1)
        browser.assert_not_called()

    def test_manual_login_is_detected_by_bounded_background_checks(self):
        wizard = self.wizard(authenticated=False)
        with patch("vibe_claw_light.onboarding.auth_status", return_value=(False, "pending")) as auth:
            wizard.refresh_login()
            auth.assert_not_called()
            wizard.enable_login_watch()
            wizard.refresh_login()
            self.assertTrue(wait_until(lambda: not wizard.checking_login))
            self.assertEqual(auth.call_count, 1)
            wizard.refresh_login()
            self.assertEqual(auth.call_count, 1)
            self.assertEqual(wizard.phase, "auth")
            self.assertEqual(wizard.error, "")
            wizard.auth_watch_deadline = time.monotonic() - 1
            wizard.auth_next_check = 0
            wizard.refresh_login()
            self.assertEqual(auth.call_count, 1)
            wizard.enable_login_watch()
            auth.return_value = (True, "connected")
            wizard.refresh_login()
            self.assertTrue(wait_until(lambda: wizard.phase == "configure"))
            wizard.auth_next_check = 0
            wizard.refresh_login()
            self.assertEqual(auth.call_count, 2)

    def test_cancelled_login_disables_automatic_detection(self):
        wizard = self.wizard(authenticated=False)
        wizard.enable_login_watch()
        wizard.phase = "authenticating"
        wizard.cancel_login()
        with patch("vibe_claw_light.onboarding.auth_status") as auth:
            wizard.refresh_login()
        auth.assert_not_called()
        self.assertEqual(wizard.phase, "auth")

    def test_ready_setup_keeps_page_available_for_first_telegram_trial(self):
        wizard = self.wizard()
        wizard.done.set()
        wizard.result = 0
        server = Mock(url="http://127.0.0.1/private-test/")
        requests = []

        def handle_request():
            requests.append(True)
            if len(requests) == 3:
                wizard.stop.set()  # La personne clique enfin sur Terminer.

        server.handle_request.side_effect = handle_request
        ticks = count(step=15)
        with patch("vibe_claw_light.onboarding.Wizard", return_value=wizard), \
                patch("vibe_claw_light.onboarding.WizardServer", return_value=server), \
                patch("vibe_claw_light.onboarding.find_cli", return_value="test-cli"), \
                patch("vibe_claw_light.onboarding.executable_command", return_value=["test-cli"]), \
                patch("vibe_claw_light.onboarding.auth_status", return_value=(True, "connected")), \
                patch("vibe_claw_light.onboarding.webbrowser.open"), \
                patch("vibe_claw_light.onboarding.time.monotonic", side_effect=lambda: next(ticks)), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(setup(self.root, "codex"), 0)
        self.assertEqual(len(requests), 3)
        server.server_close.assert_called_once()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-onboarding-http-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN})
        self.wizard = Wizard(self.root, "codex", "test-cli", True)
        self.server = WizardServer(self.wizard)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.wizard.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def request(self, method="GET", path=None, fields=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {}
        data = raw
        if method == "POST":
            request_headers.update({"Origin": self.server.origin, "Content-Type": "application/x-www-form-urlencoded"})
            if data is None:
                data = urlencode({"csrf": self.wizard.csrf, **(fields or {})})
        request_headers.update(headers or {})
        connection.request(method, path or self.wizard.path, body=data, headers=request_headers)
        response = connection.getresponse()
        status, output, received = response.status, response.read().decode(), dict(response.getheaders())
        connection.close()
        return status, output, received

    def test_page_is_only_reachable_at_secret_path(self):
        self.assertEqual(self.request()[0], 200)
        self.assertEqual(self.request(path="/")[0], 404)
        self.assertEqual(self.request(path=self.wizard.path + "?ignored=true")[0], 404)
        self.assertEqual(self.request(path="/not-the-secret/")[0], 404)

    def test_host_and_origin_rebinding_are_blocked(self):
        self.assertEqual(self.request(headers={"Host": "evil.invalid"})[0], 403)
        self.assertEqual(self.request(headers={"Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_existing_token_is_blank_masked_and_never_in_html(self):
        status, html, headers = self.request()
        self.assertEqual(status, 200)
        self.assertIn('type="password" name="token"', html)
        self.assertNotIn(TOKEN, html)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_form_escapes_untrusted_display_values(self):
        self.wizard.name = '<script>alert("test")</script>'
        self.wizard.workspace = '"><img src=x onerror=alert(1)>'
        _, html, _ = self.request()
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_post_requires_origin_and_csrf(self):
        path = self.wizard.path + "configure"
        with patch.object(self.wizard, "configure") as configure:
            self.assertEqual(self.request("POST", path, fields={"csrf": "wrong"})[0], 403)
            self.assertEqual(self.request("POST", path, fields={"csrf": "é"})[0], 403)
            self.assertEqual(self.request("POST", path, raw="name=anything")[0], 403)
            self.assertEqual(self.request("POST", path, headers={"Origin": "null"})[0], 403)
            self.assertEqual(self.request("POST", path, headers={"Origin": ""})[0], 403)
            configure.assert_not_called()

    def test_valid_post_redirects_without_echoing_token(self):
        with patch.object(self.wizard, "configure") as configure:
            status, html, headers = self.request("POST", self.wizard.path + "configure", fields={"token": OTHER_TOKEN})
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], self.wizard.path)
        self.assertNotIn(OTHER_TOKEN, html)
        configure.assert_called_once_with({"token": OTHER_TOKEN})

    def test_rejected_post_consumes_delayed_body_before_closing_connection(self):
        # Un POST arrive souvent en deux paquets. Fermer après les seuls headers
        # provoquait un reset TCP intermittent sur Windows au lieu du 403/404.
        cases = [
            (self.wizard.path + "configure", "null", self.server.host, 403),
            (self.wizard.path + "configure", self.server.origin, "evil.invalid", 403),
            ("/unknown/configure", self.server.origin, self.server.host, 404),
        ]
        with patch.object(self.wizard, "configure") as configure:
            for path, origin, host, expected in cases:
                with self.subTest(path=path, origin=origin, host=host):
                    connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
                    try:
                        body = urlencode({"csrf": self.wizard.csrf, "token": OTHER_TOKEN}).encode()
                        connection.putrequest("POST", path, skip_host=True)
                        connection.putheader("Host", host)
                        connection.putheader("Origin", origin)
                        connection.putheader("Content-Type", "application/x-www-form-urlencoded")
                        connection.putheader("Content-Length", str(len(body)))
                        connection.endheaders()
                        time.sleep(0.02)
                        connection.send(body)
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected)
                        self.assertNotIn(OTHER_TOKEN, response.read().decode())
                    finally:
                        connection.close()
        configure.assert_not_called()

    def test_duplicate_fields_and_large_body_rejected(self):
        path = self.wizard.path + "configure"
        data = urlencode({"csrf": self.wizard.csrf}) + "&token=a&token=b"
        self.assertEqual(self.request("POST", path, raw=data)[0], 400)
        self.assertEqual(self.request("POST", path, raw="a=" + "a" * 9000)[0], 400)

    def test_get_cannot_trigger_setup_mutation(self):
        with patch.object(self.wizard, "configure") as configure:
            self.assertEqual(self.request(path=self.wizard.path + "configure")[0], 404)
        configure.assert_not_called()

    def test_http_does_not_log_secret_url_or_form_values(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.request()
            self.request("POST", self.wizard.path + "configure", fields={"csrf": "wrong", "token": OTHER_TOKEN})
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
