# Cut C — sol cross-family review r1 (belt-and-braces after convergence)

You are an adversarial cross-family reviewer over a CONVERGED cut. Everything below has already passed slice gates, three scoped gemini reviews, a simplify pass, and three gemini-pro readiness rounds — your value is exactly the blind spots that whole family may share. Deliver ALL sections in one response; do not stop to ask questions.

## 1. Anchor
Repo: this checkout (loops monorepo), branch feat/arrival-libs. The cut under review: `git diff a49997cd..HEAD` — 6 implementation slices (C0-C5) + gate-ordered fixes + a simplify pass + 3 readiness remediation commits; docs/scratch commits are receipts, not code. Suites: `uv run --package <pkg> pytest libs/<pkg>/tests -q` (atoms, engine, sdk, store), root `uv run pytest tests -q`. All green at the last code commit; the current tip differs from it only by docs/scratch receipt files.

## 2. Design contract (ratified; full text docs/scratch/arrival-sliceC/design-proposal.md — read it first)
- Ordering is DECLARED, never inferred. atoms `Arrival() | ByKey(field)` + ONE totalization; ByKey sort key (K(record), record.id), id ascending — id is TIE-BREAK ONLY, NEVER semantic time (NON-NEGOTIABLE).
- Key family rule (added by readiness F1 remediation, now normative): `ts`/`id` resolve from the record ENVELOPE (payload never shadows), every other key from the flat payload — ONE definition, atoms.resolve_key_field, consumed by StoreReader.ordered, _combined_read, generate_lens, and the conformance runner.
- Missing-K = non-membership; type-mixed K refuses loudly (strict type identity, no coercion); Arrival() never synthesizes order.
- 'arrival' is single-store-only; aggregate reads default ByKey('ts'); aggregate + Arrival() refuses loudly.
- CAS token = arrival head (record_ordinal, fact_id); batch rows share the record ordinal; _INTENT_VERSION bumped 1→2; pre-bump intents refuse via IntentCorrupt (refuse, never guess).
- The whole bridge module store/jsonl.py is dissolved with residue swept; JsonlStore/SqliteStore engine classes frozen byte-for-byte except two licensed refusal-string rewords (jsonl_store.py ~:689/:755).
- Existing ts lens vector files are NORMATIVE and byte-frozen (loops-go reads them); regeneration must be byte-identical.
- KEEP fences: Spec.replay_from, VertexHandle checkpoint machinery (handle.py:752-1340), benchmarks/characterize.py, ArrivalStore write path except the CAS coordinate, legacy store families.

## 3. Do-not-re-report (settled rulings and receipted deferrals — re-litigation is noise)
(1) strict type-identity refusal incl. int/float and bool≠int (ts column REAL → column path all-float); (2) None-as-absent; (3) record-with-K-but-no-id raises the raw accessor error; (4) G3 apps-diff-empty gate deleted (ratified: apps NOT diff-empty this cut); (5) `sl store export` refuses with pointer, exit 2 even under --json; (6) ordered() prefix counts the VISIBLE stream; (7) jsonl_store.py:85 stale docstring frozen; (8) one-member-aggregate axis divergence pre-existing + refusal-pinned, wording deliberately kept; (9) is_suffix_stable lives in atoms, handle.py untouched; (10) sdk paged reads refuse unsupported orderings; read_summary/read_fact_by_id/read_ticks/read_timeline out of the ordering surface; (11) fact_key_stats/key_prefixes/resolve_entity_id are FOLD-KEY surfaces (contract payload[key]) — not ordering-family consumers (F2, refuted and audited); (12) kinds() strategy excludes '_decl.'; the filter-deletion durability gap (caught only by hypothesis cache) is accepted and receipted; (13) receipted deferrals: head-walk reconcile-mark race test, ceremony world-fixture arrival arm, lang non-hermetic .vertex collection, perf benchmarks pre-ship, _create self-enforce awaiting a ruling; (14) single_store param two-meanings receipted as design observation.

## 4. Unverified-fixes enumeration (least-reviewed commits — re-verify empirically where possible)
Every commit below was verified by a gemini gate or readiness round, but never by a non-gemini, non-Claude reviewer:
- c314a3e7 — test pinning ordered()'s prefix rides rowid not ts (gate-ordered, arbiter re-ran the mutation).
- c04af0de / 8d44561c / 0ebcead1 / ac335d66 / c7c898ee — simplify: Arrival-gated rowid sort in _fetch_combined_rows; FrozenInstanceError assertion; totalize docstring pins; OrderingError attribution reword + Raises sweep.
- fac793e1 / 13ef260c / 83ae19cc — readiness remediation: resolve_key_field family rule (3 restatements → 1); _combined_read _row_field derives envelope columns from atoms.ENVELOPE_KEYS; kinds() reserved-prefix filter + is_appendable_kind.

## 5. Verdict format
Per unverified-fix commit: PASS/FAIL with evidence. Findings: id, severity (blocker/major/minor/nit), file:line, claim, and evidence (probes you ran, with output). Close with CONVERGED / NOT_CONVERGED overall. A "none found" per area backed by the file:line ranges you actually read and at least one probe you actually ran is a valid, valuable result; bare approvals are not.
