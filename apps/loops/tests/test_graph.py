"""Graph — the ref/edge-graph view (build-1).

Covers the net-new chain traversal (memoized DFS, cycle guard, depth cap,
dangling refs, longest-chain correctness), the fetch projection over a real
store, and the lens on both registers (hubs / chains / orphans / census, zoom
rungs, shed-before-clip, channel faithfulness). Channel parity is pinned by the
harness; the cross-command grammar golden carries the byte-level surface.
"""
from __future__ import annotations

from painted import Zoom

from loops.commands.fetch import _longest_chains, _top_chains, fetch_graph
from loops.lenses.graph import graph_view

from .helpers import block_to_text
from .parity import assert_register_parity

_LAST = 1735733100.0


def _adj(pairs: dict) -> dict:
    """Build an adjacency map (source → [(target, 'ref'), ...])."""
    return {src: [(t, "ref") for t in tgts] for src, tgts in pairs.items()}


def _hub(address, inbound, *, tier="mid", predicates=None, last=_LAST):
    return {
        "address": address,
        "kind": address.split("/", 1)[0],
        "key": address.split("/", 1)[1],
        "tier": tier,
        "inbound": inbound,
        "predicates": predicates or [["ref", inbound]],
        "last": last,
        "observer": "kyle",
    }


def _data(*, hubs=(), chains=(), orphan_list=(), census=(), nodes=None):
    edges = sum(n for c in census for _, n, _ in [c]) if census else len(chains)
    typed = sum(n for p, n, t in census if t) if census else 0
    return {
        "vertex": "project",
        "nodes": nodes if nodes is not None else len(hubs) + len(orphan_list),
        "edges": edges,
        "typed_edges": typed,
        "orphans": len(orphan_list),
        "dangling": 0,
        "hubs": list(hubs),
        "chains": [list(c) for c in chains],
        "orphan_list": list(orphan_list),
        "census": [list(c) for c in census],
    }


def _render(data, zoom=Zoom.SUMMARY, width=100, *, piped=False) -> str:
    return block_to_text(graph_view(data, zoom, width, piped=piped), use_ansi=False)


class TestTraversal:
    def test_longest_chain_correctness(self):
        # a→b→c→d is the longest; the b→e branch is shorter.
        memo = _longest_chains(_adj({
            "a": ["b"], "b": ["c", "e"], "c": ["d"], "d": [], "e": [],
        }))
        assert memo["a"] == ["a", "b", "c", "d"]
        assert memo["b"] == ["b", "c", "d"]

    def test_cycle_does_not_hang(self):
        # a→b→c→a is a pure cycle — the per-path guard skips the back-edge.
        memo = _longest_chains(_adj({"a": ["b"], "b": ["c"], "c": ["a"]}))
        # Terminates, bounded at the ring size, and never repeats a node.
        for node in ("a", "b", "c"):
            assert 1 <= len(memo[node]) <= 3
            assert len(set(memo[node])) == len(memo[node])  # no node twice
        assert max(len(p) for p in memo.values()) == 3

    def test_depth_cap(self):
        # A chain longer than the cap is truncated at `cap` nodes, not crashed.
        chain = {str(i): [str(i + 1)] for i in range(50)}
        chain["50"] = []
        memo = _longest_chains(_adj(chain), cap=8)
        assert max(len(p) for p in memo.values()) == 8

    def test_top_chains_drops_subpaths(self):
        # b→c→d is contained in a→b→c→d — only the maximal chain survives.
        memo = _longest_chains(_adj({
            "a": ["b"], "b": ["c"], "c": ["d"], "d": [],
        }))
        top = _top_chains(memo)
        assert top == [["a", "b", "c", "d"]]

    def test_top_chains_needs_an_edge(self):
        # Isolated nodes (len-1 paths) are not chains.
        memo = _longest_chains(_adj({"a": [], "b": []}))
        assert _top_chains(memo) == []


class TestFetch:
    def _dangling_fixture(self, tmp_path):
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "g.vertex"
        vp.write_text(
            'name "g"\nstore "./g.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        for i, (topic, ref) in enumerate([
            ("a", "decision:b"),
            ("b", "decision:c"),
            ("c", "decision:ghost"),  # dangling — no node "ghost"
        ]):
            prog.receive(Fact.of(
                "decision", "kyle", ts=t + i, topic=topic, message="x", ref=ref,
            ))
        return vp

    def test_fetch_chain_and_dangling(self, tmp_path):
        data = fetch_graph(self._dangling_fixture(tmp_path))
        assert data["nodes"] == 3
        # a→b→c resolves (2 edges); c→ghost dangles.
        assert data["edges"] == 2
        assert data["dangling"] == 1
        assert data["typed_edges"] == 0
        assert data["chains"] == [[
            "decision/a", "decision/b", "decision/c",
        ]]
        # b and c are inbound hubs; a is a pure source (inbound 0, has a ref
        # out) so it is neither a hub nor an orphan.
        assert {h["address"] for h in data["hubs"]} == {
            "decision/b", "decision/c",
        }
        assert data["orphans"] == 0

    def test_fetch_over_grammar_fixture(self, tmp_path):
        from .builders import write_grammar_fixture

        data = fetch_graph(write_grammar_fixture(tmp_path))
        # One real ref: decision:design/rail → thread:spine.
        assert data["edges"] == 1
        assert data["chains"] == [[
            "decision/design/rail", "thread/spine",
        ]]
        hub = next(h for h in data["hubs"] if h["address"] == "thread/spine")
        assert hub["inbound"] == 1
        assert hub["predicates"] == [["ref", 1]]
        # JSON-clean: last is a float epoch, not a datetime.
        assert isinstance(hub["last"], float)

    def test_fetch_kind_filter(self, tmp_path):
        from .builders import write_grammar_fixture

        data = fetch_graph(write_grammar_fixture(tmp_path), kind="thread")
        assert all(h["kind"] == "thread" for h in data["hubs"])


class TestZooms:
    def test_minimal_is_one_line(self):
        data = _data(hubs=[_hub("thread/spine", 1)], nodes=4, orphan_list=["a/x"])
        text = _render(data, zoom=Zoom.MINIMAL).rstrip("\n")
        assert "\n" not in text
        assert "4 nodes" in text and "1 orphans" in text

    def test_minimal_sheds_before_clip(self):
        data = _data(hubs=[_hub("k/very-long-address-here", 3)], nodes=99)
        text = _render(data, zoom=Zoom.MINIMAL, width=30).rstrip("\n")
        assert len(text) <= 30
        assert "99 nodes" in text  # the load-bearing count survives

    def test_summary_shows_hubs_and_chains(self):
        data = _data(
            hubs=[_hub("thread/spine", 2), _hub("decision/rail", 1)],
            chains=[["decision/rail", "thread/spine"]],
        )
        text = _render(data)
        assert "HUBS" in text and "CHAINS" in text
        assert "thread/spine" in text
        assert "decision/rail → thread/spine" in text

    def test_detailed_adds_census_and_orphan_listing(self):
        data = _data(
            hubs=[_hub("thread/spine", 2)],
            census=[["ref", 2, False], ["blocks", 1, True]],
            orphan_list=["session/s1", "session/s2"],
        )
        summary = _render(data, zoom=Zoom.SUMMARY)
        assert "session/s1" not in summary  # orphans stay a count at SUMMARY
        detailed = _render(data, zoom=Zoom.DETAILED)
        assert "EDGES" in detailed and "blocks" in detailed
        assert "session/s1" in detailed  # listed at DETAILED

    def test_full_shows_all_chains(self):
        chains = [[f"k/{i}", f"k/{i}b"] for i in range(6)]
        data = _data(hubs=[_hub("k/0b", 1)], chains=chains)
        summary = _render(data)
        full = _render(data, zoom=Zoom.FULL)
        # SUMMARY caps at 3 chains; FULL shows all 6.
        assert summary.count(" → ") == 3
        assert full.count(" → ") == 6

    def test_typed_predicate_visible_in_hub_mix(self):
        data = _data(hubs=[
            _hub("thread/spine", 3, predicates=[["ref", 2], ["blocks", 1]]),
        ])
        text = _render(data)
        assert "blocks" in text  # typed edge shows in the hub predicate mix

    def test_summary_row_sheds_mix_before_clipping(self):
        preds = [[f"pred{i}", 8 - i] for i in range(6)]
        data = _data(hubs=[_hub("thread/spine", 30, predicates=preds)])
        text = _render(data, width=44)
        assert all(len(ln) <= 44 for ln in text.splitlines())


class TestRegisters:
    def test_empty_graph(self):
        assert "No facts" in _render(_data(nodes=0))

    def test_piped_carries_full_addresses_and_census(self):
        data = _data(
            hubs=[_hub("thread/spine", 2)],
            census=[["ref", 2, False]],
            orphan_list=["session/s1"],
        )
        text = _render(data, piped=True)
        assert "thread/spine" in text
        assert "session/s1" in text  # orphans carried whole on the agent channel
        assert "ref" in text

    def test_register_parity(self):
        data = _data(
            hubs=[
                _hub("thread/spine", 3, tier="high",
                     predicates=[["ref", 2], ["blocks", 1]]),
                _hub("decision/design/rail", 1, tier="mid"),
            ],
            chains=[["decision/design/rail", "thread/spine"]],
            orphan_list=["session/s1"],
            census=[["ref", 3, False], ["blocks", 1, True]],
        )
        assert_register_parity(
            graph_view, data,
            load_bearing=[
                "thread/spine", "decision/design/rail", "blocks",
                "3 nodes", "orphans",
            ],
        )
