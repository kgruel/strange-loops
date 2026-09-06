# Query implementation adversarial review — 2026-09-05

## Invocation

Fable 5.1 was run through the verified local `claude` CLI with the requested
model selector `claude-fable-5-1[1m]`, `--safe-mode`, `--restricted`, no
tools, `--no-session-persistence`, and JSON output. The static prompt is
`/tmp/loops-arrival-review/query-implementation-prompt-2026-09-05.md`; the
raw result is
`/tmp/loops-arrival-review/query-implementation-result-2026-09-05.json`.

The response used one turn and reported success. While its top-level `model`
field is null, `modelUsage` records `claude-fable-5-1` with 9,789 output tokens
and 7,321 thinking tokens; a 19-token Haiku routing prelude was also recorded.
The packet was deliberately limited to the new query contract, FileQuery
snapshot, consumer opener, declaration helper, and focused tests; it did not
review concurrent registry binding work.

## Findings and disposition

1. **Not adopted — later ledger append does not invalidate a bounded token.**
   The accepted read design permits custody to advance after the captured H.
   Resume re-attests token H and P with `head_at`, then bounds facts to P; a
   later head does not change that represented prefix. The temporary strict
   check was reverted. A real registry regression now appends after page one
   and successfully resumes the unchanged bounded projection.

2. **Accepted as defence in depth — compare the token generation at the
   consumer boundary.** FileQuery already compared its snapshot generation to
   the token. `open_read` now repeats that comparison after opening, so an
   adapter cannot accidentally omit it. A same-prefix SQLite payload rewrite
   regression confirms resume refusal.

3. **Accepted — a vanished projection cannot turn a continuation into an
   empty result.** The consumer now rejects an unrepresented snapshot when a
   token names P. The regression deletes the index then attempts an
   `ALLOW_BEHIND` resume.

4. **Accepted — CURRENT applies to a continuation too.** A token issued from
   an `ALLOW_BEHIND` read cannot be resumed under CURRENT if P is below H.
   FileQuery now raises `ProjectionBehind`; a focused regression covers it.

5. **Not adopted — alleged watermark hash mismatch.** A projection reports a
   `Watermark(lineage, ordinal)`, intentionally without a record hash. There
   is therefore no projection hash to compare. `ledger.head_at(watermark)` is
   the prescribed custody completion of that coordinate; it refuses a foreign
   lineage or absent ordinal, and its returned full head is the basis fact.
   Comparing it to an invented projection hash would assert evidence the
   projection does not hold.

6. **Already satisfied — cleanup on opener refusal.** The reviewer packet
   elided the surrounding `try/except BaseException`. The implementation
   closes snapshot, query, and ledger in that order while suppressing close
   errors, then re-raises the primary refusal. `OpenedRead.close()` uses the
   same order and is idempotent.

7. **Accepted with corrected invariant — declaration anchor must be licensed
   by the physical Arrival lineage.** `arrival_projection.licensed_own_lineage`
   only stamps the marker for an `_decl.genesis` fact whose id equals the log
   lineage. A fact id remains distinct from a full `Head`, but its identity
   string must equal `captured_head.lineage`. The consumer now rejects a marker
   or selected genesis id that differs; a corrupted-marker regression covers
   it. The original disposition incorrectly generalized legacy SQLite identity
   behavior to the supported Arrival projection.

8. **Not adopted — empty facts page and intra-record order issue.** A finite
   empty first select returns before accessing `rows[-1]`; `limit` is required
   to be at least one. The complete-record select uses the same `arrival_seq,
   id` direction as the main select. The reviewer’s third cursor observation
   was accepted separately as disposition 4.

## Remaining limits

The FileQuery view-generation proof hashes the entire bounded facts/ticks
projection, schema version, declaration anchor, and signature state in its
read transaction. It conservatively detects same-prefix derived-view changes,
but has O(bounded corpus) cost at every snapshot open and is not a cheap
pagination mechanism. Search remains capability-refused. This stage does not
provide a portable persisted cursor token, historical ranked search, aggregate
semantics, or read-time projection maintenance.

## Recheck

After dispositions: focused query tests passed; ruff passed. Broader
engine, SDK, and architecture checks are rerun after the concurrent registry
binding integration lands.
