# Sol integration review — slice 4 (migration sidecar), round 1

DRAFT SKELETON — finalize after WP4/WP5 merge: fill the diff spec's commit count, the
WP4/WP5 rows, and the unverified-fixes table's tail before invoking.

## 1. Anchor

Repo: /Users/kaygee/Code/loops, branch main.
Diff under review: `git diff 8a3ed22d...HEAD` (slice-4 territory: everything since the
slice-3 close). Commit count: <FILL>. New package: `libs/migrate` (entire). Engine
touches: `arrival.py` (Entry signature carriage; typed ArrivalTornTail),
`arrival_file_backend.py` (append signed-draft carriage). CLI: `commands/store.py`
(migrate verb), `store_args.py`, `commands/init.py` (comment markers). Architecture
rules: Rule 4 row (`migrate`), Rule 7 (`migrate`), Rule 11 `_LIB_LAYER`.

## 2. Design contract (quote-verbatim set)

`design:arrival-break-slice4-migration-sidecar` (ratified 2026-08-30, Kyle; six rulings
M-1..M-6) plus amendments #1 and #2 (same topic, later fold entries). NON-NEGOTIABLE
lines for this review:

- GF-3: mixed-observer batch lines REFUSE at inventory, before any target bytes; the
  refusal enumerates every offending line across all condition classes (codec-invalid /
  mixed / absent-or-empty observer); no flag disables it; types are location claims, no
  remedy in a type. Empty-string observer ('' occurs in bulk in real legacy stores) is
  the absent class, spelling-distinct in the census; NO re-attribution path exists.
- The transformer NEVER regroups (backend-contract §04 binds it): partial-batch drop →
  typed refusal; whole-unit drop → mandatory exception-report entry; kind re-deciding is
  deleted.
- Migrated fact/batch/tick records are OUTER-UNSIGNED; inner signatures byte-verbatim;
  key introductions signed by the custodian, ordinals 1..k, establish the registry for
  FUTURE writes only. Legacy tick envelopes byte-preserved (M-4 native ticks).
- Sink: admission only (`ledger.append`), NO replicate, NO self-coordination, NO
  privileged path; first touch is mint-through-registry (bootstrap = journal entry #1);
  lineage-named staging, no rename at cutover; resume DERIVED by re-run from a verified
  target head, genesis verified against the declaration (custodian identity + key);
  refuse-never-repair (F2); publish gated on five preconditions; atomic descriptor
  publish via surgical edit + re-parse-equality + temp/fsync/replace; migration report
  signed, beside the target, evidence-not-authority.
- Engine amendment #2: the adapter CARRIES a draft's signature, the GRAMMAR judges —
  no adapter-level validation; byte-preserving for unsigned drafts.
- Quarantine: nothing imports libs/migrate (Rule 4 by birth); migrate's frozen copies
  import none of engine.jsonl_codec / engine.jsonl_store / store.rebirth / store._conn
  (AST ratchet in-package, dissolves at slice 5).

## 3. Unverified-fixes enumeration

"Unverified" = unseen by sol; opus gates verified every row below empirically, but
cross-family verification is the point.

ARBITER-APPLIED (no independent gate — sol is the only independent verification):
- docs/dev/ARCHITECTURE.md Layers-table row: `migrate` appended to the record-layer
  members. UNTRACKED FILE — not in the diff; verify by reading the file directly.

Fix commits, by WP (each gate-verified in its rounds; re-verify empirically where
possible):
- WP1: fe2120ef (9 F-items: validate-then-refuse ordering, enumeration completeness,
  era census → other, content-hash claim narrowed, per-arm None-not-zero fields,
  behavioral read-only test, quarantine ratchet, Rule-4 shrink, elem["id"] restore).
- WP2: 9c1a9372 (LegacySource consolidation + empty-observer + drop semantics + signer
  required), 5a531574 (sqlite arm through row_object_fault + shim deletion),
  58d3bf51 (tick era absence-vs-null).
- WP3: 40612844 (E1 engine signature carriage), fc708a09 (E2 typed ArrivalTornTail),
  8af7ef77 (sink F1-F7), 70a6dbb2 (test touch-up), 0ce53b2a (verifier typed catch +
  interim ckdl declaration).
- WP4: <FILL>
- WP5: <FILL>

## 4. Known-open items (do not re-report; verify containment only)

- finding/s4wp3-migrate-undeclared-ckdl-bypasses-lang: OPEN by ruling — interim =
  declared dep + fenced single call site; the lang store-clause-query dissolution is
  slice-tail work. Verify the fence holds (one ckdl call site), nothing more.
- State-root test residue from pre-conftest runs (~267 journals in the user's real
  heads dir): operator cleanup, out of scope.
- Rule 4 cannot see third-party imports (ratchet idea parked for tests/architecture).

## 5. Verdict format

Per-finding: id, severity (BLOCKING/non-blocking/observation), file:line, the empirical
evidence (commands run, output), and for each §3 row a PASS/FAIL verdict. Close with
CONVERGED / NOT CONVERGED overall. Deliver ALL sections in one response; do not stop to
ask questions. For every "none found" category: the exact file:line ranges read and at
least one personally-run probe with pasted output designed to fail if the defect
existed. Write probes ONLY under your sandbox scratch dir.
