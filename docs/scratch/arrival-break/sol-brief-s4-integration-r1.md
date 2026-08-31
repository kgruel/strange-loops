# Sol integration review — slice 4 (migration sidecar), round 1

## 1. Anchor

Repo: /Users/kaygee/Code/loops, branch main.
Diff under review: `git diff 8a3ed22d...HEAD` (slice-4 territory: everything since the
slice-3 close). Commit count: 95 (five WPs, each merged --no-ff with its gate-report pointer branch). New package: `libs/migrate` (entire). Engine
touches: `arrival.py` (Entry signature carriage; typed ArrivalTornTail),
`arrival_file_backend.py` (append signed-draft carriage). CLI: `commands/store.py`
(migrate verb), `store_args.py`, `commands/init.py` (comment markers). Architecture
rules: Rule 4 row (`migrate`), Rule 7 (`migrate`), Rule 11 `_LIB_LAYER`.

## 2. Design contract (quote-verbatim set)

`design:arrival-break-slice4-migration-sidecar` (ratified 2026-08-30, Kyle; six rulings
M-1..M-6) plus amendments #1-#3 (same topic, later fold entries: #1 publish asserts location+backend only; #2 append honors RecordDraft.signature; #3 the arrival custody domain). NON-NEGOTIABLE
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
- WP4 (impl was a SONNET Claude agent — quota interlude; all others agy/Gemini):
  e1de3a4b (verb + staged dispositions), then fixes 44a14cea (custody arrival domain +
  arrival_signer_for/arrival_verifier_for — AMENDMENT #3), df17edd3 (CLI F1-F8:
  honor-or-refuse on positional-vs---vertex, --vertex REQUIRED, capability-probing
  signer guard, multi-line refusal render, pyproject metadata, e2e location pin,
  already-migrated pre-flight), e1edaa24 (migrate test-deps custody+sign declared),
  b226adce (custody compose-by-domain — one resolver per direction, four thin
  wrappers), 042f9504 (package-root exports), 080ff470 (parse-error refusal + dead
  disjunct removal + pyproject ordering).
- WP5: 70f7cdd5 (L.2 stale-prose sweep in engine, AST-verified prose-only),
  72c1136e (lang effective_store_clause query; migrate's ckdl import dissolved),
  158b5668 (Rule 19: third-party+workspace-test imports ⊆ declared deps),
  7b7c9ff1 (CLAUDE.md files + as-built HTML notes), then fixes 844d2994 (allowlist
  made SHRINK-FORCING), 7af93238 (rfc8785→apps dev group; atoms+lang→store dev
  group; allowlist 10→2), 4a127827 (vestigial regex locator swept;
  StoreClauseSpan drops .line/.raw), b3ba0bae (docs truth pass: staging path,
  report filename, the five preconditions verbatim, signed-not-verified, guard
  layering), 8ce590a9 (duplicate import).
- ARBITER-APPLIED TAIL (033063c2, no independent gate — sol is the only
  independent verification, check these FIRST): C1 libs/migrate/CLAUDE.md frozen-
  module names corrected (legacy_jsonl/legacy_sqlite/legacy_ids are the frozen
  three; legacy_source/inventory are live — the prior truth pass had it backwards)
  + line-number cite → symbol cite; C2 one E501 wrap in test_sidecar.py; C3
  test_sidecar.py:858 retired-label set narrowed to == "vertex_store_ineffective".

## 4. Known-open items (do not re-report; verify containment only)

- finding/s4wp3-migrate-undeclared-ckdl-bypasses-lang: CLOSED by WP5's dissolution
  (lang owns effective_store_clause; migrate's ckdl import gone). Verify the closure
  holds (`grep -rn "import ckdl" libs/migrate/src/` empty), nothing more.
- State-root test residue from pre-conftest runs (~267 journals in the user's real
  heads dir): operator cleanup, out of scope.
- One transient engine failure at the WP5 post-merge run (2306+1s on immediate
  re-run, name not captured): if you can reproduce ANY engine failure, that is a
  finding; a clean run confirms the flake reading.
- lang counts differ by env profile (682 worktree / 706+3s main checkout) — known,
  not a finding unless the FAIL SET is nonempty.
- Rule 19 (imports ⊆ declared deps) landed in WP5 — the former Rule-4 gap is closed; its allowlist is shrink-forcing with exactly two entries.

## 5. Verdict format

Per-finding: id, severity (BLOCKING/non-blocking/observation), file:line, the empirical
evidence (commands run, output), and for each §3 row a PASS/FAIL verdict. Close with
CONVERGED / NOT CONVERGED overall. Deliver ALL sections in one response; do not stop to
ask questions. For every "none found" category: the exact file:line ranges read and at
least one personally-run probe with pasted output designed to fail if the defect
existed. Write probes ONLY under your sandbox scratch dir.
