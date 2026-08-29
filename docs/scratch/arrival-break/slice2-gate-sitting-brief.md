# Slice-2 gate sitting — contract-text package (Kyle's rulings)

Six items accumulated across the slice, all "what does the contract text say" decisions.
Each with evidence and the panel/gate/sol trail. Rulings route into WP5 (docs + any
small ratified code additions) before the slice closes.

## 1. F2 — "Verification never repairs" (the anchor ruling)

Candidate text (proposal §E, drafted in contract voice for backend-contract.html §06):

> **Verification never repairs.** A `verify` at any level MUST NOT mutate the ledger,
> its projections, or head metadata — no catch-up, no truncation, no rebuild of
> existing projection state, no head re-stamp. A backend whose ordinary open path
> performs recovery MUST offer verification a route that does not, because an operation
> that repairs on the way to reading has destroyed the evidence it was asked to judge
> and can only report an agreement it just manufactured. Materializing a projection
> that does not yet exist is not repair: it destroys no prior state and can hide no
> divergence. Repair belongs to open-time recovery and to explicit rebuild operations,
> which say so in their names. This generalizes §07's rule that projection state is
> never used to repair canonical ledger history: neither direction of repair may
> travel under a verification verb.

The carve-out (sentence five) is the live choice: **absent ⇒ create permitted;
present ⇒ touch forbidden.** The stricter alternative (verification never writes; a
missing projection is an unanswerable scope) would refuse on a fresh clone.

New evidence since drafting:
- WP4's `finding:slice2-wp4-registry-open-needs-a-projection`: a minted log without its
  sibling index — `FileLedger` opens fine, `FileQuery` raises FileNotFoundError. A
  fresh clone IS this state. Under the carve-out, open/materialize is legal; under the
  stricter form, slice 5 needs a "not yet materialized" answer on the Query surface.
- Sol's WP2 torn-tail probe: the WRITE path recovers a torn tail under lock (truncate +
  land the suffix); WP1's `verify` takes no lock and refuses a torn tail. Consistent
  with the draft's repair-belongs-to-recovery line — the draft would ratify exactly the
  split the code already has.

## 2. Refusal root — D4 + G3 (one ruling)

Evidence: WP1's contract module translates exactly one backend error (`StaleHead` →
`HeadMismatch`, 1:1 from the CAS subclass); absence/corruption/double-mint propagate as
raw backend exceptions; two refusals (`pre-signed draft`, `Incremental` scope) raise
`NotImplementedError` outside the `ContractRefusal` root a contract-written caller
catches. Gate characterized, deliberately did not rule.

Question: does the contract OBLIGE a refusal taxonomy — every §-named refusal condition
surfaces as a typed `ContractRefusal` subclass, everything else passes through as
backend-specific — or stay silent and let adapters choose?

Recommendation: rule the narrow form — the conditions the contract TEXT names (head
mismatch, same-height fork, unknown backend, atomic limit, not-authority) must be typed
under the root; deliberately-absent capability (Incremental today) gets a typed
`NotSupported` under the root rather than `NotImplementedError`; everything else stays
backend-specific by design. Scope-the-claim: the root covers what the contract asserts,
no more.

## 3. G2 — does `head_at` join the contract surface?

§07 requires a VERIFIED `projected_through` head; the projection stores no record hash,
so resolution (watermark → full head) exists only as a concrete `FileLedger.head_at`
convention no other backend inherits. The ratified §03 table has nine rows; WP2-F-1's
fix pins the Protocol to exactly those nine both directions.

Options: (a) `head_at` joins the table (tenth row — a read op resolving a coordinate to
a verified head; natural home ArrivalQuery-adjacent or Ledger read side); (b) stays an
adapter convention, documented as such in WP5's doc pass; slice 5 decides when the
rewiring actually consumes it.

Recommendation: (a) — slice 5's verify/watermark rewiring and slice 3's head-attestation
compare-on-open both need head resolution; two consumers is a forcing function, and
adding the row now is one Protocol line + the already-written adapter method, with the
F-1 surface test updated in the same change.

## 4. WP2-D1 — does §08 portable import gain an op-table row?

`import_prefix` exists on `FileLedger`, is in `LEDGER_MUTATIONS` (the separation
ratchet covers it), but is off the Protocol. §08 is prose; the table has no row. WP2
took the narrow reading; the gate proved the growth bought real coverage.

Recommendation: defer to the DuckDB arc — one backend's import is a convention, the
second backend is where the op-table row earns its keep (same logic as the ledger/query
separation staying a unit test). Revisit if slice 5's `_run_export` repoint needs the
symmetric import verb on the contract.

## 5. WP2-gate-F-2 — resumable import (atomic-limit progress)

Import under `max_atomic_records` below the remainder can never complete (genesis-only
replica, idempotent refusal, no progress). §04 says a limit-one backend "imports by
verified single-record steps"; §12 lists import among the limits conformance exercises.
So a RESUMABLE importer is contract-implied but unbuilt; no live path reaches it
(limit defaults None).

Recommendation: acknowledge as contract debt with a named marker in §08 ("resumable
import is required for conforming limited backends; the reference file backend does not
yet implement it"), build when a limited backend exists (DuckDB arc at the earliest).
No slice-2 code.

## 6. Already routed (listed for completeness, no ruling needed)

- WP4-F3 (KDL typed-value coercion, `backend=null` → a backend named 'None') → slice-5
  adopt design.
- WP4-F1 (descriptor_for call-time import via residence's pre-existing engine.arrival
  coupling) → WP5 docstring clause.
- S2WP3-L-2 (rederive-failure staleness, pre-existing) → slice-5 rewiring design.
