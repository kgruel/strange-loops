"""Migration sidecar refusals and exception hierarchy.

All refusals in the migration sidecar root in :class:`MigrationRefused`.
This hierarchy is strictly distinct from ``ArrivalBodyError`` and
``ContractRefusal``:
- It represents sidecar-specific assertions about legacy source contents
  prior to target admission, or sink/publish preconditions.
- Exception types make location claims about what the source carries or lacks,
  and do not encode or promise remedies in their types or docstrings.
- Advisory prose naming operator options is carried in the exception message.
"""

from __future__ import annotations

__all__ = [
    "MigrationRefused",
    "LegacySourceRefused",
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

    Asserts conditions in a legacy source or staging pipeline that prevent
    deterministic transformation and publication of an Arrival lineage.
    """


class LegacySourceRefused(MigrationRefused):
    """Source contains defects (codec-invalid, mixed-observer, or absent-observer lines).

    Carries structured data across all three enumerated legacy defect classes.
    """

    def __init__(
        self,
        *,
        codec_invalid_lines: tuple[tuple[int, str], ...] | list[tuple[int, str]] = (),
        mixed_observer_lines: (
            tuple[tuple[int, tuple[str, ...], int], ...]
            | list[tuple[int, tuple[str, ...], int]]
        ) = (),
        absent_observer_lines: (
            tuple[tuple[int, int, tuple[str, ...]], ...]
            | list[tuple[int, int, tuple[str, ...]]]
        ) = (),
        source: str | None = None,
    ) -> None:
        self.source = source
        self.codec_invalid_lines: tuple[tuple[int, str], ...] = tuple(
            (int(lineno), str(msg)) for lineno, msg in codec_invalid_lines
        )
        self.mixed_observer_lines: tuple[tuple[int, tuple[str, ...], int], ...] = tuple(
            (int(lineno), tuple(str(o) for o in observers), int(absent_count))
            for lineno, observers, absent_count in mixed_observer_lines
        )
        self.absent_observer_lines: tuple[tuple[int, int, tuple[str, ...]], ...] = tuple(
            (int(lineno), int(absent_count), tuple(str(o) for o in observers))
            for lineno, absent_count, observers in absent_observer_lines
        )
        message = _format_refusal_message(
            source=self.source,
            codec_invalid_lines=self.codec_invalid_lines,
            mixed_observer_lines=self.mixed_observer_lines,
            absent_observer_lines=self.absent_observer_lines,
        )
        super().__init__(message)

