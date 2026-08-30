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

from typing import Any

__all__ = [
    "MigrationRefused",
    "LegacySourceRefused",
    "BatchRegroupRefused",
    "DeclarationKeyRefused",
    "MissingCustodianKeyRefused",
]


def _format_refusal_message(
    *,
    source: str | None,
    codec_invalid_lines: tuple[tuple[int, str], ...],
    mixed_observer_lines: tuple[tuple[int, tuple[str, ...], int], ...],
    absent_observer_lines: tuple[tuple[int, int, tuple[str, ...]], ...],
    absent_observer_spellings: dict[int, dict[str, int]] | None = None,
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
        formatted_absent: list[str] = []
        for lineno, absent_count, observers in absent_observer_lines:
            spelling_map = (absent_observer_spellings or {}).get(lineno, {})
            empty_cnt = spelling_map.get("empty", 0)
            missing_cnt = spelling_map.get("missing", 0)

            if empty_cnt > 0 and missing_cnt == 0:
                desc = f"{absent_count} row(s) with observer='' (empty string)"
            elif missing_cnt > 0 and empty_cnt == 0:
                desc = f"{absent_count} row(s) missing 'observer' field"
            elif empty_cnt > 0 and missing_cnt > 0:
                desc = f"{absent_count} row(s) with absent/empty observer ({missing_cnt} missing, {empty_cnt} empty '')"
            else:
                desc = f"{absent_count} row(s) missing 'observer' field"

            rem = f" (remaining observers: {', '.join(repr(o) for o in observers)})" if observers else ""
            formatted_absent.append(f"  line {lineno}: {desc}{rem}")

        enum_absent = "\n".join(formatted_absent)
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
            tuple[Any, ...]
            | list[Any]
        ) = (),
        absent_observer_spellings: dict[int, dict[str, int]] | None = None,
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

        norm_absent: list[tuple[int, int, tuple[str, ...]]] = []
        spellings = dict(absent_observer_spellings or {})
        for item in absent_observer_lines:
            lineno = int(item[0])
            count = int(item[1])
            obs = tuple(str(o) for o in item[2]) if len(item) > 2 else ()
            if len(item) > 3 and isinstance(item[3], dict):
                spellings[lineno] = item[3]
            norm_absent.append((lineno, count, obs))

        self.absent_observer_lines: tuple[tuple[int, int, tuple[str, ...]], ...] = tuple(norm_absent)
        self.absent_observer_spellings: dict[int, dict[str, int]] = spellings
        message = _format_refusal_message(
            source=self.source,
            codec_invalid_lines=self.codec_invalid_lines,
            mixed_observer_lines=self.mixed_observer_lines,
            absent_observer_lines=self.absent_observer_lines,
            absent_observer_spellings=self.absent_observer_spellings,
        )
        super().__init__(message)


class BatchRegroupRefused(MigrationRefused):
    """Transform rule dropped some but not all rows of a batch group.

    Refused because the sidecar cannot re-decide a ceremony's composition.
    """


class DeclarationKeyRefused(MigrationRefused):
    """A declared observer key has an invalid key shape."""


class MissingCustodianKeyRefused(MigrationRefused):
    """The custodian observer has no public key declared in .vertex."""

