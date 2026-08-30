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
    "BatchRegroupRefused",
    "DeclarationKeyRefused",
    "MissingCustodianKeyRefused",
    "JournalPreflightRefused",
    "TargetMismatchOnResumeRefused",
    "TornTailRefused",
    "PublishPreconditionRefused",
    "SourceChangedRefused",
    "LegacyStorageRefused",
]


def _format_refusal_message(
    *,
    source: str | None,
    codec_invalid_lines: tuple[tuple[int, str], ...],
    mixed_observer_lines: tuple[tuple[int, tuple[str, ...], int], ...],
    absent_observer_lines: tuple[tuple[int, int, tuple[str, ...], dict[str, int]], ...],
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
        for lineno, absent_count, observers, spelling_map in absent_observer_lines:
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
            tuple[tuple[int, int, tuple[str, ...], dict[str, int]], ...]
            | list[tuple[int, int, tuple[str, ...], dict[str, int]]]
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
        self.absent_observer_lines: tuple[
            tuple[int, int, tuple[str, ...], dict[str, int]], ...
        ] = tuple(
            (
                int(lineno),
                int(absent_count),
                tuple(str(o) for o in observers),
                dict(spellings),
            )
            for lineno, absent_count, observers, spellings in absent_observer_lines
        )
        message = _format_refusal_message(
            source=self.source,
            codec_invalid_lines=self.codec_invalid_lines,
            mixed_observer_lines=self.mixed_observer_lines,
            absent_observer_lines=self.absent_observer_lines,
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


class JournalPreflightRefused(MigrationRefused):
    """Journal directory or state root is not accessible or writable.

    Asserts that the journal state root or heads directory cannot be probed
    prior to minting genesis.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class TargetMismatchOnResumeRefused(MigrationRefused):
    """Target log on resume does not match the deterministic transform prefix.

    Asserts that records present in the resume target diverge from the
    expected deterministic transform of the source.
    """

    def __init__(
        self,
        message: str,
        *,
        target_path: str | None = None,
        ordinal: int | None = None,
    ) -> None:
        self.target_path = target_path
        self.ordinal = ordinal
        super().__init__(message)


class TornTailRefused(MigrationRefused):
    """Target log on resume ends with a torn tail or incomplete record.

    Asserts that the resume target file ends mid-record and cannot be opened
    safely under the contract.
    """

    def __init__(self, message: str, *, target_path: str | None = None) -> None:
        self.target_path = target_path
        super().__init__(message)


class PublishPreconditionRefused(MigrationRefused):
    """A required precondition for descriptor publication was not met.

    Asserts failure of target verification, equivalence re-run, bootstrap
    witness receipt verification, inventory equality, or source quiescence.
    """

    def __init__(self, message: str, *, condition: str | None = None) -> None:
        self.condition = condition
        super().__init__(message)


class SourceChangedRefused(PublishPreconditionRefused):
    """Source store content hash changed between snapshot and descriptor publish.

    Asserts that the legacy source was modified during staging, violating
    the quiescence precondition (two histories, not a migration).
    """

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ) -> None:
        self.source = source
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(message, condition="source_unchanged")


class LegacyStorageRefused(MigrationRefused):
    """Storage-level error encountered while reading legacy source store.

    Asserts that the underlying storage (e.g. SQLite database schema or file)
    failed at the database/filesystem level.
    """

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(message)

