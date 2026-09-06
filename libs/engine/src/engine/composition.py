"""Pure fold-spec composition shared by legacy and bounded aggregate readers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class ConflictingFoldSpec(Exception):
    """Two selected definitions assign incompatible folds to one kind."""

    def __init__(self, kind: str, source_a: str, source_b: str) -> None:
        self.kind = kind
        super().__init__(
            f"Conflicting fold spec for '{kind}' from '{source_a}' and '{source_b}'. "
            f"Add an explicit '{kind}' declaration to the aggregation vertex to resolve."
        )


def specs_match(a: Any, b: Any) -> bool:
    """Whether two runtime specs have the same fold-relevant declarations."""
    if len(a.folds) != len(b.folds):
        return False
    for left, right in zip(a.folds, b.folds, strict=True):
        if type(left) is not type(right):
            return False
        if hasattr(left, "key") and left.key != right.key:
            return False
        if hasattr(left, "limit") and left.limit != right.limit:
            return False
    return True


def merge_fold_specs(
    sources: Sequence[tuple[str, Mapping[str, Any]]], *, override_kinds: frozenset[str]
) -> dict[str, Any]:
    """Merge inherited specs, preserving the legacy conflict/override rule."""
    merged: dict[str, Any] = {}
    source_of: dict[str, str] = {}
    for source_name, specs in sources:
        for kind, spec in specs.items():
            existing = merged.get(kind)
            if existing is None:
                merged[kind] = spec
                source_of[kind] = source_name
            elif kind not in override_kinds and not specs_match(existing, spec):
                raise ConflictingFoldSpec(kind, source_of[kind], source_name)
    return merged
