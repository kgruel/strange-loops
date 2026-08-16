"""Rule 17: shipped prose never claims (ts, id) is the fold order."""

from __future__ import annotations

import re

from ._helpers import REPO_ROOT

# The ratified semantic (docs/RECEIPT_ORDER_FOLD.md): fold replay order is
# RECEIPT order (rowid, store-local). `(ts, id)` survives only as an explicit
# read lens. The code moved in S1/S2; this rule is what keeps the PROSE from
# drifting back, because a stale docstring is how the old model gets rebuilt in
# the next reader's head.
#
# Scope note (deliberately narrow — "scope the claim before widening the
# detection"). This scans SHIPPED prose only: `libs/*/src`, `apps/*/src`, and
# every `.md` under `spec/` and `docs/`, plus the conformance generators, whose
# case descriptions are normative text. Test files are OUT of scope on purpose:
# tests state counterfactuals constantly ("what would break under a (ts, id)
# replay") and folding those into the allowlist would dilute it from "these are
# genuinely lens" into "these are lens or hypothetical", which is exactly the
# overclaim this rule exists to prevent. `libs/engine/mutants/` is an artifact
# tree and is excluded everywhere.

_TS_ORDER = re.compile(
    r"\(ts,\s*id\)|\(ts,\s*fact_id\)|\(ts,id\)|ORDER BY ts\b|"
    r"ts ASC,\s*id ASC|ts DESC,\s*id DESC"
)
_FOLD_VOCAB = re.compile(r"\bfold|\breplay|\bFold|\bReplay|\bREPLAY")

# How far either side of the ts-pattern line the fold vocabulary may appear and
# still count as the same claim. Two lines is a wrapped sentence; wider starts
# pairing unrelated paragraphs and crying wolf.
_WINDOW = 2

# ---------------------------------------------------------------------------
# Allowlist — SHRINK ONLY.
#
# Each entry is (path relative to repo root, a substring that must appear on
# the matched line). Content markers, not line numbers: prose gets reflowed,
# and a line-numbered allowlist would churn on every unrelated edit while
# silently re-admitting a moved claim.
#
# Every entry needs a comment saying why the site is GENUINELY a lens (or a
# labeled historical record). "It has always been there" is not a reason. The
# only legal edits to this list are deletions.
# ---------------------------------------------------------------------------
_ALLOWLIST: set[tuple[str, str]] = {
    # The single-store branch folds on rowid; the multi-store branch has no
    # receipt axis at all (rowid is per-store) and says so, naming the fallback
    # as a lens and the situation as interim. This is ruling R2 in code.
    (
        "libs/engine/src/engine/vertex_reader.py",
        "(ts, id) READ LENS ordering — same rule as facts_in_range",
    ),
    (
        "libs/engine/src/engine/vertex_reader.py",
        "ORDER BY ts, id here is the explicit (ts, id) READ LENS ordering",
    ),
    # facts_by_kind's docstring states the ratified rule and names (ts, id) as
    # the thing that does NOT order the fold. Stating the negation is the
    # opposite of the claim this rule forbids.
    (
        "libs/engine/src/engine/store_reader.py",
        "``(ts, id)`` survives only as an explicit read-path lens",
    ),
    # Same shape: since_raw's docstring names the lens in order to deny it the
    # fold ("never the ...").
    (
        "libs/engine/src/engine/sqlite_store.py",
        "Event order ``(ts, id)`` is a read lens layered on top, never the",
    ),
    # read_facts' `order` parameter: an aggregate vertex genuinely pages on the
    # lens (R2), and the docstring scopes the claim to that branch.
    (
        "libs/sdk/src/sdk/read.py",
        "its pages come back on the ``(ts, id)`` read lens instead",
    ),
    # The merge ceremony (R1). Insertion by (ts, id) is what DEFINES the merged
    # store's receipt order; the prose says exactly that and says commutativity
    # is a merge property, not a fold-axis consequence.
    (
        "libs/store/src/store/merge.py",
        "ORDER BY (ts, id) is the merge INSERTION order, not a fold order",
    ),
    # The witness interval diagnostic reports arrivals that are out of
    # EVENT-TIME order, and explains that the consequence is a lens/fold
    # divergence in the view — not a perturbed fold.
    (
        "libs/engine/src/engine/witness.py",
        "that the ``(ts, id)`` read lens over this interval will order these rows",
    ),
    # SCHEMA §6: the normative statement of the ratified rule. Names (ts, id)
    # to exclude it from the fold and point at the lens area.
    (
        "spec/conformance/SCHEMA.md",
        "neither orders the fold. `(ts, id)` survives only as an explicit",
    ),
    # SCHEMA §9: the lens conformance area itself — its whole subject is the
    # (ts ASC, id ASC) read lens, defined against fold replay.
    (
        "spec/conformance/SCHEMA.md",
        "The `lens` area pins the explicit `(ts ASC, id ASC)` **read lens**",
    ),
    (
        "spec/conformance/SCHEMA.md",
        "no shared receipt axis exists",
    ),
    # The lens generator's module docstring — same subject as SCHEMA §9.
    (
        "spec/conformance/generate_lens.py",
        "pins the explicit `(ts, id)` READ LENS",
    ),
    (
        "spec/conformance/generate_lens.py",
        "reads fall back to `(ts ASC, id ASC)`",
    ),
    # The replay vector that pins the inversion. Its description names (ts, id)
    # in order to assert replay is NOT that.
    (
        "spec/conformance/generate_replay.py",
        "replay order is receipt order (rowid ascending), not (ts, id)",
    ),
    # The merge vector's description states ruling R1: the source's (ts, id)
    # INSERTION order determines the rowids, and the merged store then replays
    # that receipt sequence "rather than re-sorting by timestamp". It names the
    # pattern to assert the ceremony, not a fold order.
    (
        "spec/conformance/generate_merge.py",
        "in source (ts, id) insertion order",
    ),
    # UPGRADING is a per-release historical record. The 0.4.0 entries describe
    # what 0.4.0 did; both are now annotated as superseded with a link to the
    # decision record, so they read as history rather than as current rule.
    (
        "docs/UPGRADING.md",
        "practical symptoms by ordering folds and reads by `(ts, id)`",
    ),
    (
        "docs/UPGRADING.md",
        "`(ts, id)`, canonical bytes are JCS/RFC 8785",
    ),
    (
        "docs/UPGRADING.md",
        "`(ts, id)` is a read lens. See [receipt-order fold]",
    ),
    # The decision record itself states the superseded semantic in order to
    # supersede it, and defines the lens/fold vocabulary the rest of the repo
    # is held to.
    ("docs/RECEIPT_ORDER_FOLD.md", "(ts, id)"),
}


def _scan_targets() -> list:
    """Every shipped-prose file this rule judges.

    Derived from the filesystem, never hand-enumerated (docs/RATCHETS.md): a
    hand-written list is a silent pass for every lib, app, and doc added after
    it was written.
    """
    targets: list = []
    for production in ("libs", "apps"):
        base = REPO_ROOT / production
        if not base.is_dir():
            continue
        for package in sorted(base.iterdir()):
            src = package / "src"
            if src.is_dir():
                targets.extend(src.rglob("*.py"))
    for docs_root in ("spec", "docs"):
        base = REPO_ROOT / docs_root
        if base.is_dir():
            targets.extend(base.rglob("*.md"))
    # Conformance generators: their CASE descriptions are copied verbatim into
    # the vectors, which are normative artifacts other implementations read.
    generators = REPO_ROOT / "spec" / "conformance"
    if generators.is_dir():
        targets.extend(sorted(generators.glob("generate_*.py")))
    return [
        p
        for p in sorted(set(targets))
        if "mutants" not in p.parts
        and "__pycache__" not in p.parts
        and ".venv" not in p.parts
    ]


def _found_claims() -> set[tuple[str, str]]:
    """Every (path, line) where ts-ordering is stated near fold vocabulary."""
    found: set[tuple[str, str]] = set()
    for path in _scan_targets():
        rel = str(path.relative_to(REPO_ROOT))
        try:
            lines = path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines):
            if not _TS_ORDER.search(line):
                continue
            window = "\n".join(lines[max(0, i - _WINDOW) : i + _WINDOW + 1])
            if _FOLD_VOCAB.search(window):
                found.add((rel, line.strip()))
    return found


def _allowed(rel: str, line: str) -> bool:
    return any(rel == a_path and a_marker in line for a_path, a_marker in _ALLOWLIST)


def test_fold_order_prose_is_receipt_order():
    """No shipped prose claims `(ts, id)` orders the fold.

    Fold replay order is receipt order (``rowid``); ``(ts, id)`` is a read lens
    (docs/RECEIPT_ORDER_FOLD.md). Comments, docstrings, and spec/docs
    Markdown that still describe the old total order are not cosmetic: they are
    how the superseded model gets rebuilt in the next reader's head, and they
    are invisible to every behavioral test in the repo.

    A new hit means one of two things, and the failure message says which to
    pick. Relabel the site (say "read lens", say what it projects, or state the
    rule it is denying) — that is the fix in almost every case. Or, if the site
    is genuinely lens and cannot be phrased without the pattern, add an
    allowlist entry with a comment saying WHY it is lens. The allowlist may
    only shrink over time; each addition is a small permanent debt.
    """
    found = _found_claims()
    unexpected = sorted((p, ln) for p, ln in found if not _allowed(p, ln))

    assert not unexpected, (
        "Prose claiming `(ts, id)` / ts-ordering as FOLD or REPLAY order "
        "(fold order is receipt order — rowid; see "
        "docs/RECEIPT_ORDER_FOLD.md):\n"
        + "\n".join(f"  {p}: {ln[:120]}" for p, ln in unexpected)
        + "\n\nFix by RELABELLING the site as a read lens (preferred), or — if "
        "it truly is a lens and cannot avoid the pattern — add a (path, "
        "marker) entry to _ALLOWLIST in this file with a comment saying why. "
        "The allowlist is shrink-only."
    )


def test_allowlist_has_no_stale_entries():
    """Every allowlist entry still matches a real line — shrink-only enforced.

    Without this the list is a one-way ratchet in name only: entries would
    outlive the prose they excused and quietly pre-authorize whatever text
    landed on that marker next. A stale entry must be DELETED, which is the
    only edit direction this list allows.
    """
    found = _found_claims()
    stale = sorted(
        entry
        for entry in _ALLOWLIST
        if not any(p == entry[0] and entry[1] in ln for p, ln in found)
    )
    assert not stale, (
        "Stale _ALLOWLIST entries — the prose they excused is gone. Delete "
        "them (the list is shrink-only; never repoint an entry at new text):\n"
        + "\n".join(f"  {p}: {m}" for p, m in stale)
    )
