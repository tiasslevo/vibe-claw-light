"""Navigation Chromium réelle ; fournisseur et Telegram restent simulés.

Opt-in développement, sans dépendance du runtime :
  VCL_BROWSER_TESTS=1 PYTHONPATH=src uv run --no-project --with playwright \
      python -m unittest discover -s tests -p test_browser.py -v
Installer Chromium avec ``python -m playwright install chromium`` dans
l'environnement de test, ou définir VCL_BROWSER_EXECUTABLE. Sur Windows,
VCL_BROWSER_CHANNEL=msedge utilise Edge installé sur la machine.

VCL_BROWSER_PROVIDER=claude rejoue les mêmes parcours avec les formulaires
Claude Code ; la valeur par défaut est codex. Les CLI restent simulés.

Les formulaires sont soumis par de vrais clics. Aucun test n'ajoute ou ne
remplace un en-tête Origin : c'est précisément le comportement à vérifier.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from vibe_claw_light.config import save_config
from vibe_claw_light.diagnostics import DiagnosticCheck, DiagnosticResult
from vibe_claw_light.onboarding import Wizard, WizardHandler, WizardServer


# Uniquement un token fictif de forme valide. Aucun compte réel n'est utilisé.
TOKEN = "123456:" + "a" * 32
BROWSER_ENABLED = os.environ.get("VCL_BROWSER_TESTS") == "1"


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class FakeTelegram:
    def __init__(self):
        self.inbox = queue.Queue()

    def get_me(self):
        return {"id": 123456, "is_bot": True, "username": "BrowserTestBot"}

    def request(self, method, **kwargs):
        if method != "getWebhookInfo":
            raise AssertionError("Appel Telegram inattendu")
        return {"url": ""}

    def updates(self, offset=None, timeout=5):
        try:
            return self.inbox.get(timeout=0.03)
        except queue.Empty:
            return []

    def pair(self, code):
        self.inbox.put([{
            "update_id": 1,
            "message": {
                "text": "/start " + code,
                "from": {"id": 42, "is_bot": False},
                "chat": {"id": 42, "type": "private"},
            },
        }])


class FakeLogin:
    def __init__(self):
        self.cancelled = threading.Event()

    def poll(self):
        return 130 if self.cancelled.is_set() else None

    def cancel(self):
        self.cancelled.set()

    def close(self):
        self.cancel()


class RestartableWizardServer(WizardServer):
    """Même handler et même serveur, port réutilisable pour un vrai redémarrage."""

    allow_reuse_address = True

    def __init__(self, wizard, port=0):
        self.requested_port = port
        super().__init__(wizard)

    def server_bind(self):
        self.server_address = ("127.0.0.1", self.requested_port)
        super().server_bind()


@unittest.skipUnless(BROWSER_ENABLED, "VCL_BROWSER_TESTS=1 active les tests navigateur optionnels")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Si l'opt-in est explicite, une dépendance/navigateur absent est une
        # erreur de recette, pas un succès silencieusement ignoré.
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        options = {"headless": True}
        if os.environ.get("VCL_BROWSER_EXECUTABLE"):
            options["executable_path"] = os.environ["VCL_BROWSER_EXECUTABLE"]
        elif os.environ.get("VCL_BROWSER_CHANNEL"):
            options["channel"] = os.environ["VCL_BROWSER_CHANNEL"]
        cls.browser = cls.playwright.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)
        print(f"Navigateur réel : {cls.browser.version}", flush=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vcl-browser-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fake = FakeTelegram()
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.servers = []
        self.addCleanup(self.close_servers)
        self.auth = Mock(return_value=(False, "Connexion fictive absente"))
        patcher = patch("vibe_claw_light.onboarding.auth_status", self.auth)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.login = FakeLogin()
        patcher = patch("vibe_claw_light.onboarding.start_login", return_value=self.login)
        self.start_login = patcher.start()
        self.addCleanup(patcher.stop)
        self.diagnostics = Mock(side_effect=self.successful_diagnostics)
        self.service_start = Mock(return_value=0)
        self.service_status = Mock(return_value={"running": True, "ready": True})

    @staticmethod
    def diagnostic_result(report, *, ok=True, cached=False):
        checks = [DiagnosticCheck("telegram", "ok" if ok else "error",
                                  "Telegram fictif joignable." if ok else "Réseau temporairement indisponible.",
                                  "telegram.ok" if ok else "telegram.network", retryable=not ok)]
        if ok:
            checks.append(DiagnosticCheck("model", "ok", "Modèle fictif vérifié.", cached=cached))
        for check in checks:
            report(check)
        return DiagnosticResult(ok, tuple(checks))

    def successful_diagnostics(self, root, *, live, report, cancel):
        self.assertEqual(root, self.root)
        self.assertTrue(live)
        return self.diagnostic_result(report)

    def start_server(self, authenticated=True, *, port=0, **kwargs):
        options = {"diagnostic_runner": self.diagnostics, "service_start": self.service_start,
                   "service_status": self.service_status, **kwargs}
        wizard = Wizard(self.root, os.environ.get("VCL_BROWSER_PROVIDER", "codex"), "test-cli", authenticated,
                        telegram_factory=lambda token: self.fake, **options)
        # Le formulaire reste réaliste, avec un chemin publiable dans les
        # captures. Les écritures du test utiliseront ensuite son dossier temp.
        wizard.workspace = "~/Documents/MonAssistant"
        server = RestartableWizardServer(wizard, port=port)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.servers.append((wizard, server, thread))
        self.wizard, self.server = wizard, server
        return wizard, server

    def close_server(self, wizard, server, thread):
        wizard.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    def close_servers(self):
        for entry in reversed(self.servers):
            self.close_server(*entry)
        self.servers.clear()

    def visit(self):
        response = self.page.goto(self.server.url)
        self.assertEqual(response.status, 200)
        return response

    def form(self, action):
        return self.page.locator(f'form[action="{self.wizard.path}{action}"]')

    def submit(self, action, status=303):
        target = self.server.origin + self.wizard.path + action
        with self.page.expect_response(
                lambda response: response.url == target and response.request.method == "POST") as received:
            self.form(action).locator('button[type="submit"], button:not([type])').first.click()
        response = received.value
        self.assertEqual(response.status, status)
        return response

    def fill_configuration(self):
        self.form("configure").locator('[name="name"]').fill("Assistant de test")
        self.form("configure").locator('[name="workspace"]').fill(str(self.root / "documents"))
        self.form("configure").locator('[name="token"]').fill(TOKEN)

    def save_screenshots(self, label):
        target = os.environ.get("VCL_BROWSER_ARTIFACTS")
        if not target:
            return
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        viewport = self.page.viewport_size
        try:
            for suffix, size in (("desktop", {"width": 1280, "height": 900}),
                                 ("mobile", {"width": 390, "height": 844})):
                self.page.set_viewport_size(size)
                self.page.screenshot(path=str(directory / f"setup-{label}-{suffix}.png"),
                                     full_page=True, animations="disabled")
        finally:
            if viewport:
                self.page.set_viewport_size(viewport)

    def configure_and_pair(self, *, capture=False):
        self.visit()
        if capture:
            self.save_screenshots("configure")
        self.fill_configuration()
        self.submit("configure")
        self.assertTrue(wait_until(lambda: self.wizard.phase == "pairing"))
        self.fake.pair(self.wizard.pair_code)

    def assert_no_browser_secret(self):
        self.assertNotIn(TOKEN, self.page.content())
        values = self.page.evaluate("({local: {...localStorage}, session: {...sessionStorage}})")
        self.assertNotIn(TOKEN, str(values))
        self.assertEqual(values, {"local": {}, "session": {}})
        token_field = self.page.locator('input[name="token"]')
        if token_field.count():
            self.assertEqual(token_field.input_value(), "")

    @contextmanager
    def old_referrer_policy(self):
        """Témoin négatif : reproduire le header livré en v0.2.0 seulement."""
        original = WizardHandler.send_header

        def send_header(handler, keyword, value):
            if keyword.lower() == "referrer-policy":
                value = "no-referrer"
            return original(handler, keyword, value)

        with patch.object(WizardHandler, "send_header", send_header):
            yield

    def test_old_no_referrer_policy_really_produces_null_origin_and_403(self):
        self.start_server(authenticated=False)
        with self.old_referrer_policy():
            response = self.visit()
            self.assertEqual(response.header_value("referrer-policy"), "no-referrer")
            with patch.object(self.wizard, "check_login", wraps=self.wizard.check_login) as check_login:
                response = self.submit("check-login", status=403)
        self.assertEqual(response.request.header_value("origin"), "null")
        check_login.assert_not_called()
        self.assertEqual(self.wizard.phase, "auth")

    def test_real_form_posts_use_same_origin_and_manual_login_verifies(self):
        self.start_server(authenticated=False)
        response = self.visit()
        self.assertEqual(response.header_value("referrer-policy"), "same-origin")
        self.auth.return_value = (True, "Connexion fictive active")
        response = self.submit("check-login")
        self.assertEqual(response.request.header_value("origin"), self.server.origin)
        self.form("configure").wait_for(state="visible")
        self.assertEqual(self.wizard.phase, "configure")
        self.assert_no_browser_secret()

    def test_manual_login_is_detected_in_background_without_post(self):
        self.start_server(authenticated=False)
        self.wizard.enable_login_watch()
        posts = []
        self.page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
        self.visit()
        self.auth.return_value = (True, "Connexion manuelle fictive active")
        self.form("configure").wait_for(state="visible", timeout=15000)
        self.assertEqual(self.wizard.phase, "configure")
        self.assertEqual(posts, [])
        self.start_login.assert_not_called()

    def test_background_checks_preserve_fields_and_selected_pairing_link(self):
        self.start_server()
        self.visit()
        self.fill_configuration()
        self.page.evaluate("window.setupDocumentPreserved = true")
        self.page.wait_for_timeout(3300)
        self.assertTrue(self.page.evaluate("window.setupDocumentPreserved === true"))
        self.assertEqual(self.form("configure").locator('[name="name"]').input_value(), "Assistant de test")
        self.assertEqual(self.form("configure").locator('[name="token"]').input_value(), TOKEN)
        self.submit("configure")
        link = self.page.locator('details .link')
        self.page.locator('summary', has_text="Ouvrir le lien sur un autre appareil").click()
        link.evaluate("""node => {
            window.pairingMain = document.querySelector('main');
            const range = document.createRange();
            range.selectNodeContents(node);
            getSelection().removeAllRanges();
            getSelection().addRange(range);
        }""")
        for _ in range(2):
            with self.page.expect_response(lambda response: response.url == self.server.url
                                           and response.request.resource_type == "fetch"):
                pass
            self.page.wait_for_timeout(100)
            self.assertTrue(self.page.evaluate("window.pairingMain === document.querySelector('main')"))
            self.assertTrue(self.page.locator('details').evaluate("node => node.open"))
            self.assertEqual(self.page.evaluate("getSelection().toString()"), self.wizard.pair_link)
        self.fake.pair(self.wizard.pair_code)
        self.form("finish").wait_for(state="visible")
        self.assertEqual(self.wizard.phase, "ready")

    def test_login_button_and_cancellation_use_real_posts(self):
        self.start_server(authenticated=False)
        self.visit()
        self.submit("login")
        self.form("cancel-login").wait_for(state="visible")
        self.assertTrue(wait_until(lambda: self.wizard.auth_attempt is self.login))
        self.submit("cancel-login")
        self.form("login").wait_for(state="visible")
        self.assertTrue(self.login.cancelled.wait(2))
        self.start_login.assert_called_once()
        self.assertEqual(self.wizard.phase, "auth")

    def test_configure_cancel_pairing_and_token_are_not_retained(self):
        self.start_server()
        self.visit()
        self.fill_configuration()
        response = self.submit("configure")
        self.assertEqual(response.request.header_value("origin"), self.server.origin)
        self.assertTrue(wait_until(lambda: self.wizard.phase == "pairing"))
        self.form("cancel").wait_for(state="visible")
        link = self.page.locator('a[href^="https://t.me/BrowserTestBot?start="]')
        self.assertIn("noreferrer", link.get_attribute("rel") or "")
        self.assertIn("noopener", link.get_attribute("rel") or "")
        self.assertNotIn(TOKEN, self.page.content())
        self.submit("cancel")
        self.form("configure").wait_for(state="visible")
        self.assert_no_browser_secret()
        self.assertFalse((self.root / "config.env").exists())

    def test_existing_token_never_prefills_the_browser(self):
        save_config(self.root, {"TELEGRAM_TOKEN": TOKEN})
        self.start_server()
        response = self.visit()
        self.assertEqual(response.header_value("cache-control"), "no-store")
        self.assert_no_browser_secret()
        self.assertEqual(self.form("configure").locator('[name="token"]').get_attribute("type"), "password")
        self.page.reload()
        self.assert_no_browser_secret()

    def test_wrong_csrf_is_rejected_with_safe_recovery(self):
        self.start_server()
        self.visit()
        self.fill_configuration()
        self.form("configure").locator('[name="csrf"]').evaluate("node => node.value = 'obsolete'")
        with patch.object(self.wizard, "configure", wraps=self.wizard.configure) as configure:
            response = self.submit("configure", status=403)
        self.assertEqual(response.request.header_value("origin"), self.server.origin)
        configure.assert_not_called()
        self.assertNotIn(TOKEN, self.page.content())
        self.page.locator(f'a[href="{self.wizard.path}"]').click()
        self.form("configure").wait_for(state="visible")
        self.assert_no_browser_secret()

    def test_stale_tab_after_real_server_restart_cannot_submit_or_leak_new_path(self):
        old_wizard, old_server = self.start_server()
        self.visit()
        self.fill_configuration()
        old_path, old_origin = old_wizard.path, old_server.origin
        port = old_server.server_port
        entry = self.servers.pop()
        self.close_server(*entry)
        new_wizard, new_server = self.start_server(port=port)
        self.assertEqual(new_server.origin, old_origin)
        self.assertNotEqual(new_wizard.path, old_path)
        target = old_origin + old_path + "configure"
        with patch.object(new_wizard, "configure", wraps=new_wizard.configure) as configure:
            with self.page.expect_response(
                    lambda response: response.url == target and response.request.method == "POST") as received:
                self.page.locator(f'form[action="{old_path}configure"] button').click()
        self.assertEqual(received.value.status, 404)
        configure.assert_not_called()
        self.assertNotIn(new_wizard.path, self.page.content())
        self.assertNotIn(TOKEN, self.page.content())
        self.assertFalse((self.root / "config.env").exists())
        self.visit()
        self.assert_no_browser_secret()

    def test_pairing_only_becomes_ready_after_diagnostics_and_service_then_finish(self):
        release_model = threading.Event()
        self.addCleanup(release_model.set)

        def diagnostics(root, *, live, report, cancel):
            report(DiagnosticCheck("telegram", "ok", "Telegram fictif joignable."))
            report(DiagnosticCheck("model", "running", "Diagnostic modèle fictif en cours."))
            if not release_model.wait(12):
                return DiagnosticResult(False, ())
            return self.diagnostic_result(report)

        self.diagnostics.side_effect = diagnostics
        self.start_server()
        self.configure_and_pair(capture=True)
        self.assertTrue(wait_until(lambda: self.wizard.phase == "diagnostics"))
        self.page.get_by_text("Diagnostic modèle fictif en cours.", exact=True).wait_for(state="visible")
        self.assertFalse(self.wizard.done.is_set())
        self.assertEqual(self.form("finish").count(), 0)
        self.service_start.assert_not_called()
        release_model.set()
        self.form("finish").wait_for(state="visible")
        self.assertEqual(self.wizard.phase, "ready")
        self.assertTrue(self.wizard.done.is_set())
        self.diagnostics.assert_called_once()
        self.service_start.assert_called_once_with(self.root, cancel=self.wizard.stop)
        self.service_status.assert_called_once_with(self.root)
        self.save_screenshots("ready")
        self.submit("finish", status=200)
        self.assertTrue(self.wizard.stop.is_set())
        self.assertNotIn(TOKEN, self.page.content())
        self.assertIn("<html", self.page.content())

    def test_network_failure_retry_button_recovers_to_ready(self):
        attempts = 0

        def diagnostics(root, *, live, report, cancel):
            nonlocal attempts
            attempts += 1
            return self.diagnostic_result(report, ok=attempts > 1)

        self.diagnostics.side_effect = diagnostics
        self.start_server()
        self.configure_and_pair()
        self.form("retry").wait_for(state="visible")
        self.assertEqual(self.wizard.phase, "blocked")
        self.assertFalse(self.wizard.done.is_set())
        self.service_start.assert_not_called()
        self.assertIn("Réseau temporairement indisponible.", self.page.inner_text("body"))
        response = self.submit("retry")
        self.assertEqual(response.request.header_value("origin"), self.server.origin)
        self.form("finish").wait_for(state="visible")
        self.assertEqual(self.diagnostics.call_count, 2)
        self.service_start.assert_called_once_with(self.root, cancel=self.wizard.stop)

    def test_blocked_page_can_edit_configuration_without_exposing_saved_token(self):
        def diagnostics(root, *, live, report, cancel):
            return self.diagnostic_result(report, ok=False)

        self.diagnostics.side_effect = diagnostics
        self.start_server()
        self.configure_and_pair()
        self.form("edit-config").wait_for(state="visible")
        self.assertTrue((self.root / "config.env").exists())
        self.submit("edit-config")
        self.form("configure").wait_for(state="visible")
        self.assertEqual(self.wizard.phase, "configure")
        self.assert_no_browser_secret()
        self.service_start.assert_not_called()

    def test_failed_service_is_not_presented_as_ready_and_retry_can_finish(self):
        self.service_start.side_effect = [1, 0]
        self.service_status.side_effect = [{"running": False, "ready": False},
                                           {"running": True, "ready": True}]
        self.start_server()
        self.configure_and_pair()
        self.form("retry").wait_for(state="visible")
        self.assertFalse(self.wizard.done.is_set())
        self.assertEqual(self.form("finish").count(), 0)
        self.submit("retry")
        self.form("finish").wait_for(state="visible")
        self.assertEqual(self.service_start.call_count, 2)
        self.assertEqual(self.wizard.phase, "ready")


if __name__ == "__main__":
    unittest.main()
