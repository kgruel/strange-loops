# Slice 2 / WP4 gate report — KDL backend arm + registry + parity probe

**GATE: PASS**

Target: `slice2/wp4-kdl-registry` @ `ff86a2b4` (5 commits over wave base `0d38c969`,
ancestry verified). Gate worktree `~/Code/loops-s2wp4-gate` @
`slice2/wp4-kdl-registry-gate`, fresh `uv sync --all-packages`. The implementer's
worktree and the main checkout were not touched.

Every claim below was re-derived in this worktree. The impl report was read from git
bytes (`git show ff86a2b4:…`) and treated as the target of review, not its authority.

---

## 1. Brief oracle 1–6

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Parser: both forms accepted; unknown prop / child block / empty+blank backend refused | **PASS** | `TestStoreBackend` 7/7 green. Refusal messages match the design's spelling: `store: unknown property 'bakcend'`, `store: takes no child block`, `store: backend must not be empty` |
| 2 | Round-trip with the arm intact; backend absent from genesis payload | **PASS** | `test_backend_survives_the_document_round_trip` green; `test_store_and_path_never_enter_documents` extended with `assert "duckdb" not in blob` and green |
| 3 | Parity probe green over every repo `.vertex` | **PASS** | `test_every_tracked_vertex_resolves_identically_under_both_paths` green; scoping independently audited (item 4 below) |
| 4 | `residence.py` diff-empty; `test_residence.py` green unmodified | **PASS** | `git diff 0d38c969 HEAD -- …/residence.py` → 0 lines; same for `test_residence.py`; suite 23 passed |
| 5 | Rule 18 green with the registry registered; lang + engine green; counts reconciled | **PASS** | see the count table below |
| 6 | `git ls-files` clean on all changes | **PASS** | both new files tracked; 13 files in the diff, all tracked; no `.loops/` path in any of the 5 commits |

### Counts — re-run from scratch at both ends

Baseline measured by detaching this worktree to `0d38c969` and running the same
commands, so the env is identical at both ends (no `pyproject`/`uv.lock` in the diff).

| Suite | Base `0d38c969` | Tip `ff86a2b4` | Δ | Report claimed |
|---|---|---|---|---|
| lang | 655 passed | **670 passed** | +15 | +15 ✓ |
| engine | 1989 passed, 1 skipped | **2016 passed, 1 skipped** | +27 | +27 ✓ |
| architecture | 99 passed | **99 passed** | 0 | unchanged ✓ |
| `./dev test` (apps arm / final total) | — | **2530 passed, 1 xfailed — "All test suites passed."** | — | 2530+1xf ✓ (store arm 180 passed ✓) |

**Every delta accounted, by diffing collected test IDs base-vs-tip** (not by
arithmetic): lang +15 = 7 `TestStoreBackend` + 7 `[backend_declared]`
parametrizations + 1 `test_backend_survives_the_document_round_trip`. Engine +27 =
23 `test_arrival_registry.py` + 4 `TestBackendResidence`. **Zero tests removed or
renamed on either side** — the delta is purely additive, which is the check that a
count reconciliation can otherwise hide.

---

## 2. All four mutation demos, re-run in this worktree

Each: apply → run → record → `git checkout` → confirm `git diff` empty. Tree verified
clean and `HEAD` still `ff86a2b4` after the last restore.

| # | Mutation | Result | Verdict |
|---|---|---|---|
| a | unknown-prop refusal removed from `loader.py` | `1 failed, 236 passed` — `TestStoreBackend::test_unknown_property_refused`, `Failed: DID NOT RAISE ParseError` | **PASS** — as claimed |
| b | `store_backend=` dropped from `documents_to_vertex`'s `VertexFile` rebuild | `4 failed, 666 passed` — exactly `test_roundtrip_via_documents[backend_declared]`, `test_roundtrip_via_genesis[backend_declared]`, `test_backend_survives_the_document_round_trip`, `test_order_preserved_after_shuffle[backend_declared]` | **PASS** — the 4 named, exactly |
| c | `_reattach_ingress` carry dropped, threading intact | **full engine suite**: `1 failed, 2015 passed, 1 skipped` — only `TestBackendResidence::test_backend_survives_ingress_reattachment` | **PASS** — the "ONLY" claim holds at the widest in-package scope |
| d | `arrival_registry.py` removed from Rule 18 `_SCAN_TARGETS` | `1 failed, 98 passed` — `test_every_arrival_named_engine_module_is_scanned`, asserting `Arrival-surface modules not held to the glossary: libs/engine/src/engine/arrival_registry.py` | **PASS** — fires *and names the module* |

**Scope note on (b), in the implementer's favour.** The report's "4 failures" is
lang-scoped, which is where it was run. Under the same mutation the engine suite also
catches it (`TestBackendResidence::test_backend_survives_resolution_from_the_store`
and `…_ingress_reattachment` both fail). More failures in a wider scope is defense in
depth, not a contradiction.

**(c) is the load-bearing demo**, and it survives the strictest form of its own claim.
Run against all 2016 engine tests, exactly one catches it. That is the evidence that
the third rebuild site is a real and *separately* testable hazard — a WP that tested
threading without an ingress-shaped vertex would have shipped the bug green. The
pinning test is also non-vacuous: it first asserts re-attachment actually ran
(`env["TOKEN"] == "hunter2"`) before asserting the backend survived.

---

## 3. The three impl findings, verified at source

### (i) Three `VertexFile` rebuild sites — **CONFIRMED, root cause included**

Both carrying sites now thread the field: `declaration.py:904` (`_reattach_ingress`,
`store_backend=resolved.store_backend`) and `program.py:254`
(`_substitute_vertex_vars`, `store_backend=ast.store_backend`).

**The claimed root cause is real, and I initially misread it.** `ast.py:721` reads
`@dataclass(frozen=True)`, which looks like the stdlib decorator — but `ast.py`
defines its own `def dataclass(frozen=True): return _frozen` at `:113` and never
imports `dataclasses`. Empirically:

```
is_dataclass(VertexFile): False
replace FAILED: TypeError replace() should be called on dataclass instances
```

So every rebuild-from-an-existing-AST genuinely must hand-write its field list, and a
field it does not name is a field it drops. The generalization the finding offers
slice 5 (a constructor-completeness ratchet over the rebuild sites, not per-field
vigilance) is sound and I'd second it.

**Blast radius bounded — exactly 5 production construction sites, no sixth.**
`git grep 'VertexFile('` over `libs`+`apps` minus tests: `builder.py:192`,
`declaration.py:903`, `program.py:254`, `document.py:1016`, `loader.py:908`. No
`case VertexFile` anywhere, and no positional construction in tests either (the three
one-line test sites all use keywords) — so inserting `store_backend` between `store`
and `discover` is safe, which matters because `_frozen.__init__` *does* dispatch
`*args` positionally. `documents_to_vertex` has no production caller outside
`declaration.py`.

**`builder.py:192` characterized (the brief's question).** It cannot silently lose a
backend, because there is no source to lose it from. `VertexBuilder.__init__(name)`
seeds five fields from scratch; `self._store` is only ever set by `.store(path: str)`;
there is no `from_ast`/`VertexBuilder(ast)` seeding path anywhere in `libs` or `apps`
(only `VertexBuilder(name)` at `builder.py:296`). `build()` also omits `sources`,
`vertices`, `discover` and the rest — it is a fresh-construction API, not a rebuild
site. Default `None` is correct there, and the deliberate non-carry is right.

### (ii) `open` needs a projection — **CONFIRMED, behavior unchanged, deliberately unruled**

Reproduced: `test_opening_a_store_whose_projection_is_absent_refuses` mints an
`.arrival` log with no sibling index; `registry.open(...)` raises `FileNotFoundError`.

**The "which half" claim demonstrated, not accepted.** The pinning test asserts only
that `open` raises, which would pass whichever half threw — and `_open_file_backend`
constructs the ledger first, so either constructor could plausibly be the source. Split
apart against a freshly minted log with no index:

```
index exists? False
LEDGER half: OK -> FileLedger head ord 0
QUERY half RAISED: FileNotFoundError Store not found: …/s.db
```

So the finding is precise: the ledger half is perfectly openable and only the query
half needs the projection. `arrival_file_backend.py` is **not in the diff at all**, so
"behavior unchanged" is mechanical rather than argued. The behavior is pinned by that test, and
the WP correctly declined to rule the F2 question it was not given — the test docstring
and the finding both say so and point at Kyle's gate. Agreed: this is the right
disposition, and slice 5 is where it bites (a fresh clone has no index).

### (iii) The store-less fourth arm → `None` — **CONFIRMED**

`descriptor_for` guards `if ast.store is None: return None` before any path
arithmetic. Verified live across all four arms plus the two-level location check
(below). Reporting it rather than absorbing it was right: it widens a ruled
enumeration, and 7 of the 11 tracked vertices are that shape.

---

## 4. Design-choice audit

**`descriptor_for` purity — PASS with a documentation caveat (see F1).** Exercised
live on non-existent paths across all four arms; it never opens a store, never fails
on absence, and resolves relative locators against the vertex directory rather than
the cwd (run from `/private/tmp`, a `./s.arrival` beside `/nope/deep/v.vertex`
answered `/nope/deep/s.arrival`).

**`UnknownBackend` raised only in `open` — PASS.** One raise site,
`arrival_registry.py:187`, inside `BackendRegistry.open`. The class itself is WP1's
(`arrival_contract.py:450`). `descriptor_for` genuinely describes a
`backend="postgres"` vertex without complaint.

**No global registry, no import-time registration — PASS.** `register()` is called at
exactly one place, `with_builtin_backends`'s body (`:153`), a classmethod returning a
fresh instance. Re-registration refuses (`ValueError`, pinned).

**Lazy adapter import — PASS, independently reproduced.** A clean subprocess doing
only `import engine.arrival_registry` shows `sqlite3: False`, `engine.arrival: False`,
`engine.arrival_file_backend: False`.

**Parity probe scoping is honest — PASS.** It enumerates via
`git ls-files -z '*.vertex' .vertex`, so `.loops/` (gitignored, machine-local) cannot
skew it. I classified all 11 tracked vertices myself: 7 no-store, 3 `.jsonl`, 1 `.db`
— **zero arrival-canonical**, exactly as the docstring discloses. The disclosure is
accurate and stated where a gate would trip over it.

**The minted-fixture coverage asserts what the report claims — PASS.**
`test_the_registry_opens_the_artifact_the_legacy_path_opens` is parametrized over
**both** arrival arms (`backend="file"` explicit and bare transitional) and asserts at
**both** levels: naming (`Path(descriptor.location) == legacy.log_path`) and opening
(`ledger.head().ordinal == legacy_head["ord"]` plus
`query.projected_through().lineage == ArrivalLog(log_path).lineage()`). The ledger is
demonstrably *over* the artifact, not merely named after it.

**Backend-name strip — sound, but unpinned (F2).** `" file "` → `BackendDecl('file')`
is the right normalization: it follows from refusing blank values with the same
`.strip()`, and whitespace-significant adapter names would be the surprising choice.
Disclosing it rather than leaving it for the gate was the correct call. It is not
tested, though — see F2.

**`VertexFile.store` untouched — PASS.** The `store: Path | None = None` line is not in
the diff; only the new field and its comment are added after it.

**No consumer rewiring (SD-7) — PASS.** `git grep` for
`arrival_registry|BackendRegistry|descriptor_for` across the whole tree hits only the
new module, its own test file, and the Rule 18 target list. Nothing in a production
path calls it.

---

## 5. Contract conformance from the diff

`VertexFile.store` untouched ✓ · no consumer rewiring ✓ · no `role`/`lineage` parsing
(and `role="primary"` is actively *refused* today, so slice 5 adding it cannot collide
with a silently-accepted spelling) ✓ · no child-block grammar (refused) ✓ · backend
never enters `_decl` payloads — the extended `test_store_and_path_never_enter_documents`
re-run green, and `TestBackendResidence::test_backend_never_enters_store_payloads`
greps real sqlite payload rows for `duckdb` ✓ · `.loops/` absent from all 5 commits ✓.

Nice touch worth naming: both never-enter assertions use `"duckdb"`, not `"file"`,
precisely because `"file"` is a substring of too much to be evidence. That is the
difference between an assertion and a decoration.

---

## 6. The disclosed emission stray

**Confirmed at byte level, and the disclosure is accurate.** In
`.loops/data/project.jsonl`: `01M17DTEG4PVMM8VTNS8VZAGF9`, `kind:"finding"`, payload
carrying `"topic": "slice2-wp4-registry-open-needs-a-projection"` — `topic=` where the
kind folds by `name=`, hence no fold key. The corrected re-emit
`01M17DTQ69B5MEKHXJ03M0XRMA` is present once and its message states the supersession.
All three WP4 findings fold correctly and read back `open`. No repo action; noted for
the arc sweep.

One refinement for the sweep: the stray does **not** surface in the `Unfolded:` footer
of `loops read project --kind finding`, so the report's "a reader of the project store
will see one anomalous unfolded finding row" overstates its visibility slightly. It is
in the store bytes; the read path does not show it.

---

## Findings

**F1 — `descriptor_for`'s "no I/O, no adapter import" is true at import time, not at
call time. NON-BLOCKING (documentation precision).**
The module docstring says `descriptor_for` is "Pure: AST fields plus path arithmetic,
no I/O, no adapter import". Calling it imports `engine.arrival`, because it imports
`.residence` and `residence.py:57` does `from .arrival import ARRIVAL_SUFFIX, …` at
module level. Verified: after one `descriptor_for` call, `engine.arrival` is in
`sys.modules` (`sqlite3` stays out, and so do `FileLedger`/`FileQuery`). This is a
pre-existing `residence.py` property — `residence.py` is diff-empty, so WP4 did not
introduce it — and the subprocess test's import-level claim is exactly right. Only the
docstring's call-level phrasing overreaches. Worth a clause in WP5's doc pass.

**F2 — the backend-name strip is disclosed but not pinned. NON-BLOCKING (unpinned
behavior).**
`backend="  file  "` → `BackendDecl('file')` works, but no test asserts it.
`test_blank_backend_refused` pins `.strip()` in the *refusal check* only, not in the
*stored value*: a variant that reads `backend_name = str(...)`, refuses on
`if not backend_name.strip()`, and stores the unstripped name passes all 7
`TestStoreBackend` tests while shipping `BackendDecl('  file  ')` straight into an
`UnknownBackend` at open. Given the arc's own ratchet practice — an invariant that
lives only in a report drifts — this normalization wants one assertion. One line in
`TestStoreBackend`.

**F3 — non-string KDL property values coerce silently through `str()`. NON-BLOCKING
(bounded).**
`str(node.properties["backend"])` accepts any KDL value type:
`backend=5` → `BackendDecl('5')`, `backend=true` → `BackendDecl('True')`,
`backend=null` → `BackendDecl('None')`. All are bounded — an unregistered name is
refused at open — but `backend=null` is the uncomfortable one: it reads as "not
declared" and instead mints a backend literally named `None`, which will surface as
`no adapter registered for backend 'None'` rather than as the parse error it is. Not
in the brief's three refusals, so leaving it was correct scope discipline; flagging it
for slice 5, when adopt starts writing this property programmatically.

**F4 — two test-file nits. NON-BLOCKING (cosmetic).**
`test_document.py`'s new `_residence_stripped` has one blank line before it where the
file uses two, and its docstring says "every residence field cleared" while it clears
`store` and `store_backend` but not `path`. Harmless in context (`path` is already
`None` at all 9 call sites, which is why the old inline spelling didn't clear it
either), and no linter covers `libs/lang`. Mentioned only so it isn't mistaken for
intent.

None of F1–F4 blocks. F1 and F2 are natural WP5 pickups; F3 belongs in slice 5's adopt
design.

---

## Verdict

**GATE: PASS.**

All six brief-oracle items verified independently; all four mutation demos reproduced
with exactly the claimed failure sets, the "ONLY" claim in (c) confirmed against the
full 2016-test engine suite; all three impl findings verified at source rather than
accepted, including the `_frozen`-defeats-`replace` root cause and the bounded blast
radius of finding (i); every design choice in the audit list checked empirically. The
count reconciliation is exact and purely additive at test-ID granularity.

The work is honest about its own edges: the parity probe discloses that no tracked
vertex exercises the arrival arm before a gate could discover it, the projection
question is pinned as observed behavior rather than ruled, and the strip normalization
was named rather than buried. Four non-blocking findings, all documentation or
unpinned-normalization class, none touching behavior this WP ships.
