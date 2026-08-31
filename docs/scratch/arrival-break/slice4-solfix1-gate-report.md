# Slice 4 — sol integration r1 remediation: GATE REPORT

**Verdict: PASS** (all five sol-HIGH blockings independently remediated) **with three
non-blocking findings**, one of which is an unmet acceptance item from the brief.

Range gated: `84f9c1b1..6fb119ff` (7 commits on `slice4/sol-fix1`).
Gate worktree: `/Users/kaygee/Code/loops-wt/s4-solfix1-gate` (branch `slice4/sol-fix1-gate`).
Every probe below was **rebuilt from sol's finding text**, not from the worker's tests;
the worker's tests were then run separately as a cross-check.

---

## 1. Scope

`git merge-base main HEAD` = `84f9c1b1`. Note `main` has advanced by one commit
(`e967adbf`, the brief itself), so a two-dot `main..HEAD` diff falsely shows the brief
as deleted; the merge-base diff is the real scope.

15 files, all inside the fence:

```
libs/lang/src/lang/loader.py              libs/migrate/src/migrate/inventory.py
libs/lang/tests/test_loader.py            libs/migrate/src/migrate/legacy_source.py
libs/migrate/CLAUDE.md                    libs/migrate/src/migrate/refusals.py
libs/migrate/src/migrate/sidecar.py       libs/migrate/src/migrate/transform.py
libs/migrate/tests/{_fixtures,conftest,test_inventory,test_quarantine,
                    test_refusals,test_sidecar,test_transform}.py
```

`git status --short --untracked-files=all` → empty in both the worker's worktree and
the gate worktree. No strays, no `.tmp/`.

**Scope correction to the worker's report.** Its F4 section lists
`apps/loops/src/loops/commands/store.py` under "Files Modified". That file was **not
modified** — in this range or anywhere. The claim is false; the fix is nonetheless
correct, because `_run_migrate` never passed a custodian in the first place (it already
probed `vertex_target.stem` for the signer), so removing `transform()`'s
`VertexFile.name` default was the whole CLI-arm fix. Verified by CLI probe below.

---

## 2. The five blockings, each probe rebuilt

### F1 — `s4-sol-r1-gf3-spelling-census-loss` → FIXED

Probe: `/private/tmp/s4solfix-gate-tmp/probes/probe_f1.py` (batch of `alice` + `bob` +
`observer=""`, built by hand, not via the fixture).

```
codec_invalid_lines= ()
mixed_observer_lines= ((1, ('alice', 'bob'), {'empty': 1, 'missing': 0}),)
absent_observer_lines= ()
  line 1: observers 'alice', 'bob' (1 row(s) with observer='' (empty string))
PASS
```

The ruled shape holds: `absent_observer_lines` stays empty for the both-aspect case
(report-once-under-mixed), and the census now rides *inside* the mixed entry.

`probe_f1b.py` walks the other three spelling combinations to prove the census is
genuinely spelling-distinct rather than hardcoded:

```
missing-field   mixed=((1, ('alice','bob'), {'empty':0,'missing':1}),)
                line 1: observers 'alice', 'bob' (1 row(s) missing 'observer' field)
both-spellings  mixed=((1, ('alice','bob'), {'empty':1,'missing':1}),)
                line 1: observers 'alice','bob' (2 row(s) with absent/empty observer (1 missing, 1 empty ''))
no-absent       mixed=((1, ('alice','bob','carol'), {'empty':0,'missing':0}),)
                line 1: observers 'alice', 'bob', 'carol'      <- no census clause when there is nothing absent
PASS
```

`test_inventory.py:201`'s `len(absent_observer_lines) == 0` assertion is intact and now
pins the census alongside it.

### F2 — `s4-sol-r1-resume-incomplete-draft-diff` → FIXED

The prefix diff at `sidecar.py:869-876` now compares all six `RecordDraft` identity
fields: `k`/`kind`, `observer`, `origin`, `body`, `at`/`authored_at`, `sig`/`signature`.
Wire key names verified against `engine/arrival.py:116` (`RECORD_FIELDS`) and
`_SIG = "sig"`; unsigned records omit `"sig"` entirely, so `.get("sig") is None` matches
an unsigned draft correctly.

Probe `probe_f2_f3.py`, sol's two shapes plus a control:

```
expected_draft_signature=None
resumed_target_signature='eeWp0ff6tZpFbtU0YfjT6PX0'...
REFUSED ordinal=1 -> Target record at ordinal 1 diverges from expected deterministic draft.

expected_authored_at=101.0
resumed_target_authored_at=1001.0
REFUSED ordinal=1 -> Target record at ordinal 1 diverges from expected deterministic draft.

control: honest partial target resumed to ordinal 3 (expected 3)
```

The control arm matters: the refusal is discriminating, not a blanket "resume is now
broken". The probe also asserts the `.vertex` and the target bytes are unchanged after
each refusal — both held.

**Mutation proof (hand-run by the gate).** Dropped the `sig` comparison from the diff:

```
migration_published=True
FAIL: resume accepted an outer-signed migrated record          <- my probe goes red
FAILED tests/test_sidecar.py::test_resume_refuses_when_target_record_differs_only_in_signature
1 failed, 1 passed, 66 deselected
```

The `authored_at` arm stayed green under this mutation, which proves the two arms are
independently pinned rather than one test covering both. Restored; `git diff` empty.

### F3 — `s4-sol-r1-resume-breaks-lineage-naming` → FIXED

The M-2 door check sits at `sidecar.py:787-795`, before the prefix diff, after the head
is read (so the lineage is known):

```
lineage=01M1B1C4BZ6AZHA5XA1W46XAG0
target_name=friendly-name.arrival
required_name=01M1B1C4BZ6AZHA5XA1W46XAG0.arrival
REFUSED type=TargetMismatchOnResumeRefused
  Resume target filename 'friendly-name.arrival' does not match genesis lineage
  '01M1B1C4BZ6AZHA5XA1W46XAG0' (expected '01M1B1C4BZ6AZHA5XA1W46XAG0.arrival').
  Advisory: target arrival stores must be lineage-named (<lineage>.arrival per M-2);
  rename target file or start a fresh migration.
```

Typed refusal, names both the filename and the lineage, as ruled.

### F4 — `s4-sol-r1-custodian-authority-source` → FIXED (both arms), NOT RATCHETED

**Arm (a), sol's exact probe shape, driven through the real CLI**
(`probe_f4a_cli.py`: `project.vertex` declaring `name "display-name"`, with a keyed
observer for the file stem `project`):

```
vertex_stem='project'  vertex_declared_name='display-name'
exit_code=0
lineage=01M1B1A3CXNP2F70B26E2G6CCK
post_vertex_store= ['store "./01M1B1A3CXNP2F70B26E2G6CCK.arrival" backend="file"']
genesis_observer='project'
PASS
```

Sol's `exit_code=2 / Custodian 'display-name' has no public key declared` is gone, and
the minted genesis names the stem. The derivation `vertex.path.stem if vertex.path is
not None else vertex.name` matches `custody/signing.py:112` (`self_observer =
vertex_path.stem`) — one authority source, as ruled. The `vertex.name` fallback applies
only to an in-memory vertex with no file, which has no stem to derive from.

**Arm (b), overrides removed.** Read back from the live objects:

```
run_migration (source_path, vertex_path, *, store_dir, signer, transform_rule=None,
               resume_target=None, tool_version='0.1.0') -> MigrationOutcome
transform     (source, vertex, rule=None, *, signer) -> TransformResult
run_migration custodian params: []
transform custodian params: []
```

`grep -rn "custodian=\|custodian_key=" apps libs clients tests --include="*.py"` returns
only `GenesisRequirements(custodian=...)` (the internal dataclass) and
`_make_vertex_file(custodian_key=...)` (the test helper that *writes a real `.vertex`
file*). No caller-supplied custodian path survives; internal tests construct real
vertices. Both confirmed.

**See finding 1 below** — the removal is not pinned by any test.

### F5 — `s4-sol-r1-surgical-publish-deletes-comments` → FIXED

Probe `probe_f5.py` runs a **real `sl store migrate` publish** against a `.vertex`
whose store line carries a trailing comment:

```
before: store "./a.jsonl" // KEEP THIS OPERATOR NOTE
after:  store "./01M1B1B5ARBKNGZXDZP45BNEKD.arrival" backend="file" // KEEP THIS OPERATOR NOTE
marker_preserved=True
```

The probe additionally asserts every *other* line is byte-identical and that the store
line's trailing bytes match verbatim — both held. Sol's `marker_preserved=False` is gone.

WP5-era shapes re-checked and still refuse-shaped / correct:

```
shadowed:   count=1 span=(34,54) slice='store "./real.jsonl"'      (the commented ghost is not counted)
duplicates: count=2 span=None                                      (refuse-shaped)
slashdash:  count=1 span=(36,56) slice='store "./live.jsonl"'      (/- disabled clause skipped)
```

**Mutation proof (hand-run by the gate).** Reverted `effective_store_clause` to a
whole-line span:

```
after:  store "./01M1B1CN8SR3N9XC4DK8WWXV7A.arrival" backend="file"
marker_preserved=False
FAIL: surgical publish deleted the same-line operator comment      <- my probe goes red
FAILED libs/migrate .. test_edit_vertex_store_clause_preserves_same_line_comments
FAILED libs/lang   .. test_store_clause_with_trailing_same_line_comment
FAILED libs/lang   .. test_unusual_spacing_and_indentation
```

Restored; `git diff` empty.

**Robustness of the new hand-rolled scanner** (`probe_scanner.py`) — it sits on the
publish path, so it was fuzzed rather than trusted. 14 adversarial shapes plus 4000
random inputs under a 3s SIGALRM: **zero hangs**. Raw strings, hashed raw strings,
escaped quotes, inline block comments, semicolon terminators and comment-with-no-space
all span correctly. Malformed inputs (unterminated string / block comment / raw) never
reach the scanner — the KDL parse refuses first.

One shape the sub-line scanner cannot span is a **line-continued** store clause
(`store "./a.jsonl" \` + newline + `backend="file"`); it truncates at the newline. This
is bounded, not a defect: `edit_vertex_store_clause` re-parses in memory *before*
writing, so the case is refuse-shaped with the file untouched —

```
REFUSED condition=vertex_reparse: ... edited .vertex could not be parsed ...
file_unchanged=True
```

### F6 — `s4-sol-r1-doc-truth-drift` (ride-along) → FIXED, with one new drift (finding 3)

Spot-checked the signing-envelope docstring against the code, line by line:

| Docstring claim (`sidecar.py:51-60`) | Implementation |
|---|---|
| `report_doc = {"body": report_body, "signer": custodian}` | `sidecar.py:987-990` — exact |
| `canonical_bytes = _canonical_bytes(report_doc)` | `:991` — exact |
| `digest = sha256(canonical_bytes).hexdigest()` | `:992` — exact |
| file format `{"body":…, "signer":…, "signature":…}` | `:1001-1004` `{**report_doc, "signature": …}` — key order matches |

CLAUDE.md Stage 2 now says the lineage is *minted* (random ULID) with determinism
attributed to the transform — true: `mint_lineage()` is `str(ULID())`
(`engine/arrival.py:369-371`). Stage 7 now says *non-`None`* — true: the writer raises
`PublishPreconditionRefused(condition="report_signature")` only on `None`.

`docs/dev/ARCHITECTURE.md`'s surrounding prose ("Seven libraries", missing
`migrate → engine, lang` graph edge, "record layer has four libraries") was outside the
brief's fence and remains **open**; sol itself marked it ignored.

### F7 — `s4-sol-r1-migrate-lint` (ride-along) → FIXED, with two smuggled changes

`uv run ruff check libs/migrate` → **All checks passed!** (was 111 errors: 72 E501,
27 F401, 5 I001, 3 SIM117, 2 PTH105, 2 SIM105).

To check for behavior smuggled into the "style only" commit, I AST-compared every file
in `61d41b90..6fb119ff` with all string constants normalised away, then diffed the
string constants separately:

```
AST-IDENTICAL  inventory.py, transform.py, conftest.py, test_quarantine.py, test_refusals.py
AST-DIFFERS    legacy_source.py, refusals.py, sidecar.py, _fixtures.py,
               test_inventory.py, test_sidecar.py, test_transform.py
```

Every AST difference in the four production files is mechanical and I read all of them:
extracting a `row_bytes` local before `content_hasher.update(...)`, splitting a boolean
into `obs_missing`, a ternary becoming `if/else`, tuple-literal wrapping,
`os.replace(a, b)` → `a.replace(b)` (identical call), `try/except OSError: pass` →
`contextlib.suppress(OSError)` (identical semantics). **No refusal message string
changed** — every one is byte-preserved through implicit concatenation.

Two things did ride in that are not formatting; see findings 2 and 3.

---

## 3. Suites — all reconcile with the brief

| Suite | Command | Result |
|---|---|---|
| migrate | `uv run --directory libs/migrate pytest -q` | **68 passed** |
| custody | `uv run --directory libs/custody pytest -q` | **19 passed** |
| lang | `uv run --directory libs/lang pytest -q` | **683 passed** |
| engine | `uv run --directory libs/engine pytest -q` | **2306 passed, 1 skipped** |
| apps (full, workspace root) | `uv run pytest -q apps` | **2539 passed, 1 xfailed** |
| architecture | `uv run pytest -q tests/architecture` | **101 passed** |
| ruff | `uv run ruff check libs/migrate` | **All checks passed!** |

All basetemps outside the worktree, `TMPDIR=/private/tmp/s4solfix-gate-tmp`.

Apps is **2539 + 1x with no new tests**, which reconciles exactly: no apps file changed,
so no apps test was added. The worker only ran `test_store_migrate.py` (9 tests) and
reported that as its apps arm; the full suite is run here for the first time.

---

## 4. Findings

### Finding 1 (non-blocking, but an unmet acceptance item) — the F4 removal is not ratcheted

`finding:s4solfix1-custodian-removal-unratcheted`

Brief acceptance item 2 required: *"re-add a `custodian=` parameter path → the derivation
test red (or grep-prove the parameter cannot be reintroduced without failing a test —
pin it)."* The worker's report does not claim this proof, and it does not hold. I ran the
mutation: re-added `custodian: str | None = None` and `custodian_key: str | None = None`
to `transform()` with sol's exact bypass semantics (`custodian or vertex.path.stem`,
`custodian_key or cust_decl.key`), then ran everything:

```
migrate suite:      68 passed
architecture suite: 101 passed
```

Nothing goes red. The defect itself is genuinely fixed at HEAD — arms (a) and (b) both
verified above — but the fix is held only by review vigilance, which is exactly the class
the ratchet test exists for. A caller-supplied custodian could be reintroduced in a later
slice with a green suite.

Cheapest pin, matching the shape already used elsewhere in the repo: a test that reads
`inspect.signature(transform)` / `inspect.signature(run_migration)` and asserts no
parameter name contains `custodian`. That is enumerable and shrink-only.

### Finding 2 (non-blocking) — the F7 lint commit weakened a test assertion

`finding:s4solfix1-lint-commit-weakened-assertion`

`libs/migrate/tests/test_refusals.py:93` in commit `6fb119ff`:

```diff
-    assert "Advisory: repair the source line(s) by hand or re-run migration after a ruled re-ceremony." in msg
+    assert "Advisory: repair the source line(s) by hand" in msg
```

E501 was resolved by **shortening what is asserted** rather than by splitting the string
across two lines. The advisory's second half ("or re-run migration after a ruled
re-ceremony") is now unasserted anywhere. The test's own docstring was edited from
"…distinctly in structured data and message" to "…in structured data" in the same
commit, which papers over the reduction rather than flagging it. Small, but it is
precisely a behavior claim lost inside a commit whose message promises none.

### Finding 3 (non-blocking) — the F7 lint commit deleted a doc-truth claim

`finding:s4solfix1-lint-commit-dropped-sqlite-hash-order`

`libs/migrate/src/migrate/inventory.py`, `SourceInventory.content_hash` docstring:

```diff
             JSONL arm hashes rows in line order (facts, ticks, and batch rows in envelope order).
-            SQLite arm hashes all facts in rowid order, then all ticks in rowid order.
-            It does NOT witness batch grouping ...
+            It does NOT witness batch grouping ...
```

The SQLite-arm sentence was **deleted, not wrapped** — the other long lines in the same
docstring were reflowed. The claim was true (`_read_sqlite` hashes the facts table in
rowid order, then the ticks table in rowid order), and it is the only place that order
was documented, so the JSONL arm is now documented and the SQLite arm is not. Landing a
doc-truth deletion inside the ride-along that fixed doc-truth drift is the notable part.

### Observations (no finding filed)

- **Dead backward-compat branch re-encodes the F1 bug.**
  `LegacySourceRefused.__init__` still accepts an `int` third element in
  `mixed_observer_lines` and maps it to `{"empty": 0, "missing": <n>}` — i.e. an
  unknown-spelling count is silently labelled "missing", the exact mislabel F1 removed.
  Both producers (`_read_jsonl`, `_read_sqlite`) now pass dicts and no test exercises the
  `int` path, so it is unswept residue rather than live behavior. The `else: spellings =
  dict(item[2])` arm after the `elif isinstance(item[2], dict)` arm is unreachable.
- **F5 added one ruff error to `libs/lang`** (99 → 100): `F841 Local variable 'tok_start'
  is assigned to but never used` at `loader.py:1044`, dead code inside the new
  `_scan_kdl_node_end`. `libs/lang` is not ruff-clean today and was not in the fence, so
  this is noted, not filed.

---

## 5. Verdict

**PASS.** All five sol-HIGH blockings are remediated, each verified by a probe rebuilt
from sol's own finding text rather than from the worker's tests; both required mutation
proofs (F2 signature, F5 whole-line span) were run by hand and go red, and the third
(F4) was run and does *not* go red, which is finding 1. Both ride-alongs are done. Every
suite reconciles. Scope held exactly; the tree is clean.

Recommended dispositions:

- Flip `s4-sol-r1-gf3-spelling-census-loss` → fixed at `81b6d5d6`
- Flip `s4-sol-r1-resume-incomplete-draft-diff` → fixed at `463810a6`
- Flip `s4-sol-r1-resume-breaks-lineage-naming` → fixed at `5a634bd4`
- Flip `s4-sol-r1-custodian-authority-source` → fixed at `5486c84b` (carry finding 1)
- Flip `s4-sol-r1-surgical-publish-deletes-comments` → fixed at `06844e55`
- `s4-sol-r1-doc-truth-drift` → fixed at `61d41b90`, ARCHITECTURE.md prose still open
- `s4-sol-r1-migrate-lint` → fixed at `6fb119ff`, carry findings 2 and 3

Findings 1–3 are all one-line fixes; none reopens a sol blocking.
