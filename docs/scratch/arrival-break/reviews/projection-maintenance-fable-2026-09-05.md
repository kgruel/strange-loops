# Projection maintenance — Claude Fable 5.1 review

Date: 2026-09-05  
Final verdict: **APPROVE**

## Packet and invocation

The static packet contained the complete new maintenance coordinator and
tests, the file-adapter maintenance class, registry maintenance registration,
SDK sync result/dispatch, the relevant ratified projection text, the root's
bounded stage decisions, and validation evidence. The prompt required at most
eight concrete findings and 1,500 words. The supplement required at most five
findings and 1,000 words.

Invocation:

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json
```

Raw artifacts:

- `/tmp/loops-arrival-review/maintenance-prompt.txt`
- `/tmp/loops-arrival-review/maintenance-result.json`
- `/tmp/loops-arrival-review/maintenance-stderr.txt`
- `/tmp/loops-arrival-review/maintenance-supplement-prompt.txt`
- `/tmp/loops-arrival-review/maintenance-supplement-result.json`
- `/tmp/loops-arrival-review/maintenance-supplement-stderr.txt`

## Initial findings and dispositions

1. **Medium — target hash could change after full verification.** Fixed. The
   locked bounded walk now compares the target record hash before insertion,
   and the coordinator refuses a same-height different returned head. A
   regression injects the change and proves row/watermark rollback.
2. **Medium — a later maintainer advance could turn a successful catch-up into
   a reported failure.** Fixed. A same-lineage observed prefix at or beyond the
   adapter return is accepted and reported as the actual head. Its view
   generation is left unknown when the observing snapshot was bounded to the
   older prefix. A regression covers H1 commit followed by H2 maintenance.
3. **Low — `BaseException` wrapping demoted interrupts.** Fixed. The
   coordinator catches `Exception`; `KeyboardInterrupt` propagates after
   cleanup. Covered directly.
4. **Low — default SQLite lock wait was too short for serialized catch-up.**
   Fixed with an explicit finite 30-second timeout and a real two-thread lock
   wait/success test. No new serialization exception was invented because the
   ratified contract provides none; `ProjectionSyncError` retains the original
   SQLite cause and observed-after evidence.

The review also noted that shared schema setup owns commits before the content
transaction. This is deliberate: it may materialize idempotent derived schema,
while fact/tick rows, `own_lineage`, and the watermark remain one atomic
transaction. Existing rows, partial marks, invalid axes, and foreign identity
markers are checked before schema setup and rechecked under the write lock.

The supplement approved every disposition and found no new correctness defect.
Its sole non-blocking observation was that the lock-wait test's liveness probe
is less diagnostic than it could be. The test still proves the material
contract by holding `BEGIN IMMEDIATE`, then requiring the waiting sync to
finish without a lock failure and return the expected projected head.

Root acceptance then identified the same generation-bound issue in the no-op
branch: a projection may advance beyond the coordinator's captured head before
its first snapshot. That branch now also returns `view_generation=None` when
the actual reported projection is newer than the snapshot's bound. A focused
capture-then-advance regression raises the maintenance file total to 16.

## Model metadata

The CLI result confirms the requested reviewer through
`modelUsage.claude-fable-5-1.canonicalModel = "claude-fable-5-1"`.

Initial review Fable usage:

- input tokens: 2
- cache-read input tokens: 3,305
- cache-creation input tokens: 23,016
- output tokens: 12,493
- thinking tokens: 10,458
- context window: 1,000,000
- cost: USD 1.08581625

Initial packet preprocessing also reports Claude Haiku 4.5 usage: 16,001 input
tokens and 15 output tokens.

Supplement Fable usage:

- input tokens: 2
- cache-read input tokens: 3,305
- cache-creation input tokens: 18,085
- output tokens: 3,922
- thinking tokens: 3,109
- context window: 1,000,000
- cost: USD 0.55864625

Supplement preprocessing reports Claude Haiku 4.5 usage: 12,240 input tokens
and 16 output tokens.
