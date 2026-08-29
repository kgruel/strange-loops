# Slice 2 design proposal — backend contract extraction

Arc: `design:arrival-break-implementation`. Slice: 2. Status: **proposed, awaiting arbiter
ratification** (ratify-gate-one-level-down — slices 5–6 and the adoption ceremony build
against the decisions below).

Contract of record: `docs/architecture/arrival/backend-contract.html` (Draft v1). The
contract surface is **settled** — this proposal designs *around* it and never redesigns it.
Plan of record: `docs/scratch/arrival-break/plan.md` §"Slice 2 — Backend contract extraction",
the cross-slice sequencing spine (constraints 1–4 bind this slice), the §Verification
slice-2 line, and the Appendix disposition table.

Every load-bearing claim carries a `file:line` cite, gathered in the spot-check table at the
end. **Two deviations from the written plan are reported in §C.1 and §D.2** — deviation from a
written contract is reportable in this arc, and both change what the impl agent builds.

---

## 0. How this proposal reads the slice boundary

One scope call the arbiter can veto, stated up front because it changes WP sizing.

`plan.md:42` puts "the CLI's twin resolvers … rename into the contract" inside the slice-2
bullet. But `plan.md:69` gives slice 5 a first half that is exactly "wires the surviving verbs
to the contract ops built in slice 2", and spine constraint 7 (`plan.md:113`) decouples the CLI
cut from the libs cut entirely.

**Reading taken here:** slice 2 *builds and proves* the registry; it does **not** rewire
consumers. The CLI resolvers (`apps/loops/src/loops/commands/store.py:52-100`), the SDK's
`canonical_mode` surface, and the ~30 `open_canonical_store` importers all stay on today's
resolution path untouched. Slice 2's obligation toward them is a **parity probe** (WP4) proving
registry resolution and legacy resolution name the same artifact for every `.vertex` in the
repo. Rewiring is slice 5's, where the deletions it enables also land.

This is what makes "canonical_mode/suffix dispatch keep working UNCHANGED through slice 4"
mechanical rather than a promise: after slice 2, `residence.py` is diff-empty and the registry
is an *additive* path that only `.arrival`/explicitly-declared stores take (§B.4).

---

## A. Contract module placement + naming

### A.1 Recommendation: three modules in `libs/engine/src/engine/`

| Module | Holds | Imports |
|---|---|---|
| `arrival_contract.py` | `Head`, `RecordDraft`, `Commit`, `DurabilityReceipt`, `Capabilities`, `VerifyScope` (Open/Incremental/Full), `StoreDescriptor`; the `ArrivalLedger` and `ArrivalQuery` **Protocols**; the typed refusals (`HeadMismatch`, `SameHeightFork`, `NotAuthority`, `UnknownBackend`, `AtomicLimitExceeded`) | stdlib + `typing` only. **No sqlite3, no `arrival` import at runtime** (TYPE_CHECKING where needed) |
| `arrival_registry.py` | `BackendRegistry.register(name, opener)` / `.open(descriptor) -> (ArrivalLedger, ArrivalQuery)`; `descriptor_for(ast, vertex_path) -> StoreDescriptor \| None` | `arrival_contract`, `lang.ast`, `residence`; adapters imported **lazily inside their opener** |
| `arrival_file_backend.py` | `FileLedger` + `FileQuery` — the adapter | `arrival_contract`, `arrival`, `arrival_store`, sqlite |

**Why three, not one.** The protocol module is what everything else imports, including
`libs/store` and eventually `libs/sdk`; a single fat module would make `import
engine.arrival_contract` drag sqlite3 and the whole 1845-line `arrival.py` for a caller that
only wants to name a `Head`. It also removes a cycle by construction: the adapter imports the
contract, the registry imports both, nothing imports the registry from below.

**Why `Protocol`, not ABC.** The adapter wraps existing concrete classes rather than
inheriting from new engine machinery, and the DuckDB adapter (next arc) will live outside this
package. The repo already uses this shape for a pluggable seam —
`libs/store/src/store/transport.py:4,20-21` states `Transport` as a Protocol.

**Naming clears Rule 18.** None of *contract, registry, backend, ledger, query, descriptor,
capability, replicate, draft, commit, head* appear in `_DENIED`
(`tests/architecture/test_rule_18_arrival_vocabulary_denylist.py:73-90`). All three modules are
born on the arrival surface and **join `_SCAN_TARGETS` at birth** — the rule's own stated
trigger (same file, `:33-43`, `:55-60`) — and the §F ratchet makes that join mechanical rather
than vigilance-dependent.

**Dependency direction holds.** `engine`'s allowed runtime imports are `{lang, atoms}`
(`tests/architecture/test_rule_04_lib_dependency_dag.py:24-27`); the registry's `lang.ast`
import is inside that set. `store`'s allowed set is `{engine}` (`:20-23`), so `libs/store` may
import the contract. **Nothing in engine may import store** — this forces a decision in §C.3.

### A.2 Wrap topology — what keeps the 14 arrival test files passing

`ArrivalStore` is **not modified** by the adapter work. `open_canonical_store`
(`libs/engine/src/engine/jsonl_store.py:256-277`) keeps returning it, and the adapter is
constructed *around* it. The ledger half wraps `ArrivalLog`; the query half wraps the
projection.

| Contract op | Wraps |
|---|---|
| `mint(options)` | `ArrivalLog.mint` (`arrival.py:756`) |
| `head(lineage)` | `ArrivalLog.head` (`arrival.py:1057`), mapped to `Head` |
| `append(expected, drafts)` | `ArrivalLog.append_marked_many` (`arrival.py:1355`), with F1's full-head compare |
| `replicate(expected, records)` | batched `ArrivalLog.append_record` (`arrival.py:1426`) under one lock — see §D.2 |
| `read(coordinate)` | `ArrivalLog.read` (`arrival.py:1042`) |
| `scan(after, through)` | `ArrivalLog.walk` / `walk_marked` (`arrival.py:953`, `:1222`) |
| `verify(scope)` | `ArrivalLog._verify_from` (`arrival.py:986`) + `verify_authorship` (`arrival.py:1655`) |
| `export(through, codec)` | net-new over `scan` + `encode_record` (`arrival.py:614`) |
| `capabilities()` | net-new; static declaration of profiles/limits/durability/codecs |

`FileQuery` wraps the **projection**, not the write handle: the resume mark that
`ArrivalStore` already persists (`arrival_store.py:203` `_read_mark`, `:219` `_stamp_mark`) is
the contract's `projected_through` watermark (§07) — it exists, it just isn't named that yet.

**The custody/reads separation, mechanically.** `FileQuery` holds no reference to the ledger's
append surface: it is constructed from a read handle, never from the `ArrivalLog`. Pinned by a
unit test in WP1 asserting no ledger-mutating op name is reachable from a query handle.
Deliberately a unit test and **not** a new numbered architecture rule — scope the claim: one
adapter is not yet a pattern, and the second backend (next arc) is where a rule would earn its
keep.

---

## B. KDL `.vertex` backend arm

### B.1 The spelling

```kdl
// file backend — today's arrival store, now declared rather than inferred
name "project"
store "/Users/kaygee/Code/loops/.loops/data/project.arrival" backend="file"

loops {
    decision { fold { by "topic" } }
}
```

```kdl
// a second backend, hypothetically (out of arc; shown to prove the grammar generalizes)
name "personal"
store "./personal.duckdb" backend="duckdb"
```

The location stays the **positional argument** — it *is* the descriptor's `location`
(backend-contract.html:120-127, `:133`) — and `backend=` is a KDL property. Legacy bare
`store "<path>"` keeps parsing and keeps meaning exactly what it means today.

### B.2 AST change

Add a frozen `BackendDecl(name: str)` to `lang/ast.py` and a new field to `VertexFile`:

```python
store_backend: BackendDecl | None = None
```

`VertexFile.store` is **untouched** (`lang/ast.py:705`, still `Path | None`). That is the whole
reason all ~20 existing readers keep working byte-identically through slice 4:
`vertex_reader.py:83,86,112,114,141,204,217,992,1013`, `resolve.py:685,1174,1234-1236`,
`vertices.py:138-139,235-237`, `devtools.py:53,57,455`, `ls.py:466,613`,
`commands/store.py:94-96`.

The two fields cannot disagree, because they are not two spellings of one value: `store` is the
location, `store_backend` is the adapter designation. `BackendDecl` as a small frozen dataclass
is the house pattern — `lens: LensDecl | None` and `observers: tuple[ObserverDecl, ...] | None`
already sit on `VertexFile` that way (`lang/ast.py:707-710` region).

**Alternatives considered.**

1. *Retype `store` into a `StoreDecl` object.* Rejected: `VertexFile` is constructed by keyword
   at five production sites (`lang/loader.py:877`, `lang/document.py:1007`,
   `engine/declaration.py:892`, `engine/builder.py:192`, `engine/program.py:254`) plus ~10 test
   sites, and every `ast.store` reader above changes in the same commit. That strands
   `canonical_mode` early — the exact thing the slice is forbidden to do.
2. *A separate top-level `arrival { … }` node.* Rejected: two declaration sites that can
   disagree about one store, and the ruling already dissolved the descriptor **into** the store
   clause (`decision:design/arrival-suite-review-dispositions` §4, quoted at
   backend-contract.html:140-149).
3. *A child block, `store "…" { backend "file" }`.* Deferred, not rejected: it costs a
   mutual-exclusion rule against the property form for no slice-2 gain. **Reserved** for
   adapter-specific options (a DSN's knobs) when a second backend forces them.
4. *`role` / `lineage` properties now.* Deferred explicitly. The contract names them
   (backend-contract.html:134-135) but nothing in slices 2–4 consumes them; their forcing
   consumer is slice 5's `_run_adopt` becoming a descriptor operation (`plan.md:74`). Parsing
   fields nothing reads is how speculative grammar ossifies. They land as sibling properties in
   the same shape when adopt arrives.

### B.3 Parse-site changes — and the refusal that makes this honest

`lang/loader.py:788-789` is the whole current handler:

```python
elif key == "store":
    store = Path(_require_arg(node, 0, "path", path))
```

It reads `node.args[0]` and **nothing else**. `node.properties` and `node.children` are
populated by ckdl and then silently discarded — so `store "./x.arrival" bakcend="file"` parses
clean today and would degrade to suffix inference forever. That is precisely the failure mode
explicit declaration exists to end, so the parse change is three things, not one:

1. Read `backend` from `node.properties`; build `BackendDecl`.
2. **Refuse any unrecognized property on `store`**, and refuse a child block, in the error
   style already used one branch away at `loader.py:849` (`Unknown config key: {key}`) —
   raised through `_error` (`loader.py:64-65`) as `ParseError`. Spelling:
   `store: unknown property 'bakcend'` / `store: takes no child block`.
3. Refuse an empty or blank `backend` value (`store "…" backend=""`).

Without (2), the whole explicit-declaration guarantee is one typo deep.

### B.4 Registry resolution, and the transitional law

```
StoreDescriptor = {backend: str, location: Path, lineage: str | None, role: str | None}
descriptor_for(ast, vertex_path) -> StoreDescriptor | None
BackendRegistry.open(descriptor) -> (ArrivalLedger, ArrivalQuery)
```

Three arms, and the third is the one that keeps slices 3–4 unstranded:

- **Explicit** — `ast.store_backend is not None`: `backend` is the declared name; `location` is
  `residence.canonical_store_path(ast.store, vertex_path)` (`residence.py:121-130` — pure path
  arithmetic, no mode dispatch, survives the break the same way `sqlite_sidecars` does per
  `plan.md:74`). Unknown backend name → typed `UnknownBackend` refusal naming the registered
  adapters; never guessed (backend-contract.html:132).
- **Inferred (transitional, DIES in slice 5)** — no explicit arm and
  `residence.canonical_mode(location) == "arrival"` (`residence.py:85-105`) → synthesize
  `backend="file"`. This arm carries its slice-5 deletion marker in a comment at the site.
- **Not a ledger at all** — `canonical_mode(location)` in `("jsonl", "sqlite")` →
  `descriptor_for` returns `None`. Those modes have no ledger and never route through the
  registry; they keep resolving through `open_canonical_store`
  (`jsonl_store.py:256-277`) exactly as today.

**Explicit wins, and there is no suffix cross-check.** A `backend="file"` on a `.duckdb`-named
location is legal, because under §02 the suffix carries no meaning once the backend is
declared. Adding a "does the suffix agree?" check would re-admit inference through the back
door on the very change that removes it.

### B.5 The round-trip hazard (verified, and it would be silent)

`lang/document.py:889-894` is `documents_to_vertex(documents, *, path=None, store=None)`, and
`:1007-1024` rebuilds `VertexFile` from an explicit kwarg list (`store=store` at `:1010`).
Residence — the store locator and the path — is deliberately **excluded from declaration
documents** and supplied by the caller (`document.py:709-710`), a property pinned by
`libs/lang/tests/test_document.py:386-392` (`test_store_and_path_never_enter_documents`).

**The backend name is residence too.** Two consequences, both binding:

- It must **not** enter `_decl.*` payloads. Putting an operational adapter name into signed
  declaration history would make a storage choice part of the vertex's absorbed identity.
- It must be threaded as a third residence parameter —
  `documents_to_vertex(..., store=..., store_backend=...)` — with `engine/declaration.py:512`
  and `:515` passing it. **Without this, a `loops add` / `loops rm` declaration round-trip
  silently drops the backend arm** and the store falls back to inference. That is a data-loss
  bug that no existing test would catch.

---

## C. Admission home

**Recommendation: `engine/admission.py` grows. No new module.**

### C.1 DEVIATION from `plan.md:41` — two of the three named functions are projection, not mint

The plan assigns the mint half as "`append*`, `fact_commitment_hash` :271–299, coordinate
machinery `_stage_arrival_coordinates`/`_stamp_arrival_axis`". Source-verified, the coordinate
machinery is **contract §07 projection obligation, not §04 append transaction**:

- `_stage_arrival_coordinates(conn, coordinates)` (`sqlite_store.py:437-514`) takes a database
  connection and a *coordinates **provider*** callable and requires it
  (`:441-443`, "coordinates provider is required for mode='arrival'"). It never assigns a
  coordinate — it stages ones that already exist.
- Every refusal it and `_check_arrival_provider_agreement` (`:516-590`) raise points the
  operator at `engine.arrival_projection.rederive_projections` — a projection rebuild
  (`:475`, `:482`, `:488`, `:500`, `:512`, `:541`, `:551`, `:561`, `:578`, `:589`).
- `_stamp_arrival_axis` (`:593-615`) writes `store_meta.coordinate_axis='arrival'`
  (`:609-614`) — projection metadata — and its own docstring calls it "the ONLY gatekeeper path
  allowed to write coordinate_axis='arrival'" (`:599`).
- Its callers are `ensure_coordinate_schema` (`:617`), reached from
  `arrival_projection.py:71,593`, `store/merge.py:180-182`, `store/rebirth.py:427-429`,
  `store/slice.py:72-74` — schema-ensure and projection-rebuild sites, never an append site.

That is §07 verbatim: "Every materialized row records or can derive `(arrival_ordinal,
arrival_seq)`… Rows beyond, missing before, or inconsistent with that watermark cause refusal
or rebuild" (backend-contract.html:378-381).

**Consequence:** this machinery does **not** go to admission. It belongs to the projection/Query
half, which `plan.md:41` already routes to "the file backend's projection engine" — so in
slice 2 it **stays put** and `FileQuery`'s `projected_through` obligation is built on top of it.
The mint-half extraction is therefore narrower than the plan text: `append*` and
`fact_commitment_hash`, not the coordinate trio. **Arbiter ruling requested.**

### C.2 The split that justifies growing admission.py instead of adding a module

Split by contract §04 step, not by file convenience:

- **admission.py owns the backend-neutral half** — step 4, "Validate drafts… admission
  decision" (backend-contract.html:236). It already holds exactly that shape: declared-policy
  resolution plus typed refusals, 134 lines, no I/O, no hashing
  (`admission.py:31-125`; `grant_for_observer` at `:91`).
- **The fence and the assignment stay in the adapter** — steps 1, 3, 5, 6, 7, 8. The fence is
  backend-specific *by definition*: `flock` here (`ArrivalLog._locked_head`,
  `arrival.py:1447-1459`), a row lock in PostgreSQL, a consensus step in a service. Lifting it
  into a shared module would be lifting the one thing that cannot be shared.

That split is the argument against a separate `mint.py`: everything that would go in it is
either backend-neutral policy (belongs beside the policy already in admission.py) or
backend-specific fencing (belongs in the adapter). A third module would hold only the boundary
between them.

### C.3 What moves, and why the identity trio has no choice

Into `engine/admission.py`:

| Moving | From | Why |
|---|---|---|
| the admission op (§04 steps 1–8 orchestration, caller-side) | `store/merge.py:244-324` `_merge_into_arrival` | extraction, not redesign — the `append_marked_many` + `AppendRejected` retry loop (`:289-324`) already *is* the op |
| `MergeDivergence` / `_comparable` / `_refuse_divergence` | `store/merge.py:475-642` | **forced** — see below |
| `_verify_admitted_rows` / `_source_registry` | `store/merge.py:520-603` | admission policy (contract §04 step 4) |
| `_entry_for` → `RecordDraft` constructor | `store/merge.py:698-768` | its tick-chain nulling is the marker that this is admission |
| `fact_commitment_hash` + `_canonical_bytes` | `sqlite_store.py:271-299`, `:158-172` | see below |

**The trio's relocation is forced, not chosen.** If the admission op lives in
`engine/admission.py` and needs `MergeDivergence`, then either the trio moves in the same
change or engine imports from store — which `test_rule_04_lib_dependency_dag.py:24-27` forbids
outright (`engine`'s allowed set is `{lang, atoms}`). Deferring the physical move to slice 5 is
not available.

**`fact_commitment_hash` moves now.** It is the *fact-domain* content commitment — the inner
signature that travels through re-custody, per the just-pinned wire law
(`decision:design/arrival-wire-v1-pin`, ruling 5) — so it survives the break. Leaving it in a
module that becomes the projection engine would file the signing commitment under projections.
Its one cross-lib production caller is `store/merge.py:572`, inside `_verify_admitted_rows`,
which is moving to the same destination — the import shortens rather than lengthens.

**Constraint: do not mint a third `_canonical_bytes`.** Two spellings exist today
(`sqlite_store.py:158-172` and `arrival.py:277`). The sqlite spelling **moves with the
function** and becomes the surviving one for the fact domain; `sqlite_store.py` imports it back
for its five remaining internal callers (`:1210`, `:1590`, `:1799`, `:2442`, `:2760`), all
legacy mint paths that die in slice 5. `arrival.py`'s spelling stays put — it serves the
just-pinned wire codec, and consolidating it in slice 2 would touch the wire path one slice
after pinning it. Named here as a deliberate second spelling with consolidation deferred to
slice 5's residue sweep, so it reads as scoped rather than missed.

**Extraction stops at delegation.** `_merge_into_arrival` **delegates** to the admission op;
no merge arm is deleted. Spine constraint 3 (`plan.md:109`) is satisfied by ordering, not by
deletion.

**Rule 18:** custody moves into `admission.py`, which is the rule's own stated join trigger
(`test_rule_18…:40-43` — "they join because CUSTODY MOVED INTO THEM"). It joins
`_SCAN_TARGETS` in the same change, and Rule 18 green is that WP's gate.

---

## D. Work-package split

**Ordering.** WP1 first (everything types against its types). Then **WP2, WP3, WP4 run in
parallel worktrees** — their file sets are disjoint. WP5 last.

```
WP1 ──┬── WP2   (arrival.py, arrival_file_backend.py, vectors)
      ├── WP3   (admission.py, sqlite_store.py, store/merge.py)      ──┬── WP5
      └── WP4   (lang/*, engine/declaration.py, arrival_registry.py) ──┘
```

WP2 must not start before WP1 lands: both edit `arrival.py`, and WP2 builds on the adapter WP1
creates. WP3 and WP4 share no file with each other or with WP2.

### D.1 WP1 — contract surface + file adapter + F1 + the GF-2 ratchet

**Scope.** `arrival_contract.py`, `arrival_file_backend.py` (§A); the three Rule 18
`_SCAN_TARGETS` joins plus the §F completeness assertion; **F1 closed at both sites**.

**F1 has two sites, not one.** The plan names `arrival.py:1392` (`append_marked_many`). The
identical ordinal-only compare also sits in `append_marked`'s `build()` at
`arrival.py:1330` — `if following is not None and headr["ord"] != following`. Close both, or
the stronger pin is one method away from being bypassed.

Recommended shape: `following` widens from `int | None` to the full head (a `Head`, or the head
record), and an ordinal-only `int` is **refused** rather than accepted-and-widened —
construction over detection (`decision:practice/construction-vs-detection-ratchets`), so no
caller can pass a weaker pin. Blast radius is small: `store/merge.py:307` and tests.

**Exit criteria.**
1. All 14 arrival test files green, unmodified in intent (13 in `libs/engine/tests/`, 1 in
   `libs/store/tests/test_arrival_merge.py`).
2. CAS-race conformance gate with **full-head** compare: two writers at one expected head,
   exactly one commit wins (backend-contract.html:592).
3. Injected-failure-per-append-stage gate: no partial logical group visible
   (backend-contract.html:593).
4. Query-handle separation unit test (§A.2).
5. Rule 18 green with three modules registered, **and** the completeness assertion
   mutation-demonstrated (§F).

### D.2 WP2 — `replicate`, `export`, minimal portable import

**DEVIATION from the plan's risk framing.** `plan.md:43` and the seam analysis §3 say
`replicate` has "no implementation anywhere in the repo" and is net-new. That is true of every
**libs/store write path**, and it is *not* true of the arrival primitive:
`ArrivalLog.append_record` (`arrival.py:1426-1445`) already appends a record that carries its
own coordinate, validating rather than assigning, and checks a supplied `rh` rather than
trusting it (`:1429-1435`). So `replicate` is **composition, not greenfield**: batched
`append_record` under one lock acquisition, plus the full-head CAS pin from WP1, plus a typed
same-height-fork refusal. Stated so the impl agent does not build a second appender beside the
one that already has the right posture.

**Export and a minimal import are in scope, not just replicate.** The slice-2 verification line
(`plan.md:97`) requires "export/import/export byte identity", which cannot be gated without
both. Import is scoped to §08's default only — a new empty replica, or a non-empty target with
**exact prefix agreement** through its head, else refuse (backend-contract.html:411-417). No
merge semantics: re-coordination is admission, and admission is WP3.

**Exit criteria.** Three new replicate vector families in `spec/conformance/vectors/` —
exact-suffix accept, same-height-fork refuse, stale-replica catch-up **preserves hashes
byte-for-byte**; export → import → export byte-identical (backend-contract.html:598); snapshot
consistency while another writer appends (`:597`).

### D.3 WP3 — admission extraction

**Scope.** §C.3's moves; `_merge_into_arrival` delegates; `admission.py` joins `_SCAN_TARGETS`.
No merge arm deleted, no `canonical_mode` touched.

**Exit criteria.** `libs/store/tests/test_arrival_merge.py` and
`libs/store/tests/test_admission_verification.py` green unmodified in intent; Rule 4 green (no
`engine → store` import appears); Rule 18 green with `admission.py` scanned; mutation
demonstration in the slice-1 style — revert the delegation and the merge admission tests fail.

### D.4 WP4 — KDL arm + registry + parity probe

**Scope.** §B in full: `lang/ast.py` field, `lang/loader.py` parse + refusals,
`lang/document.py` + `engine/declaration.py` residence threading, `arrival_registry.py`.

**Exit criteria.**
1. Parser tests: both forms accepted; unknown property refused; child block refused; empty
   `backend=` refused. (Today **no test exercises props on `store` at all** — the silent-drop
   behavior is entirely unpinned.)
2. Round-trip test: a backend-declared vertex survives `vertex_to_documents` →
   `documents_to_vertex` with the arm intact, **and** the backend name still never appears in
   the genesis payload blob (extending `test_document.py:386-392`'s assertion).
3. **Parity probe** over every `.vertex` in the repo: for arrival-canonical stores the registry
   ledger names the same artifact `open_canonical_store(resolve_canonical_path(...))` opens;
   for jsonl/sqlite fixtures `descriptor_for` returns `None` and resolution is byte-identical.
4. `residence.py` diff-empty; existing `libs/engine/tests/test_residence.py` green unmodified.

### D.5 WP5 — doc pass, residue sweep, gate prep

**Scope.** `backend-contract.html` status/conformance touch-ups for what slice 2 actually
built; `libs/engine/CLAUDE.md`'s store table and `libs/store/CLAUDE.md` updated where the
admission move changes the described shape (dissolution practice — residue swept in the same
change, not a follow-up); the §E addendum's HTML edit **only if Kyle ratifies at the gate** —
otherwise WP5 ships without it and the text below stands as the open candidate.

**Exit criteria.** Full suite + 11 CI jobs green; no doc carries a claim slice 2 did not build.

---

## E. F2 addendum — candidate text for Kyle's ruling at the slice-2 gate

**Where it lands.** `docs/architecture/arrival/backend-contract.html`, §06 "Reads and
consistent snapshots", as a `<div class="doc-callout is-security">` inserted after the
verification-levels discussion (after `:344-347`, before the section closes at `:348`) — beside
the levels it constrains.

**Candidate text, contract voice:**

> **Verification never repairs.** A `verify` at any level MUST NOT mutate the ledger, its
> projections, or head metadata — no catch-up, no truncation, no rebuild of existing
> projection state, no head re-stamp. A backend whose ordinary open path performs recovery
> MUST offer verification a route that does not, because an operation that repairs on the way
> to reading has destroyed the evidence it was asked to judge and can only report an agreement
> it just manufactured. Materializing a projection that does not yet exist is not repair: it
> destroys no prior state and can hide no divergence. Repair belongs to open-time recovery and
> to explicit rebuild operations, which say so in their names. This generalizes §07's rule that
> projection state is never used to repair canonical ledger history: neither direction of
> repair may travel under a verification verb.

**Rationale for the ruling (evidence, not part of the addendum).** The invariant is held today,
carefully and in prose only, by code the break deletes: `canonical_agreement`
(`apps/loops/src/loops/commands/store.py:130-136`) resolves through the *pure* path
specifically because `resolve_store_path` would run `ensure_index`/`ensure_arrival_index`, and
"a store constructor *repairs*: it would catch the index up and then report agreement about a
store whose disagreement it had just erased." `engine/canonical_audit.py` never opens a store
for the same reason, a discipline `libs/engine/CLAUDE.md` states outright ("Verification is
`engine/canonical_audit.py`, and it never opens a store"). §06's verification levels
(backend-contract.html:331-347) describe *work* and *claim* per level and say nothing about
mutation. This is the most valuable invariant the dying code holds, and nothing in the contract
would stop a DuckDB adapter from re-acquiring it.

**One carve-out is part of what Kyle rules on.** The same function draws a line the addendum
must not erase: it *does* materialize an **absent** index during verification and argues that
this is not repair — "BUILDING an absent index from the log is not repair — there is no prior
state to destroy and no divergence it could hide… An index that DOES exist is evidence and is
never materialized through here" (`apps/loops/src/loops/commands/store.py:154-159`). The
candidate text above carries that carve-out in its fifth sentence. The ruling should confirm
the boundary explicitly, because it is the one case where a verification path legitimately
writes: **absent ⇒ create is permitted; present ⇒ touch is forbidden.** If Kyle wants the
stricter form (verification never writes, and a missing projection is simply an unanswerable
scope), that is a live alternative — it would refuse rather than build on a fresh clone, and
`FileQuery` would need a "not yet materialized" answer in slice 2.

---

## F. GF-2 — the Rule 18 `_SCAN_TARGETS` completeness ratchet

**Carried by WP1.** The deferral fact
(`finding:slice1-gate-gf2-rule18-completeness`, `01M175H98SPD0GY8TAHYHFV43G`) says to build it
"when the next arrival-surface module is born, where it pays immediately" — WP1 is that birth,
three times over.

**The test change**, in `tests/architecture/test_rule_18_arrival_vocabulary_denylist.py`,
matching the house style the repo already uses (Rule 15's `EXCEPTIONS` + `_check_exceptions`,
`test_rule_15…:28-55` and `_helpers.py:180-183`; and this file's own
`test_scan_targets_all_exist` at `:353-356`):

```python
# The join-at-birth trigger, mechanized. A module born on the arrival surface
# is named `arrival*.py` by construction, so the glob IS the birth list: an
# unregistered one is a failure, not a silent gap. Shrink-only — an entry
# needs a comment saying why that module is deliberately not held to the
# glossary.
_NOT_SCANNED: dict[str, str] = {}


def test_every_arrival_named_engine_module_is_scanned():
    """A module born on the arrival surface joins _SCAN_TARGETS at birth."""
    for path, reason in _NOT_SCANNED.items():
        assert (REPO_ROOT / path).exists(), f"stale exception: {path}"
        assert reason and reason.strip(), f"{path} has no reason"
    born = {_rel(p) for p in (REPO_ROOT / "libs/engine/src/engine").glob("arrival*.py")}
    missing = sorted(born - set(_SCAN_TARGETS) - set(_NOT_SCANNED))
    assert not missing, (
        "Arrival-surface modules not held to the glossary:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\nAdd each to _SCAN_TARGETS, or to _NOT_SCANNED with a reason."
    )
```

`_rel` and `REPO_ROOT` both already exist in `tests/architecture/_helpers.py` (`:160`, `:9`);
Rule 18 imports only `REPO_ROOT` today (`:10`) and grows the import.

**It passes today with an empty `_NOT_SCANNED`.** The glob over
`libs/engine/src/engine/` yields exactly `arrival.py`, `arrival_body.py`,
`arrival_projection.py`, `arrival_store.py` — all four already registered
(`test_rule_18…:54,61,62,63`). An empty shrink-only list is the strongest form of one.

**Scope-the-claim boundary (deliberate, and it is why `jsonl_*` needs no entry).** The ratchet
mechanizes the **name-born** trigger only. The rule's *other* trigger — "custody moved into
them", which is how `merge.py`, `receive.py`, `probe.py` and `residence.py` joined
(`test_rule_18…:40-43`) — is a judgment about what a module *does*, and a glob cannot make it;
mechanizing it would turn a location claim into a verdict claim. `jsonl_codec.py` and
`jsonl_store.py` fall outside the glob **by construction**, so the finding's named non-joiners
need no allowlist entry at all — their non-join is already argued in prose at `:45-52` and
`:55-60`, which is where a judgment belongs.

**Mutation evidence required** (slice-1 norm): add a throwaway
`libs/engine/src/engine/arrival_zzz.py` without registering it → the test fails naming the
file; register it → green. Demonstrate both; the gate re-runs them.

---

## Findings raised by this proposal

| # | Finding | Disposition sought |
|---|---|---|
| SD-1 | Coordinate machinery (`_stage_arrival_coordinates`/`_check_arrival_provider_agreement`/`_stamp_arrival_axis`) is §07 projection, not §04 mint — `plan.md:41` assigns it to admission | **Arbiter ruling.** Recommend: stays with the projection half; mint extraction narrows to `append*` + `fact_commitment_hash` |
| SD-2 | F1's ordinal-only CAS has **two** sites (`arrival.py:1330` and `:1392`); the plan names one | Close both in WP1 |
| SD-3 | `replicate` is composition over `append_record` (`arrival.py:1426`), not greenfield — the seam's "nothing preserves coordinates" was scoped to libs/store write paths | Re-frame WP2's risk; do not build a second appender |
| SD-4 | `store` node props/children are silently discarded (`loader.py:788-789`); a typo'd `backend=` would degrade to inference forever, and no test pins the behavior | Refuse unknown props/children in WP4 |
| SD-5 | The declaration round-trip (`document.py:889-894`, `:1007-1024`, `declaration.py:512,515`) drops any field not threaded as residence — a `loops add`/`rm` would silently erase the backend arm | Thread `store_backend` as residence in WP4; round-trip test as exit criterion |
| SD-6 | Slice-2 verification needs `export` **and** a minimal import, not only `replicate` (`plan.md:97` byte-identity gate) | Scope WP2 accordingly |
| SD-7 | CLI resolver rename sits in the slice-2 bullet (`plan.md:42`) but slice 5 owns consumer rewiring (`plan.md:69,113`) | §0 scope call — arbiter may veto |

---

## Load-bearing claims for spot-check

| # | Claim | Cite | Verified by |
|---|---|---|---|
| 1 | `VertexFile.store` is `Path \| None`; there is no backend/mode field today | `libs/lang/src/lang/ast.py:705` | explorer + design read |
| 2 | The `store` handler reads only `args[0]`; props and children are silently dropped | `libs/lang/src/lang/loader.py:788-789` | first-hand |
| 3 | Unknown top-level keys already refuse in the style the new refusal should match | `libs/lang/src/lang/loader.py:849`; `_error` at `:64-65` | first-hand |
| 4 | `VertexFile` is rebuilt from an explicit kwarg list in the document round-trip; residence is caller-supplied and excluded from documents | `libs/lang/src/lang/document.py:889-894`, `:1007-1024`, `:709-710` | first-hand |
| 5 | Residence never enters declaration payloads (the property the backend name must also hold) | `libs/lang/tests/test_document.py:386-392` | first-hand |
| 6 | The declaration re-projection passes residence explicitly | `libs/engine/src/engine/declaration.py:512`, `:515` | first-hand |
| 7 | `canonical_mode` is suffix-only, three arms | `libs/engine/src/engine/residence.py:85-105` | first-hand |
| 8 | `canonical_store_path` is pure path arithmetic (safe for the registry to keep using) | `libs/engine/src/engine/residence.py:121-130` | first-hand |
| 9 | `open_canonical_store` is today's mode dispatch and stays the jsonl/sqlite path | `libs/engine/src/engine/jsonl_store.py:256-277` | first-hand |
| 10 | **F1 site A** — ordinal-only CAS in `append_marked` | `libs/engine/src/engine/arrival.py:1330` | first-hand |
| 11 | **F1 site B** — ordinal-only CAS in `append_marked_many` | `libs/engine/src/engine/arrival.py:1392` | first-hand |
| 12 | `append_record` validates-never-assigns and checks a supplied `rh` (the replicate seam) | `libs/engine/src/engine/arrival.py:1426-1445` | first-hand |
| 13 | The append fence is `flock`-based and per-open-file-description (why it stays in the adapter) | `libs/engine/src/engine/arrival.py:1447-1459` | first-hand |
| 14 | **SD-1** — coordinate provider is required and never assigned | `libs/engine/src/engine/sqlite_store.py:437-443` | first-hand |
| 15 | **SD-1** — every refusal points at `rederive_projections` | `libs/engine/src/engine/sqlite_store.py:475,482,488,500,512,541` | first-hand |
| 16 | **SD-1** — `_stamp_arrival_axis` writes projection metadata and says so | `libs/engine/src/engine/sqlite_store.py:593-615`, esp. `:599`, `:609-614` | first-hand |
| 17 | **SD-1** — callers are projection-rebuild/schema sites | `arrival_projection.py:71,593`; `store/merge.py:180-182`; `store/rebirth.py:427-429`; `store/slice.py:72-74` | explorer |
| 18 | `fact_commitment_hash` definition + its one cross-lib production caller | `sqlite_store.py:271-299`; `store/merge.py:572` | explorer + design read |
| 19 | Two `_canonical_bytes` spellings exist; do not add a third | `sqlite_store.py:158-172`; `arrival.py:277` | first-hand |
| 20 | `admission.py` is 134 lines of pure policy, no I/O, no hashing | `libs/engine/src/engine/admission.py:31-125`, `__all__` at `:128` | first-hand |
| 21 | The admission op already exists as the retry loop | `libs/store/src/store/merge.py:289-324` | first-hand |
| 22 | Rule 4 forbids `engine → store` (forces the identity trio to move with the op) | `tests/architecture/test_rule_04_lib_dependency_dag.py:16-27`, esp. `:24-27` | first-hand |
| 23 | Rule 18 `_SCAN_TARGETS` current contents (the four arrival modules) | `tests/architecture/test_rule_18_arrival_vocabulary_denylist.py:53-70` | first-hand |
| 24 | `_DENIED` contains none of the proposed new names | same file, `:73-90` | first-hand |
| 25 | The join-at-birth trigger lives in a comment (GF-2's premise) | same file, `:33-43`, `:55-60` | first-hand |
| 26 | `test_allowlist_entries_still_apply` is at `:359-366`, **not** `:352` as the seam analysis states | same file, `:359-366` | first-hand (seam-analysis line drift confirmed) |
| 27 | `test_scan_targets_all_exist` is the existing companion the new test parallels | same file, `:353-356` | first-hand |
| 28 | House style for glob-vs-tuple + shrink-only allowlist | `test_rule_15_apps_import_only_sdk_and_painted.py:17-78`; `_helpers.py:180-183`, `_rel` at `:160`, `REPO_ROOT` at `:9` | explorer |
| 29 | The glob passes today with an empty `_NOT_SCANNED` (exactly four `arrival*.py` files) | `ls libs/engine/src/engine/arrival*.py` | first-hand |
| 30 | F2's invariant is held in prose by dying code | `apps/loops/src/loops/commands/store.py:130-136`; `libs/engine/CLAUDE.md` ("never opens a store") | first-hand |
| 30b | …and that same code carves out absent-index materialization as not-repair (the boundary §E asks Kyle to confirm) | `apps/loops/src/loops/commands/store.py:154-159` | first-hand |
| 31 | §06 verification levels say nothing about mutation (the gap F2 fills) | `docs/architecture/arrival/backend-contract.html:331-347` | first-hand |
| 32 | Contract requires explicit backend selection, never inferred from suffix | `docs/architecture/arrival/backend-contract.html:111-116`, `:132` | first-hand |
| 33 | Descriptor dissolves into the `.vertex` store clause (ruled) | `docs/architecture/arrival/backend-contract.html:140-149` | first-hand |
| 34 | Ledger/query separation is contract text, not an invention here | `docs/architecture/arrival/backend-contract.html:211-217` | first-hand |
| 35 | 14 arrival test files: 13 engine + 1 store | `libs/engine/tests/test_arrival_*.py` + `test_probe_arrival_matrix.py`; `libs/store/tests/test_arrival_merge.py` | first-hand |
| 36 | `Transport` Protocol precedent for a pluggable seam | `libs/store/src/store/transport.py:4,20-21` | seam analysis |
| 37 | Architecture tests run in CI via `./dev check` | `.github/workflows/ci.yml:10-27`; `dev:39-41` | explorer |
