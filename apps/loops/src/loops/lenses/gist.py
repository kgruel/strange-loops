"""Content gist extraction — meaningful one-liners from fact payloads.

Kind-aware with generic fallback. Used by store lenses to show
content previews instead of structural key names.
"""

from __future__ import annotations

from typing import Callable


# Fields to try, in priority order, when no kind-specific extractor matches
_CONTENT_FIELDS = ("message", "text", "name", "topic", "summary", "title", "description")


def content_gist(kind: str, payload: dict, max_width: int = 80) -> str:
    """Extract the most meaningful content line from a payload.

    Kind-aware extractors handle known patterns. Falls back to
    scanning common field names, then first non-empty string value.
    """
    if not isinstance(payload, dict) or not payload:
        return _truncate(str(payload), max_width) if payload else ""

    # Kind-specific extraction
    extractor = _KIND_EXTRACTORS.get(kind)
    if extractor is not None:
        result = extractor(payload)
        if result:
            return _truncate(result, max_width)

    # Prefix match: "telegram.message" matches "message" extractor
    suffix = kind.rsplit(".", 1)[-1] if "." in kind else None
    if suffix and suffix in _KIND_EXTRACTORS:
        result = _KIND_EXTRACTORS[suffix](payload)
        if result:
            return _truncate(result, max_width)

    # Generic fallback: scan common content field names
    for key in _CONTENT_FIELDS:
        val = payload.get(key)
        if val and isinstance(val, str):
            return _truncate(val, max_width)

    # Last resort: first non-empty string value
    for val in payload.values():
        if isinstance(val, str) and val:
            return _truncate(val, max_width)

    # Truly nothing: compact repr
    return _truncate(str(payload), max_width)


# ---------------------------------------------------------------------------
# Kind-specific extractors
# ---------------------------------------------------------------------------


def _extract_message(p: dict) -> str:
    """Chat message: sender + text."""
    sender = p.get("sender_name", "")
    text = p.get("text", "")
    chat = p.get("chat_title") or p.get("channel_name", "")
    if chat and sender:
        return f'{chat}: {sender}: "{text}"' if text else f"{chat}: {sender}"
    if sender:
        return f'{sender}: "{text}"' if text else sender
    return text


def _extract_decision(p: dict) -> str:
    msg = p.get("message") or p.get("rationale", "")
    topic = p.get("topic", "")
    if topic and msg:
        return f"{topic}: {msg}"
    return topic or msg


def _extract_thread(p: dict) -> str:
    name = p.get("name", "")
    status = p.get("status", "")
    return f"{name} [{status}]" if status else name


def _extract_task(p: dict) -> str:
    name = p.get("name", "")
    status = p.get("status", "")
    summary = p.get("summary", "")
    parts = [name]
    if status:
        parts.append(f"[{status}]")
    if summary:
        parts.append(summary)
    return " ".join(p for p in parts if p)


def _extract_dissolution(p: dict) -> str:
    concept = p.get("concept", "")
    into = p.get("dissolved_into", "")
    if concept and into:
        return f"{concept} → {into}"
    return concept or into


def _extract_notes(p: dict) -> str:
    return p.get("message", "") or p.get("text", "")


def _extract_error(p: dict) -> str:
    err = p.get("error", "")
    etype = p.get("error_type", "")
    if etype and err:
        return f"{etype}: {err}"
    return err or etype


_KIND_EXTRACTORS: dict[str, Callable[[dict], str]] = {
    "message": _extract_message,
    "decision": _extract_decision,
    "thread": _extract_thread,
    "task": _extract_task,
    "dissolution": _extract_dissolution,
    "notes": _extract_notes,
    "source.error": _extract_error,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_width: int) -> str:
    """Truncate to max_width, adding ellipsis if needed."""
    # Collapse newlines to spaces
    text = text.replace("\n", " ").strip()
    if max_width <= 0:
        return ""
    if len(text) <= max_width:
        return text
    return text[:max_width - 1] + "\u2026"
