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
        "chains": [
            c if isinstance(c, dict) else {"path": list(c), "truncated": False}
            for c in chains
        ],
        "orphan_list": list(orphan_list),
        "census": [list(c) for c in census],
    }


def _render(data, zoom=Zoom.SUMMARY, width=100, *, piped=False) -> str:
    return block_to_text(graph_view(data, zoom, width, piped=piped), use_ansi=False)


class TestTraversal:
    def test_longest_chain_correctness(self):
        # a→b→c→d is the longest; the b→e branch is shorter.
        chains, _trunc, _exh = _longest_chains(_adj({
            "a": ["b"], "b": ["c", "e"], "c": ["d"], "d": [], "e": [],
        }))
        assert chains["a"] == ["a", "b", "c", "d"]
        assert chains["b"] == ["b", "c", "d"]

    def test_cycle_does_not_hang(self):
        # a→b→c→a is a pure cycle — the per-path guard skips the back-edge.
        chains, _trunc, _exh = _longest_chains(_adj({"a": ["b"], "b": ["c"], "c": ["a"]}))
        # Terminates, bounded at the ring size, and never repeats a node.
        for node in ("a", "b", "c"):
            assert 1 <= len(chains[node]) <= 3
            assert len(set(chains[node])) == len(chains[node])  # no node twice
        assert max(len(p) for p in chains.values()) == 3

    def test_depth_cap(self):
        # A chain longer than the cap is truncated at `cap` nodes, not crashed.
        chain = {str(i): [str(i + 1)] for i in range(50)}
        chain["50"] = []
        chains, _trunc, _exh = _longest_chains(_adj(chain), cap=8)
        assert max(len(p) for p in chains.values()) == 8

    def test_depth_cap_marks_truncated(self):
        # A 300-node path with the real cap reports a length-128 chain FLAGGED
        # truncated — the cut is disclosed, never silent (review finding 3).
        chain = {str(i): [str(i + 1)] for i in range(300)}
        chain["300"] = []
        chains, truncated, _exh = _longest_chains(_adj(chain))
        assert len(chains["0"]) == 128
        assert "0" in truncated
        top = _top_chains(chains, truncated)
        assert top[0]["truncated"] is True
        assert len(top[0]["path"]) == 128

    def test_cycle_memo_not_poisoned_by_visit_order(self):
        # Regression (finding 2): C is reached first via A→B→C (where C→B is a
        # back-edge, skipped) and later via D→C. A tainted C result must NOT be
        # cached, or D→C→B is lost. D must find ['D','C','B'] regardless of order.
        adj = _adj({"A": ["B"], "B": ["C"], "C": ["B"], "D": ["C"]})
        import itertools

        for order in itertools.permutations(["A", "B", "C", "D"]):
            reordered = {k: adj[k] for k in order}
            chains, _trunc, _exh = _longest_chains(reordered)
            assert chains["D"] == ["D", "C", "B"], f"order {order} -> {chains['D']}"

    def test_reachable_longest_survives_visit_order(self):
        # X→N→A→B→C→D (length 6) must be found from X in ANY iteration order —
        # N→A is a back-reference into an already-explored region.
        adj = _adj({
            "A": ["N", "B"], "B": ["C"], "C": ["D"],
            "N": ["A"], "X": ["N"], "D": [],
        })
        import itertools

        for order in itertools.permutations(["A", "B", "C", "N", "X", "D"]):
            reordered = {k: adj[k] for k in order}
            chains, _trunc, _exh = _longest_chains(reordered)
            assert len(chains["X"]) == 6, f"order {order} -> {chains['X']}"

    def test_visit_budget_flags_approximate(self):
        # A tiny budget exhausts and flags the result approximate.
        chain = {str(i): [str(i + 1)] for i in range(50)}
        chain["50"] = []
        _chains, _trunc, exhausted = _longest_chains(_adj(chain), budget=5)
        assert exhausted is True

    def test_top_chains_drops_subpaths(self):
        # b→c→d is contained in a→b→c→d — only the maximal chain survives.
        chains, truncated, _exh = _longest_chains(_adj({
            "a": ["b"], "b": ["c"], "c": ["d"], "d": [],
        }))
        top = _top_chains(chains, truncated)
        assert top == [{"path": ["a", "b", "c", "d"], "truncated": False}]

    def test_top_chains_needs_an_edge(self):
        # Isolated nodes (len-1 paths) are not chains.
        chains, truncated, _exh = _longest_chains(_adj({"a": [], "b": []}))
        assert _top_chains(chains, truncated) == []


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
        assert data["chains"] == [{
            "path": ["decision/a", "decision/b", "decision/c"],
            "truncated": False,
        }]
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
        assert data["chains"] == [{
            "path": ["decision/design/rail", "thread/spine"],
            "truncated": False,
        }]
        hub = next(h for h in data["hubs"] if h["address"] == "thread/spine")
        assert hub["inbound"] == 1
        assert hub["predicates"] == [["ref", 1]]
        # JSON-clean: last is a float epoch, not a datetime.
        assert isinstance(hub["last"], float)

    def test_unsourced_inbound_from_keyless_fact(self, tmp_path):
        # A keyless fact's ref counts toward a hub's ←N (true attention) but has
        # no node address to resolve a node→node edge from — so it shows up as
        # unsourced_inbound, disclosed not redefined (review finding 6).
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "u.vertex"
        vp.write_text(
            'name "u"\nstore "./u.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  note { fold { items "collect" 50 } }\n'
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        prog.receive(Fact.of("decision", "kyle", ts=t, topic="a", message="x"))
        # A keyless collect note that refs the decision — the ref has no source
        # node address.
        prog.receive(Fact.of("note", "kyle", ts=t + 1, message="see", ref="decision:a"))

        data = fetch_graph(vp)
        total_inbound = sum(h["inbound"] for h in data["hubs"])
        # decision/a is a hub with ←1 (the keyless note), but 0 resolved edges.
        assert data["edges"] == 0
        assert total_inbound == 1
        assert data["unsourced_inbound"] == 1
        # The arithmetic reconciles: edges + unsourced == summed hub inbound.
        assert data["edges"] + data["unsourced_inbound"] == total_inbound

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

    def test_piped_orphans_one_per_line(self):
        # The agent channel lists one orphan address per line (ledger parity),
        # never a single middot-joined blob (review finding 5).
        data = _data(
            hubs=[_hub("thread/spine", 1)],
            orphan_list=["session/s1", "session/s2", "session/s3"],
        )
        text = _render(data, piped=True)
        lines = [ln.strip() for ln in text.splitlines()]
        assert "session/s1" in lines
        assert "session/s2" in lines
        assert "session/s3" in lines
        # No orphan line joins multiple addresses with a middot blob.
        orphan_lines = [ln for ln in lines if ln.startswith("session/")]
        assert len(orphan_lines) == 3
        assert all(" · " not in ln for ln in orphan_lines)

    def test_piped_lifts_hub_and_chain_caps(self):
        # The agent channel carries ALL hubs and ALL chains at SUMMARY, where the
        # TTY caps at top-10 / top-3 (review finding 4).
        hubs = [_hub(f"k/n{i:02d}", 20 - i) for i in range(15)]
        chains = [[f"k/c{i}", f"k/c{i}b"] for i in range(6)]
        data = _data(hubs=hubs, chains=chains)
        piped = _render(data, piped=True)
        for i in range(15):
            assert f"k/n{i:02d}" in piped  # all 15 hubs, not just top 10
        assert piped.count(" → ") == 6  # all 6 chains, not just top 3
        # TTY still caps.
        tty = _render(data, zoom=Zoom.SUMMARY)
        assert tty.count(" → ") == 3

    def test_truncated_chain_discloses_on_both_registers(self):
        # A truncated chain gets a trailing ⋯ on the TTY and a 'truncated' token
        # piped (review finding 3).
        data = _data(
            hubs=[_hub("k/a", 1)],
            chains=[{"path": ["k/a", "k/b", "k/c"], "truncated": True}],
        )
        tty = _render(data)
        assert "⋯" in tty
        piped = _render(data, piped=True)
        assert "truncated" in piped

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
