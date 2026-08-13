"""preflight — canonical agreement as an explicit, typed read preparation.

The JSONL doctrine says the cheap agreement gate (:func:`engine.
canonical_audit.audit_agreement`) precedes every store read verb. But the
primitive alone leaves each client to compose "audit, then maybe open" by
hand — and the easy mistake is opening FIRST: :class:`~engine.jsonl_store.
JsonlStore.__init__` repairs (catch-up, torn-line truncation, rebuild), so
an open-before-audit erases the very evidence the audit exists to inspect.

:func:`read_preflight` makes the composition explicit, with three modes
that never blur into each other:

``AUDIT_ONLY``
    Verify and report. Never constructs a store, never repairs — a damaged
    store comes back as typed damage with all evidence intact.

``AUDIT_THEN_OPEN``
    Verify; open ONLY if the audit passed. A failing audit refuses to
    open. NOTE the deliberate consequence: a fresh clone (log tracked,
    derived index absent) is a REFUSAL here, because materializing the
    index is repair by definition. That is not a bug — it is the mode
    contract. The sanctioned path for "build/repair whatever is needed and
    open" is ``RECOVER_THEN_OPEN``.

``RECOVER_THEN_OPEN``
    Audit first (the pre-repair evidence is captured in the result), then
    open — letting the store's own open-time recovery run — then audit
    again to report the post-recovery state. Recovery happens ONLY in this
    mode, and even here some damage refuses: out-of-band index rows raise
    :class:`~engine.jsonl_store.JsonlCanonicalUnsupported` at open (the
    log cannot account for them), and the result says ``refused``, typed
    distinctly from ``recovered``.

Verification is never silently conflated with repair: repair happens in
exactly one mode, is always preceded by an evidentiary audit, and is always
reported as having happened.

A sqlite-canonical target has no log/index pair to audit, so agreement is
vacuous: ``agreed=True`` with a reason saying so, and the open modes open
via :func:`engine.jsonl_store.open_canonical_store` as usual. (Chain/content
verification of a sqlite store is ``verify_chain``'s scope, not this gate's.)

The result is typed for exit-code mapping: :attr:`PreflightResult.status`
is a small closed vocabulary (``PREFLIGHT_STATUSES``) a CLI can map
directly; no integers are baked in here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .canonical_audit import AgreementReport, audit_agreement
from .residence import index_path_for, is_jsonl_canonical

__all__ = [
    "PREFLIGHT_STATUSES",
    "PreflightMode",
    "PreflightResult",
    "read_preflight",
]


class PreflightMode(Enum):
    """The three read-preparation contracts. See the module docstring."""

    AUDIT_ONLY = "audit-only"
    AUDIT_THEN_OPEN = "audit-then-open"
    RECOVER_THEN_OPEN = "recover-then-open"


#: The closed status vocabulary, in rough order of severity. A CLI maps
#: these to exit codes; the engine does not choose the integers.
#:
#: ``ok``            agreed (or vacuously agreed), and opened if requested
#: ``recovered``     RECOVER_THEN_OPEN found damage, repaired, and reopened
#: ``index-behind``  diverged, but only past the consumed prefix
#:                   (``AgreementReport.index_behind`` — a scope statement,
#:                   not an innocence claim; see that docstring)
#: ``diverged``      the artifacts disagree in a way "behind" does not cover
#: ``refused``       an open mode declined to open (audit failed in
#:                   AUDIT_THEN_OPEN, or recovery itself refused)
#: ``unreadable``    the canonical artifact itself cannot be read
PREFLIGHT_STATUSES = (
    "ok",
    "recovered",
    "index-behind",
    "diverged",
    "refused",
    "unreadable",
)


@dataclass(frozen=True)
class PreflightResult:
    """What the preflight found, what it did, and what a caller may do next."""

    mode: PreflightMode
    canonical_path: Path
    index_path: Path
    status: str
    """One of :data:`PREFLIGHT_STATUSES` — the exit-code hook."""

    report: AgreementReport | None
    """The evidentiary audit — taken BEFORE any open in every mode. ``None``
    only for a sqlite-canonical target, where agreement is vacuous."""

    post_report: AgreementReport | None
    """RECOVER_THEN_OPEN only: the audit re-run after recovery, so the
    caller can see what recovery left behind. ``None`` in other modes."""

    agreed: bool
    """Did the pre-open audit pass (vacuously True for sqlite-canonical)?"""

    opened: bool
    recovered: bool
    """True only when RECOVER_THEN_OPEN observed a failing pre-audit and the
    subsequent open succeeded — i.e. repair actually ran and took."""

    store: Any | None
    """The opened store handle (a ``SqliteStore`` subclass) in the open
    modes when opening happened; the caller owns closing it."""

    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "canonical_path": str(self.canonical_path),
            "index_path": str(self.index_path),
            "status": self.status,
            "agreed": self.agreed,
            "opened": self.opened,
            "recovered": self.recovered,
            "reason": self.reason,
            "report": self.report.as_dict() if self.report else None,
            **(
                {"post_report": self.post_report.as_dict()}
                if self.post_report
                else {}
            ),
        }


def read_preflight(
    target: Path | str | Any,
    mode: PreflightMode = PreflightMode.AUDIT_ONLY,
    **open_kwargs: Any,
) -> PreflightResult:
    """Audit a canonical store — and open it only as the mode allows.

    ``target`` is a canonical store locator (a ``.jsonl`` log or a
    sqlite-canonical db path), or a :class:`engine.probe.TargetInfo` whose
    ``canonical_path`` is taken — probe and preflight compose. A derived
    index path is accepted and re-routed to its canonical sibling via the
    probe, so no caller can accidentally audit "the index against itself".

    ``open_kwargs`` are forwarded to :func:`engine.jsonl_store.
    open_canonical_store` in the open modes (``serialize``/``deserialize``
    default to identity, matching ``ensure_index``).
    """
    canonical = _canonical_of(target)
    index = index_path_for(canonical)

    if not is_jsonl_canonical(canonical):
        return _sqlite_preflight(canonical, mode, open_kwargs)

    report = audit_agreement(canonical)
    if mode is PreflightMode.AUDIT_ONLY:
        return _audit_only_result(canonical, index, report)
    if mode is PreflightMode.AUDIT_THEN_OPEN:
        return _audit_then_open(canonical, index, report, open_kwargs)
    return _recover_then_open(canonical, index, report, open_kwargs)


# --- mode bodies ------------------------------------------------------------


def _audit_only_result(
    canonical: Path, index: Path, report: AgreementReport
) -> PreflightResult:
    status, reason = _verdict(canonical, report)
    return PreflightResult(
        mode=PreflightMode.AUDIT_ONLY,
        canonical_path=canonical,
        index_path=index,
        status=status,
        report=report,
        post_report=None,
        agreed=report.ok,
        opened=False,
        recovered=False,
        store=None,
        reason=reason,
    )


def _audit_then_open(
    canonical: Path,
    index: Path,
    report: AgreementReport,
    open_kwargs: dict[str, Any],
) -> PreflightResult:
    if not report.ok:
        status, why = _verdict(canonical, report)
        return PreflightResult(
            mode=PreflightMode.AUDIT_THEN_OPEN,
            canonical_path=canonical,
            index_path=index,
            status="refused" if status not in ("unreadable",) else status,
            report=report,
            post_report=None,
            agreed=False,
            opened=False,
            recovered=False,
            store=None,
            reason=(
                f"refusing to open: {why} — audit-then-open never repairs; "
                "recover-then-open is the sanctioned repair-and-open path"
            ),
        )
    store = _open(canonical, open_kwargs)
    return PreflightResult(
        mode=PreflightMode.AUDIT_THEN_OPEN,
        canonical_path=canonical,
        index_path=index,
        status="ok",
        report=report,
        post_report=None,
        agreed=True,
        opened=True,
        recovered=False,
        store=store,
        reason="agreement audit passed; store opened",
    )


def _recover_then_open(
    canonical: Path,
    index: Path,
    report: AgreementReport,
    open_kwargs: dict[str, Any],
) -> PreflightResult:
    """Evidence first, then the store's own recovery, then the after-picture."""
    from .jsonl_store import JsonlCanonicalUnsupported

    if not canonical.exists():
        return PreflightResult(
            mode=PreflightMode.RECOVER_THEN_OPEN,
            canonical_path=canonical,
            index_path=index,
            status="unreadable",
            report=report,
            post_report=None,
            agreed=False,
            opened=False,
            recovered=False,
            store=None,
            reason=(
                f"no canonical log at {canonical} — recovery rebuilds an "
                "index FROM the log; it never invents a log"
            ),
        )
    try:
        store = _open(canonical, open_kwargs)
    except JsonlCanonicalUnsupported as exc:
        return PreflightResult(
            mode=PreflightMode.RECOVER_THEN_OPEN,
            canonical_path=canonical,
            index_path=index,
            status="refused",
            report=report,
            post_report=None,
            agreed=report.ok,
            opened=False,
            recovered=False,
            store=None,
            reason=f"recovery refused: {exc}",
        )
    post = audit_agreement(canonical)
    recovered = not report.ok
    return PreflightResult(
        mode=PreflightMode.RECOVER_THEN_OPEN,
        canonical_path=canonical,
        index_path=index,
        status="recovered" if recovered else "ok",
        report=report,
        post_report=post,
        agreed=report.ok,
        opened=True,
        recovered=recovered,
        store=store,
        reason=(
            "store recovered and opened; pre-recovery evidence in report, "
            "post-recovery state in post_report"
            if recovered
            else "agreement audit passed; store opened (no recovery needed)"
        ),
    )


def _sqlite_preflight(
    canonical: Path, mode: PreflightMode, open_kwargs: dict[str, Any]
) -> PreflightResult:
    """Sqlite-canonical: no log/index pair, so agreement is vacuous.

    A MISSING db is ``unreadable`` in every mode — ``SqliteStore.__init__``
    creates a missing file, and a *read* preflight never creates. Even
    RECOVER_THEN_OPEN refuses: recovery rebuilds derived state from a
    canonical artifact; with no artifact there is nothing to recover FROM
    (the sqlite mirror of "recovery never invents a log"). Store creation
    is a different verb.
    """
    if not canonical.exists():
        return PreflightResult(
            mode=mode,
            canonical_path=canonical,
            index_path=canonical,
            status="unreadable",
            report=None,
            post_report=None,
            agreed=False,
            opened=False,
            recovered=False,
            store=None,
            reason=(
                f"no sqlite-canonical store at {canonical} — a read "
                "preflight never creates a store"
            ),
        )
    reason = (
        "sqlite-canonical store — no derived index to audit; agreement is "
        "vacuous (chain verification is verify_chain's scope)"
    )
    if mode is PreflightMode.AUDIT_ONLY:
        return PreflightResult(
            mode=mode,
            canonical_path=canonical,
            index_path=canonical,
            status="ok",
            report=None,
            post_report=None,
            agreed=True,
            opened=False,
            recovered=False,
            store=None,
            reason=reason,
        )
    store = _open(canonical, open_kwargs)
    return PreflightResult(
        mode=mode,
        canonical_path=canonical,
        index_path=canonical,
        status="ok",
        report=None,
        post_report=None,
        agreed=True,
        opened=True,
        recovered=False,
        store=store,
        reason=reason + "; store opened",
    )


# --- helpers ----------------------------------------------------------------


def _verdict(canonical: Path, report: AgreementReport) -> tuple[str, str]:
    """An ``AgreementReport`` as a (status, reason) pair for the vocabulary.

    ``index-behind`` re-states the report's own scope-limited flag; the
    reason keeps its wording so no caller upgrades it to an innocence claim.
    """
    if report.ok:
        return "ok", "log and index agree"
    if any(c.name == "log" and not c.ok for c in report.checks):
        return "unreadable", report.summary()
    if report.index_behind:
        return "index-behind", report.summary()
    return "diverged", report.summary()


def _canonical_of(target: Path | str | Any) -> Path:
    """A canonical path from a path-like or a ``TargetInfo``.

    A derived-index path is re-routed through the probe to its canonical
    sibling; a ``TargetInfo`` contributes its ``canonical_path`` directly.
    """
    canonical_attr = getattr(target, "canonical_path", None)
    if canonical_attr is not None:
        return Path(canonical_attr)
    if hasattr(target, "target_type"):  # a TargetInfo with no canonical
        raise ValueError(
            f"preflight needs a store-bearing target; got a "
            f"{target.target_type!r} probe with no canonical_path"
        )
    from .probe import probe_target

    info = probe_target(Path(target))
    if info.canonical_path is None:
        raise ValueError(
            f"not a store locator: {target} ({info.reason})"
        )
    return info.canonical_path


def _open(canonical: Path, open_kwargs: dict[str, Any]):
    from .jsonl_store import open_canonical_store

    kwargs: dict[str, Any] = {
        "serialize": lambda d: d,
        "deserialize": lambda d: d,
        **open_kwargs,
    }
    return open_canonical_store(canonical, **kwargs)
