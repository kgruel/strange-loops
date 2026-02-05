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


@dataclass(frozen=True)
class Select:
    """Select specific fields from a dict.

    Use with ndjson format to extract only the fields you need.

    Attributes:
        fields: Field names to keep.

    Examples:
        Select("Name", "State", "Health")  # {"Name": "x", "State": "running", "Other": "..."} → {"Name": "x", "State": "running"}
    """

    fields: tuple[str, ...]

    def __init__(self, *fields: str) -> None:
        object.__setattr__(self, "fields", tuple(fields))


@dataclass(frozen=True)
class Explode:
    """Fan-out: evaluate a path on a dict, produce N records (one per list element).

    Attributes:
        path: Dot-separated path to a list value (e.g. "data.alerts").
        carry: Optional dict mapping parent field → child field name.
               Copies parent fields into each exploded child.

    Examples:
        Explode(path="data.alerts")
        Explode(path="data.groups", carry={"name": "group_name"})
    """

    path: str
    carry: dict[str, str] | None = None


@dataclass(frozen=True)
class Project:
    """Field mapping with nested JSON paths. Produces a dict with exactly the declared fields.

    Attributes:
        fields: Dict mapping output field name → dot-separated source path.

    Examples:
        Project(fields={"alertname": "labels.alertname", "state": "state"})
    """

    fields: dict[str, str]


@dataclass(frozen=True)
class Where:
    """Record filter by field value comparison.

    Attributes:
        path: Dot-separated path to the value to check.
        op: Comparison operation (equals, not_equals, exists).
        value: Value to compare against (ignored for exists).

    Examples:
        Where(path="status", op="equals", value="success")
        Where(path="type", op="not_equals", value="recording")
        Where(path="labels", op="exists")
    """

    path: str
    op: str = "equals"
    value: str | None = None


# Type alias for parse operations
ParseOp = Skip | Split | Pick | Rename | Transform | Coerce | Select | Explode | Project | Where


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


def _apply_select(value: dict[str, Any], op: Select) -> dict[str, Any] | None:
    """Apply Select operation to pick fields from a dict."""
    if not isinstance(value, dict):
        return None

    result = {}
    for field_name in op.fields:
        if field_name in value:
            result[field_name] = value[field_name]
        # Missing fields are silently omitted (not an error)

    return result if result else None


def resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a dot-separated path against a dict.

    Examples:
        resolve_path({"a": {"b": 1}}, "a.b") → 1
        resolve_path({"a": 1}, "a.b") → None
    """
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _apply_where(value: dict[str, Any], op: Where) -> dict[str, Any] | None:
    """Apply Where filter. Returns value if it passes, None if filtered out."""
    if not isinstance(value, dict):
        return None

    resolved = resolve_path(value, op.path)

    if op.op == "exists":
        return value if resolved is not None else None
    elif op.op == "equals":
        return value if str(resolved) == op.value else None
    elif op.op == "not_equals":
        return value if str(resolved) != op.value else None
    else:
        return None


def _apply_explode(value: dict[str, Any], op: Explode) -> list[dict[str, Any]]:
    """Apply Explode: fan-out a list field into multiple records."""
    resolved = resolve_path(value, op.path)
    if not isinstance(resolved, list):
        return [value]  # Not a list — pass through as single record

    results = []
    for item in resolved:
        if isinstance(item, dict):
            record = dict(item)
        else:
            record = {"_value": item}

        if op.carry:
            for src_field, dst_field in op.carry.items():
                parent_val = resolve_path(value, src_field)
                if parent_val is not None:
                    record[dst_field] = parent_val

        results.append(record)

    return results


def _apply_project(value: dict[str, Any], op: Project) -> dict[str, Any]:
    """Apply Project: extract fields by path into a new dict."""
    result = {}
    for out_name, src_path in op.fields.items():
        result[out_name] = resolve_path(value, src_path)
    return result


def run_parse_many(
    data: dict[str, Any], pipeline: list[ParseOp]
) -> list[dict[str, Any]]:
    """Execute a parse pipeline in stream mode, returning multiple records.

    Each step transforms list[record] → list[record].
    Explode fans out (1 → N), Where filters (N → ≤N), Project reshapes (1:1).
    """
    records: list[dict[str, Any]] = [data]

    for op in pipeline:
        next_records: list[dict[str, Any]] = []
        for record in records:
            if isinstance(op, Where):
                result = _apply_where(record, op)
                if result is not None:
                    next_records.append(result)
            elif isinstance(op, Explode):
                next_records.extend(_apply_explode(record, op))
            elif isinstance(op, Project):
                next_records.append(_apply_project(record, op))
            elif isinstance(op, Select):
                result = _apply_select(record, op)
                if result is not None:
                    next_records.append(result)
            else:
                # Delegate to single-record ops
                result = _apply_single_op(record, op)
                if result is not None:
                    next_records.append(result)
        records = next_records

    return records


def _apply_single_op(value: Any, op: ParseOp) -> Any:
    """Apply a single-record parse op (non-stream ops)."""
    if isinstance(op, Skip):
        return _apply_skip(value, op)
    elif isinstance(op, Split):
        return _apply_split(value, op)
    elif isinstance(op, Pick):
        return _apply_pick(value, op)
    elif isinstance(op, Rename):
        return _apply_rename(value, op)
    elif isinstance(op, Transform):
        return _apply_transform(value, op)
    elif isinstance(op, Coerce):
        return _apply_coerce(value, op)
    elif isinstance(op, Select):
        return _apply_select(value, op)
    return None


def has_explode(pipeline: list[ParseOp]) -> bool:
    """Check if a pipeline contains any Explode ops."""
    return any(isinstance(op, Explode) for op in pipeline)


def run_parse(
    data: str | dict[str, Any], pipeline: list[ParseOp]
) -> dict[str, Any] | None:
    """Execute a parse pipeline on input data.

    Args:
        data: The input to parse — string (from lines format) or dict (from json/ndjson).
        pipeline: List of parse operations to apply in order.

    Returns:
        The parsed dict, or None if any step fails.

    Examples:
        >>> pipeline = [Split(), Pick(0, 1), Rename({0: "a", 1: "b"})]
        >>> run_parse("hello world", pipeline)
        {'a': 'hello', 'b': 'world'}

        >>> pipeline = [Select("Name", "State")]
        >>> run_parse({"Name": "x", "State": "running", "Other": "y"}, pipeline)
        {'Name': 'x', 'State': 'running'}
    """
    if not pipeline:
        # No pipeline — return dict as-is, or wrap string in {"line": ...}
        if isinstance(data, dict):
            return data
        return None

    value: Any = data

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
        elif isinstance(op, Select):
            value = _apply_select(value, op)
        elif isinstance(op, Where):
            value = _apply_where(value, op)
        elif isinstance(op, Project):
            if isinstance(value, dict):
                value = _apply_project(value, op)
            else:
                return None
        elif isinstance(op, Explode):
            # In single-record mode, explode returns first element only
            if isinstance(value, dict):
                results = _apply_explode(value, op)
                value = results[0] if results else None
            else:
                return None
        else:
            return None

        if value is None:
            return None

    # Final result must be a dict
    if not isinstance(value, dict):
        return None

    return value
