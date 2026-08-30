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


def _format_refusal_message(
    *,
    source: str | None,
    codec_invalid_lines: tuple[tuple[int, str], ...],
    mixed_observer_lines: tuple[tuple[int, tuple[str, ...], int], ...],
    absent_observer_lines: tuple[tuple[int, int, tuple[str, ...]], ...],
) -> str:
    source_prefix = f"for source {source!r} " if source else ""
    sections: list[str] = []

    if codec_invalid_lines:
        enum_codec = "\n".join(
            f"  line {lineno}: {msg}"
            for lineno, msg in codec_invalid_lines
        )
        sections.append(
            "The following source line(s) failed codec validation:\n"
            f"{enum_codec}"
        )

    if mixed_observer_lines:
        enum_mixed = "\n".join(
            f"  line {lineno}: observers {', '.join(repr(o) for o in observers)}"
            + (f" ({absent_count} row(s) missing 'observer' field)" if absent_count > 0 else "")
            for lineno, observers, absent_count in mixed_observer_lines
        )
        sections.append(
            "The following source line(s) carry batch rows spanning more than one observer "
            "(GF-3 violation), which cannot map to a single Arrival record:\n"
            f"{enum_mixed}"
        )

    if absent_observer_lines:
        enum_absent = "\n".join(
            f"  line {lineno}: {absent_count} row(s) missing 'observer' field"
            + (f" (remaining observers: {', '.join(repr(o) for o in observers)})" if observers else "")
            for lineno, absent_count, observers in absent_observer_lines
        )
        sections.append(
            "The following source line(s) carry batch rows missing the required 'observer' field:\n"
            f"{enum_absent}"
        )

    body = "\n\n".join(sections)
    return (
        f"Migration refused {source_prefix}(legacy source defects found).\n"
        f"{body}\n"
        "Advisory: repair the source line(s) by hand or re-run migration after a ruled re-ceremony."
    )


class MigrationRefused(Exception):
    """Root exception for migration sidecar refusals.

    Asserts conditions in a legacy source that prevent deterministic
    transformation into an Arrival lineage.
    """

    def __init__(
        self,
        *,
        codec_invalid_lines: (
            tuple[tuple[int, str], ...]
            | list[tuple[int, str]]
            | None
        ) = None,
        mixed_observer_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...], int], ...]
            | list[tuple[int, tuple[str, ...], int]]
            | None
        ) = None,
        absent_observer_lines: (
            tuple[tuple[int, int, tuple[str, ...]], ...]
            | list[tuple[int, int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | None
        ) = None,
        source: str | None = None,
    ) -> None:
        self.source = source

        raw_codec = codec_invalid_lines or ()
        self.codec_invalid_lines: tuple[tuple[int, str], ...] = tuple(
            (int(lineno), str(msg)) for lineno, msg in raw_codec
        )

        raw_mixed = mixed_observer_lines or ()
        normalized_mixed: list[tuple[int, tuple[str, ...], int]] = []
        for item in raw_mixed:
            lineno = int(item[0])
            observers = tuple(str(o) for o in item[1])
            absent_count = int(item[2]) if len(item) > 2 else 0
            normalized_mixed.append((lineno, observers, absent_count))
        self.mixed_observer_lines: tuple[tuple[int, tuple[str, ...], int], ...] = tuple(
            normalized_mixed
        )

        raw_absent = absent_observer_lines or ()
        normalized_absent: list[tuple[int, int, tuple[str, ...]]] = []
        for item in raw_absent:
            lineno = int(item[0])
            if len(item) >= 3:
                absent_count = int(item[1])
                observers = tuple(str(o) for o in item[2])
            else:
                absent_count = 1
                observers = tuple(str(o) for o in item[1])
            normalized_absent.append((lineno, absent_count, observers))
        self.absent_observer_lines: tuple[tuple[int, int, tuple[str, ...]], ...] = tuple(
            normalized_absent
        )

        message = _format_refusal_message(
            source=self.source,
            codec_invalid_lines=self.codec_invalid_lines,
            mixed_observer_lines=self.mixed_observer_lines,
            absent_observer_lines=self.absent_observer_lines,
        )
        super().__init__(message)


class MixedObserverBatchRefused(MigrationRefused):
    """Source lines carry batch rows from more than one observer, which this
    transformer cannot map to one record."""

    def __init__(
        self,
        offending_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...], int], ...]
            | list[tuple[int, tuple[str, ...], int]]
            | None
        ) = None,
        *,
        mixed_observer_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...], int], ...]
            | list[tuple[int, tuple[str, ...], int]]
            | None
        ) = None,
        codec_invalid_lines: (
            tuple[tuple[int, str], ...]
            | list[tuple[int, str]]
            | None
        ) = None,
        absent_observer_lines: (
            tuple[tuple[int, int, tuple[str, ...]], ...]
            | list[tuple[int, int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | None
        ) = None,
        source: str | None = None,
    ) -> None:
        mixed = mixed_observer_lines if mixed_observer_lines is not None else offending_lines
        super().__init__(
            codec_invalid_lines=codec_invalid_lines,
            mixed_observer_lines=mixed,
            absent_observer_lines=absent_observer_lines,
            source=source,
        )
        compat_lines: list[tuple[int, tuple[str, ...]] | tuple[int, tuple[str, ...], int]] = []
        for lineno, observers, absent_count in self.mixed_observer_lines:
            if absent_count == 0:
                compat_lines.append((lineno, observers))
            else:
                compat_lines.append((lineno, observers, absent_count))
        self.offending_lines: tuple[
            tuple[int, tuple[str, ...]] | tuple[int, tuple[str, ...], int], ...
        ] = tuple(compat_lines)


class AbsentObserverBatchRefused(MigrationRefused):
    """Source lines carry batch rows missing the required 'observer' field."""

    def __init__(
        self,
        offending_lines: (
            tuple[tuple[int, int, tuple[str, ...]], ...]
            | list[tuple[int, int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | None
        ) = None,
        *,
        absent_observer_lines: (
            tuple[tuple[int, int, tuple[str, ...]], ...]
            | list[tuple[int, int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | None
        ) = None,
        codec_invalid_lines: (
            tuple[tuple[int, str], ...]
            | list[tuple[int, str]]
            | None
        ) = None,
        mixed_observer_lines: (
            tuple[tuple[int, tuple[str, ...]], ...]
            | list[tuple[int, tuple[str, ...]]]
            | tuple[tuple[int, tuple[str, ...], int], ...]
            | list[tuple[int, tuple[str, ...], int]]
            | None
        ) = None,
        source: str | None = None,
    ) -> None:
        absent = absent_observer_lines if absent_observer_lines is not None else offending_lines
        super().__init__(
            codec_invalid_lines=codec_invalid_lines,
            mixed_observer_lines=mixed_observer_lines,
            absent_observer_lines=absent,
            source=source,
        )
        self.offending_lines: tuple[tuple[int, int, tuple[str, ...]], ...] = (
            self.absent_observer_lines
        )


# Alias for backward/naming symmetry
MissingObserverBatchRefused = AbsentObserverBatchRefused
