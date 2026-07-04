"""Golden coverage for the ``--why`` provenance drill lens.

Locks the per-field attribution render at default (SUMMARY) and -v (DETAILED,
superseded history) across the TTY and piped registers, plus the collect-fold
degrade. The fixture timestamps are far in the past so ``recency`` renders the
stable calendar form (``Jan 14``), not a drifting relative age — the golden is
time-stable.
"""
from __future__ import annotations

from atoms.fold import Upsert
from painted import Zoom

from loops.lenses.provenance import why_view
from loops.provenance import replay_attribution

from .helpers import block_to_text

# design/a folded over three emits: status open→review→open (twice-superseded),
# message set once and persisting under merge, label set then cleared.
_FACTS = [
    {"_ts": 1736850000.0, "_observer": "alice", "topic": "design/a",
     "message": "the body", "status": "open", "label": "draft"},
    {"_ts": 1736853600.0, "_observer": "bob", "topic": "design/a",
     "status": "review"},
    {"_ts": 1736942400.0, "_observer": "alice", "topic": "design/a",
     "status": "open", "label": ""},
]

WHY_UPSERT = replay_attribution(
    Upsert(target="s", key="topic"), _FACTS,
    kind="decision", key="design/a", key_field="topic",
)

_CITE_FACTS = [
    {"_ts": 1736850000.0, "_observer": "alice", "context": "first note"},
    {"_ts": 1736853600.0, "_observer": "bob", "context": "second note"},
]

WHY_COLLECT = replay_attribution(
    None, _CITE_FACTS, kind="cite", key="any", key_field=None,
)


def test_why_default_tty(golden):
    block = why_view(WHY_UPSERT, Zoom.SUMMARY, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


def test_why_default_piped(golden):
    block = why_view(WHY_UPSERT, Zoom.SUMMARY, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_why_verbose_tty(golden):
    block = why_view(WHY_UPSERT, Zoom.DETAILED, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


def test_why_verbose_piped(golden):
    block = why_view(WHY_UPSERT, Zoom.DETAILED, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_why_collect_piped(golden):
    block = why_view(WHY_COLLECT, Zoom.SUMMARY, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")
