**Verdict: ACCEPT.** I found no P1 or P2 blockers. This is a static review only; I ran nothing.

## Prior findings

- **F1–F4: still resolved.** The new changes do not affect them.
  - F2: the phase promotion now rewrites `data` that was loaded under the lock (`:886-894`), so it cannot clobber a replaced intent.
  - F3: retirement at `:871` acts on the intent read under the lock at `:790`. Apply holds the same lock from the intent write through `_finish`, so the file being deleted is the one that was parsed.
  - F4: error normalization still applies to the locked read. `test_recovery_reads_replacement_intent_only_after_entering_lock` pins this.
- **F5: resolved, both halves.**
  - The preflight now runs before both appends: `:527-536` in apply and `:818-827` in recovery, before `:829`.
  - Both call `preflight_projection_maintenance` with the registry supplied to that call, at the predecessor head S.
  - Both raise `AdoptionRecoveryRequired` with the `intent_path`, append nothing, and retain the intent.
  - Every exit closes the handles it opened (`arrival_maintenance.py:200-202`, `:223-227`).
  - The already-appended branch correctly skips the preflight, because the commit is already known.
  - If the head moves between `ledger.head()` and the preflight's open, the result is `HeadMismatch` wrapped as `AdoptionRecoveryRequired`.
    - The label is imprecise, but no append has been entered and the intent is retained.
    - The next recovery retires or reconciles it.
  - The `_LostReturnRegistry` open-count adjustment matches the new open order: custody first, then the preflight.

## Round 2 follow-ups

- **Intent replacement race: closed.**
  - The lock target comes from the resolved intent filename (`:787`).
  - That is the same path `arrival_adoption_intent_path(plan.target_path)` produces in apply, so both sides share one lock.
  - `:796` refuses a moved or mismatched intent.
  - There is no nested declaration lock, so no deadlock.
- **Stale `intent_path`: done.** `:522-526`, `:543-547` and `:834-837` carry it, and `errors.py:109` serializes it.
- **Registry-open wrap (`:800-806`): correct.** It happens before any append, and the cause is preserved.

## Non-blocking defects (P3)

1. **Recovery touches the filesystem before it knows an intent exists** (`:790` versus `:791-795`).
   - `_declaration_lock` runs `mkdir(parents=True)` and creates the lock file before `read_text`.
   - **Trigger:** `recover_arrival_adoption("/nonexistent/dir/x.vertex.arrival-adopt.intent")`. The exact lock location depends on `_declaration_lock_path`, which was not in the packet.
   - **Consequence:**
     - The call can create a directory tree and a lock file for a mistyped path.
     - In an unwritable location, a raw `PermissionError` or `OSError` from the lock acquisition escapes both the adoption family and the SDK family (`errors.py:537` returns it unchanged).
     - Round 2 code refused this cleanly before touching anything.
   - **Fix:** add an `intent_path.is_file()` guard that raises `AdoptionApplyError` before taking the lock, and keep the authoritative read under the lock.
   - **Reproduction:** point `intent` at a path under a read-only or nonexistent parent. Expect `AdoptionApplyError` and no new directories.
2. **`RecursionError` escapes the F4 error family** (`:792-795`).
   - **Trigger:** an intent file containing `"[" * 200000`.
   - **Consequence:** `json.loads` raises `RecursionError`, which the `except` tuple does not catch. It reaches the SDK caller raw.
   - **Fix:** add `RecursionError` to the tuple.

## Optional suggestions

- An open failure with intent phase `appended` or `synced` is reported as `AdoptionRecoveryRequired`.
  - Its docstring says "preappend", and the SDK outcome is `refused`.
  - The recovery attempt itself committed nothing, so this is not wrong. Still, add `phase=data["phase"]` to the error so an automated caller does not read `refused` as "no commit exists".
- `_require_cache` at `:817` and the `AdoptionStale` raises at `:809`, `:863` and `:868` retain the intent but omit `intent_path`.
- There is still no cancel path for an intent that was never appended and whose published cache was deliberately changed afterwards.
  - The only way out is to restore the bytes stored in the intent and then append the old adoption.
  - This is the same design question from round 2, and I am not promoting it.
- Each preflight adds a Full walk per prepare, apply and recovery. That affects cost only.

## Missing context

- `_declaration_lock_path` and `_fsync_parent`.
- `AttestedLedger._observe` and `Compared.presented`, needed to confirm that the preflight's second open takes the O(1) unchanged branch and journals nothing new.
- `_file_binding`.

None of these changes the verdict.
