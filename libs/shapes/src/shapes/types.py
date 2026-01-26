"""Type utilities for shapes: coercion, validation, initial values."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ValidationError(Exception):
    """Raised when value validation fails against a shape contract."""

    pass


# Supported type names
TYPES = frozenset({"str", "int", "float", "bool", "dict", "list", "set", "datetime"})


def initial_value(kind: str) -> Any:
    """Return the default initial value for a field type.

    Args:
        kind: Type name (str, int, float, bool, dict, list, set, datetime).

    Returns:
        Appropriate zero/empty value for the type, or None for unknown types.
    """
    match kind:
        case "dict":
            return {}
        case "list":
            return []
        case "set":
            return set()
        case "int" | "float":
            return 0
        case "bool":
            return False
        case "str":
            return ""
        case _:
            return None


def coerce_value(value: Any, kind: str) -> Any:
    """Coerce a value to the expected type.

    Attempts safe conversions (e.g., "42" -> 42 for int).
    Returns the original value if coercion is not possible.

    Args:
        value: The value to coerce.
        kind: Target type name.

    Returns:
        Coerced value, or original if coercion fails.
    """
    if value is None:
        return None

    match kind:
        case "str":
            return str(value) if not isinstance(value, str) else value
        case "int":
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    return value  # leave as-is, validation will catch
            if isinstance(value, float):
                return int(value)
            return value
        case "float":
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    return value
            return value
        case "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    return True
                if value.lower() in ("false", "0", "no"):
                    return False
            if isinstance(value, (int, float)):
                return bool(value)
            return value
        case "set":
            if isinstance(value, set):
                return value
            if isinstance(value, list):
                return set(value)
            return value
        case "list":
            if isinstance(value, list):
                return value
            if isinstance(value, set):
                return list(value)
            return value
        case _:
            return value  # dict, datetime, unknown - no coercion


def type_matches(value: Any, kind: str) -> bool:
    """Check if a value matches the declared type.

    Performs shallow type checking for containers.

    Args:
        value: The value to check.
        kind: Expected type name.

    Returns:
        True if value matches the type, False otherwise.
    """
    match kind:
        case "str":
            return isinstance(value, str)
        case "int":
            return isinstance(value, int) and not isinstance(value, bool)
        case "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case "bool":
            return isinstance(value, bool)
        case "dict":
            return isinstance(value, dict)
        case "list":
            return isinstance(value, list)
        case "set":
            return isinstance(value, (set, list))  # allow list as set input
        case "datetime":
            return isinstance(value, (str, datetime))  # ISO string or datetime
        case _:
            return True  # unknown type, permissive
