# R3 remediation report — libs-handoff wave

Branch `fix/libs-handoff-r3` off `libs-handoff-wave` (2959eaf7). One commit
per finding; every regression test verified red pre-fix.

| Finding | Sev | Disposition | Commit | Fix | Regression |
|---|---|---|---|---|---|
| SOL-R3-01 (vertex_mutation.py) | blocker | **fixed** (arbiter ruling, 3 parts) | 5c4ae34a | (a) duplicate loop-kind nodes in the input refuse typed before mutation — raw-text multiplicity check at the splitter layer (`_loops_block_child_names` / `_assert_unique_kind_nodes`; a pre-condition, not a detector; parser oracle stays the post-condition authority). (b) `_verified` gains `definition=`: after add/edit the target kind's parse must EQUAL the requested LoopDef (belt-and-braces). (c) edit carries the suffix after the block's final close through the splice; a comment INSIDE the replaced span refuses with an actionable message (quote-aware scan) — `_verified`'s preservation claim is now honest. | sol's three repros verbatim + direct `_verified` mismatch test (`test_vertex_mutation.py`, 6 tests) |
| SOL-R3-02 (sqlite_store.py) | major | **fixed** (construction-grade honesty restored; ticks-PRAGMA cache kept) | 0c191515 | `_write_fact_row`/`_write_tick_row` (both stores) read the signature back INSIDE the write transaction — after INSERT (AFTER triggers fired), before commit — one SELECT per write; `append_attested`/`append_tick_attested` return the committed value. Ceremony paths (`absorb_genesis`/`absorb_edit`) do the same read-back pre-log, pre-COMMIT. No trigger-schema rejection. | trigger-nulled + signed fact, trigger-nulled tick, trigger-nulled genesis (`test_fact_signing.py::TestCommittedRowAttestationHonesty`) |
| SOL-R3-02 genesis fork | — | **needs-arbiter note, implemented as refusal** | 0c191515 | The ruling's "apply the same to the absorb path" underdetermines the nulled-genesis case: a genesis MUST commit signed (`UnsignableGenesis` invariant), so "report signed=False honestly" is not available. Implemented: read-back mismatch → `UnsignableGenesis`, rollback, no log byte (read-back runs before `_ceremony_persist`, so no orphan log line either). Same for edit rows → `UnsignableEdit`. Judged within-fence (honest receipt + existing invariant); flagging for visibility. | `test_trigger_nulled_genesis_refuses_rather_than_lie` |
| SOL-R3-03 (ceremony.py/probe.py) | major | **fixed** | 771184c4 | (a) `probe._writable` TOTAL over inaccessible paths (`try/except OSError` → not-writable answer); `write_surface_reason` never raises. (b) apply's pre-intent `_open_store` catch widened to `JsonlCanonicalUnsupported`, `JsonlCodecError`, `UnicodeDecodeError` → typed `refused`, zero intent residue. Call sites at plan/recover untouched (sol scoped to apply's pre-intent open). | sol's two repros: 0222 store dir after plan (jsonl+sqlite), empty log + out-of-band index rows |
| SOL-R3-04 (jsonl_store.py) | major | **fixed** | 16d320a2 | `_recover_index`: interprocess lock FILE beside the index (`flock` on own fd — serializes processes AND threads) held across detect→discard→rebuild; losers re-check under the lock by reopening at the path (re-checks corruption, binds the winner's inode); blind unlink replaced by atomic quarantine rename `<name>.corrupt.<pid>-<seq>` (pid+counter, no wall clock). Locked/no-log re-raise guards preserved in front; a locked retry under the lock also re-raises (live index, not corruption). | sol's synchronized two-thread harness shape: both openers converge on ONE inode, append via one visible to the other (`test_jsonl_store.py::TestConcurrentCorruptIndexRecovery`) |
| SOL-R3-05 (preflight.py) | major | **fixed** | d2f9bfc0 | `_sqlite_busy` (sqlite_errorcode 5/6 low-byte, message fallback) checked before the generic `sqlite3.Error` branch in `_recover_then_open` → status `refused` with a busy-specific try-again reason. Closed vocabulary holds. Index-not-discarded was already guarded at the store open (locked re-raise); this is preflight's reporting honesty only — jsonl_store's guard untouched per the ruling. | BEGIN IMMEDIATE-held behind index → refused-busy, same index inode, no quarantine, log untouched |
| SOL-R3-06 (ceremony.py) | minor | **fixed** | a002b34a | Intent creation moved inside the store-lifetime `try/finally`; OSError from `_write_intent` → typed pre-ceremony `refused` (nothing mutated). | injected OSError → typed result + `store._conn is None` |

## Suites

- engine: 1472 passed, 1 skipped, **4 failed — pre-existing on wave HEAD**
  (`test_topology.py::TestTopologyCacheResolution` x4; verified failing with
  all R3 changes stashed — environment-dependent, unrelated to this wave's
  diff)
- lang: 579 passed, 3 skipped
- store: 113 passed
- loops (CLI): 2522 passed, 1 xfailed
- root: 59 passed

## Beyond-fence judgments

Only the genesis fork above; everything else fell inside the arbiter
rulings as written.
