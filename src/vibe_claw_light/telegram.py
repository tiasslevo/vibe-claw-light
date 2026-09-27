"""Telegram HTTPS sortant, sans service tiers ni dépendance Python."""
from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, TypeVar

from .formatting import format_messages, plain_chunks, utf16_length


_MESSAGES = {
    "dns": "Le nom du serveur Telegram ne peut pas être résolu (DNS). Vérifiez la connexion réseau.",
    "tls": "La connexion chiffrée à Telegram a échoué (TLS). Vérifiez la date du PC et les certificats réseau.",
    "timeout": "Telegram n'a pas répondu dans le délai prévu. Réessayez après avoir vérifié la connexion.",
    "network": "La connexion réseau à Telegram a été interrompue ou refusée.",
    "unauthorized": "Telegram a refusé le token (401). Vérifiez le token auprès de BotFather.",
    "forbidden": "Telegram refuse cet accès (403). Ouvrez la conversation privée du bot puis Démarrer.",
    "rate_limit": "Telegram demande de patienter avant une nouvelle requête (429).",
    "conflict": "Ce bot est utilisé par un autre programme ou par un webhook (409).",
    "webhook": "Ce bot est déjà associé à un webhook. Utilisez un bot disponible pour cette installation.",
    "server": "Telegram rencontre une erreur serveur temporaire (5xx).",
    "internal": "La réponse Telegram est invalide ou une erreur interne a interrompu le contrôle.",
    "cancelled": "Vérification Telegram annulée.",
    "formatting": "Telegram n'a pas accepté la mise en forme du message.",
    "not_modified": "Le message Telegram contient déjà ce texte.",
}


def _http_category(code: int) -> str:
    return {401: "unauthorized", 403: "forbidden", 409: "conflict", 429: "rate_limit"}.get(
        code, "server" if 500 <= code <= 599 else "internal"
    )


def _response_category(code: int, description: object = "") -> str:
    # Inspect only known refusal signatures. The response body is never retained
    # in the exception, a log, or a user-facing diagnostic.
    if code == 400 and isinstance(description, str):
        hint = description.lower()
        if hint.startswith("bad request: can't parse entities"):
            return "formatting"
        if hint.startswith("bad request: message is not modified"):
            return "not_modified"
    return _http_category(code)


class TelegramError(RuntimeError):
    def __init__(self, code: int, message: str = "", retry_after: int = 0,
                 *, category: str | None = None, retryable: bool | None = None):
        # Never forward response bodies, request URLs, tokens or arbitrary exception text.
        # Keep the old message argument for callers; public diagnostics use fixed labels.
        self.code = code if isinstance(code, int) else 0
        try:
            self.retry_after = min(max(int(retry_after), 0), 86400)
        except (TypeError, ValueError, OverflowError):
            self.retry_after = 0
        self.category = category or (_http_category(self.code) if self.code else "network")
        if self.category not in _MESSAGES:
            self.category = "internal"
        self.retryable = self.category in {"dns", "timeout", "network", "rate_limit", "server"} if retryable is None else retryable
        self.sanitized_message = _MESSAGES[self.category]
        if self.category == "rate_limit" and self.retry_after:
            self.sanitized_message += f" Attente indiquée : {self.retry_after} s."
        elif self.category == "internal" and self.code:
            self.sanitized_message += f" Code HTTP : {self.code}."
        super().__init__(self.sanitized_message)


def _network_error(exc: BaseException) -> TelegramError:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return TelegramError(0, category="dns")
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return TelegramError(0, category="timeout")
    if isinstance(reason, ssl.SSLError):
        return TelegramError(0, category="tls", retryable=isinstance(reason, ssl.SSLEOFError))
    # Some urllib handlers expose only a string reason. Classify without displaying it.
    hint = str(reason).lower()
    if "timed out" in hint or "timeout" in hint:
        return TelegramError(0, category="timeout")
    if "certificate" in hint or "ssl" in hint or "tls" in hint:
        return TelegramError(0, category="tls")
    if "name resolution" in hint or "getaddrinfo" in hint:
        return TelegramError(0, category="dns")
    return TelegramError(0, category="network")


def _http_error(exc: urllib.error.HTTPError) -> TelegramError:
    retry = 0
    category = _http_category(exc.code)
    try:
        payload = json.loads(exc.read(65536))
        if isinstance(payload, dict):
            category = _response_category(exc.code, payload.get("description"))
            if isinstance(payload.get("parameters"), dict):
                retry = payload["parameters"].get("retry_after", 0)
    except (ValueError, OSError, TypeError):
        pass
    finally:
        exc.close()
    return TelegramError(exc.code, retry_after=retry, category=category)


_T = TypeVar("_T")


def retry_telegram(operation: Callable[[], _T], *, cancel: threading.Event | None = None,
                   attempts: int = 3,
                   on_retry: Callable[[TelegramError, int, float], None] | None = None) -> _T:
    """Retry read-only/idempotent checks briefly; never retry rejected credentials."""
    cancel = cancel or threading.Event()
    attempts = min(max(attempts, 1), 3)
    for attempt in range(1, attempts + 1):
        if cancel.is_set():
            raise TelegramError(0, category="cancelled")
        try:
            return operation()
        except TelegramError as exc:
            delay = float(exc.retry_after or attempt)
            if not exc.retryable or attempt == attempts or delay > 5:
                raise
            if on_retry:
                on_retry(exc, attempt + 1, delay)
            if cancel.wait(delay):
                raise TelegramError(0, category="cancelled") from None
    raise AssertionError("unreachable")


class Telegram:
    def __init__(self, token: str):
        self.token = token
        self._base = f"https://api.telegram.org/bot{token}/"

    def request(self, method: str, values: dict | None = None, timeout: int = 40):
        data = urllib.parse.urlencode(values or {}).encode()
        req = urllib.request.Request(self._base + method, data=data)
        return self._response(req, timeout)

    def _response(self, req: urllib.request.Request, timeout: int):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from None
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise _network_error(exc) from None
        except (ValueError, TypeError):
            raise TelegramError(0, category="internal") from None
        if not isinstance(payload, dict):
            raise TelegramError(0, category="internal")
        if payload.get("ok") is not True:
            parameters = payload.get("parameters")
            retry = parameters.get("retry_after", 0) if isinstance(parameters, dict) else 0
            code = payload.get("error_code", 0)
            category = _response_category(code, payload.get("description")) if isinstance(code, int) else "internal"
            raise TelegramError(code, retry_after=retry, category=category)
        if "result" not in payload:
            raise TelegramError(0, category="internal")
        return payload["result"]

    def get_me(self):
        return self.request("getMe", timeout=8)

    def updates(self, offset=None, timeout=20):
        values = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            values["offset"] = offset
        return self.request("getUpdates", values, timeout=timeout + 10)

    def send(self, chat_id: int, text: str):
        if not text.strip():
            return
        for chunk in format_messages(text):
            try:
                self._send_message({"chat_id": chat_id, "text": chunk.html, "parse_mode": "HTML"})
            except TelegramError as exc:
                if exc.category != "formatting":
                    # A network failure may follow successful delivery. Never
                    # resend an uncertain message as plain text and duplicate it.
                    raise
                for plain in plain_chunks(chunk.plain):
                    self._send_message({"chat_id": chat_id, "text": plain})

    def _send_message(self, values: dict):
        for attempt in range(2):
            try:
                return self.request("sendMessage", values)
            except TelegramError as exc:
                if exc.code == 429 and attempt == 0:
                    time.sleep(min(max(exc.retry_after, 1), 30))
                else:
                    raise

    @staticmethod
    def _check_plain_message(text: str) -> None:
        if not text.strip() or utf16_length(text) > 4096:
            raise ValueError("Un message de suivi doit contenir entre 1 et 4096 caractères Telegram.")

    def send_plain(self, chat_id: int, text: str) -> int:
        """Envoie un unique message court, éditable, sans interpréter de Markdown."""
        self._check_plain_message(text)
        result = self.request("sendMessage", {"chat_id": chat_id, "text": text}, timeout=5)
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int) or isinstance(message_id, bool):
            raise TelegramError(0, category="internal")
        return message_id

    def edit(self, chat_id: int, message_id: int, text: str) -> None:
        """Met à jour le suivi en texte brut, avec un délai réseau court."""
        self._check_plain_message(text)
        values = {"chat_id": chat_id, "message_id": message_id, "text": text}
        try:
            self.request("editMessageText", values, timeout=5)
        except TelegramError as exc:
            if exc.category != "not_modified":
                raise

    def typing(self, chat_id: int):
        self.request("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=8)

    def send_document(self, chat_id: int, path: Path, caption: str = ""):
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Ce fichier dépasse la limite de 20 Mio du starter.")
        boundary = uuid.uuid4().hex
        chunks = []
        for key, value in {"chat_id": str(chat_id), "caption": caption[:900]}.items():
            chunks.extend([f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n".encode(), value.encode(), b"\r\n"])
        name = re.sub(r'["\r\n\\]', "_", path.name)
        chunks.extend([
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),
            path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
        ])
        req = urllib.request.Request(self._base + "sendDocument", data=b"".join(chunks), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self._response(req, 60)

    def download(self, file_id: str, destination: Path, max_size: int = 20 * 1024 * 1024):
        result = self.request("getFile", {"file_id": file_id})
        if result.get("file_size", 0) > max_size:
            raise ValueError("Pièce jointe trop volumineuse : 20 Mio maximum.")
        file_path = result.get("file_path", "")
        if not file_path or file_path.startswith("/") or ".." in file_path.split("/"):
            raise ValueError("Chemin Telegram invalide.")
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        temporary = destination.with_suffix(destination.suffix + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = 0
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > max_size:
                        raise ValueError("Pièce jointe trop volumineuse : 20 Mio maximum.")
                    output.write(chunk)
            if result.get("file_size") is not None and size != result["file_size"]:
                raise ValueError("Téléchargement incomplet. Renvoyez le fichier.")
            temporary.replace(destination)
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from None
        except (OSError, urllib.error.URLError) as exc:
            raise _network_error(exc) from None
        finally:
            temporary.unlink(missing_ok=True)
        return destination
