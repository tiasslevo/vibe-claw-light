from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .storage import atomic_write

DEFAULTS = {
    "PROVIDER": "codex", "AGENT_NAME": "Mon assistant", "TELEGRAM_TOKEN": "",
    "TELEGRAM_OWNER_ID": "", "TELEGRAM_CHAT_ID": "", "WORKSPACE": "workspace",
    "CODEX_BIN": "", "CLAUDE_BIN": "", "CODEX_MODEL": "", "CLAUDE_MODEL": "",
    "ALLOW_SHELL": "0", "TURN_TIMEOUT": "900",
}


def read_values(root: Path) -> dict[str, str]:
    values = dict(DEFAULTS)
    path = root / "config.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = value.strip('"')
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            if key in DEFAULTS:
                values[key] = str(value)
    return values


def save_config(root: Path, updates: dict[str, str]) -> None:
    values = read_values(root)
    unknown = set(updates) - set(DEFAULTS)
    if unknown:
        raise ValueError("Paramètre de configuration inconnu.")
    values.update({key: str(value) for key, value in updates.items()})
    text = "# Configuration privée. Ne pas publier.\n"
    text += "".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items())
    atomic_write(root / "config.env", text)


@dataclass(frozen=True)
class Config:
    root: Path
    provider: str
    name: str
    telegram_token: str
    owner_id: int | None
    chat_id: int | None
    workspace: Path
    codex_bin: str = ""
    claude_bin: str = ""
    codex_model: str = ""
    claude_model: str = ""
    allow_shell: bool = False
    timeout_seconds: int = 900

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def executable_hint(self) -> str:
        return self.codex_bin if self.provider == "codex" else self.claude_bin

    @property
    def model(self) -> str:
        return self.codex_model if self.provider == "codex" else self.claude_model


def load_config(root: Path, require_token: bool = True) -> Config:
    root = root.expanduser().resolve()
    values = read_values(root)
    provider = values["PROVIDER"].lower()
    if provider not in {"codex", "claude"}:
        raise ValueError("PROVIDER doit être codex ou claude.")
    token = values["TELEGRAM_TOKEN"].strip()
    if require_token and not token:
        raise ValueError("Configuration absente : lancez d'abord setup.")
    def identifier(key):
        value = values[key].strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{key} doit être un identifiant entier.") from None
    workspace = Path(values["WORKSPACE"]).expanduser()
    if not workspace.is_absolute():
        workspace = root / workspace
    timeout = int(values["TURN_TIMEOUT"])
    if not 30 <= timeout <= 7200:
        raise ValueError("TURN_TIMEOUT doit être compris entre 30 et 7200 secondes.")
    return Config(
        root=root, provider=provider, name=values["AGENT_NAME"][:80] or "Mon assistant",
        telegram_token=token, owner_id=identifier("TELEGRAM_OWNER_ID"),
        chat_id=identifier("TELEGRAM_CHAT_ID"), workspace=workspace.resolve(),
        codex_bin=values["CODEX_BIN"], claude_bin=values["CLAUDE_BIN"],
        codex_model=values["CODEX_MODEL"], claude_model=values["CLAUDE_MODEL"],
        allow_shell=values["ALLOW_SHELL"].lower() in {"1", "true", "yes", "oui"},
        timeout_seconds=timeout,
    )
