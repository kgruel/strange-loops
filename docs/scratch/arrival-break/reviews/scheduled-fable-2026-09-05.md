# Scheduled Fable reviews

User requested the queued Fable reviews start in 15 minutes, at high effort.

- Start: September 5, 2026, **21:22:11 America/Chicago** (September 6, 02:22:11 UTC).
- Model: `claude-fable-5-1[1m]`; effort: `high` (supported by the installed CLI).
- Thirteen reviews, sequential, safe mode, no tools, no session persistence.
- At most five findings / 1,000 words per review; 20-minute per-call timeout.
- Stop on quota, failed invocation, unreadable result, or unverified model.
  No automatic retry, account switch, or model fallback.
- Each prompt is a refreshed complete source snapshot, including untracked
  files. Packet and source SHA-256 hashes are recorded in the manifest.
  Later source drift is recorded per review; findings need primary triage.
- The job gathers reviews only. It never edits implementation or accepts a stage.

The user-domain launchd job is `com.loops.arrival-fable-reviews.20260905`.
It runs once (`RunAtLoad=true`, `KeepAlive=false`), independently of this
conversation. The runner waits until the exact due time before invoking Claude.
Its status was verified as `scheduled`, with all thirteen reviews pending.

Runner, packet snapshots, manifest and launchd plist:
`/tmp/loops-arrival-review/scheduled-2026-09-05/`.

Live status and raw JSON / findings / stderr artifacts:
`docs/scratch/arrival-break/reviews/scheduled-2026-09-05/`.

To cancel the pending/running local job:
`launchctl bootout gui/501/com.loops.arrival-fable-reviews.20260905`.

## Queue

1. restore-forward
2. initializer-current
3. sdk-declaration
4. sdk-aggregate
5. runtime-capture
6. source-execution
7. sdk-source
8. sdk-batch
9. sdk-search
10. sdk-inspect
11. sdk-verify-pagination
12. custody-observer-guard
13. export

## Resume at low effort

The first review completed successfully on Fable 5.1 at high effort. The
runner stopped because its original model check incorrectly rejected a tiny
auxiliary Haiku call included in CLI aggregate `modelUsage`. The raw result
shows Fable output 20,379 tokens (18,467 thinking) and Haiku output 14 tokens.
The completed response and all model metadata were preserved; it was not rerun.

The user changed the remaining review effort to **low**. The model check now
requires substantive Fable output and permits only the observed small Haiku
helper (at most 128 output tokens, no thinking); unknown or substantive other
model usage still refuses. Synthetic classification checks passed.

The one-shot job resumed at `--effort low`, beginning with initializer-current.
It skips the completed restore-forward review. No quota retry or account/model
fallback was introduced. First review findings remain awaiting primary triage.

## Quota stop after ten completed reviews

At 21:59:05 CDT the verification/pagination request returned an explicit
session-limit response (no model usage). The queue stopped immediately.
Ten of thirteen reviews completed: restore-forward at high effort and nine
at low effort. Remaining: verification/pagination, custody observer guard,
and export. Reported reset: September 6 at 02:20 America/Chicago. No retry
is scheduled. Review findings remain awaiting primary validation and triage.

The CLI reports approximately 1,046,536 Fable cache-creation input tokens
across completed requests, plus 26,440 cache-read tokens. Large overlapping
source packets remained expensive even after the effort reduction. Future
review packets should be narrower and focus on unresolved findings/deltas.
