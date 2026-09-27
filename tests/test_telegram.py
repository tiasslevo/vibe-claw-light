import io
import json
import socket
import ssl
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error

from vibe_claw_light.telegram import Telegram, TelegramError, retry_telegram


TOKEN = "111111111:" + "x" * 35


class FastEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.delays = []

    def wait(self, timeout=None):
        self.delays.append(timeout)
        return self.is_set()


class TelegramTests(unittest.TestCase):
    def test_network_categories_do_not_expose_exception_url_or_token(self):
        cases = [
            (socket.gaierror(socket.EAI_AGAIN, TOKEN), "dns", True),
            (TimeoutError("https://api.telegram.org/bot" + TOKEN), "timeout", True),
            (ssl.SSLCertVerificationError(1, TOKEN), "tls", False),
            (ssl.SSLEOFError(1, TOKEN), "tls", True),
            (ConnectionResetError(TOKEN), "network", True),
        ]
        for reason, category, retryable in cases:
            with self.subTest(category=category, retryable=retryable):
                with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(reason)):
                    with self.assertRaises(TelegramError) as raised:
                        Telegram(TOKEN).get_me()
                error = raised.exception
                self.assertEqual(error.category, category)
                self.assertEqual(error.retryable, retryable)
                self.assertNotIn(TOKEN, str(error))
                self.assertNotIn("https://", str(error))

    def test_http_categories_and_retry_after_are_sanitized(self):
        for code, category, retryable in [
            (401, "unauthorized", False), (403, "forbidden", False),
            (409, "conflict", False), (429, "rate_limit", True),
            (502, "server", True), (400, "internal", False),
        ]:
            body = io.BytesIO(json.dumps({"description": TOKEN, "parameters": {"retry_after": 2}}).encode())
            failure = urllib.error.HTTPError("https://api.telegram.org/bot" + TOKEN, code, TOKEN, {}, body)
            with self.subTest(code=code), patch("urllib.request.urlopen", side_effect=failure):
                with self.assertRaises(TelegramError) as raised:
                    Telegram(TOKEN).get_me()
            error = raised.exception
            self.assertEqual((error.code, error.category, error.retryable), (code, category, retryable))
            self.assertEqual(error.retry_after, 2)
            self.assertNotIn(TOKEN, str(error))
            self.assertTrue(body.closed)

    def test_invalid_response_is_internal_and_not_retried(self):
        for payload in (b"{broken", b"[]", b'{"ok":true}', b'{"ok":false,"error_code":"bad"}'):
            with self.subTest(payload=payload), patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaises(TelegramError) as raised:
                    Telegram(TOKEN).get_me()
            self.assertEqual(raised.exception.category, "internal")
            self.assertFalse(raised.exception.retryable)

    def test_json_error_response_uses_http_classification(self):
        payload = {"ok": False, "error_code": 429, "parameters": {"retry_after": 3}, "description": TOKEN}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaises(TelegramError) as raised:
                Telegram(TOKEN).get_me()
        self.assertEqual(raised.exception.category, "rate_limit")
        self.assertEqual(raised.exception.retry_after, 3)
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_recoverable_failure_retries_with_bounded_wait(self):
        event, reports = FastEvent(), []
        operation = Mock(side_effect=[TelegramError(0, category="dns"), TelegramError(503), "ready"])
        self.assertEqual(retry_telegram(operation, cancel=event, on_retry=lambda *args: reports.append(args)), "ready")
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(event.delays, [1.0, 2.0])
        self.assertEqual([report[1] for report in reports], [2, 3])

    def test_no_retry_for_bad_token_tls_or_long_rate_limit(self):
        for failure in (TelegramError(401), TelegramError(0, category="tls"), TelegramError(429, retry_after=20)):
            operation, event = Mock(side_effect=failure), FastEvent()
            with self.subTest(category=failure.category), self.assertRaises(TelegramError):
                retry_telegram(operation, cancel=event)
            self.assertEqual(operation.call_count, 1)
            self.assertEqual(event.delays, [])

    def test_cancellation_stops_retries(self):
        event = FastEvent()
        operation = Mock(side_effect=TelegramError(0, category="timeout"))
        with self.assertRaises(TelegramError) as raised:
            retry_telegram(operation, cancel=event, on_retry=lambda *args: event.set())
        self.assertEqual(raised.exception.category, "cancelled")
        self.assertEqual(operation.call_count, 1)

    def test_error_constructor_never_preserves_arbitrary_message(self):
        error = TelegramError(401, "https://api.telegram.org/bot" + TOKEN)
        self.assertEqual(error.sanitized_message, str(error))
        self.assertNotIn(TOKEN, str(error))
        self.assertNotIn("https://", str(error))


if __name__ == "__main__":
    unittest.main()
