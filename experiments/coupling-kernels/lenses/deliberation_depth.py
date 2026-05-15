"""Deliberation-depth lens — structural overfit-candidate surfacing.

Reads hypothesis kind + counts the experimental evidence that targeted each
hypothesis (incoming query-run refs). Surfaces *candidates* for review, not
verdicts — the lens structures what an agent would notice on careful reading.

The principle (project store: paradigm/suspicious-cleanness-as-overfit-check):
when a hypothesis confirms on first test with no surprises, scrutinize it. A
confirmed hypothesis backed by 7 replications is on solid ground. A confirmed
hypothesis backed by zero experimental runs (confirmed by reasoning alone) is
a candidate for review — not because it is wrong, but because the deliberation
that produced the verdict was thin.

Metric:
    depth(hypothesis) = n_within_name_facts + n_incoming_query_run_refs

    where
      n_within_name_facts = FoldItem.n (facts compressed into the key)
      n_incoming_query_run_refs = count of query-run facts with
        ``ref=hypothesis:<name>`` in their refs

Flag rule (FLAG_THRESHOLD=3):
    status == 'confirmed' AND depth <= FLAG_THRESHOLD

The within-name count counts re-emits (any status update — proposed→refined→
confirmed etc.). It is a noisy proxy for status transitions (idempotent
re-emits inflate it), but the noise is in the SAFE direction — it overstates
deliberation, so a flagged item is genuinely thin.

Surfaces three groups, ordered by review-priority:
    OVERFIT CANDIDATES: confirmed + low depth — review carefully
    WELL-REPLICATED:    confirmed + high depth — stable
    REJECTED/REFINED:   non-confirmed — included for completeness

Precondition: vertex must declare both ``hypothesis`` and ``query-run`` kinds,
with query-runs carrying ``ref=hypothesis:<name>``. Designed for the
experimental vertex pattern (coupling-kernels.vertex is the reference).

Limitations encoded for future-me:
- Does not detect hypothesis→hypothesis replication chains (e.g.
  truncation-effect-at-fixed-sigma replicating truncation-as-coupling-function).
  Such chains are encoded by naming suffix, not by structured refs.
  emit_hypothesis() does not currently accept refs — that is the precondition
  gap for a v2 that traces replication lineage. See decision:
  design/deliberation-depth-via-incoming-refs.
- The flag is a SURFACE, not a DETECTOR. A flagged item is a candidate for
  agent review. Treating "lens flagged X" as "X is overfit" reproduces the
  write-receipt-vs-current-state conflation at the practice layer.

Zoom levels:
- MINIMAL:  one-line counts ("3 candidates · 2 replicated · 2 rejected")
- SUMMARY:  names + depth tags per group
- DETAILED: + message snippet (first ~140 chars)
- FULL:     + status, observer, ts
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


FLAG_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Cross-section computation
# ---------------------------------------------------------------------------

def _incoming_run_refs(state: FoldState) -> dict[str, int]:
    """Count query-run facts with ``ref=hypothesis:<name>`` per name.

    Walks the query-run section once, accumulates refs of the form
    ``hypothesis:<name>``. Returns {name: count}.
    """
    counts: dict[str, int] = {}
    for section in state.sections:
        if section.kind != "query-run":
            continue
        for item in section.items:
            for ref in item.refs:
                if ref.startswith("hypothesis:"):
                    name = ref[len("hypothesis:"):]
                    counts[name] = counts.get(name, 0) + 1
    return counts


def _hypothesis_section(state: FoldState) -> FoldSection | None:
    for section in state.sections:
        if section.kind == "hypothesis":
            return section
    return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _depth(item: FoldItem, run_refs: dict[str, int]) -> tuple[int, int, int]:
    """Return (depth, n_within, n_runs) for an item."""
    name = item.payload.get("name", "")
    n_within = item.n
    n_runs = run_refs.get(name, 0)
    return n_within + n_runs, n_within, n_runs


def _classify(items: tuple[FoldItem, ...], run_refs: dict[str, int]):
    """Return (candidates, replicated, other) — each list of (item, depth, n_within, n_runs)."""
    candidates: list[tuple[FoldItem, int, int, int]] = []
    replicated: list[tuple[FoldItem, int, int, int]] = []
    other: list[tuple[FoldItem, int, int, int]] = []

    for item in items:
        depth, n_w, n_r = _depth(item, run_refs)
        status = str(item.payload.get("status", "")).lower()
        row = (item, depth, n_w, n_r)
        if status == "confirmed":
            if depth <= FLAG_THRESHOLD:
                candidates.append(row)
            else:
                replicated.append(row)
        else:
            other.append(row)

    # Candidates: thinnest deliberation first (most suspect at top)
    candidates.sort(key=lambda r: r[1])
    # Replicated: deepest first (most-validated visible first)
    replicated.sort(key=lambda r: -r[1])
    # Other: by name for stability
    other.sort(key=lambda r: r[0].payload.get("name", ""))

    return candidates, replicated, other


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _snippet(text: str, limit: int = 140) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _label(item: FoldItem) -> str:
    return item.payload.get("name", "?")


def _depth_tag(depth: int, n_w: int, n_r: int) -> str:
    return f"[depth={depth} | n={n_w} +{n_r}runs]"


def _render_row(rows, row, zoom, width, style, dim, *, show_status=False):
    item, depth, n_w, n_r = row
    name = _label(item)
    tag = _depth_tag(depth, n_w, n_r)
    status = item.payload.get("status", "")
    status_tag = f" [{status}]" if show_status and status else ""
    rows.append(Block.text(
        f"  {name}{status_tag} {tag}", style, width=width,
    ))
    if zoom >= Zoom.DETAILED:
        body = item.payload.get("message", "")
        if body:
            rows.append(Block.text(f"    {_snippet(body)}", dim, width=width))


def fold_view(data: FoldState, zoom: Zoom, width: int | None, **kwargs) -> Block:
    section = _hypothesis_section(data)
    if section is None or not section.items:
        return Block.text("(no hypotheses)", Style(dim=True), width=width)

    run_refs = _incoming_run_refs(data)
    candidates, replicated, other = _classify(section.items, run_refs)

    if zoom <= Zoom.MINIMAL:
        parts = []
        if candidates:
            parts.append(f"{len(candidates)} candidates")
        if replicated:
            parts.append(f"{len(replicated)} replicated")
        if other:
            parts.append(f"{len(other)} rejected/refined")
        return Block.text(" · ".join(parts) or "(empty)", Style(), width=width)

    plain = Style()
    dim = Style(dim=True)
    bold = Style(bold=True)
    warn = Style(bold=True)  # could pick a color via theme; bold for portability

    rows: list[Block] = []

    if candidates:
        rows.append(Block.text(
            f"Overfit candidates — confirmed with depth <= {FLAG_THRESHOLD} ({len(candidates)})",
            warn, width=width,
        ))
        for row in candidates:
            _render_row(rows, row, zoom, width, plain, dim)

    if replicated:
        if rows:
            rows.append(Block.text("", plain, width=width))
        rows.append(Block.text(
            f"Well-replicated — confirmed with depth > {FLAG_THRESHOLD} ({len(replicated)})",
            bold, width=width,
        ))
        for row in replicated:
            _render_row(rows, row, zoom, width, plain, dim)

    if other:
        if rows:
            rows.append(Block.text("", plain, width=width))
        rows.append(Block.text(
            f"Rejected / refined ({len(other)})",
            dim, width=width,
        ))
        for row in other:
            _render_row(rows, row, zoom, width, dim, dim, show_status=True)

    return join_vertical(*rows)
