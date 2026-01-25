"""Spec-driven projections from KDL declarations.

Parses .projection.kdl files into ProjectionSpec, then instantiates
Projection instances with fold functions built from declarative ops.

Fold ops:
  - latest "field"           → state[field] = event value (or timestamp)
  - collect "field" max=N    → append to bounded list
  - count "field"            → increment counter
  - upsert "field" key=K     → update-or-insert into dict (or add to set)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kdl
from rill import Projection


@dataclass(frozen=True)
class FieldSpec:
    """A typed field in an event or state block."""
    name: str
    type: str  # str, int, float, bool, dict, list, set, datetime
    optional: bool = False

    @classmethod
    def from_type_str(cls, name: str, type_str: str) -> FieldSpec:
        if type_str.endswith("?"):
            return cls(name=name, type=type_str[:-1], optional=True)
        return cls(name=name, type=type_str, optional=False)


@dataclass(frozen=True)
class FoldOp:
    """A single fold operation."""
    op: str  # latest, collect, count, upsert
    target: str  # state field name
    props: dict[str, Any] = field(default_factory=dict)  # key=, max=, etc.


class ValidationError(Exception):
    """Raised when event validation fails."""
    pass


@dataclass(frozen=True)
class EventSpec:
    """Declares the shape of incoming events."""
    name: str
    fields: tuple[FieldSpec, ...]

    def validate(self, event: dict) -> None:
        """Validate event dict against spec. Raises ValidationError on mismatch.

        Permissive: unknown fields are ignored, only declared fields are checked.
        """
        for field in self.fields:
            # Required field missing?
            if not field.optional and field.name not in event:
                raise ValidationError(
                    f"missing required field '{field.name}' in event '{self.name}'"
                )

            # Type check if field present and not None
            if field.name in event:
                value = event[field.name]
                if value is not None and not _type_matches(value, field.type):
                    raise ValidationError(
                        f"field '{field.name}' expected {field.type}, "
                        f"got {type(value).__name__} in event '{self.name}'"
                    )


@dataclass(frozen=True)
class ProjectionSpec:
    """Parsed projection specification."""
    name: str
    about: str
    events: tuple[EventSpec, ...]
    state_fields: tuple[FieldSpec, ...]
    fold_ops: tuple[FoldOp, ...]

    def initial_state(self) -> dict[str, Any]:
        """Create the initial state dict from field declarations."""
        state: dict[str, Any] = {}
        for f in self.state_fields:
            state[f.name] = _initial_value(f.type)
        return state

    def event(self, name: str) -> EventSpec:
        """Look up an event spec by name. Raises KeyError if not found."""
        for e in self.events:
            if e.name == name:
                return e
        raise KeyError(f"no event '{name}' in projection '{self.name}'")


def _type_matches(value: Any, type_str: str) -> bool:
    """Check if value matches declared type. Shallow check for containers."""
    match type_str:
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


def _initial_value(type_str: str) -> Any:
    """Default initial value for a state field type."""
    match type_str:
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


def parse_projection_spec(path: Path) -> ProjectionSpec:
    """Parse a .projection.kdl file into a ProjectionSpec."""
    doc = kdl.parse(path.read_text())

    name = ""
    about = ""
    events: list[EventSpec] = []
    state_fields: list[FieldSpec] = []
    fold_ops: list[FoldOp] = []

    # Top-level should be a single `projection` node
    for node in doc.nodes:
        if node.name == "projection":
            name = str(node.args[0]) if node.args else ""
            for child in node.nodes or []:
                if child.name == "about":
                    about = str(child.args[0]) if child.args else ""
                elif child.name == "event":
                    events.append(_parse_event(child))
                elif child.name == "state":
                    state_fields = _parse_fields(child)
                elif child.name == "fold":
                    fold_ops = _parse_fold(child)

    if not name:
        raise ValueError(f"Missing projection name in {path}")

    return ProjectionSpec(
        name=name,
        about=about,
        events=tuple(events),
        state_fields=tuple(state_fields),
        fold_ops=tuple(fold_ops),
    )


def _parse_event(node: kdl.Node) -> EventSpec:
    name = str(node.args[0]) if node.args else ""
    fields = _parse_fields(node)
    return EventSpec(name=name, fields=tuple(fields))


def _parse_fields(node: kdl.Node) -> list[FieldSpec]:
    fields: list[FieldSpec] = []
    for child in node.nodes or []:
        field_name = child.name
        field_type = str(child.args[0]) if child.args else "str"
        fields.append(FieldSpec.from_type_str(field_name, field_type))
    return fields


def _parse_fold(node: kdl.Node) -> list[FoldOp]:
    ops: list[FoldOp] = []
    for child in node.nodes or []:
        op_name = child.name
        target = str(child.args[0]) if child.args else ""
        props = {k: v for k, v in child.props.items()}
        ops.append(FoldOp(op=op_name, target=target, props=props))
    return ops


class SpecProjection(Projection[dict[str, Any], dict[str, Any]]):
    """A Projection instantiated from a ProjectionSpec.

    The fold function is built from the spec's fold ops.
    """

    def __init__(self, spec: ProjectionSpec):
        super().__init__(spec.initial_state())
        self.spec = spec
        self._fold_fns = [_build_fold_fn(op, spec) for op in spec.fold_ops]

    @property
    def name(self) -> str:
        return self.spec.name

    def apply(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        """Apply all fold ops to produce new state."""
        # Shallow copy — fold ops mutate their target fields
        new_state = dict(state)
        for fn in self._fold_fns:
            fn(new_state, event)
        return new_state


def _build_fold_fn(op: FoldOp, spec: ProjectionSpec):
    """Build a callable (state, event) -> None for a fold op."""
    target = op.target

    # Find the state field type for this target
    state_type = "dict"  # default
    for f in spec.state_fields:
        if f.name == target:
            state_type = f.type
            break

    match op.op:
        case "latest":
            return _make_latest(target)
        case "collect":
            max_size = int(op.props.get("max", 0))
            return _make_collect(target, max_size)
        case "count":
            return _make_count(target)
        case "upsert":
            key_field = str(op.props.get("key", ""))
            if not key_field:
                raise ValueError(f"upsert op requires key= prop (target: {target})")
            return _make_upsert(target, key_field, state_type)
        case _:
            raise ValueError(f"Unknown fold op: {op.op}")


def _make_latest(target: str):
    """state[target] = event timestamp or current time."""
    def fold(state: dict, event: dict) -> None:
        state[target] = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
    return fold


def _make_collect(target: str, max_size: int):
    """Append event to state[target] list, bounded."""
    def fold(state: dict, event: dict) -> None:
        items = state[target]
        items.append(event)
        if max_size and len(items) > max_size:
            state[target] = items[-max_size:]
    return fold


def _make_count(target: str):
    """Increment state[target]."""
    def fold(state: dict, event: dict) -> None:
        state[target] = state.get(target, 0) + 1
    return fold


def _make_upsert(target: str, key_field: str, state_type: str):
    """Insert/update in dict, or add to set."""
    if state_type == "set":
        def fold(state: dict, event: dict) -> None:
            key_value = event.get(key_field)
            if key_value is not None:
                state[target].add(key_value)
        return fold
    else:
        # dict: key → event data
        def fold(state: dict, event: dict) -> None:
            key_value = event.get(key_field)
            if key_value is not None:
                state[target][key_value] = event
        return fold
