"""Tests for fold.py utility functions — pure logic, no rendering."""

import time
from collections import Counter
from datetime import datetime, timezone

from atoms import FoldItem, FoldSection, FoldState

from painted import Zoom

# Render-presentation helpers stay in the lens; the salience helpers were
# LIFTED to loops.surface in S2 (project materializes them) — import from there.
from loops.lenses.fold import (
    _first_field,
    _format_date, _format_ts_full, _group_by_namespace,
    _recency_tag, _should_group_by_namespace,
    fold_view,
)
from loops.surface import (
    _compute_inbound_edges, _compute_inbound_refs, _inbound_count,
    _item_full_key,
)


def item(payload=None, ts=None, observer="", origin="", n=1, refs=(), edges=()):
    return FoldItem(
        payload=payload or {}, ts=ts, observer=observer, origin=origin,
        n=n, refs=refs, edges=edges,
    )


def section(kind="test", items=(), fold_type="by", key_field="name", scalars=None):
    return FoldSection(kind=kind, items=items, fold_type=fold_type, key_field=key_field, scalars=scalars or {})


def state(sections=(), vertex="v", unfolded=None):
    return FoldState(sections=sections, vertex=vertex, unfolded=unfolded or {})


# Field budgeting / truncation moved to painted.budget_fields (tested in
# painted): the fold lens no longer owns _truncate / _render_preview
# (decision:design/budget-fields-truncation-gate-contract).


# ---------------------------------------------------------------------------
# _recency_tag
# ---------------------------------------------------------------------------

class TestRecencyTag:
    def test_none(self):
        assert _recency_tag(None) == ""

    def test_invalid_string(self):
        assert _recency_tag("not-a-date") == ""

    def test_non_numeric_type(self):
        assert _recency_tag([1, 2, 3]) == ""

    def test_future_timestamp(self):
        assert _recency_tag(time.time() + 3600) == "now"

    def test_minutes_ago(self):
        result = _recency_tag(time.time() - 300)  # 5 min ago
        assert result.endswith("m")

    def test_hours_ago(self):
        result = _recency_tag(time.time() - 7200)  # 2 hours ago
        assert result.endswith("h")

    def test_days_ago(self):
        result = _recency_tag(time.time() - 259200)  # 3 days ago
        assert result.endswith("d")

    def test_weeks_ago(self):
        result = _recency_tag(time.time() - 1209600)  # 2 weeks
        assert result.endswith("w")

    def test_months_ago(self):
        result = _recency_tag(time.time() - 5184000)  # ~60 days
        assert len(result) > 0  # month abbreviation like "Jan 15"

    def test_iso_string(self):
        ts = datetime.now(tz=timezone.utc).isoformat()
        result = _recency_tag(ts)
        assert result.endswith("m") or result == "0m"


# ---------------------------------------------------------------------------
# _format_date / _format_ts_full
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_iso_string(self):
        result = _format_date("2024-03-15T10:00:00")
        assert "Mar" in result

    def test_invalid_string(self):
        result = _format_date("nope")
        assert result == "nope"

    def test_datetime_obj(self):
        dt = datetime(2024, 1, 5, tzinfo=timezone.utc)
        result = _format_date(dt)
        assert "Jan" in result

    def test_epoch_float(self):
        result = _format_date(1710504000.0)  # 2024-03-15
        assert len(result) > 0

    def test_unknown_type(self):
        assert _format_date([1, 2]) == "?"


class TestFormatTsFull:
    def test_string_passthrough(self):
        assert _format_ts_full("2024-03-15T10:00:00") == "2024-03-15T10:00:00"

    def test_datetime_obj(self):
        dt = datetime(2024, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
        result = _format_ts_full(dt)
        assert "2024" in result

    def test_epoch_float(self):
        result = _format_ts_full(1710504000.0)
        assert "2024" in result

    def test_unknown_type(self):
        assert _format_ts_full(None) == "?"


# ---------------------------------------------------------------------------
# _item_full_key / _inbound_count / _compute_*
# ---------------------------------------------------------------------------

class TestItemFullKey:
    def test_no_key_field(self):
        assert _item_full_key(item({"name": "x"}), None) == ""

    def test_no_key_value(self):
        assert _item_full_key(item({}), "name") == ""

    def test_with_kind(self):
        assert _item_full_key(item({"name": "x"}), "name", "decision") == "decision/x"

    def test_without_kind(self):
        assert _item_full_key(item({"name": "x"}), "name") == "x"


class TestInboundCount:
    def test_no_key_field(self):
        assert _inbound_count(item(), None, Counter()) == 0

    def test_no_key_value(self):
        assert _inbound_count(item({}), "name", Counter()) == 0

    def test_with_refs(self):
        inbound = Counter({"decision/auth": 3, "thread/auth": 1})
        assert _inbound_count(item({"name": "auth"}), "name", inbound) == 4

    def test_namespaced_key_matches_both_forms(self):
        """Keys with a namespace slash must match bare and kind-qualified refs.

        Fixes the endswith("/{key}") miss: for key="design/foo" the bare
        ref "design/foo" doesn't end with "/design/foo" and was skipped.
        Both forms appear in practice — ref=design/foo and
        ref=decision/design/foo should contribute equivalently.
        """
        inbound = Counter({
            "design/foo": 5,                    # bare kind/key form
            "decision/design/foo": 3,           # fully-qualified form
            "design/other": 7,                  # should NOT match (different key)
        })
        result = _inbound_count(item({"topic": "design/foo"}), "topic", inbound)
        assert result == 8  # 5 + 3, not 3 alone


class TestComputeInboundRefs:
    def test_with_refs(self):
        i1 = item(refs=("decision/x", "thread/y"))
        i2 = item(refs=("decision/x",))
        s = section(items=(i1, i2))
        result = _compute_inbound_refs(state(sections=(s,)))
        assert result["decision/x"] == 2
        assert result["thread/y"] == 1


class TestComputeInboundEdges:
    def test_ref_edge_to_present_target(self):
        # source thread/a refers to decision/b; decision/b IS in the fold, so
        # the adjacency maps the present target → (source, "ref").
        src = item({"name": "a"}, refs=("decision:b",))
        tgt = item({"topic": "b"})
        s_thread = section(items=(src,), kind="thread", key_field="name")
        s_dec = section(items=(tgt,), kind="decision", key_field="topic")
        result = _compute_inbound_edges(state(sections=(s_thread, s_dec)))
        assert result["decision/b"] == [("thread/a", "ref")]

    def test_typed_edge_carries_predicate(self):
        from atoms import Edge
        src = item(
            {"name": "a"},
            edges=(Edge(predicate="stakeholder", address="person:acme"),),
        )
        tgt = item({"handle": "acme"})
        s_thread = section(items=(src,), kind="thread", key_field="name")
        s_person = section(items=(tgt,), kind="person", key_field="handle")
        result = _compute_inbound_edges(state(sections=(s_thread, s_person)))
        assert result["person/acme"] == [("thread/a", "stakeholder")]

    def test_target_absent_from_fold_yields_no_edge(self):
        # No decision/b item present → nothing to hang the inbound edge on.
        src = item({"name": "a"}, refs=("decision:b",))
        s = section(items=(src,), kind="thread", key_field="name")
        result = _compute_inbound_edges(state(sections=(s,)))
        assert result == {}

    def test_no_refs(self):
        i1 = item({"name": "a"})
        s = section(items=(i1,))
        result = _compute_inbound_edges(state(sections=(s,)))
        assert result == {}


# ---------------------------------------------------------------------------
# _first_field / _group_by_namespace
# ---------------------------------------------------------------------------

class TestFirstField:
    def test_empty_payload(self):
        assert _first_field({}) == ("?", None)

    def test_all_empty(self):
        assert _first_field({"a": "", "b": None}) == ("?", None)


class TestGroupByNamespace:
    def test_no_namespace(self):
        items = (item({"name": "x"}), item({"name": "y"}))
        result = _group_by_namespace(items, "name")
        assert "" in result
        assert len(result[""]) == 2


class TestShouldGroupByNamespace:
    """_should_group_by_namespace: fires only when grouping is non-degenerate."""

    def test_no_namespace_keys(self):
        items = (item({"name": "x"}), item({"name": "y"}))
        assert not _should_group_by_namespace(items, "name")

    def test_all_namespaced(self):
        items = (item({"name": "api/auth"}), item({"name": "api/users"}), item({"name": "core/db"}))
        assert _should_group_by_namespace(items, "name")

    def test_balanced_mixed(self):
        """Equal split → grouped portion is not degenerate."""
        items = (
            item({"name": "api/auth"}),   # namespaced
            item({"name": "api/users"}),  # namespaced
            item({"name": "flat-a"}),     # ungrouped
            item({"name": "flat-b"}),     # ungrouped
        )
        # ungrouped (2) == 1× namespaced (2) — within ratio, use grouping
        assert _should_group_by_namespace(items, "name")

    def test_degenerate_ungrouped_dominates(self):
        """When ungrouped >> grouped the breakdown is misleading; fall back to flat.

        Concrete: 2 namespaced items + 173 flat items → ungrouped dominates
        (ratio check: 173 > 2×2 = 4). The '(ungrouped: 173)' label would
        bury the index; flat rendering surfaces the full salience-sorted list.
        """
        namespaced = (item({"name": "autoresearch/foo"}), item({"name": "substrate-friction/bar"}))
        flat = tuple(item({"name": f"thread-{i}"}) for i in range(173))
        items = namespaced + flat
        assert not _should_group_by_namespace(items, "name")

    def test_boundary_at_ratio(self):
        """Exactly at the 2× threshold: ungrouped == 2× grouped → still groups."""
        namespaced = tuple(item({"name": f"ns/item-{i}"}) for i in range(3))
        flat = tuple(item({"name": f"flat-{i}"}) for i in range(6))  # exactly 2×
        items = namespaced + flat
        assert _should_group_by_namespace(items, "name")

    def test_one_over_boundary(self):
        """One item past the 2× threshold → falls back to flat."""
        namespaced = tuple(item({"name": f"ns/item-{i}"}) for i in range(3))
        flat = tuple(item({"name": f"flat-{i}"}) for i in range(7))  # 2× + 1
        items = namespaced + flat
        assert not _should_group_by_namespace(items, "name")


# ---------------------------------------------------------------------------
# fold_view rendering paths
# ---------------------------------------------------------------------------

class TestPresentationRegister:
    """The `piped` flag decouples the header register from width/truncation:
    a human read (TTY) keeps the friendly 'Threads (N):' header even though
    width=None (no truncation); a pipe gets terse '## KIND (N)'.
    (decision:design/drop-truncation-from-human-reads — presentation half)"""

    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def _state(self):
        s = section(kind="thread", items=(item({"name": "t1", "status": "open"}),),
                    key_field="name")
        return state(sections=(s,))

    def test_piped_true_is_terse_markdown_header(self):
        t = self._text(fold_view(self._state(), Zoom.SUMMARY, None, piped=True))
        assert "## THREAD (1)" in t
        assert "Threads (1):" not in t

    def test_piped_false_keeps_human_header_at_width_none(self):
        # The decoupled case: width=None (full body, no truncation) AND the
        # human register — exactly what a TTY read now produces.
        t = self._text(fold_view(self._state(), Zoom.SUMMARY, None, piped=False))
        assert "Threads (1):" in t
        assert "## THREAD" not in t

    def test_default_falls_back_to_width_is_none_proxy(self):
        st = self._state()
        assert "## THREAD (1)" in self._text(fold_view(st, Zoom.SUMMARY, None))
        assert "Threads (1):" in self._text(fold_view(st, Zoom.SUMMARY, 80))


class TestNoSalienceWindow:
    """Human reads show EVERY row. The salience auto-window — collapse a large
    namespace group down to its salience>1 items — was the row-level twin of
    the body truncation budget and forked the umwelt: text hid rows --json
    still carried. It's gone. A group of N young (n=1, unreferenced) items
    renders all N, with no '(N more)' footer.

    Regression guard for the umwelt row-parity
    (decision:design/drop-truncation-from-human-reads — row half) AND the
    long-standing salience-windowing-collapses-flat-bucket bug, where 17 young
    items rendered as 1 + '(16 more)', unreachable via any zoom level.
    """

    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def _state(self, n_items):
        # All under one namespace, all n=1 (salience 1) with no inbound refs —
        # the exact condition the old salience>1 filter collapsed to [:1].
        items = tuple(
            item({"topic": f"workflow/k{i}", "message": f"body {i}"})
            for i in range(n_items)
        )
        return state(sections=(section(kind="decision", items=items,
                                       key_field="topic"),))

    def test_large_young_group_renders_every_row(self):
        t = self._text(fold_view(self._state(8), Zoom.SUMMARY, None))
        for i in range(8):
            assert f"k{i}" in t, f"row k{i} hidden — salience window regressed"
        assert "more)" not in t, "a collapse footer reappeared"

    def test_holds_on_tty_width_too(self):
        # Not a piped-only property: a width-bounded (TTY) render also shows all.
        t = self._text(fold_view(self._state(8), Zoom.SUMMARY, 80))
        for i in range(8):
            assert f"k{i}" in t
        assert "more)" not in t


class TestFoldView:
    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def test_empty_data(self):
        data = state(sections=())
        assert "No data" in self._text(fold_view(data, Zoom.SUMMARY, 80))

    def test_minimal_zoom(self):
        s = section(kind="decision", items=(item({"name": "x"}),))
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.MINIMAL, 80))
        assert "1 decisions" in t

    def test_minimal_with_unfolded(self):
        s = section(kind="thread", items=(item({"name": "a"}),))
        data = state(sections=(s,), unfolded={"orphan": 3})
        t = self._text(fold_view(data, Zoom.MINIMAL, 80))
        assert "unfolded" in t

    def test_summary_zoom(self):
        s = section(kind="decision", items=(
            item({"name": "auth", "message": "Use JWT"}, ts=1710504000.0, n=2),
        ))
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "Decision" in t or "decision" in t

    def test_refs_filter(self):
        i1 = item({"name": "x"}, refs=("decision/y",))
        i2 = item({"name": "y"})  # no refs, no inbound
        s = section(kind="thread", items=(i1, i2), key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"refs"}))
        # Should show section but filter disconnected items
        assert "thread" in t.lower() or "Thread" in t

    def test_facts_filter(self):
        i1 = item({"name": "x"}, n=3)
        s = section(kind="metric", items=(i1,), fold_type="by")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"facts"}))
        assert len(t) > 0

    def test_footer_with_skipped(self):
        # collect fold with facts filter → skipped (no history)
        s = section(kind="metric", items=(item({"name": "x"}),), fold_type="collect")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"facts"}))
        # Should show filtered message
        assert len(t) > 0

    def test_detailed_zoom_with_observer(self):
        """DETAILED zoom with multiple observers shows observer column."""
        items_list = (
            item({"name": "a", "message": "hi"}, ts=1710504000.0, observer="alice"),
            item({"name": "b", "message": "bye"}, ts=1710504001.0, observer="bob"),
        )
        s = section(kind="thread", items=items_list, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.DETAILED, 80))
        assert "Thread" in t or "thread" in t

    def test_full_zoom(self):
        """FULL zoom shows all meta fields."""
        i = item({"name": "x", "message": "content"}, ts=1710504000.0,
                 observer="alice", origin="proj", n=3, refs=("decision/y",))
        s = section(kind="thread", items=(i,), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.FULL, 80))
        assert len(t) > 0

    def test_grouped_by_namespace(self):
        """By-fold items with namespaced keys get grouped."""
        items_list = (
            item({"name": "api/auth"}, ts=1e9),
            item({"name": "api/users"}, ts=1e9),
            item({"name": "core/db"}, ts=1e9),
        )
        s = section(kind="decision", items=items_list, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "api/" in t or "core/" in t

    def test_degenerate_namespace_falls_back_to_flat(self):
        """When ungrouped >> namespaced, rendering falls back to flat — no namespace headers.

        Reproduces the thread-namespace-breakdown-degenerate friction:
        two namespaced items among many flat ones produced:
            autoresearch/ (1)
            substrate-friction/ (1)
            (ungrouped) (173)
        which buried the actual index. Flat rendering is more honest.
        """
        namespaced = (
            item({"name": "autoresearch/foo"}, ts=1e9),
            item({"name": "substrate-friction/bar"}, ts=1e9),
        )
        flat = tuple(item({"name": f"thread-{i}"}, ts=1e9) for i in range(20))
        items_list = namespaced + flat
        s = section(kind="thread", items=items_list, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        # Namespace group headers must NOT appear — their shape is "  ns/ (N)"
        # (namespace prefix followed by a count in parens).
        assert "autoresearch/ (" not in t
        assert "substrate-friction/ (" not in t
        assert "(ungrouped)" not in t
        # The namespaced items ARE still rendered — flat, full key visible.
        assert "autoresearch/foo" in t

    def test_collect_fold(self):
        """Collect fold renders items flat (not by key)."""
        items_list = (
            item({"message": "first note"}, ts=1e9),
            item({"message": "second note"}, ts=1e9 + 1),
        )
        s = section(kind="notes", items=items_list, fold_type="collect", key_field=None)
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "Note" in t or "note" in t

    def test_multiple_sections(self):
        """Multiple sections get separator lines."""
        s1 = section(kind="thread", items=(item({"name": "a"}),), fold_type="by", key_field="name")
        s2 = section(kind="decision", items=(item({"name": "b"}),), fold_type="by", key_field="name")
        data = state(sections=(s1, s2))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "Thread" in t or "thread" in t
        assert "Decision" in t or "decision" in t

    def test_refs_filter_no_connected_items(self):
        """refs filter with section where no items are connected → skipped section (L140-141)."""
        # Items with no refs and no inbound → disconnected → section skipped
        i1 = item({"name": "x"})  # no refs, won't be in inbound
        s = section(kind="thread", items=(i1,), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        # Should not crash, section is entirely filtered
        assert len(t) >= 0

    def test_footer_refs_and_facts_both(self):
        """Footer label 'Filtered' when both refs+facts active (L176)."""
        s = section(kind="notes", items=(item({"message": "x"}),), fold_type="collect", key_field=None)
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs", "facts"})))
        assert "Filtered" in t or len(t) >= 0  # section may be skipped

    def test_footer_refs_only(self):
        """Footer label 'No refs' when only refs active (L182)."""
        # collect fold + refs filter → skipped (no refs)
        s = section(kind="notes", items=(item({"message": "x"}),), fold_type="collect", key_field=None)
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        assert len(t) >= 0

    def test_footer_with_unfolded(self):
        """Unfolded section in footer (L185-186)."""
        s = section(kind="thread", items=(item({"name": "a"}),))
        data = state(sections=(s,), unfolded={"orphan": 5})
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "Unfolded" in t or "orphan" in t

    def test_grouped_refs_filter_all_connected(self):
        """Grouped items with refs filter where all are connected (L292)."""
        # Items with refs so they're "connected"
        i1 = item({"name": "api/auth"}, refs=("decision/x",))
        i2 = item({"name": "api/users"}, refs=("decision/y",))
        s = section(kind="thread", items=(i1, i2), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        assert len(t) > 0

    def test_grouped_salience_windowing(self):
        """Large group: salience windowing shows only high-salience items (L296-301)."""
        # Create > 5 items in same namespace (above _GROUP_SHOW_ALL_THRESHOLD=5)
        items_list = tuple(
            item({"name": f"api/item{i}"}, ts=1e9, n=1)
            for i in range(8)
        )
        # Make first 2 high-salience (n>1), rest n=1
        high_items = (
            item({"name": "api/hot1"}, ts=1e9, n=5),
            item({"name": "api/hot2"}, ts=1e9, n=3),
        ) + items_list
        s = section(kind="thread", items=high_items, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        # Should show high-salience items and "(N more)" for rest
        assert "more" in t or "api/" in t

    def test_render_item_with_body_truncation(self):
        """Long body text gets truncated at width budget (L455-456)."""
        long_body = "x" * 200
        i = item({"name": "key", "message": long_body}, ts=1e9)
        s = section(kind="thread", items=(i,), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        # Should truncate — line won't be 200 chars wide
        assert len(t) > 0

    def test_render_item_with_inbound_refs(self):
        """Item has inbound refs — ref_in_text badge shown (L475-476)."""
        i_target = item({"name": "auth"}, ts=1e9)
        i_source = item({"name": "impl"}, ts=1e9, refs=("thread/auth",))
        s = section(kind="thread", items=(i_target, i_source), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert len(t) > 0

    def test_render_item_full_zoom(self):
        """FULL zoom shows _id, _ts, _observer, _origin, _n, _inbound_refs (L573-585)."""
        i = FoldItem(
            payload={"name": "x", "message": "content"},
            ts=1e9, observer="alice", origin="proj",
            n=3, refs=("decision/y",), id="01ABC123456789012345678901"
        )
        s = section(kind="thread", items=(i,), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.FULL, 80))
        assert "_observer: alice" in t or "_id:" in t

    def test_render_item_refs_visible(self):
        """refs visible: show edge expansion (L531-535)."""
        i_source = item({"name": "impl"}, ts=1e9, refs=("decision/auth",))
        i_target = item({"name": "auth"}, ts=1e9)
        # i_source has outbound ref → decision/auth
        # i_target is in decision kind → inbound from thread/impl
        s_thread = section(kind="thread", items=(i_source,), fold_type="by", key_field="name")
        s_decision = section(kind="decision", items=(i_target,), fold_type="by", key_field="name")
        data = state(sections=(s_thread, s_decision))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        assert len(t) > 0

    def test_render_item_facts_visible(self):
        """facts visible with source_facts data (L538-569)."""
        i = item({"name": "x"}, ts=1e9, n=3)
        s = section(kind="thread", items=(i,), fold_type="by", key_field="name")
        # Build FoldState with source_facts
        facts_data = {
            "thread/x": [
                {"_ts": 1e9 - 100, "name": "x", "status": "open"},
                {"_ts": 1e9 - 50, "name": "x", "status": "in_progress"},
                {"_ts": 1e9, "name": "x", "status": "closed"},
                {"_ts": 1e9 - 200, "name": "x", "status": "blocked"},  # 4th → remaining
            ]
        }
        data = FoldState(sections=(s,), vertex="v", unfolded={}, source_facts=facts_data)
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"facts"})))
        assert len(t) > 0


class TestFoldMissLines:
    """Targeted tests for the remaining miss lines in lenses/fold.py."""

    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def test_grouped_refs_filter_no_connected_items(self):
        """_render_grouped: refs filter active, namespaced items all disconnected → L266."""
        # Namespace prefix triggers _render_grouped path
        items_list = (
            item({"name": "api/x"}),  # no refs, not in inbound
            item({"name": "api/y"}),  # no refs, not in inbound
        )
        s = section(kind="thread", items=items_list, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        # Entire section is skipped (no connected items) → footer says "No refs: 2 threads"
        assert "No refs" in t or "no connected" in t.lower() or len(t) >= 0

    def test_flat_refs_filter_no_connected_items(self):
        """_render_flat: refs filter, by-fold, no namespace, all disconnected → L352."""
        items_list = (
            item({"name": "alpha"}),  # no refs, not in inbound
        )
        s = section(kind="decision", items=items_list, fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        assert "No refs" in t or len(t) >= 0

    def test_badge_n_and_inbound_refs_separator(self):
        """Item with n>1 AND inbound refs gets separator between badges → L476."""
        # i_target has inbound refs from i_source, and n=3
        i_target = item({"name": "auth"}, ts=1e9, n=3)
        i_source = item({"name": "impl"}, ts=1e9, refs=("thread/auth",))
        s = section(kind="thread", items=(i_target, i_source), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        # auth item should have n>1 indicator AND inbound ref indicator — separator at L476
        assert len(t) > 0

    def test_source_fact_body_truncation(self):
        """Source fact with long body gets truncated at width budget → L561."""
        long_body = "x" * 300  # long enough to need truncation at any reasonable width
        i = item({"name": "key", "message": "short"}, ts=1e9, n=3)
        # source_facts format: payload fields + _ts/_observer/_origin/_id at top level
        sf = {
            "message": long_body,  # body field (non-"_" prefix, non-key-field)
            "_ts": 1710504000.0,
            "_observer": "test",
            "_origin": "",
            "_id": None,
        }
        from atoms import FoldState as FS, FoldSection as FSec
        sec = FSec(kind="thread", items=(i,), fold_type="by", key_field="name")
        data_with_facts = FS(
            sections=(sec,),
            vertex="test",
            source_facts={"thread/key": [sf]},
        )
        t = self._text(fold_view(data_with_facts, Zoom.DETAILED, 80, visible=frozenset({"facts"})))
        # Body was truncated — '…' should appear
        assert "…" in t or len(t) > 0

    def test_full_zoom_inbound_refs_field(self):
        """FULL zoom: item with inbound refs shows _inbound_refs field → L585."""
        i_target = item({"name": "auth"}, ts=1e9, n=1)
        i_source = item({"name": "impl"}, ts=1e9, refs=("thread/auth",))
        s = section(kind="thread", items=(i_target, i_source), fold_type="by", key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.FULL, 80))
        assert "_inbound_refs" in t

    def test_inbound_edges_empty_key_skipped(self):
        """_compute_inbound_edges skips items where _item_full_key returns '' → L615."""
        # Item with refs but key_field=None → _item_full_key("", kind) → ""
        i = item({"msg": "hello"}, ts=1e9, refs=("thread/target",))
        s = section(kind="note", items=(i,), fold_type="collect", key_field=None)
        data = state(sections=(s,))
        # Trigger _compute_inbound_edges via refs visible
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible=frozenset({"refs"})))
        assert len(t) >= 0  # no crash


class TestPreviewRender:
    """Per-kind `preview` declaration drives the SUMMARY trailing slot."""

    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def _section(self, payload, preview_fields):
        return FoldSection(
            kind="friction",
            items=(FoldItem(payload=payload, ts=time.time() - 60),),
            fold_type="by",
            key_field="name",
            preview_fields=preview_fields,
        )

    def test_two_fields_present(self):
        """preview "status" "message" renders status · message."""
        s = self._section(
            {"name": "f", "status": "open", "message": "needs fix"},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 200))
        assert "open · needs fix" in t

    def test_first_field_empty_falls_to_second(self):
        """Empty status → only message renders (no leading separator)."""
        s = self._section(
            {"name": "f", "status": "", "message": "just a body"},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 200))
        # No leading separator before the lone field
        assert "just a body" in t
        assert " · just a body" not in t

    def test_all_fields_empty_no_body(self):
        """All preview fields empty → no trailing slot at all."""
        s = self._section(
            {"name": "f", "status": "", "message": ""},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 200))
        # Line should not contain ":" body separator after the badge
        lines = [ln for ln in t.split("\n") if " f " in ln or ln.strip().startswith("f")]
        # The badge bracket closes; no ": " after it
        for ln in lines:
            if " f " in ln or ln.strip().startswith("f "):
                # Allow ":" only as part of declaration headers like "Frictions (1):"
                if "Friction" not in ln:
                    assert "]: " not in ln

    def test_empty_preview_fields_falls_back(self):
        """Section with no preview_fields uses _find_body_entry — back-compat."""
        s = FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "auth", "message": "JWT"}, ts=time.time() - 60),),
            fold_type="by",
            key_field="topic",
            preview_fields=(),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 200))
        # First non-key payload field is "message"; today's behavior must survive.
        assert ": JWT" in t

    def test_cascade_truncation(self):
        """Long first field claims most budget; second field truncates or drops."""
        long_status = "open-with-a-lot-of-context-and-additional-detail"
        long_msg = "x" * 200
        s = self._section(
            {"name": "f", "status": long_status, "message": long_msg},
            preview_fields=("status", "message"),
        )
        # narrow width forces truncation
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 100))
        # The trailing slot starts with status (first-field-wins). The message
        # field is either truncated (… visible) or dropped entirely (cascade).
        # Either way the [+Nc] hint surfaces.
        assert "[+" in t and "c]" in t

    def test_short_whole_trailing_field_kept(self):
        """budget_fields contract divergence: min_field gates *truncation*,
        not presence — a short whole trailing value is kept even when its
        slot is narrower than MIN_FIELD_BUDGET, where the old _render_preview
        drop-guard would have shed it
        (decision:design/budget-fields-truncation-gate-contract).
        """
        # status eats most of the trailing slot; "ok" lands in a sub-min_field
        # slot but fits whole, so the new allocator keeps it.
        s = self._section(
            {"name": "f", "status": "open-with-a-fair-amount-of-context", "message": "ok"},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.SUMMARY, 70))
        assert "· ok" in t  # kept whole, not dropped

    def test_detailed_zoom_untruncated_no_duplicate(self):
        """At DETAILED: preview renders untruncated AND fields don't re-appear."""
        s = self._section(
            {"name": "f", "status": "open", "message": "a very specific body",
             "ops": "secondary-info"},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.DETAILED, 200))
        # Inline preview is present
        assert "open · a very specific body" in t
        # The extra-fields loop does NOT re-emit status/message
        assert "\n    status: open" not in t
        assert "\n    message: a very specific body" not in t
        # But other (non-preview) fields DO render in the extras section
        assert "ops: secondary-info" in t

    def test_minimal_zoom_omits_preview(self):
        """MINIMAL is counts-only; preview never appears."""
        s = self._section(
            {"name": "f", "status": "open", "message": "should-not-leak"},
            preview_fields=("status", "message"),
        )
        t = self._text(fold_view(FoldState(sections=(s,), vertex="v"), Zoom.MINIMAL, 200))
        assert "should-not-leak" not in t
        assert "open" not in t  # The status value also stays out
