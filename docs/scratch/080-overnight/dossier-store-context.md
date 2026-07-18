# Dossier chapter: store context — the decision graph under the 0.8.0 wave

Harvested 2026-07-17 (overnight run) from the project store
(`/Users/kaygee/Code/loops/.loops/data/project.db`), read directly via sqlite
because the rendered `sl read --facts` view shows the fold head + a status
timeline per key, not full per-emission bodies. Every quote below is verbatim
from a fact payload (fact IDs given) or from a cited source file with line
numbers. Where the store or sources contradict the tasking prompt or a fact's
own paraphrase, that is flagged inline — those flags are the point.

Method note for reproducers: the CLI route to the same rows is
`sl read project --facts --kind <K> --key <key>`; the raw route is
`sqlite3 .loops/data/project.db "SELECT id, ts, payload FROM facts WHERE
kind='thread' AND json_extract(payload,'$.name')='<name>' ORDER BY ts"`.

---

## 1. thread:loops-go-conformance-oracle — all 8 emissions

Status: **open**. 8 emissions, 2026-06-03 → 2026-07-13. Fold key `name=`,
tier high, 4 inbound refs. This thread is the durable handoff with the
loops-go second implementation ("The other instance has no loops store — this
thread is OUR durable handoff", repeated in emissions 1 and 2).

### E1 — 01KT5QXFRN3RFSXCFJC8B161AQ, 2026-06-03 03:20, kyle/loops-claude
GO (conditional) verdict on the oracle thesis:

> "loops-go (~/Code/loops-go) is a SECOND implementation of the loops protocol
> in Go, built by a separate instance as a differential+property conformance
> ORACLE — deliverable is a hardened protocol (SPEC.md) + conformance suite,
> not the binary."

> "VERDICT: invest in M3-M5; the thesis (differential oracle blind to shared
> bugs, property oracle catches them) is verified real."

Three gating items named: C3 tick-envelope mis-spec ("payload is TWO shapes by
boundary scope, not uniformly keyed-by-kind"), I1 un-muzzle the property
oracle ("it t.Logf-s violations instead of t.Errorf, so green is decorative"),
budgeted adversarial/fuzz vectors. Open forks R1–R3 pending Kyle.

### E2 — 01KT5RXFBR6JN0AP8VQCW7J0JC, 2026-06-03 03:37, kyle/loops-claude
Two-instance review convergence. R1 resolved ("JSON keys are strings → string
fold keys, value-canonical at fold-time, 7≡7.0→\"7\""), R4 resolved ("init =
fold identity element"). R2 still open at this point. H4 named:

> "H4 — rowid-DESC is multi-sited (sqlite_store.py:234,311,326) +
> single-store reachable, needs a general \"most-recent reads order by
> (ts,id)\" rule."

### E3 — 01KTYAZNWA9FWCN2NADRVVPZF5, 2026-06-12 16:35, observer EMPTY
R2 resolved Python-side:

> "off-type in numeric fold = skip + {target}_rejected counter in fold state;
> bool is off-type; Latest missing-_ts joins the rule (no wall-clock
> fallback). Also settled: fold replay order is (ts,id) — the H4 general rule
> — while witness/chain order stays rowid (design/fold-replay-order-event-time)."

### E4 — 01KTYTZEC5HV0KDP3ANYSQDV54, 2026-06-12 21:14, kyle/loops-claude
Structural finding — the attestation epoch invalidated the plan's "semantic,
not byte-identical" comparison invariant:

> "Signing demands a byte-exact canonicalization tier (JCS RFC 8785 discipline
> from vouch work); cross-impl hash divergence renders as FALSE TAMPER ALARM,
> not test failure — highest-stakes conformance surface in the port."

Also: "a Go chain verifier IS an external witness."

### E5 — 01KTYVBMPEDKRTM6RTZB440A9G, 2026-06-12 21:21, kyle/loops-claude
SPEC §8 Attestation authored: JCS canonical bytes, three envelope
constructions, window hash "incremental sha256 over hex row-hashes in witness
order", Ed25519, "domains loops-tick-v1/loops-fact-v1 protocol-normative",
"§8.4 chain linkage + two-ordering-authorities as normative rule (receipt not
chronology)". Plus §0.5 invariant 4:

> "byte-exact tier carve-out (set-determinacy deliberately does not hold at
> the chain — witness order is attested behavior)."

### E6 — 01KTYVPV15ZB8EJX36W6EHB6AR, 2026-06-12 21:27, kyle/loops-claude
Both halves landed on r2-replay-conformance: "(ts,id) replay fix in ReadFacts
... Go did NOT conform before, real catch", "30 fold vectors +
merge-commutativity differential green". Sequencing warning:

> "§8.7 vectors MUST NOT generate until after migration or they pin pre-JCS
> bytes."

### E7 — 01KWG7N8X43S6WQ82AGWT45BYZ, 2026-07-02 01:38, observer EMPTY
Stale critical-path corrected: JCS + re-anchor "DONE and RELEASED — c1f50ed
... shipped in v0.4.0". Consequence:

> "section-8.7 attestation vectors AND the new section-10 interchange vectors
> are UNBLOCKED — nothing pins pre-JCS bytes anymore. Go-side next step is
> vector generation, not waiting."

### E8 — 01KXCXEPES6ZEKYZKJK237AHQ8, 2026-07-13 04:58, kyle/loops-claude — the live head
The emission the cursor-axis session must answer, in full:

> "S5 cursor-axis check needed against the Go vector set: S5 ratified ts
> (epoch-seconds fold axis) as the ontology as_of cursor with equal-cursors
> default; witness-order (fact-id/rowid) deferred until a fact-cursor read
> surface exists. SPEC §9.4 grounds residence on witness order and calls
> ts-based as-of 'undefined within windows' — verify the §9.3/§10 Go vectors
> don't assume a witness cursor, or mark the ts choice as
> incumbent-provisional in the vectors."

**Empirical check run tonight (the thing E8 asks for):**

- `~/Code/loops-go/testdata/vectors/` contains ONLY `fold_vectors.json` and
  `parse_vectors.json`. Zero grep hits for `as_of`/`as-of`/`cursor`/`witness`
  in either. **There are no §9.3/§10 Go vectors yet to assume anything.**
  They are "owed" per SPEC §10.5 (SPEC.md:1235-1240) and §8.7 (SPEC.md:912).
- **The quote in E8 is a paraphrase that shifts the referent.** SPEC §9.4
  (SPEC.md:1121-1141) does NOT call ts-based as-of "undefined within windows."
  The exact sentence (SPEC.md:1132-1135), arguing why declaration events must
  live in the `facts` table rather than a third table:
  > "The alternatives fail it structurally: a third table has no shared
  > witness order with the facts it interprets (\"as of\" becomes undefined
  > within windows, and the §10 stream needs an interleaving the store never
  > recorded)"
  So §9.4 grounds *residence* on shared witness order; the "undefined within
  windows" clause condemns the third-table alternative, not the ts axis per
  se. The tension E8 names is real but softer than its wording: the SPEC's
  as-of *interleaving argument* presumes witness order is the axis that makes
  "as of" well-defined inside a window, while the incumbent S5 implementation
  resolves as-of on `ts`.
- Owed-vector shapes that DO pin witness order: §10.1 dump is "one JSONL
  stream carrying every row — facts, declaration events, ticks — in witness
  order (§8.4)" (SPEC.md:1193-1195); §8.7's two-authorities fixture requires
  "fold state must follow §6.2, window membership must follow §8.4"
  (SPEC.md:918-920). §6.2 (SPEC.md:566) is normative: "Replay processes facts
  in (ts, id) order," explicitly because rowid is not merge-stable.

---

## 2. The S5 ratification — where it actually lives

**Contradiction with the prompt: there is NO decision-kind fact ratifying the
S5 cursor axis.** A full scan of `decision`/`design` facts across the S5
window (2026-07-12 → 2026-07-14) returns only: absorb-genesis-atomic-primitive,
bulk-emit-ndjson, payload-constraints-in-declarations,
internal-table-s3-read-exclusion, batch-emit-ingress (x2),
env-values-are-ingress, param-secrets-indirection. The ratification is carried
in three places, none of them a `decision` row:

1. **Thread emissions.** thread:vertex-state-in-store
   (01KXCWEY7N5CXMQE62EW6E1TJN, 2026-07-13 04:41): "NEXT ENTRY: S5
   ontology-as-of, equal cursors (Opus) — resolver as_of, read path second
   cursor, equal-cursors default (§9.3); exit = honest rewind, GATE OPENS for
   0.7.0 TUI/cursor." And thread:loops-go-conformance-oracle E8 above: "S5
   ratified ts (epoch-seconds fold axis)."

2. **The implementation docstring** —
   `libs/engine/src/engine/declaration.py:50-61`, the closest thing to a
   ratification text:
   > "The ``as_of`` cutoff is ``_ts <= as_of`` (a declaration edit at
   > ``ts == as_of`` participates), matching ``StoreReader.facts_between``'s
   > inclusive upper bound (``ts <= until_ts``). With the equal-cursors
   > default (``as_of = until_ts``, SPEC §9.3) ... **when a fact and a
   > declaration edit share an exact float ``ts``, the fact folds under the
   > NEW ontology** — the edit wins its own instant, regardless of physical
   > append order. The tie-break is purely ``ts``-based (not witness/rowid
   > order), so it is reproducible across runs and across a
   > ``rebuild(dump(S))`` that reassigns rowids. Witness-order (\"as of\" the
   > fact cursor) is the finer axis SPEC §9.4 grounds fact-residence on; it is
   > deferred (Q1) until a fact-cursor read surface exists — until then ``ts``
   > with this inclusive tie-break is the single axis."

3. **SPEC §9.3** (~/Code/loops-go/SPEC.md:1110-1119), normative:
   > "a historical read has two independent cursors: **facts-as-of** (which
   > facts replay) and **ontology-as-of** (which declaration state interprets
   > them). The default MUST be equal cursors — an honest snapshot of what a
   > reader at T would have seen. Unequal cursors ... are legitimate
   > *deliberate reinterpretation* and MUST be explicitly requested, never a
   > silent default. Non-critical state (lenses) MAY follow the reading
   > session's present without violating honesty."

Related surviving-quality context: S5 merged 8fca98b but "the arc is NOT
closed" until Sol's holistic review BLOCK (8 findings) was hardened
(01KXD1NMNQ4VQFZN3GCYVKXDPQ, 2026-07-13 06:12). Hardening finding 2 touched
the cursor directly: "pre-genesis as_of leaks the CURRENT FILE AST" → fixed as
"pre-genesis as_of projects the GENESIS FLOOR (Unhistorized carries docs;
never the drifted file)" (01KXE4BQK6RZGSDP5HA0ANP7WN, 2026-07-13 16:18).
Finding 3: "edit ceremony observable half-applied under rewind — absorb_edit
stamps per-row ts so a cursor can land inside the batch ... needs one shared
effective ts per ceremony" → fixed as "one shared ts per edit ceremony +
expected_head CAS (StaleDeclarationHead)". Arc closed 2026-07-13
(01KXETBERETBRZWSH7R72KH33E, status=resolved); "The 0.7.0 TUI/temporal-cursor
gate is now genuinely open (S5's claim, now review-backed)"
(01KXECQJ349N1Z1WQA69KM280Y). Retrospective: retrospective:internal-table-s0-hardening
(01KXF1VFC3Q6Z7GN405Z1JXECP, 2026-07-14).

Also relevant from the S5 review saga (observation
session/2026-07-13-hardening-closing-review, 01KXECQJDD1DS6R2ENQYT1F9CZ):
"implementer rationalized a real boundary bug as 'scheduling artifact' in S5 —
cross-adapter review refused the rationalization and was right."

---

## 3. The cursor-axis prior stack (the three-authorities conflict's history)

The store already contains a settled two-authorities doctrine; the 0.8.0
question is which authority the *user-facing temporal cursor* speaks.

- **decision:source/cursor-is-source-managed** (01KK4SE9BW, 2026-03-07):
  "Source cursor (dedup state) is source-managed, not system-managed." (Old,
  different 'cursor' — ingress dedup — but it is the word's first use in the
  store; do not conflate.)
- **observation:architecture/rowid-is-load-bearing-for-single-store-ordering**
  (01KRT1AJ3P, 2026-05-17): "rowid is load-bearing; do not remove or replace
  its role in ordering without verifying id-based replacement provides
  equivalent monotonicity AND cross-store interleaving guarantees ... The
  cross-store case is the gotcha: rowid is per-database, so it can't be the
  global ordering primitive — that's what id-as-ULID is for. Both columns earn
  their existence."
- **observation:design/event-order-vs-witness-order** (01KTQ9638G,
  2026-06-09): "Two irreducible orders, two claims. Event order (ULID,
  fact.ts) = when things happened; read-path's order ... Witness order (rowid)
  = when this store received them; the chain's order — chain claims
  receipt-integrity, not chronology. The killer case is late arrival ... a
  backfilled/synced fact carries an honest old event-ts; under id-ordered
  windows it lands inside a sealed window and triggers a false tamper alarm
  caused by truthfulness."
- **decision:design/chain-witness-order** (01KTQ9J8F7, 2026-06-09, ratified):
  "Chain ordering authority is witness order (rowid), never id order. Window
  cursors stay fact ids (portable handles); membership and hashing resolve
  cursor->rowid and walk append order ... ULID keeps its job — event order for
  the read path."
- **decision:design/fold-replay-order-event-time** (01KTYAZNJT, 2026-06-12,
  ratified): "FOLD REPLAY orders by (ts, id) — event order, store-independent
  total order — so merge(A,B) and merge(B,A) re-fold identically; WITNESS
  ORDER (rowid) remains the chain/window/attestation authority — merge
  directions ARE different custody events and their chains legitimately
  differ ... Pinned by TestMergeFoldCommutativity."
- **decision:design/tick-chain-at-store-layer** (01KTPYB93B, 2026-06-09):
  tick rows carry "fact_cursor (max fact ULID at tick time — explicit id-based
  window boundary, not ts-inferred)". This is the tick-anchor authority's
  substrate: a tick names its boundary by fact id, resolved to rowid for
  membership (per chain-witness-order).

The third authority in the 080 thread's framing — "tick anchor (Rewind mock's
-vv: 'last tick before the mark', chain-verified)" — exists only in the TUI
design corpus (~/Downloads), not as any store fact or code path.

Internal-table meta decisions that constrain any cursor design:

- **decision:design/internal-table-meta-schema** (01KWG156XJ, 2026-07-01,
  RATIFIED by Kyle): "Current state = stock Latest fold keyed (event-kind,
  subject); ontology-asof = time-cutoff on that fold — resolver is a
  projection, no delta composition." Lenses "live as lens-defined events
  marked non-normative-for-rewind-honesty."
- **decision:design/declaration-events-whole-document** (01KWHWTG0Z,
  2026-07-02): "facts are deltas composed by declared folds; declarations are
  documents composed by nothing" — composition rule code-frozen as Latest,
  whole doc.
- **decision:design/internal-row-placement-facts** (01KWJ8JHCD, 2026-07-02,
  RESOLVED by Kyle): declaration events are facts-table rows in a reserved
  kind namespace; "merge must not be lossy about meaning"; "merge appends a
  'merged' receipt event (source lineage, cursor, dump hash) making
  native-ontology rewind of imported facts resolvable in one store."

---

## 4. thread:dispatch-default-subsumes-vertex-pre-router — boundary of TUI entry seam

Single emission (01KWVXTBFF, 2026-07-06, kyle/loops-claude, status=open,
ops=loops-cli, feature=painted-070-bump):

> "painted 0.7.0's run_app(default=) models 'unmatched arg0 ⇒ default handler
> receiving full argv' — EXACTLY the tier-3 vertex-shorthand pre-router that
> cli/app.py:236-238 comments say painted couldn't do. The whole known-set
> gate + manual fall-through (incl the completion-dispatch bug just patched)
> is now a dissolution candidate: pass default=<vertex-shorthand AppCommand>
> to run_app, delete the known-set gate, let painted own all dispatch.
> Deferred out of the release bump (touches the most-used sl <vertex> path,
> needs own test+smoke cycle)."

Context prior — decision:design/full-painted-integration-residue
(01KV45R9BB, 2026-06-14): "Governing principle reaffirmed by Kyle: anything
painted can do -> prefer painted, grow painted before working around it."
The 080-design-wave thread names this thread explicitly at the TUI session:
"entry seam overlaps thread:dispatch-default-subsumes-vertex-pre-router."

---

## 5. thread:discover-children-as-cascade-targets — boundary, stays OUT

Single emission (01KWMXNZ34, 2026-07-03, status=open,
feature=discover-cascade):

> "Should discover children be LIVE cascade targets at all, vs read-only
> aggregation? Replay is now sound either way, but live receive still routes
> root facts into member stores and re-mints their ticks by design.
> seal-fanout wants that cascade deliberately; aggregation-only roots want it
> never. Likely needs an explicit per-child or per-root declaration rather
> than the current implicit behavior."

Its exclusion is itself ratified: decision:design/roadmap-070-substrate-cut
says "fix/discover-cascade stays out (design-gated by
thread:discover-children-as-cascade-targets, same as it stayed out of 0.6.0)."
Downstream sessions should treat this as a wall, not an invitation.

---

## 6. The roadmap spine — three ratified decisions

### decision:design/roadmap-060-static-honest-wave (01KWGGZN5Y, 2026-07-02, RATIFIED Kyle 2026-07-01)
Wave content that now belongs to 0.8.0 (only the *number* was superseded):

> "0.7.0 = everything needing design+discussion: TUI shell + shared temporal
> cursor (Rewind/Watch as ONE abstraction), gated on the internal table
> landing FIRST (rewind ships honest, never facts-through-today's-ontology —
> the responsible ordering; SPEC section-9.3). Digest last regardless
> (non-deterministic summarization + cross-vertex WRITE path — first concrete
> in-repo Peer/Grant consumer, own design pass)."

> "painted ALREADY HAS the interactive substrate (event loop etc., available
> now) — no upstream build gate; the TUI mocks are mocks, but the questions
> they raise drive refinement. Corpus: ~/Downloads/'Terminal UI for loops'
> (9 lens studies + shell + Static TTY + 7 palettes, all at 4 fidelity
> levels)."

(The 080 thread later walks the "no upstream gate" claim back to "PAINTED
TRIAGE the 'no upstream gate' claim never got" — see §8.)

### decision:design/roadmap-substrate-after-060 (01KWJBNW80, 2026-07-02, ratified Kyle)
"(6) two-cursor read path" was item six of the substrate decomposition;
"vocabulary pass before 0.7.0 ships user-facing words."

### decision:design/roadmap-070-substrate-cut (01KXQ40F0P, 2026-07-16, Kyle)
> "0.7.0 = the substrate cut ... The roadmap wave (TUI shell + shared temporal
> cursor + Digest) RENUMBERS to 0.8.0; roadmap-060-static-honest-wave's 0.7.0
> allocation is superseded on that point only, its content unchanged."

Released floor confirmed by thread:release-070 (01KXQ4NGE4, resolved,
2026-07-16): tag v0.7.0, PyPI-verified; "Rides 0.8.0: TUI shell + shared
temporal cursor + Digest ..., fold-state-as-of (lifts the read-router
refusal), rewound search index (vertex_search), --ontology-as-of
unequal-cursors escape."

---

## 7. Strata — doubly downstream

### decision:design/strata-cut-ratified (01KWQ89GHB, 2026-07-04, RATIFIED)
> "cascade lineage is NOT key-joinable — _tick_to_fact (vertex.py:911-927)
> carries child tick payload/observer/origin onto the parent fact but NEVER
> the child tick id/since/window_hash, so read-side tree assembly is a
> heuristic ts+payload reconciliation (ambiguous on identical payloads,
> unprovable) ... A view rendering heuristic lineage as if it were attested
> structure fails the static-honest bar on PRINCIPLE ... Consequence fed
> forward: the 0.7.0 internal table (SPEC 9) should carry parent_tick_id /
> child_vertex_ref on tick rows, turning Strata into a straight recursive
> query over stored FKs. Strata rides 0.7.0."

### observation:architecture/strata-tick-lineage-unmet (01KXQ49YWN, 2026-07-16)
The fed-forward requirement was NOT landed:

> "the internal-table arc did NOT land it: the ticks schema is unchanged
> (sqlite_store.py ~281-293), _tick_to_fact still drops the child tick id, and
> the 'lineage' §9 added is DECLARATION lineage (genesis/own_lineage), a
> different concept. Strata is therefore doubly downstream in the 0.8.0 wave:
> it needs a tick-lineage schema design (post-freeze, coordinating with the Go
> oracle) AND its stacked view wants Digest output (recursive digests). No
> design fact exists yet for tick lineage as columns vs fact-borne events."

---

## 8. The wave agenda itself — thread:080-design-wave (3 emissions, all 2026-07-16/17)

### E1 — 01KXQ49N02, the four-session sizing (quoted selectively; it is the densest fact in the store)
> "(1) CURSOR AXIS — gating, first: ts (S5 ratified) vs witness order (SPEC
> 9.4 grounds residence there, calls ts-as-of 'undefined within windows') vs
> tick anchor (Rewind mock's -vv) — three authorities in live conflict; run
> the loops-go-conformance-oracle vector check inside this session; building
> fold-as-of first would bake ts in de facto."

> "(2) DAEMON-SHAPED ENGINE ACCESS — one seam counted three times: ticked's
> quadratic poll, Watch's change-detection, TUI live-refresh are the SAME
> missing primitive (long-lived VertexProgram handle, WAL-incremental refresh,
> receive() without reload, change feed into an event loop); one output
> contract serves all three."

> "(3) TUI SHELL INTEGRATION — the prototype is complete
> (layout/keys/composer/command-bar-honesty) but the seams are blank:
> lens-mount mechanism (8 view docs, 3 tabs, no mount path), entry+quit (mock
> q=zoom-out collides with store_app quit; entry seam overlaps
> thread:dispatch-default-subsumes-vertex-pre-router), store_app retirement
> first (fifth time fork), PAINTED TRIAGE the 'no upstream gate' claim never
> got (scrubber widget, toast, 17-slot theme roles vs Palette's 5,
> external-change feed into Surface), and ONE coordinated lens-signature
> migration instead of three (zoom unification + cursor threading +
> cross-lens-shared-row-renderer all rewrite the same seam — sequenced
> independently = 3x golden churn)."

> "(4) DIGEST — last, ratified: signing/observer of synthesized close facts,
> grant shape (Grant.potential has no target-vertex dimension), Peer/Grant
> persistence collides with frozen _decl vocab (Go-oracle coordination), no
> cross-store append path, LLM home vs DAG ratchet, coverage backlink,
> Dissolution counterpart."

> "MECHANICAL once (1) settles: fold-as-of (vertex_facts until=T + Spec
> replay; --why replay_attribution is the per-key precedent), --diff (set
> difference of two reconstructions)."

### E2 — 01KXQ5ZFYY, next-session entry marker
> "what does a temporal cursor position resolve to — ts (S5's ratified choice,
> epoch-seconds fold axis), witness order (SPEC 9.4's ordering authority;
> calls ts-as-of 'undefined within windows'), or tick anchor (Rewind mock's
> -vv: 'last tick before the mark', chain-verified)? ... Everything downstream
> inherits the answer: fold-as-of, --diff, scrubber semantics, Watch's seq-N
> tail; building fold-as-of first would bake ts in de facto."

(Note: both E1 and E2 repeat the "calls ts-as-of 'undefined within windows'"
paraphrase whose referent-shift is documented in §1 above. The design session
should work from SPEC.md:1132-1135 verbatim, not the paraphrase.)

### E3 — 01KXQ6SZE2, tonight's charter
> "OVERNIGHT RUN ENTERED 2026-07-16 (Kyle asleep, full delegation): run 0.8.0
> through to the end. ... Sequence: grounding dossier -> design sessions 1-4
> in forced order (cursor axis w/ Go-vector oracle check inside;
> daemon-shaped access; TUI integration; Digest) -> implementation in
> dependency order (fold-as-of + --diff mechanical once axis settles).
> Done-bar per slice: gates green + codex review + arbitration."

---

## 9. Facts mentioning scrubber / Watch / TUI / store_app / digest / daemon

### Scrubber / rewind lineage
- **thread:replay-visualizer-on-painted** (01KV42XRF0, 2026-06-14, open):
  "painted's animation model and loops' temporal model are the SAME shape
  (structural isomorphism), so a viewer is mostly wiring not new machinery ...
  replay fold facts[0..cursor_N]->state (pure SINCE R2 fold-determinism) ...
  The R2 determinism work ... is EXACTLY what makes scrubbable deterministic
  frames possible." Must-grow list for painted: "(1) playback controls
  pause/seek/step/speed -> propose TimelineSurface mixin; (2) diff-over-time
  highlighting; (3) DAG/ref-graph node-link layout; (4) viewport/LOD."
  Note the staging assumed a per-tick frame axis ("yield FoldState per tick as
  cursor advances") — an implicit vote for the tick-anchor authority that
  predates S5.
- **friction:as-of-silent-drop-on-fold-path** (01KXQ3NSKE, 2026-07-16, open):
  "sl read <v> --as-of X on the DEFAULT FOLD path silently renders head state
  ... inside the wave whose charter is 'rewound reads must never silently lie'
  (SPEC 9.3 preamble)." Interim honest-refusal shipped in 0.7.0 (184dfce);
  fold-as-of is the 0.8.0 lift.

### TUI / store_app
- **observation:rendering/painted-tui-framework-grown** (01KW4SGC2Y,
  2026-06-27): "painted.tui grew a full interactive framework the loops read
  path doesnt use: nav-stack Action model (Push/Pop/Stay/Quit/Focus/
  Search/Emit), built-in filters ... tui/store_app.py predates most of it and
  hand-rolls truncation/scroll/rows; it is a ticks-first DB inspector reached
  via store -i, not a fold explorer. Interactive read path should be a
  fold-Surface on these primitives, retiring store_apps hand-rolled rendering."
- **decision:design/interactive-read-path-tree-drill** (01KW4TY7ZN,
  2026-06-27): "recommended interaction model = single-pane fold-tree drill
  (collapsible corpus outline) ... read does NOT split: one fetch two
  renderers, Surface is a fidelity tier (isatty-gated), static Block
  byte-identical (golden-guarded) ... retire tui/store_app sweeping its
  residue."
- **decision:design/interactive-tier-greenlight-by-use** (01KW5S1RJR,
  2026-06-28, Resolved Kyle): "DEFER the interactive/TUI renderer ...
  Greenlight is EXPERIENTIAL, not a metric threshold: Kyle re-triggers a
  design discussion once the static CLI feels good to use for both of us
  (human + agent)." — The 0.6.0/0.8.0 roadmap ratification (2026-07-01) is
  that re-trigger; this decision's deferral is spent, but its
  "-i errors cleanly / Format.JSON forces STATIC / do not advertise -i" seam
  is the current shipped state the TUI session inherits.
- **observation:rendering/height-offered-only-in-tui** (01KX7H4JBK,
  2026-07-11): "a static (data, fidelity, width) signature that omits height
  matches actual static-path usage exactly (height is never wanted there);
  height is a live/Surface concern."
- **observation:rendering/store-app-holds-no-fidelity-duplication**
  (01KX7H6CYP, 2026-07-11): "NOTHING in store_app.py is flag-compilation or
  Fidelity-parsing residue ... The FidelityState dataclass there is a
  NAVIGATION state (a facts-within-a-tick-window drill cursor), a domain
  concept that merely shares the word fidelity ... store_app ... is a
  legitimate Surface consumer, not a shadow renderer." (Guards the retirement
  scope: retire it as a redundant app, not as fidelity residue.)

### Daemon
- **friction:no-daemon-shaped-store-access** (01KXM4GB63, 2026-07-16, open):
  "every engine touchpoint is CLI-shaped: load_vertex_program does KDL parse +
  pin-verify + compile + FULL-history replay per emit ... Cost per cycle is
  O(total facts ever) -> quadratic over the daemon's life. Consumer-side
  caching is the wrong fix (restart-safety design correctly treats the WAL
  store as the only coordination channel). Fix-shape: daemon-shaped access in
  engine — long-lived VertexProgram handle with WAL-incremental refresh
  (replay facts since last seen rowid) and receive() without reload."
  Note: the fix-shape as written says "since last seen rowid" — a witness-axis
  incremental feed; the cursor-axis session should notice this consumer
  already assumes witness order for change feeds.
- **friction:engine-write-path-no-receipt-no-close** (01KXPVPFGV, 2026-07-16,
  open): "receive -> Receipt(fact_id, tick)" and "VertexProgram has no
  close()/context-manager." (Receipt shipped in 0.7.0 per release-070; the
  close()/handle-lifecycle half feeds session 2.)
- **friction:sqlite-probes-in-apps** (01KXP65GV1, 2026-07-16, open): "Fix-
  shape: engine grows a probe surface (era/genesis/declaration introspection)
  and the allowlist ratchets to empty. Same family as
  no-daemon-shaped-store-access: consumer-forced engine needs."
- **observation:architecture/daemon-access-serves-tui** (01KXPVPJVM,
  2026-07-16): "ticked's 2s-poll daemon ... and the 0.7.0 TUI are the SAME
  consumer shape — a long-lived process needing incremental reads (replay
  facts since last rowid, not full history) and receive() without reload ...
  the engine design session for daemon access should sit BEFORE TUI work."
- **thread:tasked-forcing-function** (01KXPYFHSW, 2026-07-16, open): ordered
  entry points — daemon-shaped access, conditional emit/CAS ("absorb_edit
  expected_head is the in-house precedent"), payload value-typing at
  receive(), fold-shape read grammar for embedded clients. "When 1+2 land,
  tasked's substrate.py deletes as its docstring predicts — that deletion is
  the arc's done-bar."
- **Historical daemon priors that still bind vocabulary and posture:**
  decision:design/orchestration-dissolves-daemon (01KKC7RMAN, 2026-03-10):
  "The orchestration vertex does not need a persistent runtime ... resolved by
  dissolution." decision:paradigm/eventful-over-polling-implicit (01KR76CQD7,
  2026-05-09): "'eventful over polling, derived over scheduled' ... Multiple
  separate decisions rejected the dedicated-runtime / continuous-evaluation
  pattern." thread:daemon-as-new-lib (01KQ95XWB4, 2026-04-28, **parked**): the
  full lib sketch (UDS transport, vertex registry, thin-client CLI) — parked,
  not ratified. Session 2 is chartered as *daemon-shaped access* (a handle
  contract in engine), which is compatible with these priors; a session-2
  outcome that resurrects a persistent daemon process would contradict two
  standing decisions and must supersede them explicitly if it goes there.

### Digest
- roadmap-060 (§6 above) is the only ratified Digest content: "Digest last
  regardless (non-deterministic summarization + cross-vertex WRITE path —
  first concrete in-repo Peer/Grant consumer, own design pass)."
- **observation:architecture/parallel-authorization-paths** (01KXQ49YQ9,
  2026-07-16): "Two parallel authorization paths exist and only one is
  enforced: (a) lang-AST GrantDecl/ObserverDecl -> identity.py ObserverCheck
  (enforced at emit ...); (b) engine.Peer/Grant frozen dataclasses with
  Vertex.receive(grant=) gating — ZERO production consumers ... Horizon
  (read-side visibility) is enforced NOWHERE. This is a dissolution candidate
  that must resolve BEFORE Digest builds on either path."
- **observation:design/store-type-portfolio** (01KWJQ3KRD, 2026-07-02):
  "cumulative deep research (digest-coverage's natural home)" — the only other
  digest mention; a validation frame, not a constraint.
- **thread:decl-lens-tombstone-vocab-gap** (01KXCSPJFA, 2026-07-13, open):
  "vocab is code-frozen, mirrored by loops-go oracle; minting a tombstone
  mid-slice is a cross-impl spec change. Revisit as a coordinated vocab
  addition with the Go oracle." Binds Digest's "Peer/Grant persistence
  collides with frozen _decl vocab" item: any _decl vocabulary change is a
  Go-oracle-coordinated spec change, never a local addition.

---

## 10. Constraints downstream designs must honor

Every item below is a ratified decision or normative SPEC rule currently in
force. Superseding any of them requires an explicit supersession emit, not a
silent design-around.

1. **Equal cursors is the default; unequal is explicit.** SPEC §9.3
   (normative): "The default MUST be equal cursors ... Unequal cursors ...
   MUST be explicitly requested, never a silent default." `--ontology-as-of`
   is the reserved unequal-cursors escape (docs/CLI-CHEATSHEET.md, "reserved
   for 0.8.0, not yet wired").
2. **Rewound reads must never silently lie.** SPEC §9.3 preamble charter,
   enforced in 0.7.0 as the read-router's honest refusal (184dfce,
   friction:as-of-silent-drop-on-fold-path). Fold-as-of must lift the refusal,
   not bypass it. Lenses may follow the present ("non-critical state (lenses)
   MAY follow the reading session's present").
3. **Fold replay order is (ts, id) — merge-stable event order.**
   decision:design/fold-replay-order-event-time + SPEC §6.2 (normative).
   Pinned by TestMergeFoldCommutativity. Any cursor semantics that re-fold
   history must preserve merge-commutativity of the reconstruction.
4. **Chain/window/attestation authority is witness order (rowid), never id
   order; window cursors are fact ids resolved to rowid.**
   decision:design/chain-witness-order. A tick's `fact_cursor` is an id-based
   boundary (design/tick-chain-at-store-layer). Witness order is *attested
   behavior* (SPEC §0.5 invariant 4 carve-out, oracle E5).
5. **The S5 incumbent: ontology as_of resolves on ts, inclusive cutoff
   (`_ts <= as_of`), edit wins its own instant; witness-axis as-of is
   deferred "until a fact-cursor read surface exists"**
   (declaration.py:50-61). The cursor-axis session may ratify, refine, or
   supersede this — but fold-as-of built before that session "would bake ts in
   de facto" (080-design-wave E1/E2), which is why session 1 is first.
6. **Declaration events are whole-subject documents, Latest per
   (kind,subject), residing in the facts table under the reserved `_decl.*`
   namespace; resolver is a projection, no delta composition.**
   design/internal-table-meta-schema, design/declaration-events-whole-document,
   design/internal-row-placement-facts, all ratified; SPEC §9.4 records the
   residence resolution as normative.
7. **The `_decl.*` vocabulary is code-frozen and oracle-mirrored.** Any
   addition (lens tombstone, Peer/Grant persistence kinds) is a coordinated
   cross-implementation spec change (thread:decl-lens-tombstone-vocab-gap,
   S4 refusal decision). Digest cannot mint vocabulary unilaterally.
8. **Pre-genesis as_of projects the genesis floor, never the drifted file;
   edit ceremonies have one shared effective ts + expected_head CAS.**
   Hardening outcomes, review-backed (01KXE4BQK6). Scrubber/diff semantics
   must not resurrect mid-ceremony states.
9. **Head-only surfaces stay head-only:** default folded read, store summary,
   and every write/identity path — "you cannot write or sign into the past"
   (docs/CLI-CHEATSHEET.md, --as-of section). Note fold-as-of (0.8.0) will
   deliberately move the folded read out of this list; the write/identity
   half is not negotiable.
10. **Daemon session posture:** "eventful over polling, derived over
    scheduled" (paradigm decision) and "orchestration dissolves daemon"
    (design decision) stand; the chartered deliverable is a long-lived
    engine handle contract (WAL-incremental refresh, receive() without
    reload, change feed), one contract serving ticked + Watch + TUI
    (architecture/daemon-access-serves-tui), sequenced BEFORE TUI work.
11. **TUI session pre-commitments:** Surface is a fidelity tier on ONE fetch
    (read does not split; static Block byte-identical, golden-guarded —
    design/interactive-read-path-tree-drill); store_app retires as a
    redundant Surface consumer, not as fidelity residue
    (rendering/store-app-holds-no-fidelity-duplication); prefer/grow painted
    over working around it (design/full-painted-integration-residue, Kyle);
    height stays a Surface-tier concern
    (rendering/height-offered-only-in-tui); one coordinated lens-signature
    migration, not three (080-design-wave E1).
12. **Digest is last, and gated:** first in-repo Peer/Grant consumer
    (roadmap-060, ratified) — but the parallel-authorization-paths
    dissolution must resolve before Digest picks a path
    (architecture/parallel-authorization-paths).
13. **fix/discover-cascade and its design question stay out of this wave**
    (roadmap-070-substrate-cut: "design-gated by
    thread:discover-children-as-cascade-targets").
14. **Go-oracle coordination is part of the cursor decision, not after it:**
    the vector check runs inside session 1 (080-design-wave E2: "it's the
    same decision"). Empirical state: no §9.3/§10 vectors exist yet
    (testdata/vectors has only fold/parse), so the decision constrains
    vectors-to-be, not shipped ones; owed vectors already pin witness order
    for dump (§10.1) and two-authorities behavior (§8.7).
15. **Strata requires a tick-lineage schema design first** (parent_tick_id /
    child_vertex_ref never landed — architecture/strata-tick-lineage-unmet);
    any tick-schema change coordinates with the Go oracle post-freeze.
