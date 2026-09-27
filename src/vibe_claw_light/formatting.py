"""Petit rendu Markdown vers le sous-ensemble HTML de Telegram, sans dépendance.

Comme dans Nao, les titres deviennent du gras et les tableaux des listes lisibles
sur mobile. Le HTML du modèle n'est jamais interprété. Le découpage porte sur le
texte visible avant de générer des balises équilibrées pour chaque message.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from urllib.parse import urlsplit


MESSAGE_LIMIT = 3500  # Marge sous les 4096 caractères acceptés par Telegram.


@dataclass(frozen=True)
class _Tag:
    name: str
    value: str = ""

    def opening(self) -> str:
        if self.name == "a":
            return f'<a href="{escape(self.value, quote=True)}">'
        if self.name == "code" and self.value:
            return f'<code class="language-{escape(self.value, quote=True)}">'
        return f"<{self.name}>"


@dataclass
class _Span:
    text: str
    tags: tuple[_Tag, ...] = ()


@dataclass(frozen=True)
class FormattedMessage:
    html: str
    plain: str


def utf16_length(text: str) -> int:
    """Les offsets des entités Telegram sont exprimés en unités UTF-16."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _append(spans: list[_Span], text: str, tags: tuple[_Tag, ...] = ()) -> None:
    if not text:
        return
    if spans and spans[-1].tags == tags:
        spans[-1].text += text
    else:
        spans.append(_Span(text, tags))


def _extend(spans: list[_Span], extra: list[_Span]) -> None:
    for span in extra:
        _append(spans, span.text, span.tags)


def _add_tag(tags: tuple[_Tag, ...], tag: _Tag) -> tuple[_Tag, ...]:
    if tag.name == "a":
        # Les styles peuvent entourer un lien, les autres entités non.
        tags = tuple(existing for existing in tags if existing.name in {"b", "i", "s"})
    return tags if tag in tags else (*tags, tag)


def _safe_url(value: str) -> bool:
    if not value or len(value) > 2048 or re.search(r"[\s\x00-\x1f\x7f<>]", value):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"}:
            return bool(parsed.hostname) and parsed.username is None and parsed.password is None
        return parsed.scheme.lower() == "mailto" and bool(parsed.path) and not parsed.netloc
    except ValueError:
        return False


def _link(text: str, start: int) -> tuple[str, str, int] | None:
    """Reconnaît les liens usuels, y compris les URL contenant des parenthèses."""
    match = re.search(r"(?<!\\)\]\(", text[start + 1:])
    if not match:
        return None
    end_label = start + 1 + match.start()
    cursor, nesting = end_label + 2, 1
    url_start = cursor
    while cursor < len(text):
        char = text[cursor]
        if char == "\\" and cursor + 1 < len(text):
            cursor += 2
            continue
        if char == "(":
            nesting += 1
        elif char == ")":
            nesting -= 1
            if not nesting:
                target = text[url_start:cursor].strip()
                # Un titre Markdown facultatif n'est pas envoyé dans le href.
                title = re.fullmatch(r'(.+?)\s+["\'].*["\']', target)
                if title:
                    target = title[1]
                target = target.removeprefix("<").removesuffix(">")
                target = re.sub(r"\\([()])", r"\1", target)
                return text[start + 1:end_label], target, cursor + 1
        cursor += 1
    return None


def _closing(text: str, marker: str, start: int) -> int:
    cursor = start
    while (cursor := text.find(marker, cursor)) >= 0:
        before = text[cursor - 1] if cursor else ""
        after = text[cursor + len(marker):cursor + len(marker) + 1]
        if before and not before.isspace() and before != "\\":
            if marker == "_" and after and (after.isalnum() or after == "_"):
                pass
            elif len(marker) == 1 and (before == marker or after == marker):
                pass
            else:
                return cursor
        cursor += len(marker)
    return -1


def _inline(text: str, tags: tuple[_Tag, ...] = (), depth: int = 0) -> list[_Span]:
    if depth >= 12:
        return [_Span(text, tags)]
    spans: list[_Span] = []
    plain: list[str] = []

    def flush() -> None:
        _append(spans, "".join(plain), tags)
        plain.clear()

    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "\\" and cursor + 1 < len(text) and text[cursor + 1] in r"\`*_{}[]()#+-.!>|~":
            plain.append(text[cursor + 1])
            cursor += 2
            continue
        if char == "`":
            marker = re.match(r"`+", text[cursor:])[0]
            end = text.find(marker, cursor + len(marker))
            if end >= 0:
                flush()
                code = text[cursor + len(marker):end]
                if code.startswith(" ") and code.endswith(" ") and code.strip():
                    code = code[1:-1]
                # Telegram interdit les autres entités imbriquées dans le code.
                _append(spans, code, (_Tag("code"),))
                cursor = end + len(marker)
                continue
        link_start = cursor + 1 if text.startswith("![", cursor) else cursor
        if text[link_start:link_start + 1] == "[" and (link := _link(text, link_start)):
            label, target, end = link
            flush()
            link_tags = _add_tag(tags, _Tag("a", target)) if _safe_url(target) else tags
            _extend(spans, _inline(label, link_tags, depth + 1))
            cursor = end
            continue
        if char == "<":
            end = text.find(">", cursor + 1)
            if end >= 0 and _safe_url(text[cursor + 1:end]):
                flush()
                target = text[cursor + 1:end]
                _append(spans, target, _add_tag(tags, _Tag("a", target)))
                cursor = end + 1
                continue
        consumed = False
        for marker, names in (("***", ("b", "i")), ("___", ("b", "i")),
                              ("**", ("b",)), ("__", ("b",)), ("~~", ("s",)),
                              ("*", ("i",)), ("_", ("i",))):
            if not text.startswith(marker, cursor):
                continue
            content_start = cursor + len(marker)
            if content_start >= len(text) or text[content_start].isspace():
                continue
            if marker.startswith("_") and cursor and (text[cursor - 1].isalnum() or text[cursor - 1] == "_"):
                continue
            end = _closing(text, marker, content_start)
            if end < 0:
                continue
            flush()
            inner_tags = tags
            for name in names:
                inner_tags = _add_tag(inner_tags, _Tag(name))
            _extend(spans, _inline(text[content_start:end], inner_tags, depth + 1))
            cursor = end + len(marker)
            consumed = True
            break
        if not consumed:
            plain.append(char)
            cursor += 1
    flush()
    return spans


def _cells(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _parse(text: str) -> list[_Span]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Les caractères de contrôle ne portent aucune mise en forme utile.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    lines = text.split("\n")
    spans: list[_Span] = []
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor]
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker, info = fence.groups()
            lang = info.strip().split(maxsplit=1)[0] if info.strip() else ""
            lang = lang if re.fullmatch(r"[A-Za-z0-9_+.-]{1,40}", lang) else ""
            cursor += 1
            code: list[str] = []
            end_fence = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
            while cursor < len(lines) and not end_fence.match(lines[cursor]):
                code.append(lines[cursor])
                cursor += 1
            tags = (_Tag("pre"), _Tag("code", lang)) if lang else (_Tag("pre"),)
            _append(spans, "\n".join(code), tags)
            if cursor < len(lines):
                cursor += 1
        elif ("|" in line and cursor + 1 < len(lines) and "|" in lines[cursor + 1]
              and all(re.fullmatch(r":?-{3,}:?", cell) for cell in _cells(lines[cursor + 1]))):
            headers = _cells(line)
            cursor += 2
            first = True
            while cursor < len(lines) and "|" in lines[cursor] and lines[cursor].strip():
                cells = _cells(lines[cursor])
                if not first:
                    _append(spans, "\n\n")
                for index, cell in enumerate(cells):
                    if index:
                        label = headers[index] if index < len(headers) else str(index + 1)
                        _append(spans, "\n")
                        _extend(spans, _inline(label + " : " + cell))
                    else:
                        _extend(spans, _inline(cell, (_Tag("b"),)))
                first = False
                cursor += 1
            if first:
                _extend(spans, _inline(" | ".join(headers), (_Tag("b"),)))
        elif re.match(r"^\s*>[ >]?", line):
            quoted: list[str] = []
            while cursor < len(lines) and re.match(r"^\s*>", lines[cursor]):
                quoted.append(re.sub(r"^\s*> ?", "", lines[cursor]))
                cursor += 1
            for index, quote in enumerate(quoted):
                if index:
                    _append(spans, "\n", (_Tag("blockquote"),))
                _extend(spans, _inline(quote, (_Tag("blockquote"),)))
        else:
            heading = re.match(r"^ {0,3}#{1,6}\s+(.+)$", line)
            if heading:
                _extend(spans, _inline(re.sub(r"\s+#+\s*$", "", heading[1]), (_Tag("b"),)))
            elif re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line):
                _append(spans, "────────")
            else:
                bullet = re.match(r"^(\s*)[-+*]\s+(.+)$", line)
                if bullet:
                    body = bullet[2]
                    check = re.match(r"\[([ xX])\]\s+(.*)$", body)
                    prefix = ("☐ " if check[1] == " " else "☑ ") if check else "• "
                    line = bullet[1] + prefix + (check[2] if check else body)
                _extend(spans, _inline(line))
            cursor += 1
        if cursor < len(lines):
            _append(spans, "\n")
    return spans


def _render(spans: list[_Span]) -> str:
    rendered: list[str] = []
    active: tuple[_Tag, ...] = ()
    for span in spans:
        common = 0
        while common < min(len(active), len(span.tags)) and active[common] == span.tags[common]:
            common += 1
        rendered.extend(f"</{tag.name}>" for tag in reversed(active[common:]))
        rendered.extend(tag.opening() for tag in span.tags[common:])
        rendered.append(escape(span.text, quote=False))
        active = span.tags
    rendered.extend(f"</{tag.name}>" for tag in reversed(active))
    return "".join(rendered)


def _plain(spans: list[_Span]) -> str:
    """Conserve aussi les destinations des liens lors d'un repli sans HTML."""
    result: list[str] = []
    current_url = ""
    label: list[str] = []

    def flush() -> None:
        visible = "".join(label)
        result.append(visible)
        if current_url and visible != current_url:
            result.append(f" ({current_url})")
        label.clear()

    for span in spans:
        url = next((tag.value for tag in span.tags if tag.name == "a"), "")
        if url != current_url:
            flush()
            current_url = url
        label.append(span.text)
    flush()
    return "".join(result)


def _split(spans: list[_Span], limit: int) -> list[list[_Span]]:
    if limit < 2:
        raise ValueError("La limite doit permettre au moins un caractère Unicode complet.")
    chunks: list[list[_Span]] = []
    current: list[_Span] = []
    used = 0
    for span in spans:
        remaining = span.text
        while remaining:
            available = limit - used
            length, end = 0, 0
            for char in remaining:
                width = 2 if ord(char) > 0xFFFF else 1
                if length + width > available:
                    break
                length += width
                end += 1
            if end < len(remaining) and end:
                # Préférer une ligne ou un mot entier sans perdre d'espaces.
                boundary = max(remaining.rfind("\n", 0, end), remaining.rfind(" ", 0, end)) + 1
                if boundary >= end // 2 and boundary:
                    end = boundary
                    length = utf16_length(remaining[:end])
            if end:
                _append(current, remaining[:end], span.tags)
                used += length
                remaining = remaining[end:]
            if remaining or used == limit:
                if current:
                    chunks.append(current)
                current, used = [], 0
    if current:
        chunks.append(current)
    return chunks


def plain_chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    return ["".join(span.text for span in chunk) for chunk in _split([_Span(text)], limit)]


def md_to_telegram_html(text: str) -> str:
    return _render(_parse(text))


def format_messages(text: str, limit: int = MESSAGE_LIMIT) -> list[FormattedMessage]:
    return [FormattedMessage(_render(chunk), _plain(chunk)) for chunk in _split(_parse(text), limit)]
