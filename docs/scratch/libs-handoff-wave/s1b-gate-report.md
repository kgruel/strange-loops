# S1b GATE report — slice/s1b-jsonl-ceremonies

Gate: independent verification against the ratified contract
`docs/scratch/libs-handoff-wave/s1a-encoding-proposal.md` (10-item oracle).
Branch verified: `slice/s1b-jsonl-ceremonies` @ a5426107 (merge-base includes
bc7f91c5 — confirmed). Verified in an isolated worktree via pointer branch
`slice/s1b-jsonl-ceremonies-gate`; independent oracle script:
`gate_oracle.py` (scratchpad; 44 checks, 0 failures) — written from the
proposal, not from the slice's tests.

## Overall verdict: **FAIL** — one narrow blocker (golden fixtures never committed); everything else PASSES

## Verdict table

| Item | Verdict | Evidence |
|---|---|---|
| Suites | PASS* | store 111 passed; loops 2521 passed + 1 xfailed; root 59 passed — match claims. Engine on fresh checkout: **1314 passed, 10 FAILED** (all 10 = missing golden fixtures, see item 7). With fixtures regenerated locally: 1324 passed. Topology-4: pass here after `uv sync` — consistent with the "pre-existing on base, vanish after sync" claim (S7's gate); not independently reproduced on bc7f91c5. |
| 1 genesis | PASS | Independent run: one plain `_decl.genesis` fact line, signed, id == lineage, offset == size, audit_deep ok. Receipt surface matches sqlite-canonical. |
| 2 second genesis | PASS | `GenesisExists`; log sha256-identical before/after. |
| 3 multi-change ceremony | PASS | One `"t":"batch"` line (log has exactly genesis + 1 line), N records, ONE effective ts, every row signed; declaration resolution round-trips to `parse(edited)`; audit_deep ok. |
| 4 single-change ceremony | PASS | Plain `"t":"fact"` line verified at the byte level; grep of full log bytes confirms no 1-row batch ever written. |
| 5 stale head | PASS | `StaleDeclarationHead`; log sha256-identical; lawful pre-CAS index catch-up confirmed (orphan durable line consumed, offset == size, log unchanged). |
| 6 fault injection | PASS | (a) unsignable → `UnsignableEdit`, log sha-identical; (b) `_stamp` crash injection → batch line durable + index rolled back → reopen tails ALL 3 rows atomically, offset == size, audit_deep ok, retry sane (diff empty — ceremony landed); (c) byte-chop mid-batch → truncated whole on open, neither row indexed, audit_deep ok. Matches the proposal's recovery matrix (except the genesis row — see deviation). |
| 7 rebuild equivalence | **FAIL (fixtures) / PASS (behavior)** | Behavior: delete `.db` → rebuild reproduces identical 7-field fact rows in rowid order; `own_lineage` gone with the db; explicit `adopt_lineage` re-derives it. But the golden-fixture half of the slice is broken — see "Blocker" below. |
| 8 trailing-batch index edit | PASS | Constructed independently: doctored EACH of the 3 rows of a trailing batch in sqlite (3 store copies); `audit_agreement` flags `last-line` for every victim. Open answers with rebuild. |
| 9 golden fixtures | **FAIL** | Fixture *tests* are correct (refusal CLASS pinned: `JsonlCodecError` + message patterns; torn tail → truncation not error; mixed-ts `_decl` batch → audit divergence not codec error — D1 boundary pinned). `generate_negatives.py` verified deterministic (ran twice, sha-identical). But the fixture `.jsonl` files are NOT in git — see Blocker. |
| 10 reanchor scope pin | PASS | Independent two-liner: `reanchor()` on a JsonlStore raises `JsonlCanonicalUnsupported`. |
| Codec adversarial | PASS | Hand-crafted lines all refused with attributable `JsonlCodecError`: 1-row batch ("at least 2 rows"), empty rows, nested batch, tick-in-batch, dup-id-in-batch, extra envelope key, trailing garbage on the line ("not valid JSON: Extra data"), non-TEXT inner payload. `serialize_batch` validates in the serialize direction too. Verbatim payload + signature byte-identical through serialize→deserialize→index→export→re-import. |
| Open-time cost | PASS | Diff-read of `_prefix_intact`/`_check_last_line`/`_suffix_unindexed`: batch expansion only on the single last-consumed line (per-inner-row `row_matches`, bounded by ceremony size); `_suffix_unindexed` probes by FIRST inner row — sound, since the crash window leaves the whole line unindexed. No content walk crept in. |
| Deviation (genesis recovery) | **JUSTIFIED** | See below. |
| export_jsonl flatten (deviation 3) | PASS + location claim | Flatten is index-equivalent: export of a ceremony-bearing store yields plain fact lines only; re-import/rebuild of the flattened log produces byte-identical index rows. **Location claim for the wave review:** the exported artifact LOSES the ceremony atomicity boundary — a torn tail in a rebuilt-from-export log can expose a ceremony subset as well-formed lines, and D1's audit assertion (batch-only) no longer applies. Property of exports by design per the impl report; flagged, not a fix. |

## Deviation ruling — genesis crash recovery: **JUSTIFIED**

(a) The hijack-vector claim is real and primary-sourced: commit `71de5111`
(2026-07-13, "adopt ceremony replaces singleton heuristic, ontology honesty
channel (re-review 1, 2)") removed the singleton-adoption heuristic from
`resolve_declaration_documents` with explicit rationale — "a pre-marker own
genesis and a merged-foreign one are physically identical, so ANY inference
(even a singleton heuristic) is the hijack vector it tries to close."
The S1a proposal's matrix row ("adopt as self, retry gets GenesisExists")
was stale against a ratchet that predates it. Reintroducing silent adoption
would have undone re-review #1.

(b) Walked the actual path by constructing the crash state independently
(`_stamp` injection during genesis): genesis line durable, `own_lineage`
unstamped → reopen tails the row in → retry raises `AmbiguousGenesis`
(typed) → explicit `adopt_lineage()` heals to the durable genesis id →
subsequent retry gets the honest `GenesisExists` → audit_deep ok. Complete,
typed, and documented (corrected docstrings in `sqlite_store.py` verified in
the diff).

(c) Fresh-clone path (log tracked, no db) on the crash store: opens, indexes
the genesis row, identity re-derives via explicit adoption. Works.

## Blocker — golden fixtures are gitignored, and the golden is unrecoverable

Root `.gitignore` line 9 (`*.jsonl`) swallows
`libs/engine/tests/fixtures/jsonl/*.jsonl`. Only the two generators are
committed. Consequences:

1. **Any fresh checkout of the branch has 10 red engine tests**
   (`test_jsonl_golden_fixtures.py` — FileNotFoundError). The impl report's
   "1320 passed" and "fixtures live in libs/engine/tests/fixtures/jsonl/"
   were true only of the impl worktree, where generated files existed
   locally. `git status` shows nothing (ignored), so the omission was
   invisible.
2. **The Go cross-language contract has no artifact in git.**
   `generate_golden.py` is non-deterministic by design ("ids/ts minted;
   tests read the committed bytes, never regenerate") — so the impl
   worktree's golden bytes exist ONLY on that worktree's disk and cannot be
   reconstructed from the repo. My local regeneration makes all 1324 engine
   tests pass, which proves the tests pin *shape*, not bytes — the byte
   contract itself is missing. (`generate_negatives.py` IS deterministic —
   verified by double-run sha compare — so the negatives are recoverable.)

**Required fix (impl agent, on the slice branch — one commit):** add a
gitignore exception (`!libs/engine/tests/fixtures/jsonl/*.jsonl` or a
scoped `.gitignore` in the fixtures dir) and commit the fixture files —
specifically the impl worktree's golden bytes, i.e. the ones its tests
actually ran against. The gate deliberately did NOT commit its own
regenerated golden: that would silently mint a different contract than the
one the slice was tested with.

After that one commit, this gate flips to PASS — every behavioral item
already passes independently.
