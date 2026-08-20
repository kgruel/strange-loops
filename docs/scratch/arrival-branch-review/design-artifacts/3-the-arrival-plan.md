The Arrival Plan

Arrival substrate · implementation

# The Arrival Plan

The ruled implementation plan for the arrival substrate: two adversarially-reviewed waves through the libraries and the SDK, then the sidecar, the vectors, and a CLI rebuilt from scratch on top.

 Sibling to The Arrival Substrate, The Arrival Log, and The Migration Sidecar. Authority: the ratified architecture anchor 01M070N08HX69QAEQ3TRPY72CQ (declared-fold-order amendment #4) and seven ruled plan:arrival-* facts, Kyle-ratified 2026-08-17. Every slice below is ruled ground; deviation during implementation is reportable against these facts.

## §1The shape of the work

Two branches, each carried through one full impl-pipeline run — per-slice implementer with an independent empirical gate, a cross-family review of the whole branch diff, a simplify pass, and re-review to convergence — followed by a strictly sequential tail. The prior wave's review rounds are the reason for this shape: cross-family findings cluster at cross-slice seams, and the seams between the cuts are exactly where arrival can go subtly wrong.

Wave 1feat/arrival-libsSlices 0 + A–D. One pipeline run, merged --no-ff at convergence.

Wave 2SDK surfaceDesign fact ratifies after wave 1 merges. Public-surface bar.

Tail 1SidecarLive-store migration. Gitignore/gitattributes residue sweep rides it.

Tail 2VectorsInterleave-uniqueness families; oracle re-run over mirrored impls.

Tail 3CLI rebuildThin wrapper over the SDK, license to drop non-fitting concepts.

Main never holds a half-reshaped funnel: the cuts land together or not at all.

## §2Laws of the arc

Library correctness governs. No deviation for schedule pressure. The SDK is designed as an eventual public surface — Kyle's apps convert onto it over time as reference consumers, and that corpus is the basis for publicizing the system. Naming, API shape, and docs are held to that bar.

Scope law: libs only. Cuts A–D and the SDK touch libs/engine, libs/store, and later libs/sdk exclusively. apps/ is diff-empty across every slice, enforced mechanically at each gate. The census behind this: 113 non-test funnel references in libs, 64 in apps/loops — and every CLI site rides the residence.py API, so the funnel changes beneath it without a caller moving.

The hazard clock is accepted, explicitly. No live store flips format until its sidecar ceremony. Between wave-1 merge and migration, _receipt_order is gone from libs, so legacy multi-replica JSONL merge is not merely risky but removed. Kyle ruled both the fold-order hazard and the capability removal accepted; the trigger condition is behavioral and single-writer discipline covers it.

The vocabulary ratchet. Prior-CLI concepts must not leak into libs or SDK. An architecture-rule test carries a denylist over new identifiers and docstrings (jsonl_canonical, receipt_order, event-as-ordering, reanchor-as-operation, merge-touches-custody, rewind, mergeability/union discipline, the two CAS species) with a shrink-only allowlist for legacy modules until their cut dissolves them. The denylist is not fixed: growing it is a standing item in every review round — slice gates, cross-family rounds, and simplify all carry "candidate ratchet additions."

Ratify-gate one level down. Any decision whose blast radius exceeds its slice — a wire format, a record grammar — is proposed by a design agent, spot-checked and ratified by Kyle as its own design fact, and only then implemented against.

## §3Wave 1 — the five slices

0

### The arrival log primitive

All four cuts consume the primitive; nobody builds it inside cut A's sweep. Scope: file format and record grammar, minted genesis record, append, ordinal read, torn-line handling (_read_lines / _truncate_torn_line migrate here — arrival is where they are genuinely correct), and resume-from-offset designed in from the start.

Ratify-gateA design agent proposes the record grammar and the arrival file suffix name (collision-unchecked today); Kyle ratifies the design fact before any implementation launches. The vocabulary-ratchet seed list ratifies inside this same fact.

GateTwo-process concurrency against one store — never exercised empirically anywhere in the tree — is this slice's gate item: it is an append-log property.

A

### Authority

Arrival becomes canonical; the lineage genesis moves into it; records become complete. The residence.py funnel grows the arrival answer — the suffix switch at residence.py:56-62 is the whole mode flip — and the libs-side funnel semantics are swept: residence (23 refs), jsonl_store (23), vertex_reader (22), probe (12), preflight (8), compiler (6), canonical_audit (5), declaration/ceremony/handle (10), plus libs/store jsonl/compact (4). own_lineage's two writer ceremonies (absorb_genesis, adopt_lineage) re-point to arrival genesis.

GateThe authority test answered literally: delete every projection and everything still answers from arrival. Plus the libs/sign and observer-key-registry trace for file-position bindings (an anchor open item).

B

### Projections

catch_up/_rebuild re-point to arrival as source. The .jsonl becomes a second derived output, re-keyed to set membership — a mergeable projection has no stable byte offset. merge_store/receive_store are rewritten as append-into-arrival plus re-derivation of both projections, never direct index inserts. reanchor becomes a permanent refusal, retiring the queued log-rewrite ceremony. PR #8 dispositions landing here: discard R1-as-doctrine; keep test_merge_direction_is_deterministic.

GateTwo named empirical holes close here: (1) trace whether an index rebuild invalidates outstanding witness positions — rowid reassignment, "the natural next question"; (2) the semantic git merge driver for the derived JSONL projection, proven by actually performing a git merge of a JSONL projection, which has never been done.

C

### Ordering

Declared projection order lands: arrival or by KEY, with the substrate read primitive ordered(prefix=W, key=K) totalized by (K(record), record.id) — and id is never semantic time. _receipt_order dissolves with its residue swept in the same change, scoped to libs (the frozen sidecar's last-0.x reader keeps its copy by design). generate_lens.py generalizes from ts-only to arbitrary declared keys. CAS is rewritten as a qualified predicate over the arrival axis, preserving the lineage-filtered _decl.*-only semantics — including the token that escaped into the persisted intent record at ceremony.py:432. PR #8 dispositions: rewrite the CAS token coordinate to arrival head; rewrite the combined-read fold fork (a combined read declares a projection ordering, and the member-count fork disappears); keep Spec.replay_from, the VertexHandle checkpoint machinery, the benchmark arms, and Rule 17.

GateConformance lens vectors regenerate under declared keys; the projection taxonomy (arrival-stable / insertion-sensitive / order-independent) drives the checkpoint-dispatch tests.

D

### Surfaces

The one place that fights back. canonical_audit.py's entire offset/prefix custody model moves to arrival — including the default L1 gate (_check_offset, _suffix_unindexed, _check_last_line), not just --deep; the jsonl comparison becomes set membership; blast radius is one call site. Seals re-base on (arrival_lineage, ordinal), fixing the latent defect on main where chain commitments rest on rowid, an axis a rebuild regenerates.

Done-criteriapreflight.py untouched — its pure-reader contract and scope-not-verdict discipline are preserved verbatim. WitnessAggregateUnsupported and the A10 cross-store lineage refusal stay verbatim. The federated-read vs. admission distinction is protected in the new store API; signature verification at admission is new code.

GateAudit vectors over a deliberately rebuilt and shuffled index: L1 must answer from arrival, not byte offsets.

## §4Wave 2 — the SDK surface

Its own branch and pipeline run. The design fact ratifies after wave 1 merges, so the API contract is drawn from the substrate's real shape rather than speculation: ArrivalHead / DeclarationHead, guarded_append, the two-scope CAS, admission and federated read as distinct API verbs, and the ordered(prefix, key) read primitive. This ratify-gate is where the public-surface bar is enforced, and the vocabulary ratchet extends over libs/sdk.

## §5The tail

Sidecar. The frozen last-0.x-reader and first-arrival-writer, built to the fully-ruled Migration Sidecar spec with the verifier inside; the merge-lab signed-tick and aggregate arms are its starting point. Live-store migration happens here and nowhere earlier. The .gitignore sweep (*.jsonl, .loops/) and the .gitattributes merge-driver registration ride this same change — the driver is built and tested in slice B, but tracking the projection only makes sense once the store it projects has migrated.

Conformance vectors. The interleave-uniqueness families, sharing fixtures with the sidecar verifier. The loops-go / siftd mirrored-implementation blind spot — the audits' most consistently raised gap — resolves here by re-running the conformance oracle.

CLI rebuild. Last, from scratch, as a thin wrapper over the SDK, with ruled license to drop non-fitting concepts. Named residue waiting for it: the init.py:141-142 hardcoded-suffix regex, and the read-fact-body-by-id friction, which dissolves into (lineage, ordinal) addressing — a single record is exactly the coordinate arrival mints.

## §6What each slice inherits from PR #8

 | Disposition | Item | Lands in

 | Keep | Spec.replay_from (docstring word only) | C

 | Keep | VertexHandle checkpoint machinery | C

 | Keep | Benchmark arms (same-runner A/B) | C

 | Keep | Rule 17 prose ratchet | C

 | Keep | test_merge_direction_is_deterministic | B

 | Rewrite | CAS token coordinate → arrival head (incl. ceremony.py:432) | C

 | Rewrite | Combined-read fold fork → declared projection ordering | C

 | Rewrite | Authority prose (store_reader, witness, declaration, docs) | A / D

 | Discard | R1-as-doctrine (merge defines receipt order) | B

Backing facts (project store, all Kyle-ratified 2026-08-17):

plan:arrival-libs-slice-0 @ 01M08X5TV95ZGK0TMBJP8SSGMA

plan:arrival-arc-sequence @ 01M08XEHRQ9ADB2WPRY847FEX2

plan:arrival-arc-wave-shape @ 01M08XX3995Y37N64VZ08B2H35

plan:arrival-vocabulary-ratchet @ 01M08Y86P4XPYSGYA5MPA4V29H

plan:arrival-libs-slice-A @ 01M090QW6ZHDMPDP6P5TZAYTPB

plan:arrival-libs-slice-B @ 01M090QZCBP0FW09YM5AEX65B3

plan:arrival-libs-slice-C @ 01M090R7FQ5T159V8NT1KDFH8T

plan:arrival-libs-slice-D @ 01M090RAN7Z9FMZX0S5KSEZ322

plan:arrival-wave-2-and-tail @ 01M090RHHX3NB62JF9DTRY8JVF

Architecture anchor: decision:design/declared-fold-order amendment #4 @ 01M070N08HX69QAEQ3TRPY72CQ

Next entry point: branch feat/arrival-libs, launch the slice-0 design agent. Cut A does not start before the slice-0 design fact ratifies.
