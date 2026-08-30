"""Migration sidecar refusals and exception hierarchy.

All refusals in the migration sidecar root in :class:`MigrationRefused`.
This hierarchy is strictly distinct from ``ArrivalBodyError`` and
``ContractRefusal``:
- It represents sidecar-specific assertions about legacy source contents
  prior to target admission.
- Exception types make location claims about what the source carries or lacks,
  and do not encode or promise remedies in their types or docstrings.
- Advisory prose naming operator options is carried in the exception message.
"""

from __future__ import annotations

__all__ = [
    "MigrationRefused",
    "MixedObserverBatchRefused",
    "AbsentObserverBatchRefused",
    "MissingObserverBatchRefused",
]


class MigrationRefused(Exception):
    """Root exception for migration sidecar refusals.

    Asserts a condition in a legacy source that prevents deterministic
    transformation into an Arrival lineage.
    """


class MixedObserverBatchRefused(MigrationRefused):
    """Source lines carry batch rows from more than one observer, which this
    transformer cannot map to one record."""

    def __init__(
        self,
        offending_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
        ),
        *,
        source: str | None = None,
    ) -> None:
        self.offending_lines: tuple[tuple[int, tuple[str, ...]], ...] = tuple(
            (int(lineno), tuple(str(o) for o in observers))
            for lineno, observers in offending_lines
        )
        self.source = source

        enumeration = "\n".join(
            f"  line {lineno}: observers {', '.join(repr(o) for o in observers)}"
            for lineno, observers in self.offending_lines
        )
        source_prefix = f"for source {source!r} " if source else ""
        message = (
            f"Migration refused {source_prefix}(GF-3: mixed-observer batch lines found).\n"
            "The following source line(s) carry batch rows spanning more than one observer, "
            "which cannot map to a single Arrival record:\n"
            f"{enumeration}\n"
            "Advisory: repair the source line(s) by hand or re-run migration "
            "after a ruled re-ceremony."
        )
        super().__init__(message)


class AbsentObserverBatchRefused(MigrationRefused):
    """Source lines carry batch rows missing the required 'observer' field."""

    def __init__(
        self,
        offending_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
        ),
        *,
        source: str | None = None,
    ) -> None:
        self.offending_lines: tuple[tuple[int, tuple[str, ...]], ...] = tuple(
            (int(lineno), tuple(str(o) for o in observers))
            for lineno, observers in offending_lines
        )
        self.source = source

        enumeration = "\n".join(
            f"  line {lineno}: missing observer field"
            + (f" (found observers: {', '.join(repr(o) for o in observers)})" if observers else "")
            for lineno, observers in self.offending_lines
        )
        source_prefix = f"for source {source!r} " if source else ""
        message = (
            f"Migration refused {source_prefix}(batch rows missing observer field).\n"
            "The following source line(s) carry batch rows missing the required 'observer' field:\n"
            f"{enumeration}\n"
            "Advisory: repair the source line(s) by hand to include valid author observers "
            "or re-run migration after a ruled re-ceremony."
        )
        super().__init__(message)


# Alias for backward/naming symmetry
MissingObserverBatchRefused = AbsentObserverBatchRefused
