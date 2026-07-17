"""Deterministic sample data for golden tests.

All timestamps are epoch-based for reproducibility.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atoms import FoldItem, FoldSection, FoldState, WalkedItem

# Fixed reference point: 2025-01-15T12:00:00 UTC
REF_TS = 1736942400.0
REF_DT = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# ── fold ──────────────────────────────────────────────────────────────────
SAMPLE_FOLD = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(
                    payload={"topic": "Use SQLite for persistence",
                             "message": "Chose SQLite over filesystem for atomic writes and query support."},
                    ts="2025-01-15T10:00:00+00:00",
                ),
                FoldItem(
                    payload={"topic": "KDL for config format",
                             "message": "KDL is human-friendly and supports nested structure."},
                    ts="2025-01-14T09:30:00+00:00",
                ),
            ),
        ),
        FoldSection(
            kind="thread",
            fold_type="by",
            key_field="name",
            items=(
                FoldItem(
                    payload={"name": "vertex-routing", "status": "active"},
                    ts="2025-01-15T11:00:00+00:00",
                ),
                FoldItem(
                    payload={"name": "tick-nesting", "status": "exploring"},
                    ts="2025-01-14T16:00:00+00:00",
                ),
            ),
        ),
        FoldSection(
            kind="task",
            fold_type="by",
            key_field="name",
            items=(
                FoldItem(
                    payload={"name": "implement fold", "status": "in-progress",
                             "summary": "Wire up Spec.apply to projection fold loop."},
                    ts="2025-01-15T11:30:00+00:00",
                ),
                FoldItem(
                    payload={"name": "add observer field", "status": "done",
                             "summary": "Peer dissolved — observer is now a field on Fact."},
                    ts="2025-01-14T14:00:00+00:00",
                ),
            ),
        ),
        FoldSection(
            kind="change",
            fold_type="collect",
            key_field=None,
            items=(
                FoldItem(
                    payload={"summary": "Added boundary detection to Spec",
                             "files": "libs/atoms/src/atoms/spec.py"},
                    ts="2025-01-15T11:45:00+00:00",
                ),
                FoldItem(
                    payload={"summary": "Refactored tick emission",
                             "files": "libs/engine/src/engine/temporal.py"},
                    ts="2025-01-15T10:30:00+00:00",
                ),
            ),
        ),
    ),
    vertex="session",
)

# Legacy alias for any remaining references
SAMPLE_STATUS = SAMPLE_FOLD

# ── stream ─────────────────────────────────────────────────────────────────
SAMPLE_STREAM = {
    "facts": [
        {
            "kind": "decision",
            "ts": "2025-01-15T10:00:00+00:00",
            "payload": {
                "topic": "Use SQLite for persistence",
                "message": "Chose SQLite over filesystem for atomic writes.",
            },
            "observer": "kaygee",
        },
        {
            "kind": "task",
            "ts": "2025-01-15T09:30:00+00:00",
            "payload": {
                "name": "implement fold",
                "status": "in-progress",
                "summary": "Wire up Spec.apply.",
            },
            "observer": "kaygee",
        },
        {
            "kind": "change",
            "ts": "2025-01-14T16:00:00+00:00",
            "payload": {
                "summary": "Added boundary detection",
                "files": "libs/atoms/src/atoms/spec.py",
            },
            "observer": "kaygee",
        },
        {
            "kind": "thread",
            "ts": "2025-01-14T15:00:00+00:00",
            "payload": {"name": "vertex-routing", "status": "active"},
            "observer": "kaygee",
        },
    ],
    "fold_meta": {
        "decision": {"key_field": "topic"},
        "task": {"key_field": "name"},
        "change": {"key_field": None},
        "thread": {"key_field": "name"},
    },
    "vertex": "session",
}

# Legacy alias
SAMPLE_LOG = SAMPLE_STREAM

# ── store ───────────────────────────────────────────────────────────────────
# freshness uses a fixed datetime so we can mock _relative_time
SAMPLE_STORE = {
    "facts": {
        "total": 42,
        "kinds": {
            "disk": {
                "count": 20,
                "latest": REF_DT,
                "sample_payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
                "recent": [
                    {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
                    {"fs": "/dev/sda2", "pct": "78%", "mount": "/data"},
                ],
            },
            "memory": {
                "count": 22,
                "latest": REF_DT,
                "sample_payload": {"used_mb": 4096, "total_mb": 16384},
                "recent": [{"used_mb": 4096, "total_mb": 16384}],
            },
        },
    },
    "ticks": {
        "total": 12,
        "names": {
            "disk": {
                "count": 8,
                "latest": REF_DT,
                "sparkline": "\u2581\u2582\u2583\u2585\u2587\u2588\u2585\u2583",
                "payload_keys": ["fs", "pct", "mount"],
                "latest_payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
            },
            "memory": {
                "count": 4,
                "latest": REF_DT,
                "sparkline": "\u2581\u2583\u2585\u2587",
                "payload_keys": ["used_mb", "total_mb"],
                "latest_payload": {"used_mb": 4096, "total_mb": 16384},
            },
        },
    },
    "freshness": REF_DT,
}

# ── compile (loop) ──────────────────────────────────────────────────────────
SAMPLE_COMPILE_LOOP = {
    "type": "loop",
    "name": "disk.loop",
    "command": "df -h",
    "kind": "disk",
    "observer": "system-monitor",
    "every": 60,
    "format": "columns",
    "parse": [
        {"op": "skip_header", "lines": 1},
        {"op": "split", "delimiter": "\\s+"},
        {"op": "pick", "fields": ["fs", "pct", "mount"]},
    ],
}

# ── compile (vertex) ────────────────────────────────────────────────────────
SAMPLE_COMPILE_VERTEX = {
    "type": "vertex",
    "name": "system-monitor",
    "store": "system.db",
    "discover": "./loops/",
    "emit": True,
    "specs": {
        "disk": {
            "state_fields": ["fs", "pct", "mount"],
            "folds": [
                {"field": "pct", "op": "replace"},
                {"field": "mount", "op": "replace"},
            ],
            "boundary": {"kind": "threshold", "field": "pct", "value": "90%"},
        },
        "memory": {
            "state_fields": ["used_mb", "total_mb"],
            "folds": [{"field": "used_mb", "op": "replace"}],
            "boundary": None,
        },
    },
    "routes": {"disk": "disk", "memory": "memory"},
}

# ── validate ────────────────────────────────────────────────────────────────
SAMPLE_VALIDATE = {
    "results": [
        {"path": "loops/disk.loop", "valid": True, "error": None},
        {"path": "loops/memory.loop", "valid": True, "error": None},
        {
            "path": "loops/broken.loop",
            "valid": False,
            "error": "Parse error: unexpected token 'foo' at line 3\nExpected 'command' or 'kind' declaration",
        },
    ],
    "checked": 3,
    "errors": 1,
}

# ── test ────────────────────────────────────────────────────────────────────
SAMPLE_TEST = {
    "results": [
        {"fs": "/dev/disk1", "pct": "27%", "mount": "/"},
        {"fs": "/dev/disk2", "pct": "65%", "mount": "/data"},
        {"fs": "/dev/disk3", "pct": "91%", "mount": "/backup"},
    ],
    "skipped": 1,
}

# ── run facts ───────────────────────────────────────────────────────────────
SAMPLE_FACTS = [
    {
        "kind": "disk",
        "ts": 1700000000.0,
        "payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
        "observer": "system-monitor",
        "origin": "disk.loop",
    },
    {
        "kind": "memory",
        "ts": 1700000060.0,
        "payload": {"used_mb": 4096, "total_mb": 16384},
        "observer": "system-monitor",
        "origin": "memory.loop",
    },
]

# ── run ticks ───────────────────────────────────────────────────────────────
SAMPLE_TICKS = [
    {
        "name": "disk",
        "ts": 1700000000.0,
        "payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
        "origin": "system-monitor",
    },
    {
        "name": "memory",
        "ts": 1700000060.0,
        "payload": {"used_mb": 4096, "total_mb": 16384},
        "origin": "memory.loop",
    },
]

# ── declarations (sl vertices) ───────────────────────────────────────────────
# Exercises the declarations lens AND the preview_fields decl rendering.
SAMPLE_DECLARATIONS = {
    "vertex_name": "session",
    "kinds": [
        {"name": "decision", "fold_op": "by:topic", "target": "topic",
         "preview_fields": ["topic", "message"]},
        {"name": "thread", "fold_op": "by:name", "target": "name",
         "preview_fields": ["name", "status"]},
        {"name": "change", "fold_op": "collect"},
    ],
    "observers": [
        {"name": "kaygee", "identity": "kyle/loops-claude",
         "grants": ["read", "emit"]},
    ],
    "combine": [
        {"path": "~/Code/loops/.loops/project.vertex", "alias": "project"},
    ],
    "sources": [
        {"template": "reading", "list_path": "config/reading",
         "header": ["name", "url"],
         "rows": [{"name": "lobsters", "url": "https://lobste.rs/rss"}]},
    ],
}

# ── fold: preview-fields path ────────────────────────────────────────────────
# A section that declares preview_fields exercises the explicit per-kind
# preview render in _render_item_line (vs the heuristic first-field fallback).
SAMPLE_FOLD_PREVIEW = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            preview_fields=("message", "rationale"),
            items=(
                FoldItem(
                    payload={"topic": "Use SQLite",
                             "message": "Atomic writes and query support.",
                             "rationale": "Filesystem lacks transactions."},
                    ts="2025-01-15T10:00:00+00:00",
                    n=3,
                ),
            ),
        ),
    ),
    vertex="session",
)

# ── fold: namespace-grouped path + salience windowing + tied-group tiebreak ──
# Exercises _render_grouped (multi-namespace, >5-item group → salience>1 window
# + "(N more)" collapse) AND the tied-group-sum tiebreak that the fold-order
# decision turns on: groups grpA and grpB both sum to salience 5, but grpA's
# first item appears FIRST in fold order (index 0), so it must render first —
# a salience pre-sort would surface grpB/z (salience 5) first and flip them.
SAMPLE_FOLD_GROUPED = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                # grpA: x(n=2)+y(n=3) → group sum 5; appears first in fold order
                FoldItem(payload={"topic": "grpA/x", "message": "alpha x"},
                         ts="2025-01-15T10:00:00+00:00", n=2),
                # grpB: z(n=5) → group sum 5 (TIE with grpA)
                FoldItem(payload={"topic": "grpB/z", "message": "beta z"},
                         ts="2025-01-14T10:00:00+00:00", n=5),
                FoldItem(payload={"topic": "grpA/y", "message": "alpha y"},
                         ts="2025-01-13T10:00:00+00:00", n=3),
            ),
        ),
        FoldSection(
            kind="note",
            fold_type="by",
            key_field="topic",
            items=(
                # >5 items in one namespace → windowing: salience>1 shown, rest collapse
                FoldItem(payload={"topic": "big/a", "message": "a"},
                         ts="2025-01-15T10:00:00+00:00", n=4),
                FoldItem(payload={"topic": "big/b", "message": "b"},
                         ts="2025-01-15T09:00:00+00:00", n=2),
                FoldItem(payload={"topic": "big/c", "message": "c"},
                         ts="2025-01-15T08:00:00+00:00", n=1),
                FoldItem(payload={"topic": "big/d", "message": "d"},
                         ts="2025-01-15T07:00:00+00:00", n=1),
                FoldItem(payload={"topic": "big/e", "message": "e"},
                         ts="2025-01-15T06:00:00+00:00", n=1),
                FoldItem(payload={"topic": "big/f", "message": "f"},
                         ts="2025-01-15T05:00:00+00:00", n=1),
                FoldItem(payload={"topic": "big/g", "message": "g"},
                         ts="2025-01-15T04:00:00+00:00", n=1),
            ),
        ),
    ),
    vertex="session",
)

# ── fold: refs edge-expansion path (--refs / visible={"refs"}) ───────────────
# design/c is referenced by BOTH design/a and design/b (two same-section inbound
# sources) → the "← source" list order must follow fold order (a before b). Also
# carries outbound refs and observer/id so DETAILED+/FULL meta lines render.
SAMPLE_FOLD_REFS = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(payload={"topic": "design/a", "message": "refs c"},
                         ts="2025-01-15T10:00:00+00:00", observer="ann",
                         id="01AAAAAAAAAAAAAAAAAAAAAAAA", n=2,
                         refs=("decision/design/c",)),
                FoldItem(payload={"topic": "design/b", "message": "also refs c"},
                         ts="2025-01-15T09:00:00+00:00", observer="bob",
                         id="01BBBBBBBBBBBBBBBBBBBBBBBB", n=1,
                         refs=("decision/design/c",)),
                FoldItem(payload={"topic": "design/c", "message": "referenced twice"},
                         ts="2025-01-15T08:00:00+00:00", observer="ann",
                         id="01CCCCCCCCCCCCCCCCCCCCCCCC", n=3),
            ),
        ),
    ),
    vertex="session",
)

# ── fold: walked ref-graph path (--refs N → WalkedItem rows) ─────────────────
# A primary decision whose ref walks to a thread (depth 1) which walks to an
# observation (depth 2) — exercises _render_walked's via-anchor grouping and
# the depth>1 ↳ marker.
SAMPLE_FOLD_WALKED = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(payload={"topic": "design/root", "message": "anchor"},
                         ts="2025-01-15T10:00:00+00:00",
                         id="01RRRRRRRRRRRRRRRRRRRRRRRR", n=2,
                         refs=("thread:walk-target",)),
            ),
        ),
    ),
    vertex="session",
    walked=(
        WalkedItem(
            item=FoldItem(payload={"name": "walk-target", "status": "open"},
                          ts="2025-01-15T09:00:00+00:00",
                          id="01TTTTTTTTTTTTTTTTTTTTTTTT", n=1,
                          refs=("observation:deep",)),
            section_kind="thread", key_field="name",
            via_anchor="decision/design/root", depth=1,
        ),
        WalkedItem(
            item=FoldItem(payload={"topic": "deep", "message": "two hops out"},
                          ts="2025-01-15T08:00:00+00:00",
                          id="01DDDDDDDDDDDDDDDDDDDDDDDD", n=1),
            section_kind="observation", key_field="topic",
            via_anchor="thread/walk-target", depth=2,
        ),
    ),
)

# ── fold: source-facts drill path (--facts / visible={"facts"}) ──────────────
# One by-fold item has history (n>1 → drillable, source facts shown), one does
# not (n=1 → section skipped → "No history:" footer). source_facts keyed by
# "kind/key"; entries carry _ts for reverse-chrono ordering.
SAMPLE_FOLD_FACTS = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(payload={"topic": "design/evolved", "message": "v3 body"},
                         ts="2025-01-15T10:00:00+00:00",
                         id="01EEEEEEEEEEEEEEEEEEEEEEEE", n=3),
            ),
        ),
        FoldSection(
            kind="note",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(payload={"topic": "note/fresh", "message": "single"},
                         ts="2025-01-15T09:00:00+00:00",
                         id="01FFFFFFFFFFFFFFFFFFFFFFFF", n=1),
            ),
        ),
    ),
    vertex="session",
    source_facts={
        "decision/design/evolved": [
            {"topic": "design/evolved", "message": "v1 body",
             "_ts": 1736850000.0, "_id": "01G1"},
            {"topic": "design/evolved", "message": "v2 body",
             "_ts": 1736853600.0, "_id": "01G2"},
            {"topic": "design/evolved", "message": "v3 body",
             "_ts": 1736942400.0, "_id": "01G3"},
        ],
    },
)

# ── stream: tiered rows (rail glyph vs tier word) ────────────────────────────
# One high-tier fact, one untiered — locks the rail-gutter glyph (TTY) and the
# tier WORD (piped ledger) that test_parity_stream_ticks.py only content-checks
# (register parity), not byte-locks. Distinct from SAMPLE_STREAM (no tiers).
SAMPLE_STREAM_TIERED = {
    "vertex": "demo",
    "facts": [
        {
            "kind": "decision", "ts": "2025-01-15T10:32:00+00:00",
            "observer": "kyle", "id": "01JQ8FAAAAAAAAAAAAAAAAAAAA",
            "payload": {"topic": "design/sqlite-persistence",
                        "message": "Chose SQLite over flat files"},
            "tier": "high",
        },
        {
            "kind": "task", "ts": "2025-01-14T09:05:00+00:00",
            "observer": "loops-claude", "id": "01JQ8FBBBBBBBBBBBBBBBBBBBB",
            "payload": {"name": "implement-fold", "status": "in-progress"},
        },
    ],
    "fold_meta": {
        "decision": {"key_field": "topic"},
        "task": {"key_field": "name"},
    },
}

# ── stream: tick drill-down (single tick, _tick metadata) ────────────────────
# stream_view's ``tick_meta is not None`` branch — header rows via
# tick_drill_rows + facts, no vertex card (card path is skipped whenever a
# tick drill is active). Unreachable from any live CLI wiring today
# (fetch_tick_facts has no caller — S7 relocated ticks under `store ticks`,
# which drills through fold_view instead) but the branch is still live code
# the render_row consolidation will touch, so it gets a golden regardless.
SAMPLE_STREAM_TICK_DRILL = {
    "vertex": "demo",
    "facts": [
        {"kind": "decision", "ts": "2025-01-15T10:00:00+00:00",
         "payload": {"topic": "design/sqlite", "message": "chose sqlite"},
         "observer": "kaygee", "id": "01TICKDRILLAAAAAAAAAAAAAA"},
        {"kind": "task", "ts": "2025-01-15T09:30:00+00:00",
         "payload": {"name": "implement-fold", "status": "done"},
         "observer": "kaygee"},
    ],
    "fold_meta": {
        "decision": {"key_field": "topic"},
        "task": {"key_field": "name"},
    },
    "_tick": {
        "index": 0, "total": 5,
        "boundary": {"name": "session", "status": "end"},
        "since": "2025-01-15T09:00:00+00:00", "ts": "2025-01-15T10:00:00+00:00",
        "envelope": None,
    },
}

# ── stream: tick RANGE drill-down (0:3 form, range_end + range_boundaries) ───
SAMPLE_STREAM_TICK_RANGE = {
    "vertex": "demo",
    "facts": [
        {"kind": "decision", "ts": "2025-01-15T10:00:00+00:00",
         "payload": {"topic": "design/sqlite", "message": "chose sqlite"},
         "observer": "kaygee"},
    ],
    "fold_meta": {"decision": {"key_field": "topic"}},
    "_tick": {
        "index": 0, "total": 5, "range_end": 3,
        "boundary": {}, "since": None, "ts": None,
        "range_boundaries": [
            {"name": "session", "status": "end"},
            {"name": "manual", "status": ""},
        ],
        "envelope": None,
    },
}

# ── stream: tick error (out-of-range drill) ──────────────────────────────────
SAMPLE_STREAM_TICK_ERROR = {
    "vertex": "demo",
    "facts": [],
    "fold_meta": {},
    "_tick_error": "Tick index 9 out of range (have 5 ticks)",
}

# ── stream: single-fact id lookup (--id mode) ────────────────────────────────
# is_id_lookup forces FULL-equivalent graft (id/observer/origin) at every zoom.
SAMPLE_STREAM_ID_LOOKUP = {
    "vertex": "demo",
    "_id_lookup": True,
    "facts": [
        {"kind": "decision", "ts": "2025-01-15T10:00:00+00:00",
         "payload": {"topic": "design/sqlite", "message": "chose sqlite",
                     "rationale": "atomic writes and query support"},
         "observer": "kaygee", "id": "01IDLOOKUPAAAAAAAAAAAAAAAA",
         "origin": "cli"},
    ],
    "fold_meta": {"decision": {"key_field": "topic"}},
}

# ── stream: ontology honesty callout (SPEC §9.2/§9.5) ────────────────────────
SAMPLE_STREAM_ONTOLOGY_NOTICE = {
    "vertex": "demo",
    "ontology_notice": "no declaration lineage — ontology is the current file",
    "facts": [
        {"kind": "decision", "ts": "2025-01-09T10:00:00+00:00",
         "payload": {"topic": "design/x", "message": "y"}, "observer": "kaygee"},
    ],
    "fold_meta": {"decision": {"key_field": "topic"}},
}

# ── ticks: listing (store ticks), real ticks_view contract ──────────────────
# {"ticks": [...], "vertex": str} — distinct from SAMPLE_TICKS above (which is
# the flat run-ticks list shape consumed by _run_ticks_view, a different lens).
SAMPLE_TICKS_LISTING = {
    "vertex": "demo",
    "ticks": [
        {
            "name": "demo", "ts": "2025-01-15T10:32:00+00:00",
            "since": "2025-01-15T09:00:00+00:00", "origin": "session",
            "boundary": {"name": "session", "status": "end"},
            "kind_counts": {"decision": 3, "task": 2}, "tier": "high",
        },
        {
            "name": "demo", "ts": "2025-01-14T18:00:00+00:00",
            "since": "2025-01-14T12:00:00+00:00", "origin": "manual",
            "boundary": {}, "kind_counts": {"decision": 1},
        },
        {
            # No since → no duration; no boundary/name fallback in the body.
            "name": "demo", "ts": "2025-01-13T08:00:00+00:00",
            "since": None, "origin": "manual",
            "boundary": {}, "kind_counts": {},
        },
    ],
}

SAMPLE_TICKS_ONTOLOGY_NOTICE = {
    "vertex": "demo",
    "ontology_notice": "no declaration lineage — ontology is the current file",
    "ticks": [
        {
            "name": "demo", "ts": "2025-01-15T10:32:00+00:00",
            "since": "2025-01-15T09:00:00+00:00", "origin": "session",
            "boundary": {"name": "session", "status": "end"},
            "kind_counts": {"decision": 3},
        },
    ],
}

# ── sync: instance vertex (ran/skipped/errors/ticks) ─────────────────────────
# _format_ago (loops.lenses.sync) reads time.time() directly with NO calendar
# cutover (unlike _grammar.recency) — tests MUST freeze loops.lenses.sync.time
# .time, unlike every other fixture in this module (old timestamps alone don't
# make this one deterministic).
#
# One `ran` kind is deliberately long enough that the rendered "Ran: ..." line
# exceeds 80 columns: sync_view's rows use Block.text(..., width=width) with
# the default Wrap.NONE (single-line hard truncate, no ellipsis), so a TTY
# read (width=80) silently drops the tail while a piped read (width=None)
# carries the line whole — the tty/piped goldens must actually diverge to be
# worth having both (S0 codex review finding: the original fixture's longest
# line was ~50 cols, so both registers rendered byte-identical).
SAMPLE_SYNC_INSTANCE = {
    "ran": ["disk", "memory", "network-interface-diagnostics-and-telemetry-extended"],
    "skipped": [
        {"kind": "network", "last_run_ts": REF_TS - 300, "cadence_interval": 3600},
        {"kind": "temp"},  # no timestamps — bare-kind fallback
    ],
    "fact_counts": {
        "disk": 3, "memory": 2,
        "network-interface-diagnostics-and-telemetry-extended": 7,
    },
    "errors": [
        {"kind": "battery", "observer": "system-monitor",
         "payload": {"error": "sensor unavailable"}},
    ],
    "ticks": [
        {"name": "disk", "ts": REF_TS, "payload": {"fs": "/dev/sda1"},
         "origin": "disk.loop"},
    ],
}

# ── sync: aggregation vertex (children breakdown) ────────────────────────────
# Same over-80-column device as SAMPLE_SYNC_INSTANCE above, applied to the
# child breakdown line ("<name>: N facts (kinds...)").
SAMPLE_SYNC_AGGREGATION = {
    "ran": [], "skipped": [], "fact_counts": {}, "errors": [], "ticks": [],
    "children": [
        {
            "name": "project",
            "ran": ["decision", "network-interface-diagnostics-and-telemetry-extended"],
            "fact_counts": {
                "decision": 4,
                "network-interface-diagnostics-and-telemetry-extended": 9,
            },
            "skipped": [
                {"kind": "thread", "last_run_ts": REF_TS - 600, "cadence_interval": 1800},
            ],
        },
        {
            "name": "meta", "ran": [], "fact_counts": {},
            "skipped": [{"kind": "note"}],
        },
    ],
}

# ── sync: nothing configured ──────────────────────────────────────────────────
SAMPLE_SYNC_EMPTY = {
    "ran": [], "skipped": [], "fact_counts": {}, "errors": [], "ticks": [],
}

# ── ls / kind_stat: `ls <vertex> --kind <kind>` descent view ─────────────────
# Matches fetch_kind_stat's real contract (commands/ls.py): epoch-float
# earliest/latest/entry.latest, tiered entries. Deterministic without a clock
# patch — REF_TS is well past recency()'s 30-day calendar cutover.
SAMPLE_KIND_STAT = {
    "vertex_name": "project", "kind": "decision", "fold_op": "by:topic",
    "count": 42, "vertex_total": 100, "share": 42.0,
    "earliest": REF_TS - 5 * 86400, "latest": REF_TS,
    "distinct_keys": 3,
    "entries": [
        {"key": "design/sqlite", "count": 20, "latest": REF_TS,
         "leaf": True, "tier": "high"},
        {"key": "design/kdl", "count": 15, "latest": REF_TS - 86400,
         "leaf": True, "tier": "mid"},
        {"key": "design/misc", "count": 7, "latest": REF_TS - 2 * 86400,
         "leaf": True, "tier": ""},
    ],
}

# ── ls / kind_stat: --key prefix drill (one level deeper) ────────────────────
SAMPLE_KIND_STAT_DRILLED = {
    **SAMPLE_KIND_STAT,
    "key_prefix": "design/",
    "distinct_keys": 3,
}

# ── ls root (population): multi-vertex, local+config layering, shadow ───────
# Matches _run_ls_root's real fetch contract (commands/population.py + the
# per-vertex shape built by commands/vertices._extract_vertex_info /
# _enrich_with_stats): local layer (cwd, always stat'd) shadowing a config
# vertex of the same name, plus an aggregation and a hybrid vertex in config.
SAMPLE_LS_ROOT = {
    "local_vertices": [
        {
            "name": "project", "kind": "instance", "facts": 128,
            "kind_count": 3,
            "kind_stats": [
                {"kind": "decision", "count": 80},
                {"kind": "thread", "count": 30},
                {"kind": "task", "count": 18},
            ],
            "mtime": REF_TS,
            "loops": [],
            "shadows": True,
            "shadows_path": "/Users/kaygee/.config/loops/project/project.vertex",
        },
    ],
    "vertices": [
        {
            "name": "project", "kind": "instance", "facts": 12,
            "kind_count": 1,
            "kind_stats": [{"kind": "note", "count": 12}],
            "mtime": REF_TS - 86400,
            "loops": [{"name": "note.loop", "folds": ["by:topic"]}],
        },
        {
            "name": "meta", "kind": "aggregation", "facts": None,
            "kind_count": 0, "kind_stats": [],
            "mtime": None, "loops": [], "combine": ["project", "identity"],
        },
        {
            "name": "identity", "kind": "hybrid", "facts": 40,
            "kind_count": 2,
            "kind_stats": [
                {"kind": "trait", "count": 25}, {"kind": "peer", "count": 15},
            ],
            "mtime": REF_TS - 3600,
            "loops": [{"name": "trait.loop", "folds": ["collect"]}],
            "combine": ["external"],
            "store": "identity.db", "discover": "./loops/",
        },
    ],
    "cwd": "/Users/kaygee/Code/loops",
    "expand_config": False,
    "terse": False,
}

# ── fold: unfolded-kinds coverage signal ─────────────────────────────────────
# A vertex with one declared kind plus undeclared kinds present in the store —
# exercises the MINIMAL loose-render and the "Unfolded:" footer.
SAMPLE_FOLD_UNFOLDED = FoldState(
    sections=(
        FoldSection(
            kind="decision",
            fold_type="by",
            key_field="topic",
            items=(
                FoldItem(payload={"topic": "design/only", "message": "declared"},
                         ts="2025-01-15T10:00:00+00:00", n=1),
            ),
        ),
    ),
    vertex="session",
    unfolded={"log": 5, "scratch": 2},
)
