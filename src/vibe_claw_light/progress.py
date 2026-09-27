"""Activité réelle des outils, sans arguments, chemins ni sorties techniques."""
from __future__ import annotations

from dataclasses import dataclass
import time

from .telegram import TelegramError


LABELS = {
    "read": "📖 Lecture de fichiers",
    "write": "✏️ Modification de fichiers",
    "search": "🔎 Recherche dans les fichiers",
    "web": "🌐 Recherche sur Internet",
    "command": "⚙️ Action sur l’ordinateur",
    "task": "🤝 Travail avec un autre agent",
    "tool": "🔧 Utilisation d’un outil",
}


@dataclass(frozen=True)
class Activity:
    kind: str
    key: str = ""


def activities(provider: str, event: dict):
    """Ne jamais transmettre le contenu libre d'un événement au suivi Telegram."""
    if provider == "codex":
        if event.get("type") not in {"item.started", "item.completed"}:
            return
        item = event.get("item")
        if not isinstance(item, dict):
            return
        kind = {"command_execution": "command", "file_change": "write",
                "web_search": "web", "mcp_tool_call": "tool",
                "collab_tool_call": "task"}.get(item.get("type"))
        key = item.get("id")
        # Sans ID, seul le résultat est compté pour éviter le doublon début/fin.
        if kind and (key or event["type"] == "item.completed"):
            yield Activity(kind, key[:256] if isinstance(key, str) else "")
    elif provider == "claude":
        blocks = []
        if event.get("type") == "assistant":
            message = event.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), list):
                blocks = message["content"]
        elif event.get("type") == "stream_event":
            inner = event.get("event")
            if isinstance(inner, dict) and inner.get("type") == "content_block_start":
                blocks = [inner.get("content_block")]
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            kind = {"Read": "read", "Write": "write", "Edit": "write",
                    "MultiEdit": "write", "NotebookEdit": "write",
                    "Grep": "search", "Glob": "search", "Bash": "command",
                    "WebSearch": "web", "WebFetch": "web", "Task": "task",
                    "Agent": "task"}.get(name if isinstance(name, str) else "", "tool")
            key = block.get("id")
            yield Activity(kind, key[:256] if isinstance(key, str) else "")


class ToolProgress:
    """Un message cumulatif par demande ; appels sous le mutex du bot."""

    def __init__(self, send, edit, *, clock=time.monotonic):
        self.send, self.edit, self.clock = send, edit, clock
        self.counts: dict[str, int] = {}
        self.seen: set[str] = set()
        self.message_id: int | None = None
        self.dirty = False
        self.disabled = False
        self.next_update = 0.0
        self.retry_at = 0.0

    def record(self, event: Activity):
        if not isinstance(event, Activity) or event.kind not in LABELS:
            return
        if event.key:
            if event.key in self.seen or len(self.seen) >= 4096:
                return
            self.seen.add(event.key)
        self.counts[event.kind] = self.counts.get(event.kind, 0) + 1
        self.dirty = True

    def render(self):
        lines = ["Activité de cette demande"]
        for kind, count in self.counts.items():
            lines.append(LABELS[kind] + (f" × {count}" if count > 1 else ""))
        return "\n".join(lines)

    def flush(self, *, force=False):
        now = self.clock()
        if (self.disabled or not self.dirty or now < self.retry_at
                or (not force and now < self.next_update)):
            return
        try:
            if self.message_id is None:
                self.message_id = self.send(self.render())
                if type(self.message_id) is not int:
                    self.disabled = True
            else:
                self.edit(self.message_id, self.render())
            self.dirty = False
            self.next_update = self.clock() + 2
        except TelegramError as exc:
            if exc.code == 429:
                self.retry_at = now + max(exc.retry_after or 5, 2)
            elif self.message_id is None:
                # Un envoi avec réponse perdue pourrait déjà être visible.
                # Ne pas le dupliquer ; la réponse finale reste indépendante.
                self.disabled = True
            else:
                self.retry_at = now + 5
