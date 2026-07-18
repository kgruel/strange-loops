# 0.8.0 final contracts — post-panel arbitration

*2026-07-17 ~01:40. Arbiter: loops-claude. Inputs per session: codex
high-effort advisor + codex cross-exam (s1) + 2 Claude high-effort panel
lenses each (8 total, all AMEND / zero fatal). Full panel reviews:
`*-panel-*.md` in this dir. This doc records DISPOSITIONS — what the final
contract is where it differs from the advisor drafts. Everything not listed
is accepted as drafted.*

## Session 1 — temporal cursor (RATIFIED, v3)

Base: s1-arbitration.md v2 (A1–A13). Panel dispositions:

- **A5 MODIFIED (honesty panel's catch, accepted over my own v2):**
  unanchored wall-clock `--at` **refuses with teaching** that names
  `--as-of` — no auto-route, labeled or otherwise. My v2 fallback breached
  the design's own explicitness clause and was mode-unstable under future
  anchor backfill. Explicit request means the user types the projection
  flag themselves; it costs one retype.
- **A9 extended:** mixed witness/projection modes within one aggregate
  answer are REFUSED (a chimera answers no well-posed question); teaching
  names uniform `--as-of`. Current-membership reads are a **named
  derogation** (continuous with shipped aggregate-head behavior), with
  sunset = aggregate internal tables (§9.5), and marker carriage becomes a
  **ratchet test**, not review vigilance.
- **A10 narrowed (panel N1 — live corpus has no lineage ids):** durable
  handle serialization is **refused for unadopted stores** (teaching names
  `absorb`/adoption); in-session positions work everywhere. No surrogate
  ids invented.
- **A2 hardened (both panels converged):** receipt-group boundary becomes
  **durable** — group id carried in the `_decl` event payload (a §9.2
  spec touch, queued to the oracle thread TOGETHER with
  GlobalReceiptPosition — the two protocol amendments travel as one
  coordination). Interim engine enforcement: contiguity+shared-ts
  heuristic with **refuse-on-ambiguity**, enforced at the engine `at=`
  selector (not only the CLI resolver). Conformance vectors owed: no live
  data exercises ceremonies (1 `_decl` row across 47 stores).
- **A13 extended (N3):** cursor output contract carries the shipped
  honesty-ladder status (`file-pre-genesis` etc.) — on every current
  store, `--at` resolves ontology to the current file and MUST say so.
- **A9 implementation rider (N4):** combined tick drill deliberately
  returns empty envelopes today — pass envelopes through or the flagship
  aggregate never engages witness anchoring; `tick:` for non-source
  members resolves by claimed ts, disclosed as claim.
- **A11 extended:** the answering mode is a **machine-readable field** in
  structured output, not only rendered text.
- **Riders (N5):** fix false gen_id monotonicity docstring (empirically
  falsified, ~1/5000 within-ms ULID inversions); id-bearing incremental
  read scoped for Watch.
- Legacy tick markers: ts-placed, visually distinct, era-disclosed.

## Session 2 — VertexHandle (RATIFIED with amendments)

Base: s2-codex-advisor.md. All 3 engine + 6 consumer amendments ACCEPTED:

- Probe connection **transaction-free between probes** is a contract
  invariant with an exit test (data_version pinned in an open txn =
  unbounded staleness — empirically verified, the draft's failure table
  was wrong).
- Post-write reconstruction canonicalizes **state, not admission**;
  admission serializability defers to the conditional-emit/CAS sibling.
- Tick-append wording: "existing single-writer convention", not
  "serialization".
- Handle exposes a **tick query hydrated at open** (one blessed epoch
  scan) — ticked's reconcile needs task→latest-close over all history.
- `changes()` gains **idle timeout / deadline wake**; resume-from-position
  is **scoped out** of 0.8.0 (head-start-only; failure-table row
  reconciled).
- S7 **split**: ticked-cutover (achievable) vs tasked-deletion (gated on
  CAS sibling). Carve-outs recorded: notify_reply one-shot foreign load;
  check_emit reads observers/grants from the held compile.
- VertexSnapshot carries cumulative visible_domain_count;
  `refresh(force=True)` gets defined semantics.
- **Fabricated benchmark citation replaced** with panel measurements
  (100k forced-full 269–510ms; ordinary-refresh 250ms gate holds ONLY via
  checkpoint rung 4 → **promoted to required-for-cutover**; collect-heavy
  kind added to S5 fixtures).

## Session 3 — TUI shell (RATIFIED with amendments)

Base: s3-codex-advisor.md. All 9 amendments ACCEPTED:

- **apps/tasks' 7 run_cli sites fold into the ONE migration branch**
  (deferring them would leave a latent second migration — the constraint
  forbids exactly that).
- S0 **adds byte goldens** for stream/ticks/ls/sync/population BEFORE any
  lens body changes (current golden coverage is vacuous exactly where
  render_row lands hardest).
- piped→width=None becomes an **enumerable ratchet test** paired with the
  `piped=` kwarg deletion.
- read -i claim corrected: replaces a **silent downgrade** (fold.py:259),
  not an error.
- Painted reconciliation (upstream moved past the dossier snapshot):
  **consume-and-verify** shipped ViewportAdapter (host.py) + HostSurface
  (tui/surface.py); shell drives ViewportAdapter per mounted view;
  caller-side re-render + plan/publish ticket discipline — no
  set_data/set_fidelity adapter invented. Height: loops lenses stay
  3-arg/omitted-arm (upstream HeightRenderer exists; commission claim
  rescoped). Theme roles: kebab-case, declared vocabulary, on-label.
  **quit_keys explicitly overridden** wherever HostSurface defaults would
  reimpose q-quits (corpus ruling: q=zoom-out; Q/ctrl-c quits). Poll-backed
  change iterator is **plan of record**, not a stopgap awaiting a promised
  0.13 API.

## Session 4 — Digest (HELD AT PROPOSED — Kyle's gate, deliberately)

Base: s4-codex-advisor.md + both panels' amendments (all accepted into the
PROPOSAL). Not ratified tonight because the panel is right that three
calls are Kyle's, and the advisor draft pre-decided one of them:

1. **Canonical evaluator**: decl-chain classifier (3-state, strict-aware)
   as authority with the engine gate as enforcement shadow — engine Grant
   cannot express the undeclared-forgiven tier. Evaluator-singleness needs
   a ratchet test (live production grants in tasks.vertex depend on
   precedence order — drift = privilege escalation).
2. **Owner-only first slice**: the advisor rejected it as a dodge; the
   panel showed the rejection proves too much (it indicts today's emit
   baseline). Both paths are presented NEUTRALLY; sequencing is Kyle's.
3. **Promotion**: architecture/parallel-authorization-paths is an
   observation (no prescription) — binding it as Gate 0 requires promoting
   it to a decision: Kyle's ratification act.

Coverage-verifiability amendments A–G accepted into the proposal
(lineage-unopened degraded mode; two-store verifier input contract;
manifest-order check-or-declare; conjunctive six-step rule + fail-closed
selection persistence; prompt-preimage retention statement; exported
canonical-bytes surface; no-rowid-persists ratchet).

Shippable tonight regardless of the gate: NOTHING writes — design facts
only. (The advisor's non-writing slices — planner/preview/coverage-verify —
remain available post-ratification.)

## Protocol coordination queue (one package to loops-go)

1. GlobalReceiptPosition — durable store-wide receipt ordinal (facts+ticks
   interleaving; §10 prerequisite).
2. `_decl` receipt-group id — payload-carried ceremony boundary (§9.2).
3. Vectors owed: §8.7 two-authorities late-arrival; cursor-selection
   (fold-at-position incl. backdated straddle); same-ts id tie-break;
   mid-/split-group ceremony; §10 dump/rebuild witness-order.
