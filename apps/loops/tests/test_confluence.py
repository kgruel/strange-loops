"""Confluence — the observer-cut view (build-1).

Covers the fetch projection (one vertex_facts scan → per-observer census,
touched keys, MAX-tier inheritance) and the lens on both registers:
delegation-path grouping (render-only), the unattributed bucket, tier
gutters, zoom rungs, and shed-before-clip. Channel faithfulness is pinned
by the parity harness; the cross-command grammar golden
(golden/test_grammar_parity.py) carries the byte-level surface.
"""
from __future__ import annotations

from painted import Zoom

from loops.lenses.confluence import confluence_view

from .helpers import block_to_text
from .parity import assert_register_parity

_LAST = "2026-07-01T12:00:00+00:00"
_FIRST = "2026-06-01T09:00:00+00:00"


def _obs(name, count, *, kinds=None, tier="", keys=0, touched=()):
    return {
        "name": name,
        "count": count,
        "kinds": kinds or {"decision": count},
        "keys": keys,
        "touched": [list(t) for t in touched],
        "first": _FIRST,
        "last": _LAST,
        "tier": tier,
    }


def _data(observers):
    return {
        "vertex": "project",
        "total_facts": sum(o["count"] for o in observers),
        "observers": observers,
    }


def _render(data, zoom=Zoom.SUMMARY, width=100, *, piped=False) -> str:
    return block_to_text(
        confluence_view(data, zoom, width, piped=piped), use_ansi=False
    )


class TestGrouping:
    def test_compound_nests_under_emitting_root(self):
        data = _data([
            _obs("kyle/loops-claude", 40, tier="high"),
            _obs("kyle", 10, tier="mid"),
        ])
        text = _render(data)
        assert "└ kyle/loops-claude" in text
        # Root row precedes its children despite the lower count.
        lines = text.splitlines()
        root_i = next(
            i for i, ln in enumerate(lines) if "kyle" in ln and "└" not in ln
        )
        child_i = next(
            i for i, ln in enumerate(lines) if "└ kyle/loops-claude" in ln
        )
        assert root_i < child_i

    def test_root_gutter_rolls_up_group_max(self):
        # Root is mid on its own; its child is high → root gutter shows ◆
        # (decision:design/observer-compound-delegation-path).
        data = _data([
            _obs("kyle/loops-claude", 40, tier="high"),
            _obs("kyle", 10, tier="mid"),
        ])
        text = _render(data)
        root_line = next(
            ln for ln in text.splitlines() if "kyle " in ln and "└" not in ln
        )
        assert "◆" in root_line

    def test_no_nesting_without_emitting_root(self):
        # a/b with no bare "a" observer renders flat — no dangling └.
        data = _data([_obs("kyle/loops-claude", 40, tier="high")])
        assert "└" not in _render(data)

    def test_unattributed_bucket(self):
        data = _data([_obs("", 12)])
        text = _render(data)
        assert "(unattributed)" in text
        assert "(unattributed)" in _render(data, piped=True)


class TestZooms:
    def test_minimal_is_one_line_with_rollup(self):
        data = _data([_obs("kyle", 10), _obs("relay", 2)])
        text = _render(data, zoom=Zoom.MINIMAL).rstrip("\n")
        assert "\n" not in text
        assert "2 observers" in text and "12 facts" in text

    def test_minimal_sheds_names_never_clips(self):
        # Long names at a narrow width: the one-liner rolls names into +N
        # instead of severing the tail.
        data = _data([
            _obs("a-rather-long-observer-name/with-delegate", 40),
            _obs("another-long-observer", 30),
            _obs("third-observer", 20),
            _obs("fourth", 10),
        ])
        text = _render(data, zoom=Zoom.MINIMAL, width=60).rstrip("\n")
        assert "+4" in text
        assert len(text) <= 60

    def test_detailed_adds_touched_keys_both_channels(self):
        touched = [("decision", "design/rail", 3), ("thread", "spine", 1)]
        data = _data([
            _obs("kyle", 4, tier="high", keys=2, touched=touched),
        ])
        for piped in (False, True):
            text = _render(data, zoom=Zoom.DETAILED, piped=piped)
            assert "decision:design/rail" in text and "×3" in text
            assert "thread:spine" in text
        # SUMMARY keeps keys off — the specificity rung.
        assert "design/rail" not in _render(data, zoom=Zoom.SUMMARY)

    def test_full_adds_activity_window(self):
        data = _data([_obs("kyle", 4)])
        assert "2026-06-01" in _render(data, zoom=Zoom.FULL)
        piped = _render(data, zoom=Zoom.FULL, piped=True)
        assert "2026-06-01T09:00:00" in piped

    def test_summary_row_sheds_mix_before_clipping(self):
        kinds = {f"kind{i}": 10 - i for i in range(8)}
        data = _data([_obs("kyle", 44, kinds=kinds, tier="high")])
        text = _render(data, width=48)
        row = next(ln for ln in text.splitlines() if "kyle" in ln)
        assert "+" in row  # rolled up, not severed
        assert all(len(ln) <= 48 for ln in text.splitlines())


class TestRegisters:
    def test_piped_carries_untiered_word_and_full_mix(self):
        kinds = {f"kind{i}": i + 1 for i in range(6)}
        data = _data([_obs("project", 21, kinds=kinds, tier="")])
        text = _render(data, piped=True)
        assert "untiered" in text
        for k in kinds:
            assert f"{k}=" in text

    def test_empty_store(self):
        text = _render(_data([]))
        assert "No facts" in text

    def test_register_parity(self):
        data = _data([
            _obs("kyle/loops-claude", 40,
                 kinds={"decision": 30, "thread": 10}, tier="high", keys=7),
            _obs("kyle", 10, kinds={"log": 10}, tier="mid", keys=3),
            _obs("", 5, kinds={"session": 5}, keys=0),
        ])
        assert_register_parity(
            confluence_view, data,
            load_bearing=[
                "kyle/loops-claude", "(unattributed)", "40", "10", "5",
                "decision", "thread", "log", "session", "3 observers",
                "55 facts",
            ],
        )


class TestFetch:
    def test_fetch_over_real_store(self, tmp_path):
        from loops.commands.fetch import fetch_confluence

        from .builders import write_grammar_fixture

        vp = write_grammar_fixture(tmp_path)
        data = fetch_confluence(vp)
        names = {o["name"]: o for o in data["observers"]}
        assert set(names) == {"kyle", "loops-claude"}
        assert data["total_facts"] == sum(o["count"] for o in names.values())
        # kyle touched keyed facts → touched populated, tier inherited from
        # the entity projection (may be any tier, but never invented for
        # an observer with no touched keys).
        kyle = names["kyle"]
        assert kyle["keys"] > 0
        assert ["decision", "design/rail", 2] in kyle["touched"]
        # loops-claude emitted one keyed decision.
        assert names["loops-claude"]["count"] == 1
        # JSON-clean: ISO strings, list-shaped touched.
        assert isinstance(kyle["first"], str)

    def test_fetch_kind_filter(self, tmp_path):
        from loops.commands.fetch import fetch_confluence

        from .builders import write_grammar_fixture

        vp = write_grammar_fixture(tmp_path)
        data = fetch_confluence(vp, kind="thread")
        assert set(o["name"] for o in data["observers"]) == {"kyle"}
        assert all(
            k.startswith("thread")
            for o in data["observers"]
            for k in o["kinds"]
        )
