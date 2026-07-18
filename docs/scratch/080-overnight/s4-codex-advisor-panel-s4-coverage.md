# Skeptic panel — COVERAGE-VERIFIABILITY lens on the Digest design (s4)

*2026-07-17. Reviewer: Claude-family skeptic, coverage-verifiability lens.
Subject: `docs/scratch/080-overnight/s4-codex-advisor.md` §4 (coverage backlink
and Dissolution safety) plus the manifest/envelope design in §1. Method:
re-derived the verification algorithm against the real substrate — live store
queries, engine/store source reads, `sl store verify` — not against the
document's own claims.*

## Verdict: AMEND

The coverage mechanism is genuinely verifiable — I walked the six-step
verifier against the actual schema and attacked it under merge, slice, and
content mutation, and the structural claims hold **provided all six steps are
conjunctive for dissolution**. But the design is written against a store state
that does not exist yet (lineage-opened source), asserts one property no
verifier step checks (manifest witness order), and leaves two checkability
gaps (below-cutline recomputation contract, prompt-commitment preimage).
Named amendments below. Nothing invalidates the approach.

## The verification algorithm, walked concretely

For each step in §4's verifier, here is the exact query/computation on the
real substrate, and whether it can run without trusting the digest author.

**Step 1 — source lineage matches.** Mechanism: compare manifest
`source.lineage` to `store_meta.own_lineage`
(`SELECT value FROM store_meta WHERE key='own_lineage'`,
`engine/sqlite_store.py:165-175`). **Empirical break: the flagship store has
no referent.** `sqlite3 .loops/data/project.db "SELECT name FROM sqlite_master
WHERE type='table'"` returns no `store_meta` table at all, and
`SELECT kind, count(*) FROM facts WHERE kind LIKE '_decl%'` returns **zero
rows** — the live project store (3,086 facts) has never run `absorb_genesis`.
The machinery exists (`sqlite_store.py:560+`, `sl store absorb`), but the
manifest field `source.lineage` and verifier step 1 are undefined against the
very store Digest is chartered to digest first. See Amendment A.

**Step 2 — every id exists and lies in the claimed cursor interval.**
Mechanism: `SELECT rowid FROM facts WHERE id = ?` for `after`, `through`, and
each manifest id; membership is `rowid(after) < rowid(id) <= rowid(through)`.
This is checkable, and it is **append-stable**: `merge.py:99` is
`INSERT OR IGNORE` with no rowid control, so a fact merged in after the digest
— even with a backdated `ts` — lands at the append edge, outside any captured
interval. The window set can never grow after capture. This is a real strength
of the witness-cursor choice over ts bounds; confirmed against
`_window_hash`'s own ordering-authority note (`sqlite_store.py:1192-1200`).
Caveat: rowid *values* are not durable — the facts table has a TEXT primary
key, so `compact_store` (VACUUM, `store/compact.py:24`) renumbers implicit
rowids. Order survives (VACUUM copies in rowid order); values don't. The
design already keeps rowids out of manifests; pin it as a test (Amendment G).

**Step 3 — uniqueness and count.** Trivial; the doc correctly demotes count
to diagnostic.

**Step 4 — recompute the manifest commitment.** Mechanism exists and is
transport-stable: `_fact_commitment_hash` (`engine/sqlite_store.py:215-232`)
is content-only (excludes id/rowid), embeds the stored payload TEXT
**verbatim**, and canonicalizes via JCS (`_canonical_bytes`,
`sqlite_store.py:102-109`, Go-oracle-pinned). Slice and merge copy the payload
column byte-identically (`slice.py:84-85`, `merge.py:93-99`), so the
commitment recomputes identically in any custody context holding the rows. A
source-store content mutation (sqlite is an open file) produces a mismatch →
uncovered. Fail-closed, correct. One implementation snag: these helpers are
module-private underscored functions in `engine.sqlite_store`; the doc forbids
reimplementation but names no export (Amendment F).

**Step 5 — covered ⊆ eligible inputs, never below-cutline.** The envelope
carries `input`/`context`/`coverage` ids but **no window-ids set and no
cutline record**. The check is therefore only computable by *re-deriving*
window ids from the interval on the source store (below-cutline =
window \ input). That works — but it is an unstated contract, and it works
only for as long as the eligibility rule is "in-window ∧ in-input." In the
first slice (full-window selection, no top-k) the check is vacuous-but-sound.
If a later selection slice ships without persisting the selection rule or the
excluded set, step 5 becomes uncheckable (Amendment D). Note the safe
asymmetry, which I verified is load-bearing rather than accidental: the
verifier only ever proves the covered set *valid*, never *sufficient*.
Sufficiency ("all contributing facts for this key/state are covered") is
computed dissolution-side against the local store. Under-claiming inputs can
therefore never cause false dissolution — the conservative direction is
structural. (Minor: `FoldState` tracks only the most recent contributing fact
id, `atoms/fold_state.py:52`; the full contributing set for the key-level rule
needs a kind+key scan. Computable, but Slice 5's exit criteria should name

**Step 6 — source chain seals through the endpoint; signature and target
receipt verify.** This is real, content-binding machinery today:
`window_hash` commits every full fact row (id, kind, ts, observer, origin,
payload, signature-when-present) in rowid order over
`(window_start, fact_cursor]` (`sqlite_store.py:1192-1219`), and
`verify_chain` *recomputes* it — "window_hash mismatch — facts in window
altered" (`sqlite_store.py`, verify_chain body). Ran it:
`sl store verify project` → chain intact, 58/58 ticks chained+signed,
3080/3086 facts sealed, 6 on live edge, signatures checked against the
registry. So "coverage pending until a source tick seals through `through`"
is implementable now, and the era-honesty language the doc uses ("verify to
the available era") matches shipped behavior (2,462 of 3,086 facts are
pre-signing-era unsigned; the verifier already discloses this).

## Attack walks

**Merge (A10 case — ids present, lineage different).** Digest facts and
source facts merged into a third store: ids and payload bytes survive
(verified above), but witness order does not — `merge.py` has no ORDER BY and
assigns new rowids in arrival order; s1 A4 concedes this. Step 1 refuses
(different/absent `own_lineage`) → uncovered. Correct and honest: coverage
claims are verifiable only against the source lineage's store. The doc should
state the verifier's input contract explicitly — verification is a two-store
operation (digest fact + resolvable source store), and there is today **no
lineage→store resolution mechanism** for a verifier holding only the target
(Amendment B).

**Same-lineage slice (the sharpest attack I found).** Today a slice has no
`store_meta` (slice copies only facts/ticks, `slice.py:84-103`) → step 1
refuses. But once genesis machinery matures, a slice *will* carry the source's
`_decl.genesis` fact rows (kind filter passes by default), and an
adopt/backfill could stamp the same `own_lineage` — yielding a store that
passes step 1 with a *different witness order* (slice's INSERT...SELECT has no
ORDER BY; a ts-indexed WHERE can return ts order, not rowid order). Interval
membership checks against that store answer for the wrong prefix — exactly
the "same handle, different prefix" scenario A10 exists to prevent. **The
defense is step 6, not step 1**: slice deliberately strips all chain columns
("a slice is a new custody context," `slice.py:93-99`), so no slice can
present a source chain sealing through the claimed endpoint. Verification
fails → uncovered. This holds **only if the six steps are conjunctive for
dissolution** — the doc says so in prose ("a later target tick seals its
receipt"; step 6 includes the source chain), but the property deserves a
fail-closed fixture: same-lineage-marker, reordered, chainless store must
verify UNCOVERED (Amendment, folded into D's fixture list / Slice 3 exits).

**Content mutation.** Caught twice independently: step 4 (manifest commitment
mismatch) and step 6 (`verify_chain` window recompute). No trust in the
digest author required.

**Digest-of-digest.** Explicitly deferred (§6) — correct, since recursive
coverage would need the target's chain state as a *source*, and tick lineage
is unmet (observation:architecture/strata-tick-lineage-unmet). The deferral
list is honest about why.

**Unsealed live edge.** "Coverage pending until sealed" is checkable (6
live-edge facts exist in the store right now; the verify command already
distinguishes them). No silent promotion path found.

## Is the structural/semantic split honest?

Yes — not a fig leaf, on three grounds I could not break:

1. The structural claim is *exact*: these fact ids, these content bytes, this
   interval, this lineage, asserted covered by this keyed observer. Every
   element recomputes from the store without trusting the author.
2. The semantic claim is *attributed*, not laundered: the covered-set
   assertion rides under a declared observer's signature, and dissolution
   requires trust-policy acceptance **on top of** structural verification.
   Accountability is real because the observer is a keyed, declared identity
   — the same accountability model as every other fact in the system.
3. The UI language is mandated ("coverage claimed by … · manifest verified",
   never "summary proven from facts"), and "covered, not merely old" is
   enforced by construction: no verifier step consults age, window
   membership alone, or kind.

The one soft spot: `prompt_commitment` is a hash whose preimage has no stated
retention home. A commitment without a producible preimage supports
author-side audit only, not third-party audit — the doc's "support audit, not
deterministic replay" slightly oversells it (Amendment E).

## Amendments

- **A (required). Define the lineage-unopened source case.** The live project
  store has no `store_meta` table and zero `_decl.*` rows; `source.lineage`
  has no referent and verifier step 1 is undefined against the first intended
  source. Either make "source lineage opened (absorb_genesis)" an explicit
  precondition for any coverage-bearing digest (refuse with teaching), or
  define an era-honest degraded mode ("no lineage marker — coverage pending,
  era-limited"). Silent today.
- **B (required). State the verifier's input contract.** Verification is a
  two-store operation: (digest fact, source store resolvable by lineage).
  Un-resolvable source ⇒ uncovered. Slice 5's "reachable target digest facts"
  assumes a lineage→store discovery mechanism that does not exist; name it as
  the dependency it is.
- **C (required). Resolve the order claim.** The manifest commitment is
  specified "in source witness order," but no verifier step checks manifest id
  order against source witness order. Either add the order check to step 2/3
  or declare order presentation-only. An asserted-but-unverified property in
  a verification spec is exactly the kind of drift this design exists to
  prevent.
- **D (required). Pin the step-5 recomputation contract and the conjunctive
  rule.** Step 5 is checkable only by re-deriving window ids from the
  interval; state that. Add fixtures: (i) future selection slices must
  persist the selection rule or excluded set or step 5 fails closed;
  (ii) same-lineage-marker chainless/reordered store verifies UNCOVERED
  (step 6 is the witness-order authority, all six steps conjunctive for
  dissolution).
- **E (minor). Prompt preimage retention.** State where prompt bytes live
  (dry-run artifact retention policy) or downgrade the audit claim to
  "binding if the author produces the preimage."
- **F (minor, implementation-plan). Export the canonical surface.**
  `_fact_commitment_hash` / `_canonical_bytes` are private to
  `engine.sqlite_store`; the manifest builder and verifier need a named
  export, or the "use the existing helper" instruction forces an import of
  underscored internals.
- **G (minor, ratchet). No rowid ever persists.** `compact_store` VACUUMs;
  implicit rowids renumber (TEXT PK table). Order survives, values don't.
  Add the enumerable test: manifests and handles contain fact ids only.

## What I confirmed empirically (methods)

- Live store has no `store_meta`, no `_decl.*` rows: direct sqlite3 queries
  on `.loops/data/project.db` (3,086 facts, 2,462 unsigned, 58 ticks).
- Chain verification runs and recomputes window content: `sl store verify
  project` (58/58 chained+signed, 3080/3086 sealed, live-edge disclosure) +
  `verify_chain` source ("window_hash mismatch — facts in window altered").
- Content commitment is content-only, JCS, payload-verbatim, transport-
  stable: `engine/sqlite_store.py:102-109, 195-232`; slice/merge copy columns
  byte-identically with no ORDER BY (`store/slice.py:84-103`,
  `store/merge.py:93-108`).
- Slice strips chain columns and carries no lineage marker (`slice.py:93-99`)
  — the fact that defeats the same-lineage-slice attack via step 6.
- Interval append-stability: no code path controls rowid on insert; merge is
  `INSERT OR IGNORE` at the append edge.
- `absorb_genesis` exists to open lineage (`sqlite_store.py:560+`,
  `sl store absorb`) — Amendment A is precondition-able, not blocked.
