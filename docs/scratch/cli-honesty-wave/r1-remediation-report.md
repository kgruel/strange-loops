# cli-honesty-wave — round 1 remediation report

Agent: r1-remediation. Base: `6fc1dfb` (cli-honesty-wave tip, S1–S4 + R2 fix +
gate reports + sol brief). All verification via `uv run --package loops loops …`
(never the stale global `sl`). Reproductions run BEFORE each fix and re-run
AFTER; fixture: isolated `LOOPS_HOME` with `statusv` (decision by topic —
statusless; thread by name — status-bearing) and `citev` (decision/thread/cite).

## Verdict table

| Finding | Severity | Verdict | Commit |
|---|---|---|---|
| chw-sol-r1-s1-f1-comma-key-census | HIGH | FIXED | `859702b` |
| chw-sol-r1-s1-f2-custom-lens-inert | HIGH | FIXED | `cf05ca3` |
| chw-sol-r1-s2-f1-key-before-kind | MEDIUM | FIXED | `649c81b` |
| chw-sol-r1-s4-f1-nonref-field-bypass | HIGH | FIXED | `49e4e4c` |
| chw-r2-sibling-store-error-to-stdout | — | FIXED | `5f1b0df` |
| chw-s4-raw-emit-empty-cite | — | FIXED | `49e4e4c` (shared with s4-f1 per brief) |

No finding required judgment beyond its ruling — zero stops.

## Suite

- Worktree cwd: `uv run --package loops pytest apps/loops/tests -q` →
  **2500 passed, 1 xfailed** (baseline 2485 + 15 new pinning tests).
- `.loops`-bearing cwd (scratch dir with `.loops/project.vertex` declaring
  design/thread/decision/cite, via `uv run --project <worktree>`): →
  **2500 passed, 1 xfailed**.

One pre-existing fixture adapted: `test_why_flag.py` seeded two zero-address
cites as collect-degrade material; they now carry a resolvable ref
(consequence of the chw-s4-raw-emit-empty-cite ruling, noted in-file).

## Per-finding evidence

### 1. chw-sol-r1-s1-f1-comma-key-census — `859702b`

Files: `apps/loops/src/loops/cli/dispatch.py`, `apps/loops/tests/test_read_status.py`.

Fix per ruling: the census input is now the post-key_or set —
`_status_field_census(data, key_or=…)` narrows each section's items via
fetch's `_item_matches_key` (the predicate `surface.filter` mirrors as
`_row_matches_key`) before counting; a kind with no surviving rows counts as
empty (not evidence). No second detection layer.

Before:
```
$ loops read statusv --key design/a --status open --plain        # control
exit=2  stderr: read --status: kind 'decision' has no status field …
$ loops read statusv --key design/a,missing --status open --plain # defect
exit=0  stdout: No data yet.
stderr: note: kind 'decision' has no status field — --status cannot match it
```
After: the comma spelling answers byte-identically to the control —
`exit=2`, empty stdout, same refusal line. Boundary checks: all-prefixes-miss
(`--key nope1,nope2`) stays an honest empty at exit 0; a comma key reaching
the status-bearing thread (`--key design/a,t1`) keeps the mixed note + filter
at exit 0.

Tests: `TestCommaKeyCensus` (4: refusal, single/comma parity incl. identical
stderr, all-miss honest empty, mixed note+filter).

### 2. chw-sol-r1-s1-f2-custom-lens-inert — `cf05ca3`

Files: `apps/loops/src/loops/cli/dispatch.py`, `apps/loops/tests/test_read_status.py`.

Fix per ruling (REFUSE): on the static gate-fail branch, an explicit
`--status` refuses before any rendering — exit 2, stderr, wording in the S1
live/interactive family (`read --status: a custom lens renders its own shape
and does not apply the status filter — drop --status, or drop --lens X.` /
`… drop the vertex-declared lens.`). Placed before the `Format.JSON` branch
so `--json` cannot fall through to the raw dump. The inert note for --status
is overturned: `--status` is removed from the note's flag list; the bareword
`status=` predicate keeps its pre-S1 note-and-render behavior (S1 scoped the
honesty layer to the explicit flag).

Before:
```
$ loops read statusv --kind decision --status open --lens autoresearch --plain
exit=0  stdout: ## DECISION (1) … design/a …
stderr: note: read-grammar transforms (--match/--status/…) are inert …
```
After:
```
exit=2  stdout: (empty)
stderr: read --status: a custom lens renders its own shape and does not
apply the status filter — drop --status, or drop --lens autoresearch.
```
`--json` variant also refuses (exit 2, empty stdout).

Tests: `TestCustomLensStatusRefusal` (3: plain refusal, --json refusal,
bareword predicate keeps the note and the note no longer mentions --status).

### 3. chw-sol-r1-s2-f1-key-before-kind — `649c81b`

Files: `apps/loops/src/loops/commands/ls.py`, `apps/loops/tests/test_ls_exit_discipline.py`.

Fix per ruling: kind validation before key-applicability. `fetch_kind_stat`'s
collect-fold `--key` refusal now fires only for DECLARED kinds; an undeclared
kind falls through to `_run_kind_stat`'s count==0 validator and exits with
read's validator message, byte-identical to the no-key invocation. Live
undeclared kinds (`tick.*`) pass the validator on their row count and hit a
post-validator key-applicability backstop (same collect-fold message, exit 1),
so `--key` on a keyless kind never silently no-ops. Declared keyless kinds
keep today's exit-1 refusal (fetch data-API contract unchanged).

Before:
```
$ loops ls statusv --kind bogus --plain            # control
exit=2  stderr: Vertex 'statusv' does not declare kind 'bogus'. / Declared kinds: decision, thread
$ loops ls statusv --kind bogus --key x --plain    # defect
exit=1  stderr: Error: kind 'bogus' is a collect-fold (no fold key) — --key doesn't apply …
```
After: both exit 2 with identical stderr (validator message). Regression
guard: `ls citev --kind cite --key x` (declared collect) still exits 1 with
the collect-fold message.

Corner noted (parity-improving, within ruling): on an aggregation vertex,
`--kind bogus --key x` now reports the aggregation no-own-store error like
the no-key form, instead of the collect-fold error.

Tests: byte-identical pair + declared-collect regression guard in
`TestBogusKind`.

### 4. chw-sol-r1-s4-f1-nonref-field-bypass — `49e4e4c`

Files: `apps/loops/src/loops/commands/emit.py`, `apps/loops/tests/test_cite_vertex_slot.py`.

Fix per ruling: the cite refusal gate counts ONLY `field == "ref"`
resolutions (`cite_unresolved` / `cite_resolved` filtered on the
UnresolvedRef/ResolvedRef `field` attr). Non-ref fields keep their normal
typed-pin / sibling-`_ref` behavior; they can neither rescue nor doom a cite.
Refusal counts (attempted/inert disclosure) now derive from ref-field
attempts only.

Before:
```
$ loops citev cite thread:absent -m thread:other
exit=0  stderr: WARN: ref 'thread:absent' did not resolve — stored as typed
unresolved pin / stored: cite/<no-fold> @ … (refs: 1 resolved)
```
After:
```
exit=2  stderr: ERROR: ref 'thread:absent' did not resolve / ERROR: cite
refused — all 1 entity ref(s) failed to resolve; … nothing stored
```
Control (`-m ordinary`) unchanged (exit 2). Partial drop
(`thread:arc thread:absent`) still stores with WARN + typed pin.

Test: `test_resolving_nonref_field_address_does_not_rescue`.

### 5. chw-r2-sibling-store-error-to-stdout — `5f1b0df`

Files: `apps/loops/src/loops/commands/store.py`, `apps/loops/tests/test_store_command.py`.

Fix mirrors the R2 ls fix (`6c8d965`): pre-flight refusal in
`_dispatch_store`'s base-inspect path before `run_cli`, via `resolve._err` —
byte-identical message, stderr, exit 1. No local-layer clause: unlike ls,
`_resolve_target`'s bare path has no local-vertex fallback, so the root's
absence alone decides.

Before:
```
$ LOOPS_HOME=<empty> loops store --plain     # from an empty cwd
exit=1  stdout: <home>/.vertex not found. Run 'loops init' first.  stderr: (empty)
```
After: same exit 1, stdout empty, message on stderr.

Test: `TestBareStoreEmptyHome`.

Sibling defect OUT of this ruling's scope, recorded not fixed:
`loops store <missing-name>` still prints `<name> does not exist` to stdout
at exit 1 (raised inside `fetch()` under `run_cli`). Queued as a
finding-shaped emit for the arbiter.

### 6. chw-s4-raw-emit-empty-cite — `49e4e4c` (shared commit with #4)

Files: `apps/loops/src/loops/commands/emit.py`,
`apps/loops/tests/test_cite_vertex_slot.py`, `apps/loops/tests/test_why_flag.py`.

Fix per ruling: the cmd_emit cite gate refuses zero-address cites (exit 2,
stderr, nothing stored) — `payload["ref"]` carrying no addresses at all.
All-inert cites still store as provenance-only. After both fixes the gate is
ONE coherent condition, stated in the code comment: a cite stores only when
its `ref` field carries at least one address AND not every attempted
ref-field entity resolution failed.

Before:
```
$ loops emit citev cite message=x
exit=0  stderr: stored: cite/<no-fold> @ …
```
After:
```
exit=2  stderr: ERROR: cite refused — no ref addresses in the payload; a cite
is an attention signal and needs at least one ref; nothing stored
```
Boundary held: `emit citev cite ref=nosuchkind:zzz` (all-inert) still stores
at exit 0.

Tests: `TestZeroAddressCite` (4: no-ref-field refusal, resolving-message
composition with #4, empty `ref=` refusal, all-inert still stores).

## Round 2 addendum — chw-sol-r2-f1-malformed-token-evades-gate (HIGH) — `a52017d`

Sol r2 verified the six r1 fixes PASS across evasion variants but found the
cite gate's `ref_addrs` counted every non-empty comma token, so malformed
tokens (`ref=:x`, `ref=kind:`, quoted prose) evaded the zero-address refusal:
the canonical resolver rejects those shapes, so zero real addresses produced
neither resolved nor unresolved entries and read as "all inert" — empty cites
stored at exit 0.

Files: `apps/loops/src/loops/commands/resolve.py`,
`apps/loops/src/loops/commands/emit.py`,
`apps/loops/tests/test_cite_vertex_slot.py`.

Fix per ruling (reuse, don't re-validate): the resolver's ref-field token
acceptance is extracted as `resolve.parse_ref_token` — non-empty, no internal
whitespace (prose), `Address.parse` succeeding WITH a kind —
`_resolve_entity_refs`' loop now calls it, and the cite gate counts only
tokens it accepts. One spelling of the discriminator, shared by both call
sites. Semantics: valid-address-but-undeclared-kind stays inert
(provenance-worthy, counts and stores); an unparseable token never counts;
ALL tokens malformed refuses exit 2 like zero-address; a malformed token
riding a storing cite gets a per-token WARN on stderr with storage unchanged
(the raw token stays in the ref payload — verified in the store:
`ref=":x,nosuchkind:zzz"` stores payload ref `":x,nosuchkind:zzz"`).

Before (all exit 0, silent store):
```
$ loops emit citev cite 'ref=:x'              → stored: cite/<no-fold> @ …
$ loops emit citev cite 'ref=kind:'           → stored
$ loops emit citev cite 'ref=not an address'  → stored
```
After:
```
$ loops emit citev cite 'ref=:x'
exit=2  stderr: ERROR: ref ':x' does not parse as an address (kind:key) /
ERROR: cite refused — none of its 1 ref token parses as an address; …
nothing stored
```
`kind:` and prose identical. Mixed cases store with WARN:
```
$ loops emit citev cite 'ref=:x,nosuchkind:zzz'   # inert rescues
exit=0  stderr: WARN: ref ':x' does not parse as an address (kind:key) —
kept as raw text, not a ref / stored: …
$ loops emit citev cite 'ref=:x,thread:other'     # valid rescues
exit=0  WARN + stored (refs: 1 resolved)
```
Dry-run refuses (exit 2, no fact-JSON preview); `--json` refuses with empty
stdout (the structured receipt only fires post-store); verb-first
`cite t :x` refuses identically. r1 regressions held: all-inert
`ref=nosuchkind:zzz` still stores; valid cites store with resolution.

**Boundary consequence flagged for the arbiter**: the reused acceptance
requires a kind (a self-describing ref needs a separator), so a bare
separator-less token (`ref=barekey`) is malformed and now refuses when
alone — previously it stored silently as dead text (never attempted, never
pinned). Chosen because the alternative (bare `Address.parse` non-None)
would count quoted prose as an address — prose parses as a bare key — and
contradict the finding; a subset rule would have been a new validator.
Pinned as `test_bare_separatorless_key_is_malformed`.

Suite after: **2509 passed, 1 xfailed** from the worktree AND the
`.loops`-bearing cwd (prior 2500 + 9 new tests in
`TestMalformedTokenGate`). `./dev check` (architecture ratchet) 59 passed.
