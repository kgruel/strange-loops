# SCC census — dual-reading discount pass

Rider on S3 (graph build-2, b163fa4/3a94cc5): *"dual-reading discount pass on the
SCC census before designing against it."* The question was whether the 40 SCCs
that falsified the ref-graph DAG assumption are real, or artifacts of S1's
dual-reading of legacy slash-form addresses.

**Answer: the discount for aliasing is exactly zero. Dual-reading creates no
spurious edges in this store. But the census is still not measuring what the DAG
assumption was about — every one of the 41 SCCs is a product of *entity-node*
granularity, and the underlying fact graph is a DAG.**

## Reproduction

Census mechanism: `fetch_graph` (apps/loops/src/loops/commands/fetch.py:1132)
reverses `Surface.inbound_edges` into a resolved node→node adjacency, then runs
iterative Tarjan (`_strongly_connected`, fetch.py:996). Membership goes through
`_resolves_to_node` → `atoms.Address.readings`, the S1 dual-reading contract.

Reproduced live against `.loops/data/project.db`:

| | at commit (2026-07-18) | today (2026-07-26) |
|---|---|---|
| SCCs | 40 | 41 |
| largest | 159 | 165 |
| self-loops | 13 | 13 |

Drift is store growth over the wave, not a mechanism change. All numbers below
are today's.

Size distribution: 165, 23, 21, 10, 10, 7, 6, 6, 5×4, 4×4, 3×7, 2×18.
Long tail of pairs; one dominant giant component holding 165 of the nodes.

## Classification

Total edges in the resolved adjacency: **1783**, of which 1544 matched under an
exact kind-qualified reading, 222 under the slash bare-dual reading only, 17
under a literal bare key.

**(b) aliasing artifact — 0 SCCs.** The test that matters is *fan-out*: does any
single raw ref resolve, via its two readings, to more than one node? If yes, the
extra target is a spurious edge. Measured: **0 of 1783 refs resolve to >1 node.**
Pruning fan-out leaves the census bit-identical (41 SCCs, largest 165). The 222
bare-dual matches are not aliases — they are the *repair* S1's sol-P1 fix
existed to make. `ref=paradigm/three-shapes-recursive` reaching
`decision/paradigm/three-shapes-recursive` is the author's intent; the legacy
kind-qualified reading alone would send it to a nonexistent `paradigm` kind.
Deleting bare-only matches wholesale ("strict" adjacency) drops the census to 35
SCCs, but that is not a discount — it is deleting 239 real edges. `paradigm/`,
`architecture/`, `design/` are topic prefixes that collide with kind names, which
is exactly the ambiguity dual-reading preserves rather than guesses.

**(c) dangling/resolution artifact — 0.** Structurally impossible here: the
adjacency is built only from `target in node_addrs and source in node_addrs`
(fetch.py:1228–1238). Unresolved refs land in the `dangling` / `filter_excluded`
buckets and never reach Tarjan.

**(d) self-loop trivia — 13, already segregated.** All 13 are a topic's later
fact carrying a ref to its own address (7 colon-form, 6 legacy slash). Tarjan
never surfaces them as SCCs; the census reports them in a separate `self_loops`
list. Real in the data, but not cycles anyone designs against.

**(a) genuine semantic cycle — 41 at entity granularity, ~0 at fact
granularity.** This is the finding the rider was reaching for, arrived at from a
different direction.

Rebuilding the graph at *fact* granularity — each emitted fact as its own edge,
timestamped — gives 1961 ref edges, of which **1958 point backward in time**: the
target entity's first appearance precedes the emitting fact. Only 3 are forward
(all three are same-session emits where a plan/thread named a sibling before the
sibling's first fact landed; listed below). The fact-level ref graph is a DAG
modulo three edges.

The cycles appear because the fold collapses every fact of a topic into one node
and takes the **UNION of its refs across all time**. `decision/X` emitted at t1
refs `Y`; `Y` at t3 refs `X`; `X` re-emitted at t5 refs `Z`. At fact granularity
that is a chain; at entity granularity `X` is one node holding all three refs, so
`X↔Y` closes. Confirming the mechanism: **41 of 41 SCCs contain at least one
re-emitted (multi-fact) entity.** In the giant component, 53 of 165 members are
re-emitted.

Anomalous forward edges:
- `plan/lightweight-emission-ergonomics → plan/salience-driven-display-impl`
- `decision/design/key-prefix-as-fold-key-aware-filter-primitive → decision/practice/multi-prefix-emit-as-routing-paths`
- `thread/vouch-substrate-session-owed → decision/design/attestation-substrate-with-progressive-policy`

## Discounted count

| class | SCCs |
|---|---|
| aliasing artifact (dual-reading) | 0 |
| dangling / resolution artifact | 0 |
| genuine at entity granularity | 41 |
| …of those, surviving at fact granularity | ~0 (fact graph is a DAG bar 3 edges) |
| self-loops (segregated, not SCCs) | 13 |

## Design against this

1. The DAG-falsification **stands as stated** — the entity-level ref graph is
   emphatically not a near-DAG, and no aliasing discount touches that.
2. But it is falsified for a different reason than the audit assumed: node
   granularity + ref UNION across re-emission, not mutual referencing.
3. Anything consuming the ref graph must therefore state its granularity. At
   fact granularity a topological order exists (time); at entity granularity it
   does not.
4. For batch-emit (thread:ref-graph-dag-assumption-audit): ordering a batch by
   emission sequence is sound, because emits reference already-existing entities
   — the 1958/1961 backward ratio is that invariant measured. Do not try to
   topologically sort the *entity* graph; it has no order.
5. S1's dual-reading is exonerated as a cycle source and should not be
   discounted away. The colon-form rewrite-at-rest migration (deferred per S1-F2)
   would not change the census by a single SCC.
