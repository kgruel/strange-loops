"""Parse: declarative primitives for transforming raw text into structured data.

Parse vocabulary transforms: string → list → dict

Pipeline composition: each op takes input, produces output.
Applied left to right: [Split(), Pick(0, 2), Rename({0: "a", 1: "b"})]

Operations:
    - Skip: Filter out lines/records (returns None to exclude)
    - Split: Divide text into fields by delimiter
    - Pick: Select specific fields by position
    - Rename: Map positional indices to named keys
    - Transform: String manipulation (strip, replace)
    - Coerce: Type conversion (int, float, bool, str)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Skip:
    """Filter out lines/records from the pipeline.

    Skip returns None (stopping the pipeline) when a condition matches.
    Works on strings (before Split) or dicts (after Rename).

    Attributes:
        startswith: Skip if value starts with this prefix.
        contains: Skip if value contains this substring.
        equals: Skip if value equals this exactly.
        field: For dict input, check this field instead of whole value.
        predicate: Escape hatch — callable returns True to skip.

    Examples:
        Skip(startswith="Filesystem")     # Skip header line
        Skip(contains="System/Volumes")   # Skip system paths
        Skip(field="cpu", equals="0")     # Skip idle processes (string compare)
        Skip(predicate=lambda x: x.get("cpu", 0) == 0)  # Skip where cpu==0 (after Coerce)
    """

    startswith: str | None = None
    contains: str | None = None
    equals: str | None = None
    field: str | None = None
    predicate: Callable[[Any], bool] | None = None


@dataclass(frozen=True)
class Split:
    """Split string into list of fields.

    Attributes:
        delim: Delimiter to split on. None = whitespace (like awk).
        max: Maximum number of splits. None = unlimited.

    Examples:
        Split()                # "a  b  c" → ["a", "b", "c"]
        Split(delim=":")       # "a:b:c" → ["a", "b", "c"]
        Split(delim="=", max=1) # "key=a=b" → ["key", "a=b"]
    """

    delim: str | None = None
    max: int | None = None


@dataclass(frozen=True)
class Pick:
    """Select fields by position from a list.

    Attributes:
        indices: Positions to select (0-indexed).

    Examples:
        Pick(0, 2)    # ["a", "b", "c", "d"] → ["a", "c"]
        Pick(0, -1)   # ["a", "b", "c"] → ["a", "c"]
    """

    indices: tuple[int, ...]

    def __init__(self, *indices: int) -> None:
        object.__setattr__(self, "indices", tuple(indices))


@dataclass(frozen=True)
class Rename:
    """Map positional indices to named keys, producing a dict.

    Attributes:
        mapping: Map from position (0-indexed) to field name.

    Examples:
        Rename({0: "user", 1: "pid"})  # ["alice", "1234"] → {"user": "alice", "pid": "1234"}
    """

    mapping: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Wrap mapping in MappingProxyType for effective immutability."""
        object.__setattr__(self, "mapping", MappingProxyType(dict(self.mapping)))


@dataclass(frozen=True)
class Transform:
    """String manipulation on dict fields.

    Attributes:
        field: The field name to transform.
        strip: Characters to strip from ends. None = no strip.
        replace: Tuple of (old, new) for replacement. None = no replace.
        lstrip: Characters to strip from left. None = no lstrip.
        rstrip: Characters to strip from right. None = no rstrip.

    Examples:
        Transform("pct", strip="%")           # {"pct": "27%"} → {"pct": "27"}
        Transform("size", rstrip="Gi")        # {"size": "123Gi"} → {"size": "123"}
        Transform("path", replace=("//", "/")) # {"path": "a//b"} → {"path": "a/b"}
    """

    field: str
    strip: str | None = None
    replace: tuple[str, str] | None = None
    lstrip: str | None = None
    rstrip: str | None = None


@dataclass(frozen=True)
class Coerce:
    """Type conversion on dict fields.

    Attributes:
        types: Map from field name to target type.
               Types: int, float, bool, str

    Examples:
        Coerce({"count": int})              # {"count": "42"} → {"count": 42}
        Coerce({"pct": int, "size": float}) # Multiple fields
    """

    types: Mapping[str, type] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Wrap types in MappingProxyType for effective immutability."""
        object.__setattr__(self, "types", MappingProxyType(dict(self.types)))


# Type alias for parse operations
ParseOp = Skip | Split | Pick | Rename | Transform | Coerce


def _apply_skip(value: str | dict[str, Any], op: Skip) -> str | dict[str, Any] | None:
    """Apply Skip operation — returns None if the value should be filtered out.

    Skip works on strings (before Split) or dicts (after Rename).
    Returns the value unchanged if not skipped, None if skipped.
    """
    # Predicate takes priority — escape hatch for complex logic
    if op.predicate is not None:
        if op.predicate(value):
            return None
        return value

    # Determine what to check
    if op.field is not None:
        # Field mode: extract field from dict
        if not isinstance(value, dict):
            return None  # Can't access field on non-dict
        if op.field not in value:
            return value  # Field missing — don't skip
        check_value = value[op.field]
    else:
        # Direct mode: check the value itself
        check_value = value

    # Convert to string for comparison
    check_str = str(check_value)

    # Apply filters
    if op.startswith is not None and check_str.startswith(op.startswith):
        return None
    if op.contains is not None and op.contains in check_str:
        return None
    if op.equals is not None and check_str == op.equals:
        return None

    return value


def _apply_split(value: str, op: Split) -> list[str] | None:
    """Apply Split operation to a string."""
    if not isinstance(value, str):
        return None

    if op.delim is None:
        # Whitespace split: collapse runs of whitespace (like awk)
        parts = value.split()
    else:
        if op.max is not None:
            parts = value.split(op.delim, op.max)
        else:
            parts = value.split(op.delim)

    return parts


def _apply_pick(value: list[str], op: Pick) -> list[str] | None:
    """Apply Pick operation to a list."""
    if not isinstance(value, list):
        return None

    result = []
    for idx in op.indices:
        try:
            result.append(value[idx])
        except IndexError:
            return None

    return result


def _apply_rename(value: list[str], op: Rename) -> dict[str, str] | None:
    """Apply Rename operation to a list, producing a dict."""
    if not isinstance(value, list):
        return None

    result = {}
    for idx, name in op.mapping.items():
        try:
            result[name] = value[idx]
        except IndexError:
            return None

    return result


def _apply_transform(value: dict[str, Any], op: Transform) -> dict[str, Any] | None:
    """Apply Transform operation to a dict field."""
    if not isinstance(value, dict):
        return None

    if op.field not in value:
        return None

    field_value = value[op.field]
    if not isinstance(field_value, str):
        return None

    # Apply transforms in order: strip, lstrip, rstrip, replace
    if op.strip is not None:
        field_value = field_value.strip(op.strip)
    if op.lstrip is not None:
        field_value = field_value.lstrip(op.lstrip)
    if op.rstrip is not None:
        field_value = field_value.rstrip(op.rstrip)
    if op.replace is not None:
        old, new = op.replace
        field_value = field_value.replace(old, new)

    # Return new dict with transformed field
    result = dict(value)
    result[op.field] = field_value
    return result


def _coerce_value(value: str, target_type: type) -> Any:
    """Coerce a string value to the target type.

    Returns the coerced value, or raises ValueError on failure.
    """
    if target_type is int:
        return int(value)
    elif target_type is float:
        return float(value)
    elif target_type is bool:
        lower = value.lower()
        if lower in ("true", "1", "yes"):
            return True
        elif lower in ("false", "0", "no"):
            return False
        else:
            raise ValueError(f"Cannot coerce '{value}' to bool")
    elif target_type is str:
        return str(value)
    else:
        raise ValueError(f"Unknown target type: {target_type}")


def _apply_coerce(value: dict[str, Any], op: Coerce) -> dict[str, Any] | None:
    """Apply Coerce operation to dict fields."""
    if not isinstance(value, dict):
        return None

    result = dict(value)
    for field_name, target_type in op.types.items():
        if field_name not in result:
            return None
        try:
            result[field_name] = _coerce_value(result[field_name], target_type)
        except (ValueError, TypeError):
            return None

    return result


def run_parse(line: str, pipeline: list[ParseOp]) -> dict[str, Any] | None:
    """Execute a parse pipeline on a line of text.

    Args:
        line: The input string to parse.
        pipeline: List of parse operations to apply in order.

    Returns:
        The parsed dict, or None if any step fails.

    Examples:
        >>> pipeline = [Split(), Pick(0, 1), Rename({0: "a", 1: "b"})]
        >>> run_parse("hello world", pipeline)
        {'a': 'hello', 'b': 'world'}

        >>> pipeline = [Split(), Pick(0, 99)]  # Index out of range
        >>> run_parse("hello world", pipeline)
        None
    """
    if not pipeline:
        return None

    value: Any = line

    for op in pipeline:
        if isinstance(op, Skip):
            value = _apply_skip(value, op)
        elif isinstance(op, Split):
            value = _apply_split(value, op)
        elif isinstance(op, Pick):
            value = _apply_pick(value, op)
        elif isinstance(op, Rename):
            value = _apply_rename(value, op)
        elif isinstance(op, Transform):
            value = _apply_transform(value, op)
        elif isinstance(op, Coerce):
            value = _apply_coerce(value, op)
        else:
            return None

        if value is None:
            return None

    # Final result must be a dict
    if not isinstance(value, dict):
        return None

    return value
