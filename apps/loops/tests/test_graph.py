"""Graph — the ref/edge-graph view (build-1).

Covers the net-new chain traversal (memoized DFS, cycle guard, depth cap,
dangling refs, longest-chain correctness), the fetch projection over a real
store, and the lens on both registers (hubs / chains / orphans / census, zoom
rungs, shed-before-clip, channel faithfulness). Channel parity is pinned by the
harness; the cross-command grammar golden carries the byte-level surface.
"""
from __future__ import annotations

from painted import Zoom

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view
from loops.commands.fetch import (
    _longest_chains,
    _strongly_connected,
    _top_chains,
    fetch_graph,
)
from loops.lenses.graph import graph_view

from .helpers import block_to_text
from .parity import assert_register_parity


def _ctx(reporter=None) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter())

_LAST = 1735733100.0


def _adj(pairs: dict) -> dict:
    """Build an adjacency map (source → [(target, 'ref'), ...])."""
    return {src: [(t, "ref") for t in tgts] for src, tgts in pairs.items()}


def _hub(
    address,
    inbound,
    *,
    tier="mid",
    predicates=None,
    last=_LAST,
    outbound=0,
    in_addrs=(),
    out_addrs=(),
):
    return {
        "address": address,
        "kind": address.split("/", 1)[0],
        "key": address.split("/", 1)[1],
        "tier": tier,
        "inbound": inbound,
        "outbound": outbound,
        "predicates": predicates or [["ref", inbound]],
        "in_addrs": list(in_addrs),
        "out_addrs": list(out_addrs),
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
        assert chains["a"][0] == ["a", "b", "c", "d"]
        assert chains["b"][0] == ["b", "c", "d"]
        # Predicates ride parallel to the path — head None, one label per hop.
        assert chains["a"][1] == [None, "ref", "ref", "ref"]

    def test_cycle_does_not_hang(self):
        # a→b→c→a is a pure cycle — the per-path guard skips the back-edge.
        chains, _trunc, _exh = _longest_chains(_adj({"a": ["b"], "b": ["c"], "c": ["a"]}))
        # Terminates, bounded at the ring size, and never repeats a node.
        for node in ("a", "b", "c"):
            path = chains[node][0]
            assert 1 <= len(path) <= 3
            assert len(set(path)) == len(path)  # no node twice
        assert max(len(p) for p, _ in chains.values()) == 3

    def test_depth_cap(self):
        # A chain longer than the cap is truncated at `cap` nodes, not crashed.
        chain = {str(i): [str(i + 1)] for i in range(50)}
        chain["50"] = []
        chains, _trunc, _exh = _longest_chains(_adj(chain), cap=8)
        assert max(len(p) for p, _ in chains.values()) == 8

    def test_depth_cap_marks_truncated(self):
        # A 300-node path with the real cap reports a length-128 chain FLAGGED
        # truncated — the cut is disclosed, never silent (review finding 3).
        chain = {str(i): [str(i + 1)] for i in range(300)}
        chain["300"] = []
        chains, truncated, _exh = _longest_chains(_adj(chain))
        assert len(chains["0"][0]) == 128
        assert "0" in truncated
        top = _top_chains(chains, truncated)
        assert top[0]["truncated"] is True
        assert len(top[0]["path"]) == 128
        assert len(top[0]["predicates"]) == 128  # parallel to the path

    def test_cycle_memo_not_poisoned_by_visit_order(self):
        # Regression (finding 2): C is reached first via A→B→C (where C→B is a
        # back-edge, skipped) and later via D→C. A tainted C result must NOT be
        # cached, or D→C→B is lost. D must find ['D','C','B'] regardless of order.
        adj = _adj({"A": ["B"], "B": ["C"], "C": ["B"], "D": ["C"]})
        import itertools

        for order in itertools.permutations(["A", "B", "C", "D"]):
            reordered = {k: adj[k] for k in order}
            chains, _trunc, _exh = _longest_chains(reordered)
            assert chains["D"][0] == ["D", "C", "B"], f"order {order} -> {chains['D']}"

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
            assert len(chains["X"][0]) == 6, f"order {order} -> {chains['X']}"

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
        assert top == [{
            "path": ["a", "b", "c", "d"],
            "predicates": [None, "ref", "ref", "ref"],
            "truncated": False,
        }]

    def test_top_chains_needs_an_edge(self):
        # Isolated nodes (len-1 paths) are not chains.
        chains, truncated, _exh = _longest_chains(_adj({"a": [], "b": []}))
        assert _top_chains(chains, truncated) == []

    def test_predicate_retained_through_walk(self):
        # (c) The predicate that entered each hop survives the DFS — mixed
        # predicates along one chain are all recorded, parallel to the path.
        adj = {
            "a": [("b", "blocks")], "b": [("c", "ref")], "c": [("d", "owner")],
            "d": [],
        }
        chains, _trunc, _exh = _longest_chains(adj)
        assert chains["a"] == (
            ["a", "b", "c", "d"], [None, "blocks", "ref", "owner"],
        )

    def test_predicate_hop_label_is_deterministic_when_parallel(self):
        # A node reaching one target via >1 predicate labels the hop with the
        # lexicographically smallest — a stable label, not a correctness axis.
        adj = {"a": [("b", "ref"), ("b", "blocks")], "b": []}
        chains, _trunc, _exh = _longest_chains(adj)
        assert chains["a"] == (["a", "b"], [None, "blocks"])


class TestSCC:
    def test_pure_dag_reports_no_cycles(self):
        sccs, self_loops = _strongly_connected(_adj({
            "a": ["b"], "b": ["c"], "c": [],
        }))
        assert sccs == []
        assert self_loops == []

    def test_three_node_cycle_is_one_scc(self):
        sccs, self_loops = _strongly_connected(_adj({
            "a": ["b"], "b": ["c"], "c": ["a"],
        }))
        assert sccs == [["a", "b", "c"]]
        assert self_loops == []

    def test_self_loop_reported_distinctly(self):
        # A self-edge is a size-1 SCC Tarjan would not surface — reported as a
        # self-loop, kept OUT of the multi-node scc list.
        sccs, self_loops = _strongly_connected(_adj({"a": ["a"], "b": []}))
        assert sccs == []
        assert self_loops == ["a"]

    def test_scc_and_self_loop_coexist(self):
        sccs, self_loops = _strongly_connected(_adj({
            "a": ["b"], "b": ["a"], "c": ["c"], "d": [],
        }))
        assert sccs == [["a", "b"]]
        assert self_loops == ["c"]

    def test_large_cycle_is_iterative(self):
        # A cycle far deeper than the recursion limit must not blow the stack
        # (iterative Tarjan — same guarantee as the chain walk's depth cap).
        ring = {str(i): [str((i + 1) % 5000)] for i in range(5000)}
        sccs, self_loops = _strongly_connected(_adj(ring))
        assert len(sccs) == 1
        assert len(sccs[0]) == 5000
        assert self_loops == []


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
            "predicates": [None, "ref", "ref"],
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
            "predicates": [None, "ref"],
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

    def test_outbound_resolved_only_dangling_not_counted(self, tmp_path):
        # a→b→c resolves; c→ghost dangles. Each hub's →M counts RESOLVED
        # outbound only — c's dangling ref does NOT bump its →M.
        data = fetch_graph(self._dangling_fixture(tmp_path))
        hubs = {h["address"]: h for h in data["hubs"]}
        # b → c (one resolved outbound); its ref lands on a node.
        assert hubs["decision/b"]["outbound"] == 1
        assert hubs["decision/b"]["out_addrs"] == ["decision/c"]
        # c → ghost is dangling — not a resolved edge, so →M stays 0.
        assert hubs["decision/c"]["outbound"] == 0
        assert hubs["decision/c"]["out_addrs"] == []
        # The dangling ref stays in the top-line counter, not in any →M.
        assert data["dangling"] == 1
        # Inbound neighbor addresses are resolved node sources.
        assert hubs["decision/c"]["in_addrs"] == ["decision/b"]
        assert hubs["decision/b"]["in_addrs"] == ["decision/a"]

    # --- build-2: key honoring + three-bucket partition -------------------
    def _scoped_fixture(self, tmp_path):
        """decision (by topic) + note (collect), engineered so that under
        ``--key architecture/`` all three buckets are nonzero at once:

        * dangling — ``decision:ghost`` resolves nowhere;
        * filter_excluded — ``decision:design/out`` is a real node but out of
          the ``architecture/`` scope;
        * keyless — a collect note (kept in scope by a ``summary`` prefix that
          matches ``--key``, yet still sourceless) refs an in-scope decision.
        """
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "s.vertex"
        vp.write_text(
            'name "s"\nstore "./s.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  note { fold { items "collect" 50 } }\n'
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        prog.receive(Fact.of(
            "decision", "kyle", ts=t, topic="architecture/base", message="x"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 1, topic="architecture/edge",
            message="x", ref="decision:design/out"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 2, topic="design/out", message="x"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 3, topic="architecture/dead",
            message="x", ref="decision:ghost"))
        prog.receive(Fact.of(
            "note", "kyle", ts=t + 4, message="see", summary="architecture/see",
            ref="decision:architecture/base"))
        return vp

    def test_key_honored_narrows_nodes(self, tmp_path):
        vp = self._scoped_fixture(tmp_path)
        full = fetch_graph(vp)
        scoped = fetch_graph(vp, key="architecture/")
        assert full["nodes"] == 5
        assert scoped["nodes"] < full["nodes"]  # --key honored, not dropped
        assert "decision/design/out" not in {h["address"] for h in scoped["hubs"]}

    def test_three_bucket_partition_simultaneously(self, tmp_path):
        data = fetch_graph(self._scoped_fixture(tmp_path), key="architecture/")
        assert data["dangling"] == 1
        assert data["dangling_list"] == ["decision:ghost"]
        assert data["filter_excluded"] == 1
        assert data["filter_excluded_list"] == ["decision:design/out"]
        assert data["unsourced_inbound"] >= 1  # keyless note → in-scope decision

    def test_unfiltered_has_no_filter_excluded(self, tmp_path):
        # Without a scope, global IS in-scope — filter_excluded is structurally
        # zero and the honest dangling (the ghost alone) stands.
        data = fetch_graph(self._scoped_fixture(tmp_path))
        assert data["filter_excluded"] == 0
        assert data["dangling"] == 1
        assert data["dangling_list"] == ["decision:ghost"]

    # --- build-2: --edge predicate selection ------------------------------
    def _typed_edge_fixture(self, tmp_path):
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "e.vertex"
        vp.write_text(
            'name "e"\nstore "./e.db"\n\n'
            "loops {\n"
            '  person { fold { items "by" "handle" } }\n'
            "  decision {\n"
            '    fold { items "by" "topic" }\n'
            '    edge "stakeholder" targets="person"\n'
            "  }\n"
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        prog.receive(Fact.of("person", "kyle", ts=t, handle="alice", name="Alice"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 1, topic="a", message="x",
            stakeholder="alice", ref="decision:b"))
        prog.receive(Fact.of("decision", "kyle", ts=t + 2, topic="b", message="x"))
        return vp

    def test_edge_predicate_filter(self, tmp_path):
        vp = self._typed_edge_fixture(tmp_path)
        assert {c[0] for c in fetch_graph(vp)["census"]} == {"ref", "stakeholder"}

        stake = fetch_graph(vp, edge="stakeholder")
        assert {c[0] for c in stake["census"]} == {"stakeholder"}
        stake_hubs = {h["address"] for h in stake["hubs"]}
        assert "person/alice" in stake_hubs  # stakeholder sink survives
        assert "decision/b" not in stake_hubs  # ref-only inbound excluded

        refonly = fetch_graph(vp, edge="ref")
        assert {c[0] for c in refonly["census"]} == {"ref"}
        ref_hubs = {h["address"] for h in refonly["hubs"]}
        assert "decision/b" in ref_hubs
        assert "person/alice" not in ref_hubs

    def test_edge_comma_or_keeps_both(self, tmp_path):
        both = fetch_graph(self._typed_edge_fixture(tmp_path), edge="ref,stakeholder")
        assert {c[0] for c in both["census"]} == {"ref", "stakeholder"}

    # --- build-2: chain predicate retention (fetch level) -----------------
    def test_chain_carries_mixed_predicate_labels(self, tmp_path):
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "m.vertex"
        vp.write_text(
            'name "m"\nstore "./m.db"\n\n'
            "loops {\n"
            '  person { fold { items "by" "handle" } }\n'
            "  decision {\n"
            '    fold { items "by" "topic" }\n'
            '    edge "stakeholder" targets="person"\n'
            "  }\n"
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        prog.receive(Fact.of("person", "kyle", ts=t, handle="alice", name="Alice"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 1, topic="y", message="x", stakeholder="alice"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 2, topic="x", message="x", ref="decision:y"))
        # x --ref--> y --stakeholder--> alice: the predicate of each hop is kept.
        assert fetch_graph(vp)["chains"] == [{
            "path": ["decision/x", "decision/y", "person/alice"],
            "predicates": [None, "ref", "stakeholder"],
            "truncated": False,
        }]

    # --- build-2: cycle census over the resolved graph --------------------
    def test_fetch_cycle_census(self, tmp_path):
        from atoms import Fact
        from engine import load_vertex_program

        vp = tmp_path / "c.vertex"
        vp.write_text(
            'name "c"\nstore "./c.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        prog = load_vertex_program(vp)
        t = 1735732800.0
        # Mutual refs → a 2-node SCC. The chain walk must still terminate.
        prog.receive(Fact.of(
            "decision", "kyle", ts=t, topic="a", message="x", ref="decision:b"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=t + 1, topic="b", message="x", ref="decision:a"))
        data = fetch_graph(vp)
        assert data["cycles"]["sccs"] == [["decision/a", "decision/b"]]
        assert data["cycles"]["self_loops"] == []
        # The near-DAG fixture reports empty cycles (the common case is clean).
        clean = fetch_graph(self._dangling_fixture(tmp_path))
        assert clean["cycles"] == {"sccs": [], "self_loops": []}


class TestBuild2CLI:
    def _vp(self, tmp_path):
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
        prog.receive(Fact.of(
            "decision", "kyle", ts=1735732800.0, topic="architecture/x", message="x"))
        prog.receive(Fact.of(
            "decision", "kyle", ts=1735732801.0, topic="design/y", message="x",
            ref="decision:architecture/x"))
        return vp

    def test_edge_without_graph_lens_refuses(self, tmp_path):
        reporter = BufferReporter()
        rc = read_view.run([str(self._vp(tmp_path)), "--edge", "ref"], _ctx(reporter))
        assert rc == 2
        assert "--lens graph" in reporter.err_text  # teaching message, not silent

    def test_edge_with_graph_lens_honored(self, tmp_path):
        reporter = BufferReporter()
        rc = read_view.run(
            [str(self._vp(tmp_path)), "--lens", "graph", "--edge", "ref"],
            _ctx(reporter),
        )
        assert rc == 0

    def test_key_honored_on_graph_lens_via_cli(self, tmp_path):
        # friction:graph-fetch-drops-key — --key used to be byte-identically
        # dropped; the scoped JSON node count must now be strictly smaller.
        import json

        vp = self._vp(tmp_path)
        r_full = BufferReporter()
        read_view.run([str(vp), "--lens", "graph", "--json"], _ctx(r_full))
        r_scoped = BufferReporter()
        read_view.run(
            [str(vp), "--lens", "graph", "--key", "architecture/", "--json"],
            _ctx(r_scoped),
        )
        full = json.loads(r_full.out_text)
        scoped = json.loads(r_scoped.out_text)
        assert scoped["nodes"] < full["nodes"]


class TestZooms:
    def test_minimal_is_one_line(self):
        data = _data(hubs=[_hub("thread/spine", 1)], nodes=4, orphan_list=["a/x"])
        text = _render(data, zoom=Zoom.MINIMAL).rstrip("\n")
        assert "\n" not in text
        assert "4 nodes" in text and "1 orphans" in text

    def test_minimal_wraps_hub_never_sheds(self):
        # The top-hub segment is content, not chrome — it must survive on the
        # narrow TTY (faithful with piped, which never sheds). Overflow wraps
        # onto a hanging-indented continuation line instead of being dropped.
        data = _data(hubs=[_hub("k/very-long-address-here", 3)], nodes=99)
        text = _render(data, zoom=Zoom.MINIMAL, width=30).rstrip("\n")
        assert "99 nodes" in text  # the load-bearing count survives
        assert "k/very-long-address-here ←3" in text  # hub not shed
        assert "\n" in text  # wrapped, not clipped

    def test_minimal_hub_faithful_across_registers(self):
        data = _data(hubs=[_hub("k/very-long-address-here", 3)], nodes=99)
        tty = _render(data, zoom=Zoom.MINIMAL, width=30)
        piped = _render(data, zoom=Zoom.MINIMAL, piped=True)
        # The hub segment appears on both registers regardless of TTY width.
        assert "k/very-long-address-here ←3" in tty
        assert "k/very-long-address-here ←3" in piped

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

    def test_hub_row_shows_outbound_degree_both_registers(self):
        # ←N →M appears on the hub row on the TTY AND the piped column.
        data = _data(hubs=[_hub("thread/spine", 3, outbound=2)])
        tty = _render(data)
        assert "←3 →2" in tty
        piped = _render(data, piped=True)
        assert "←3 →2" in piped

    def test_minimal_gains_top_hub_segment(self):
        data = _data(hubs=[_hub("decision/foo", 31), _hub("thread/bar", 4)])
        text = _render(data, zoom=Zoom.MINIMAL).rstrip("\n")
        # Top hub (inbound-sorted) rides the rollup as the rightmost segment.
        assert "hubs decision/foo ←31" in text

    def test_minimal_omits_hub_segment_when_no_hubs(self):
        data = _data(hubs=[], nodes=3, orphan_list=["a/x"])
        text = _render(data, zoom=Zoom.MINIMAL)
        assert "hubs " not in text

    def test_detailed_neighbor_lists_tty_capped(self):
        # -v renders ← / → neighbor lines under the hub; the TTY caps at ~5.
        ins = [f"decision/n{i}" for i in range(7)]
        data = _data(hubs=[
            _hub("thread/spine", 7, outbound=1,
                 in_addrs=ins, out_addrs=["thread/x"]),
        ])
        text = _render(data, zoom=Zoom.DETAILED)
        assert "← decision/n0, decision/n1" in text
        assert "+2" in text  # 7 inbound, capped at 5 → "+2" overflow
        assert "→ thread/x" in text

    def test_detailed_neighbor_lists_piped_uncapped(self):
        ins = [f"decision/n{i}" for i in range(7)]
        data = _data(hubs=[
            _hub("thread/spine", 7, in_addrs=ins, out_addrs=["thread/x"]),
        ])
        text = _render(data, zoom=Zoom.DETAILED, piped=True)
        for i in range(7):
            assert f"decision/n{i}" in text  # all 7, uncapped on the agent channel
        assert "+2" not in text

    def test_neighbor_line_omitted_when_side_empty(self):
        # A hub with no outbound neighbors emits no empty "→ " stub.
        data = _data(hubs=[
            _hub("thread/spine", 2, in_addrs=["decision/a"], out_addrs=[]),
        ])
        for piped in (False, True):
            text = _render(data, zoom=Zoom.DETAILED, piped=piped)
            assert "← decision/a" in text
            lines = [ln.strip() for ln in text.splitlines()]
            assert not any(ln == "→" or ln.startswith("→ ") and ln[2:].strip() == ""
                           for ln in lines)

    def test_neighbor_lists_absent_at_summary(self):
        # The neighbor lists are a -v disclosure — SUMMARY stays terse.
        data = _data(hubs=[
            _hub("thread/spine", 1, in_addrs=["decision/a"]),
        ])
        assert "← decision/a" not in _render(data, zoom=Zoom.SUMMARY)

    def test_chain_leaf_vs_truncated_at_detailed(self):
        # A chain that ENDS gets (leaf); a truncated one keeps ⋯ — never both.
        data = _data(
            hubs=[_hub("k/a", 1)],
            chains=[
                {"path": ["k/a", "k/b"], "truncated": False},
                {"path": ["k/x", "k/y"], "truncated": True},
            ],
        )
        tty = _render(data, zoom=Zoom.DETAILED)
        assert "k/a → k/b (leaf)" in tty
        assert "k/x → k/y ⋯" in tty
        assert "(leaf)" not in tty.split("k/x")[1]  # truncated line has no leaf
        piped = _render(data, zoom=Zoom.DETAILED, piped=True)
        assert "k/a → k/b  leaf" in piped
        assert "k/x → k/y  truncated" in piped

    def test_chain_leaf_absent_at_summary(self):
        data = _data(
            hubs=[_hub("k/a", 1)],
            chains=[{"path": ["k/a", "k/b"], "truncated": False}],
        )
        assert "(leaf)" not in _render(data, zoom=Zoom.SUMMARY)


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


class TestBuild2Render:
    def test_chain_predicate_labels_render_both_registers(self):
        # A chain carrying predicates renders labelled hops (the box-draw glyph
        # is decorative; the predicate WORD is the load-bearing part).
        chain = {
            "path": ["decision/x", "decision/y", "person/alice"],
            "predicates": [None, "ref", "stakeholder"],
            "truncated": False,
        }
        data = _data(hubs=[_hub("decision/x", 1)], chains=[chain])
        expect = "decision/x ─ref→ decision/y ─stakeholder→ person/alice"
        assert expect in _render(data, zoom=Zoom.FULL)
        assert expect in _render(data, zoom=Zoom.FULL, piped=True)

    def test_chain_without_predicates_stays_bare_arrow(self):
        # A synthetic chain with no predicate data degrades to bare arrows — no
        # spurious labels, and the existing ` → ` grammar is unchanged.
        data = _data(
            hubs=[_hub("k/a", 1)],
            chains=[{"path": ["k/a", "k/b"], "truncated": False}],
        )
        text = _render(data)
        assert "k/a → k/b" in text
        assert "k/a ─" not in text  # no labelled hop when predicates absent

    def test_filter_excluded_disclosed_both_registers(self):
        data = _data(hubs=[_hub("decision/x", 1)])
        data["dangling"] = 1
        data["filter_excluded"] = 3
        assert "3 out-of-scope refs" in _render(data, zoom=Zoom.DETAILED)
        assert "filter_excluded: 3" in _render(data, piped=True)

    def test_cycles_section_and_disclosure(self):
        data = _data(hubs=[_hub("decision/a", 1)])
        data["cycles"] = {
            "sccs": [["decision/a", "decision/b"]],
            "self_loops": ["decision/c"],
        }
        # SUMMARY discloses the count; -v lists members (SCCs and self-loops
        # distinctly); the agent channel carries every member.
        assert "2 cycles" in _render(data, zoom=Zoom.SUMMARY)
        detailed = _render(data, zoom=Zoom.DETAILED)
        assert "CYCLES" in detailed
        assert "decision/a ↔ decision/b" in detailed
        assert "decision/c ↺ self" in detailed
        piped = _render(data, piped=True)
        assert "cycles: 2" in piped
        assert "scc: decision/a decision/b" in piped
        assert "self-loop: decision/c" in piped

    def test_clean_graph_hides_cycle_and_scope_disclosure(self):
        # The common case (near-DAG, no filter) shows neither a cycle line nor
        # a filter_excluded disclosure — zeros stay hidden, no new chrome.
        data = _data(hubs=[_hub("decision/x", 1)])
        text = _render(data, zoom=Zoom.DETAILED)
        assert "cycle" not in text.lower()
        assert "out-of-scope" not in text

    def test_register_parity_predicate_chain(self):
        data = _data(
            hubs=[_hub("decision/x", 2, tier="high")],
            chains=[{
                "path": ["decision/x", "person/alice"],
                "predicates": [None, "stakeholder"],
                "truncated": False,
            }],
        )
        assert_register_parity(
            graph_view, data,
            load_bearing=["decision/x", "person/alice", "stakeholder"],
        )
