"""Telegram HTTPS sortant, sans service tiers ni dépendance Python."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class TelegramError(RuntimeError):
    def __init__(self, code: int, message: str, retry_after: int = 0):
        self.code, self.retry_after = code, retry_after
        super().__init__(message)


class Telegram:
    def __init__(self, token: str):
        self.token = token
        self._base = f"https://api.telegram.org/bot{token}/"

    def request(self, method: str, values: dict | None = None, timeout: int = 40):
        data = urllib.parse.urlencode(values or {}).encode()
        req = urllib.request.Request(self._base + method, data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read())
            except (ValueError, OSError):
                payload = {}
            exc.close()
            retry = payload.get("parameters", {}).get("retry_after", 0)
            labels = {
                401: "Token Telegram invalide. Relancez setup.",
                403: "Le bot ne peut pas vous écrire. Ouvrez sa conversation puis Démarrer.",
                409: "Ce bot est utilisé par un autre programme ou par un webhook.",
                429: "Telegram demande de ralentir les messages.",
            }
            raise TelegramError(exc.code, labels.get(exc.code, f"Telegram HTTP {exc.code}"), retry) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise TelegramError(0, "Connexion Telegram indisponible. Nouvelle tentative automatique.") from None
        if not payload.get("ok"):
            raise TelegramError(int(payload.get("error_code", 0)), "Telegram a refusé la requête.")
        return payload["result"]

    def get_me(self):
        return self.request("getMe")

    def updates(self, offset=None, timeout=20):
        values = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            values["offset"] = offset
        return self.request("getUpdates", values, timeout=timeout + 10)

    def send(self, chat_id: int, text: str):
        # Texte simple : aucune erreur de parsing Markdown sur une réponse du modèle.
        if not text.strip():
            return
        for start in range(0, len(text), 3500):
            values = {"chat_id": chat_id, "text": text[start:start + 3500]}
            for attempt in range(2):
                try:
                    self.request("sendMessage", values)
                    break
                except TelegramError as exc:
                    if exc.code == 429 and attempt == 0:
                        time.sleep(min(max(exc.retry_after, 1), 30))
                    else:
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
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.load(response)
            if not payload.get("ok"):
                raise TelegramError(0, "Envoi du document refusé.")
        except (OSError, urllib.error.URLError):
            raise TelegramError(0, "Le document n'a pas pu être envoyé.") from None

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
        except (OSError, urllib.error.URLError):
            raise TelegramError(0, "Téléchargement Telegram interrompu.") from None
        finally:
            temporary.unlink(missing_ok=True)
        return destination
