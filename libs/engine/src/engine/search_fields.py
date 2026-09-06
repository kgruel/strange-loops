"""Pure payload text extraction shared by legacy and Arrival FTS builders."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

__all__ = ["EXTRACTION_VERSION", "extract_field_text"]

# Bump whenever the token text emitted for one declared field changes.  The
# version forms part of SearchFieldSpec's hash, forcing explicit reindexing.
EXTRACTION_VERSION = "search-field-v1"


def extract_field_text(payload: Mapping[str, Any], field: str) -> str:
    """Extract one declared search path with the established legacy semantics.

    Dot paths traverse mappings. Strings pass through; lists concatenate string
    members and ``text`` members of mappings; mappings serialize as JSON; other
    scalar values use ``str``. Missing/None paths contribute no text.
    """
    value: Any = payload
    for part in field.split("."):
        if isinstance(value, Mapping):
            value = value.get(part)
        else:
            return ""
        if value is None:
            return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return " ".join(parts)
    if isinstance(value, Mapping):
        return json.dumps(dict(value))
    return str(value)
