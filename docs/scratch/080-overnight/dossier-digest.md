# Dossier: Digest — design state and its named collisions

*0.8.0 grounding dossier, chapter: Digest (design session 4). Compiled 2026-07-17 from the
project store, the TUI corpus (`~/Downloads/Terminal UI for loops/`), and code on `main`
(post-v0.7.0, release commit 053ee87). Everything below is quoted evidence; editorial
judgments are marked as such.*

---

## 0. The headline empirical finding

**There is no dedicated Digest design fact.** All three of:

```
sl read project --kind design --key digest    → "No data yet."
sl read project --kind decision --key digest  → "No data yet."
sl read project --kind thread --key digest    → "No data yet."
```

Digest's design state is *distributed* across the roadmap charter, the salience contract,
the 080-design-wave thread's collision list, two 2026-07-16 audit observations, and one
corpus mock (`Digest View.dc.html`). There is also **no `digest` verb in the CLI** — the
command roster in `apps/loops/src/loops/cli/app.py:256-275` (`_DESCRIPTIONS`) has no digest
entry, and no digest lens exists in `apps/loops/src/loops/lenses/` (shipped lenses:
confluence, graph, horizon, provenance, plus the core fold/stream/gist set). Beware the
false-positive: FTS `--grep digest` mostly returns hits on *cryptographic* digest
(signing) facts — the two concepts share a word throughout the store.

Also note the FTS trap while researching this chapter (friction:fts-grep-splits-punctuated-terms,
2026-07-17): "`--grep` silently returns 0 results for punctuated terms: … 'digest-coverage'
(hyphen) … tokenize apart in FTS5, so exact-phrase searches … read as ABSENCE when the
content exists."

## 1. The charter — what Digest is chartered to be

### 1.0 Store-dump census

The requested literal case-insensitive grep has **19 hits** in
`docs/scratch/080-overnight/store-dumps/facts-60d.txt`, **zero hits** in
`docs/scratch/080-overnight/store-dumps/designs-all.txt`, and **14 hits** in
`docs/scratch/080-overnight/store-dumps/fold-current.txt`. The zero is important:
the design-only export contains no Digest design row. The fold export repeats the
current projections of facts quoted below; it does not add a dedicated Digest
decision. Four `facts-60d.txt` hits are lexical false positives in which *digest*
means a cryptographic hash, not this feature: the Go attestation spec
(`facts-60d.txt:863`), per-observer signing (`:937`), the delta-2 signing engine
(`:1026`), and tick-key custody (`:1052`). They remain relevant to signing, but
they are not Digest feature facts.

The feature-bearing facts, quoted in full at their first use in this chapter or
in the closing evidence ledger, are `facts-60d.txt:6,8,10-11,18-21,23,324,390,394,
404,416-417` and their current-fold counterparts
`fold-current.txt:28,65,93,95,137,202,633,723,1157,1233,1331-1332`. This explicit
inventory prevents the FTS punctuation bug itself from turning a missing search
result into an absence claim (`facts-60d.txt:11`; `fold-current.txt:1157`).

### 1.1 decision:design/roadmap-060-static-honest-wave (RATIFIED Kyle 2026-07-01)

> "Digest last regardless (non-deterministic summarization + cross-vertex WRITE path —
> first concrete in-repo Peer/Grant consumer, own design pass)."

That one sentence carries three of the six collisions: non-determinism (→ LLM home),
cross-vertex write (→ no cross-store append path), Peer/Grant consumer (→ grant shape +
persistence).

### 1.2 thread:080-design-wave, first emission (fact id 01KXQ49N02Y6XRP8P6TCAP2GCQ, 2026-07-16)

The collision list this chapter grounds, verbatim:

> "(4) DIGEST — last, ratified: signing/observer of synthesized close facts, grant shape
> (Grant.potential has no target-vertex dimension), Peer/Grant persistence collides with
> frozen _decl vocab (Go-oracle coordination), no cross-store append path, LLM home vs DAG
> ratchet, coverage backlink, Dissolution counterpart."

### 1.3 The corpus mock — `Digest View.dc.html` ("Design study — turn 7 · digest · the loop closing")

The only concrete behavioral sketch that exists. Key lines (tags stripped):

> "Every lens so far **reads** the store. Digest is the only one that **writes back** —
> it's the loop **closing**. When a tick resolves it doesn't just end; it **emits a
> synthesis**: a window of facts compressed into one **close** fact that flows up into a
> parent loop. 142 facts in, one fact out."

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Digest View.dc.html:23`.

> "The compression is **not deletion** — append-only means the 142 facts remain,
> addressable: Provenance proves the summary from them, Rewind visits the window."

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Digest View.dc.html:26`.

The `-vv` mechanism panel:

> "digest = summarize( fold( facts in window ) )
> result is itself a fact — kind=close · refs the window it summarizes
> flows to loops/roadmap — appended as 01JQ9K… · seq +1
> recurses — parent folds it in; its own digest compresses further → Strata
> additive — 142 facts remain; the digest layers on top — nothing overwritten"

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Digest View.dc.html:77-84`.

The `-v` panel establishes the cutline semantics: "ranked by salience — the digest keeps
the top of the window … below the cutline isn't lost — it stays in the store and
re-competes next window" (`Digest View.dc.html:68`). The closing TUI note says:
"digest is the **close** action itself — resolve a tick and it emits the synthesis
**you can edit** before it flows up" (`Digest View.dc.html:99`).

Mock invocation grammar: `loops digest project --since 'last tick'`.

### 1.4 Sequencing facts

- thread:080-design-wave: Digest is session **4 of 4**, "last, ratified", after cursor
  axis, daemon-shaped access, and TUI integration.
- observation:architecture/strata-tick-lineage-unmet (2026-07-16): "Strata is therefore
  doubly downstream in the 0.8.0 wave: it needs a tick-lineage schema design (post-freeze,
  coordinating with the Go oracle) AND its stacked view wants Digest output (recursive
  digests)."
- decision:design/observer-typing-dissolves-to-declared-peer (RATIFIED 2026-07-04):
  "Confluence surfaces peer-declaration candidates the way reconcile surfaces
  edge-declaration candidates (read surface generates demand for the dormant Peer
  primitive, read-only, **before Digest needs it for gating**)."
- observation (store-type-portfolio, 2026-07-03): "cumulative deep research
  (digest-coverage's natural home)" — the domain-neutrality stress store for this feature.

---

## 2. Collision 1 — signing/observer of synthesized close facts

**The question:** a Digest fact is machine-synthesized (non-deterministic summarization).
Who is its `observer`, and under whose key does it sign?

### 2.1 Who signs today

The whole fact-signing surface lives in `libs/custody/src/custody/signing.py` (one module,
promoted from apps/loops in the 0.7.0 substrate cut). The fact signer contract
(`signing.py:103-121`):

> "Returns a callable (observer str, content digest str) -> signature str | None, matching
> engine's fact_signer contract (design/fact-signing-per-observer-keys). Key resolution per
> observer:
> 1. ``keys/<observer>/ed25519.key`` — the per-observer layout;
> 2. flat ``keys/ed25519.key`` — ONLY for the self-observer (the vertex's own name),
>    delta-2 back-compat;
> 3. otherwise None — that observer's facts append unsigned (honest per-observer
>    pre-signature era)."

Domain constants are string-pinned here: `TICK_DOMAIN = "loops-tick-v1"`,
`FACT_DOMAIN = "loops-fact-v1"` (`signing.py:30-31`); the architecture ratchet forbids
re-hardcoding them elsewhere (custody CLAUDE.md: "never re-hardcode them elsewhere, import").

The emit path composes it by injection (`apps/loops/src/loops/commands/emit.py:762-774`):

```python
from custody import fact_signer_for, tick_signer_for
...
_tick_signer = tick_signer_for(writable_path)
program = load_vertex_program(
    writable_path, validate_ast=False, run_dispatcher=_execute_boundary_run,
    tick_signer=_tick_signer,
    fact_signer=fact_signer_for(writable_path),
)
```

"INJECTION NOT IMPORT" is the load-bearing boundary posture (signing.py:3-4: "The engine
takes callables, never imports sign"; decision:design/tick-key-custody-colocated:
"append_tick takes optional signer callable, verify_chain takes optional key-lookup,
apps/loops composes; preserves no-cross-lib-imports, makes progressive policy structural").

### 2.2 Observer resolution and verification are strict per-observer

Observer on emit resolves: `--observer` flag → `.vertex` declaration → `$LOOPS_OBSERVER`
env (emit.py:935 help text: "Observer string (default: from .vertex declaration or
$LOOPS_OBSERVER)"; identity.py:83). Verification is exact-observer, not any-key
(`signing.py:163-171`):

> "verifier is a callable (observer, signature, content digest) -> bool that checks against
> THAT observer's declared key EXACTLY — authorship is a per-observer claim, so the tick
> path's any-key relaxation (a receipt-claim affordance) deliberately does not apply here.
> An observer with no declared key fails verification of any signature attributed to it (a
> signed fact from an unregistered observer is unverifiable, which verify reports as a
> break — the registry is the trust anchor)."

The registry is store-canonical post-0.7.0 (`signing.py:194-201`: "Routes through the
store-backed resolver (SPEC §9.5): once a lineage is opened, the current-head keys come
from the store's declaration, not the file").

### 2.3 What this means for a synthesized close fact (data, not prescription)

The project vertex's declared observers today (`/Users/kaygee/Code/loops/.loops/project.vertex:74-88`):
`project`, `kyle/loops-claude`, `kyle`, `relay` — each with a key. There is no digest/
synthesizer observer. The structural options the code affords: (a) a new declared observer
with its own key under `keys/<observer>/` (minted only via `ensure_signing_key` —
`signing.py:41-56`: "the single entry point for minting custody"); (b) the self-observer
(vertex name, flat key); (c) an undeclared observer name → emits unsigned (honest NULL) but
*verify-breaks if signed*. Note the empty-observer guard (`signing.py:130-135`): "An empty
observer must never sign: ``keys_root / \"\"`` collapses to the flat layout, which would
mint the VERTEX key's authorship claim for an anonymous writer."

Prior art for the identity question: decision:design/fact-signing-per-observer-keys
(2026-06-12): "Observers without keys emit unsigned — honest NULL becomes a PER-OBSERVER
era." And decision:design/observer-typing-dissolves-to-declared-peer: "no observer-type
enum. Observer is the base level — a bare string. 'Type' = whether the name resolves to a
declared Peer and what that declaration says (horizon/potential; attested-vs-bare derivable
from signing)."

The cross-vertex twist: `fact_signer_for(vertex_path)` is keyed to ONE vertex's `keys/`
directory. A digest synthesized *from* vertex A but appended *to* vertex B (the mock's
"flows to loops/roadmap") would sign under whichever vertex's custody directory the writer
composes — the signer builders have no cross-vertex concept. Key custody is deliberately
co-located per store (decision:design/tick-key-custody-colocated: "the private key lives at
.loops/keys/ next to the store it signs … slice/merge strip chain → new custody context →
key dies with the store's home").

---

## 3. Collision 2 — Grant.potential has no target-vertex dimension

### 3.1 The dataclass, verbatim (`libs/engine/src/engine/peer.py:13-51`)

```python
@dataclass(frozen=True, slots=True)
class Grant:
    """Optional policy: what an observer can see/do.

    Separates permission policy from identity. Observer is just a name;
    Grant holds the constraints.

    Attributes:
        horizon: What you can see (None = unrestricted)
        potential: What you can do (None = unrestricted)
    """

    horizon: frozenset[str] | None = None
    potential: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class Peer:
    """Atomic identity: name + horizon + potential.
    ...
    """

    name: str
    horizon: frozenset[str] | None = None   # None = unrestricted
    potential: frozenset[str] | None = None  # None = unrestricted
```

`potential` is a frozenset of **fact kinds** ("Constrained peer — can only emit health and
deploy facts", engine CLAUDE.md Level 3). Both dimensions are kind-sets. **Nothing in the
shape addresses WHICH vertex/store a write may land in** — the collision as named. The
module header (`peer.py:7-8`): "None = unrestricted. frozenset() = explicitly empty (locked
out). Constraints emerge through delegation, not through upfront enumeration." Operators:
`grant()` (union), `restrict()` (intersection), `delegate()` (child, narrow-only),
`grant_of()`, `expand_grant()`, `restrict_grant()` (peer.py:54-171).

### 3.2 The gate that would consume it (`libs/engine/src/engine/vertex.py:506-507`)

```python
# Gate 1: potential check (only if grant provided)
if grant is not None and grant.potential is not None and kind not in grant.potential:
    return Receipt(fact_id=None, tick=None, stored=False)
```

### 3.3 It has zero production consumers — and a parallel enforced path with a *different* schema

observation:architecture/parallel-authorization-paths (2026-07-16 audit), verbatim:

> "Two parallel authorization paths exist and only one is enforced: (a) lang-AST
> GrantDecl/ObserverDecl -> identity.py ObserverCheck (enforced at emit — 'forbidden' when
> decl.grant.potential excludes the kind); (b) engine.Peer/Grant frozen dataclasses with
> Vertex.receive(grant=) gating — ZERO production consumers (no CLI site constructs one;
> every receive() call is bare). Horizon (read-side visibility) is enforced NOWHERE. This is
> a dissolution candidate that must resolve BEFORE Digest builds on either path — Digest is
> chartered as the first in-repo Peer/Grant consumer, and building it on the unenforced path
> while the enforced path speaks a different schema would fork authorization semantics."

Verified in code:

- All three production `receive` call sites pass no grant: `init.py:301 v.receive(fact)`,
  `emit.py:782 receipt = program.receive(fact)`, `emit.py:1228 program.receive(fact)`.
  emit.py:786-789 even documents it: "cmd_emit passes no grant, so the only reachable gate
  is observer-state ownership."
- The enforced path's schema (`libs/lang/src/lang/ast.py:639-654`):

  ```python
  class GrantDecl:
      """Grant constraints for an observer."""
      potential: frozenset[str]  # kinds this observer can emit

  class ObserverDecl:
      """An observer declared in a vertex file."""
      name: str
      identity: str | None = None
      grant: GrantDecl | None = None  # emission constraints
      key: str | None = None  # Ed25519 public key, raw-32-byte base64
  ```

  **GrantDecl has `potential` only — no `horizon` field at all.** Enforcement:
  `apps/loops/src/loops/commands/identity.py:240-243` — `if decl.grant is not None and
  kind not in decl.grant.potential:` → `ObserverCheck("forbidden", ...)`; emit.py:631-634
  maps `forbidden` to a hard exit-1 refusal.
- `Grant.horizon` is read by no code outside peer.py itself (repo-wide grep: every `horizon`
  hit in engine is peer.py; the `horizon` hits in apps are the unrelated **Horizon lens** —
  `fetch.py:1122 fetch_horizon`, a boundary-proximity view. Same word, disjoint concept —
  a naming hazard for the design session).

---

## 4. Collision 3 — Peer/Grant persistence vs the frozen `_decl.*` vocab

### 4.1 The reserved-kind constants (internal-table S0), verbatim

`libs/lang/src/lang/document.py:128-151`:

```python
# ---------------------------------------------------------------------------
# Reserved-kind vocabulary (SPEC §9.2, code-frozen)
# ---------------------------------------------------------------------------

DECL_PREFIX = "_decl."

DECL_GENESIS = "_decl.genesis"
DECL_KIND_DEFINED = "_decl.kind-defined"
DECL_KIND_RETIRED = "_decl.kind-retired"
DECL_OBSERVER_DEFINED = "_decl.observer-defined"
DECL_OBSERVER_RETIRED = "_decl.observer-retired"
DECL_MEMBER_DEFINED = "_decl.member-defined"
DECL_MEMBER_REMOVED = "_decl.member-removed"
DECL_VERTEX_DEFINED = "_decl.vertex-defined"
DECL_SOURCE_DEFINED = "_decl.source-defined"
DECL_SOURCE_RETIRED = "_decl.source-retired"
DECL_LENS_DEFINED = "_decl.lens-defined"
DECL_TRANSIT = "_decl.transit"
DECL_MERGED = "_decl.merged"

#: Declaration-protocol version stamped into the genesis payload. ...
DECLARATION_PROTOCOL_VERSION = 1
```

Thirteen kinds, no `peer-*`, no `grant-*`. The tombstone map (document.py:153-167) carries
the precedent for how vocab gaps are handled:

> "A ``*-defined`` kind ABSENT from this map is a **singleton with no tombstone** …
> Removing such a subject is inexpressible in the code-frozen vocabulary; the edit ceremony
> (S4) refuses it rather than mint a new kind unilaterally
> (thread:decl-lens-tombstone-vocab-gap — a later coordinated vocab change with the
> loops-go oracle)."

That is the operative rule for this collision: **new `_decl.*` kinds are never minted
unilaterally; they are coordinated vocab changes with the Go oracle.**

### 4.2 Why the Go oracle makes this a hard freeze

`~/Code/loops-go/SPEC.md` §9.2 ("The meta-schema (normative vocabulary, code-frozen)"):

> "Their kinds come from a **fixed, implementation-defined vocabulary** — the store
> describes its own attention topology over time, but the language it describes it *in* is
> frozen in code, never drawn from the store. This terminates the regress: there is no
> meta-meta-schema."

And Python's resolver treats unknown kinds as inert (`libs/engine/src/engine/declaration.py:47-48`):
"Unknown ``_decl.*`` kinds (receipts, future protocol) are skipped safely." So a
Python-only `_decl.peer-defined` would not error — it would be **silently skipped** by both
the Go oracle and any older Python, which is exactly the divergence class the two-impl
setup exists to catch.

Adjacent guards that close the write-side escape hatches:

- Write-time reservation in the runtime (`vertex.py:522-528`): `if self._store is not None
  and is_internal_kind(kind): raise ReservedKindError(...)` — "recorded via the absorb
  ceremony, not ingest".
- `sqlite_store.py:380-388` `ReservedKindViolation`: "The edit ceremony emits only
  ``*-defined``/``*-retired``/``*-removed`` declaration events (SPEC §9.2 table). This
  primitive is not a general ``_decl.*`` (or domain-kind) append escape."
- The same reservation in `_run_close` (emit.py:1080-1090) and the single predicate
  `is_internal_kind` (document.py:170-177: "The single predicate every read/emit/filter
  site should route through").

### 4.3 The dissolution-shaped fact hiding in the vocab table

The Go SPEC's own stratum table (§9.2) declares the payload of `observer-defined` as:
**"public key, grant, scope"** (Constitution stratum, meaning-critical, portable). And the
Python document form already persists grants there —
`libs/lang/src/lang/document.py:493-502`:

```python
def _observer_to_payload(o: ObserverDecl) -> dict[str, Any]:
    grant = (
        {"potential": sorted(o.grant.potential)} if o.grant is not None else None
    )
    return {
        "name": o.name,
        "identity": o.identity,
        "grant": grant,
        "key": o.key,
    }
```

So grant-persistence **already exists** for the enforced (lang) schema, riding
`_decl.observer-defined` — with `potential` only, no `horizon`. The collision, stated
precisely: persisting *engine's* Peer/Grant (horizon + potential, plus whatever
target-vertex dimension Digest adds) either (a) extends the `observer-defined` document
payload (a payload-shape change both impls must agree on), or (b) mints new `_decl.*` kinds
(frozen-vocab coordination, the tombstone-gap precedent), or (c) resolves by dissolving the
unenforced engine path into the enforced one (the audit observation's "dissolution
candidate that must resolve BEFORE Digest builds on either path").

---

## 5. Collision 4 — no cross-store append path

### 5.1 What the mock demands

`Digest View.dc.html -vv`: the close fact "flows to **loops/roadmap** — appended as
01JQ9K… · seq +1" — a fact synthesized from vertex `project`'s window, appended into a
*different* vertex's store. roadmap-060 names it "cross-vertex WRITE path."

### 5.2 What exists today

The prompt's broad claim **"no cross-store append path" is false.** There is a
cross-store append path today: select facts into a slice, then merge/receive that
SQLite store into the target. What is true is narrower: there is no
Digest-specific API that accepts one newly synthesized `Fact`, resolves a target
vertex, applies its Grant policy, and appends there atomically.

The concrete cross-store surface is:

- **merge_store** (`libs/store/src/store/merge.py:32-42`): "Merge source facts/ticks into
  target with deduplication. Dedup is INSERT OR IGNORE on the id primary key." Operates via
  `ATTACH DATABASE` on two whole store files. Signature: `merge_store(target: Path,
  source: Path, *, dry_run: bool = False)`. Notably it already solved the ordering and
  signature-carriage problems a cross-store write needs (merge.py:74-84): "ORDER BY (ts,
  id): insertion (witness) order is deterministic … merge(A,B) and merge(B,A) re-fold
  identically — the witness histories differ (they ARE different custody events), the
  semantics do not. The fact SIGNATURE travels … a per-observer authorship claim over
  content only — unlike the tick chain columns (receipt custody, store-local, stripped
  below). Carried verbatim, never re-signed."
- **push_store / pull_store** (`libs/store/src/store/transport.py:51-60,96-105`): slice local → transport → remote
  receive. "Cursor tracking is the caller's responsibility (libs/store is stateless)"
  (store CLAUDE.md).
- **slice_store** (`libs/store/src/store/slice.py:25-39,73-90`): filters by time,
  kind, observer, and origin into a new store while preserving fact IDs and
  authorship signatures.
- **receive_store** (`libs/store/src/store/receive.py:29-46`): copies an incoming
  store when the target is absent or calls `merge_store` when it exists.

The mechanism is explicitly described as "Every data movement decomposes to:
slice on source -> move bytes -> merge on target" (`libs/store/src/store/transport.py:1-4`).
`merge_store` then executes `INSERT OR IGNORE INTO facts ... SELECT ... FROM
src.facts ORDER BY ts, id` (`libs/store/src/store/merge.py:73-103`). Thus facts
really are appended across stores. The missing layer is product semantics: no
single call combines synthesis, target-vertex resolution, target authorization,
signer selection, coverage backlinks, and receipt.

### 5.3 The nearest in-tree analogs (and their limits)

- **Nested child ticks re-enter the parent** (`vertex.py` receive_receipt docstring):
  "After local routing, forwards to children that accept the kind. Child ticks become facts
  that re-enter this vertex (but not back to the originating child, to prevent recursion)."
  This IS the mock's "flows up into a parent loop" — but only within one in-process
  `VertexProgram` tree, and the Receipt explicitly disclaims cross-store bookkeeping
  (vertex.py:71-73): "``fact_id``/``stored`` describe THIS vertex's store only — a fact
  forwarded to a nested child with its own store is appended there under the child's own
  bookkeeping, not reflected here."
- **id_override** (`vertex.py` receive_receipt args): "Pre-generated fact id to store under
  (rare — replay/transport-shaped callers; ordinary writers let the store mint and read the
  id off the Receipt)" — the receiving-side hook a cross-store append would ride to
  preserve fact identity (merge dedup depends on ids surviving round-trips, merge.py:4-7).
- **The unmerged branch**: `fix/discover-cascade` (off main since 2026-07-04, stayed out of
  0.6.0 AND 0.7.0) carries cross-host child-skip + signer pass-down; design-gated by
  thread:discover-children-as-cascade-targets. It is the standing evidence that cross-store
  write topology is recognized as an unresolved design question, not a missing feature.

### 5.4 Grant interaction

Because the append target is a *different* vertex, this collision loops back into
collision 2: `Grant.potential` gates kinds at ONE vertex's `receive()`; nothing in the
Grant shape or the enforced ObserverCheck path expresses "may append kind=close **into
vertex loops/roadmap**". The mock's flow crosses precisely the dimension the shape lacks.

---

## 6. Collision 5 — LLM home vs the DAG ratchet

### 6.1 The ratchet, verbatim (`tests/test_architecture.py:230-246`)

```python
_LIB_ALLOWED_RUNTIME: dict[str, set[str]] = {
    "atoms": set(),
    "lang": set(),
    "sign": set(),  # loops-agnostic utility — shared with vouch/pile/comms
    "store": {
        "engine",  # rebirth.py reuses tick_row_hash — chain hashing stays
                   # single-sourced; duplicating it would fork the format
    },
    "engine": {
        "lang",   # program.py, compiler.py — lang provides AST types
        "atoms",  # function-local lazy imports in compiler.py, vertex.py, program.py
    },
    "custody": {
        "sign",    # Ed25519 primitives
        "engine",  # load_declaration — store-canonical observer-key registry
    },
}
```

With `LIBS = ("atoms", "custody", "engine", "lang", "sign", "store")` and
`APPS = ("loops", "hlab", "strange_loops")` (test_architecture.py:18-19). "All other
cross-lib runtime imports are forbidden" (test docstring, :252-253). Apps are constrained
by different rules — Rule 1 `test_apps_do_not_import_store_reader` (:122, with a
**shrink-only** exceptions list: "Shrink-only: reroute through the vertex read interface,
don't add", :133) and Rule 2 `test_apps_no_raw_sqlite` (:164) — but apps may import all
libs and arbitrary third-party packages.

### 6.2 The empirical LLM inventory: zero

A repo-wide grep for `anthropic|openai|llm|LLM` across `libs/*/src` and `apps/loops/src`
returns one false positive (a `$VAR` regex in `engine/compiler.py:416`). `apps/loops`
dependencies (`apps/loops/pyproject.toml:6`):
`["lang", "atoms", "engine", "custody", "sign", "store", "painted"]` — no LLM SDK anywhere
in the workspace. `digest = summarize( fold( facts in window ) )` (the mock) has no home
today; `fold(...)` is pure substrate, `summarize(...)` is the roadmap's "non-deterministic
summarization."

### 6.3 Where LLM-calling code could legally live (structural facts)

- `_LIB_ALLOWED_RUNTIME` governs **cross-imports among the six names in `LIBS`**,
  not imports of third-party packages (`tests/test_architecture.py:18,228-246,
  263-273`). Therefore an existing lib could technically import an LLM SDK
  without violating this particular test. If that code also imported another
  in-repo lib, the map would have to allow that edge. A new `digest` lib would
  also have to be added to `LIBS` or the ratchet would not inspect it at all.
- **apps/loops** (or a new app) is unconstrained by the lib DAG. Precedent: everything
  effectful-and-composed (signers, run dispatchers) already lives at the app layer.
- **The established seam for exactly this shape is injection.** The engine already takes
  `tick_signer=`, `fact_signer=`, `run_dispatcher=` callables rather than importing their
  providers (emit.py:770-774; signing.py:3-4 "The engine takes callables, never imports
  sign"; decision:design/tick-key-custody-colocated: "Engine boundary: INJECTION not
  import … apps/loops composes; preserves no-cross-lib-imports, makes progressive policy
  structural (no signer = legacy era)"). A `summarizer` callable injected from the app
  layer is the same pattern; whether Digest follows it is the design question, but the
  pattern is pre-paved and the ratchet enforces its cheapest path.
- Cautionary precedent on ratchet drift: observation 2026-07-16 — "tests/test_architecture.py
  Rule 4 has drifted at exactly the signing seam: LIBS still lists painted … and omits sign
  entirely" — fixed as dissolution-residue during the custody move. The ratchet only
  protects seams it actually covers.

---

## 7. Collision 6 — coverage backlink + Dissolution counterpart

### 7.1 The ratified contract (decision:design/salience-three-term-contract, Kyle 2026-07-01)

> "RATIFIED (Kyle 2026-07-01, from Dissolution View study): the salience contract is the
> three-term formula salience = f(recency, inbound-refs, digest-coverage). Recency +
> inbound-refs already live on Surface.salience; DIGEST-COVERAGE is the new term — 'is this
> fact represented in a close fact?' — and is the safety property that makes decay honest
> (things dissolve when COVERED, not when old; still addressable)."

### 7.2 What code implements today: two terms, not three

`apps/loops/src/loops/surface.py:91-94`:

```python
inbound: int = 0  # MATERIALIZED (lifted from the lens) — was render-only
inbound_predicates: tuple[tuple[str, int], ...] = ()
salience: int = 0  # MATERIALIZED = n + inbound (lifted from _salience)
```

`digest-coverage` appears **nowhere in code**. The inbound machinery that would carry a
backlink-based coverage signal exists (`surface.py:266 _compute_inbound_refs` — "Count
inbound references (ref + typed edges) across all sections") but counts refs generically;
nothing distinguishes "referenced by a close fact" from any other inbound edge.

### 7.3 The backlink question — named but never designed

The **only** store hit for "backlink" is the 080-design-wave thread itself. No design fact
resolves what the backlink IS. The mock offers two non-equivalent mechanisms in adjacent
lines (`Digest View.dc.html -vv`): "kind=close · **refs the window it summarizes**" —
i.e. the close fact's outbound edge targets *a window* (a tick's since..ts span), while
per-fact coverage (Dissolution View's "absorbed → project digest", per-key `✓ safe … meaning
survives in close/project`) needs the covered *fact/key* to be resolvable from the close
fact. Candidate substrates all exist but none is designated: union `ref=` edges (refs are
"attention-events … UNION edge", CLAUDE.md), typed edges ("edge \"<field>\"
targets=\"<kind>\" … late-bound and retroactive",
decision:architecture/typed-edges-overlay-default), or tick-window membership (Tick carries
`since/ts` — "Retrieve the facts that produced this tick: store.between(tick.since,
tick.ts)", engine CLAUDE.md Level 2). Note the cutline nuance: per the `-v` mock only the
top-of-window makes the digest ("below the cutline … re-competes next window"), so
window-membership and covered-by are NOT the same set — a purely window-shaped backlink
would over-claim coverage. (That last sentence is inference from the mock, flagged as such.)

### 7.4 The Dissolution counterpart

`Dissolution View.dc.html` ("turn 8 · dissolution · forgetting without deleting") is the
read-side twin. Its own words:

> "A fact can decay to nothing only when its meaning is **represented elsewhere** — folded
> into a digest's **close**, or genuinely orphaned with nothing depending on it. **Age
> alone never dissolves anything**: an open, unabsorbed task stays bright no matter how
> old."

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Dissolution View.dc.html:26`.

> "a fact dissolves only when its meaning is **covered elsewhere** — **digest coverage** is
> the safety check, **not age**. this is why Digest makes dissolution possible"

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Dissolution View.dc.html:61-62`.

> "coverage — folded → 0 ok — once in a close, salience may reach 0 safely"

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Dissolution View.dc.html:71-76`.

> "It's the counterpart to **Digest** — coverage is what makes fading safe — and to Rewind:
> dissolved is never gone, scrub back and it's bright again."

Source: `/Users/kaygee/Downloads/Terminal UI for loops/Dissolution View.dc.html:93`.

No dissolution lens exists in code (lenses dir has no dissolution module; the mock's
`--lens dissolution` is unimplemented). Supporting ratified state the Digest session
inherits:

- decision:design/grammar-domain-neutrality (2026-07-03): "digest-coverage IS data-level
  staleness (dissolved when covered, not when old — identical for a design thread covered
  by a decision and a chat memory covered by a consolidation digest)."
- decision:design/static-grammar-hybrid-by-register (2026-07-02): "⊘ stale eventually wants
  digest-coverage, not pure age" — a 0.6.0 known-collision left open for exactly this
  session.
- decision:design/salience-max-propagation (2026-07-02): "coverage is an identity property"
  (defined at KEY level, facts inherit).
- observation (salience feed, 2026-07-03): "Dissolution-as-coverage-not-deletion (already
  ratified) satisfies 'never get rid of things' as-is."

---

## 8. Vocabulary hazards for the design session (all empirical)

1. **"close" is already three things**: the mock's synthesized fact kind (`kind=close`);
   the CLI `close` verb — "Close a session — mint a boundary tick" (app.py:260), which
   re-emits an existing thread/task with resolution + `produced` field
   (emit.py:1024-1040 `_run_close`: "Emits the resolution fact with a ``produced`` field
   listing what the thread generated"); and `seal` — "Seal a window — mint a signed tick"
   (app.py:263). The salience contract's "close fact" ("is this fact represented in a close
   fact?") predates any decision about which of these it denotes.
2. **"digest" collides with cryptographic digest** across the entire signing surface
   (`(observer, digest) -> sig`, custody throughout) — store searches and API naming both
   trip on it.
3. **"Horizon" is both Grant.horizon (unenforced visibility policy) and the shipped 0.6.0
   Horizon lens** (boundary proximity, fetch.py:1122).

## 9. Prompt-assertion check

Most collisions the task named exist as stated, with two corrections and one refinement.
The broad "no cross-store append path" claim is **refuted** by `slice_store` +
`merge_store`/`receive_store` + transport (`libs/store/src/store/slice.py:25-39,
73-90`; `merge.py:32-42,73-103`; `receive.py:29-46`; `transport.py:1-4`). The
missing path is a single-fact, authorization-aware, target-resolving Digest write.
The DAG does **not** by itself forbid an LLM SDK in a lib; it forbids unlisted
runtime edges between named repo libs (`tests/test_architecture.py:228-246,
263-273`). App-layer injection is the established architectural fit, not the only
location this test permits.

The prompt's item (3)
said "the reserved-kind constants from internal-table S0" live behind the collision — true,
but the sharper code fact is that **grant persistence already exists** in the frozen vocab
(`_decl.observer-defined` payload carries `grant: {potential: [...]}`, document.py:493-502;
Go SPEC table: "public key, grant, scope") — the collision is specifically about *engine's*
Peer/Grant shape (horizon + any new target-vertex dimension) not fitting that persisted
schema, on top of the new-kind freeze. And item (6)'s "coverage backlink" has *no* design
fact anywhere — the term's only occurrence in the store is the 080 thread's collision list
itself; its content had to be reconstructed from the two corpus mocks.

## 10. Design questions Digest must answer

1. What exact source cut is summarized: tick window, cursor interval, fold head,
   selected identities, or an editable salience cut?
2. What is emitted: a domain kind named `close`, an ordinary declared kind, or a
   new protocol/declaration kind; and what is its stable payload schema?
3. Which observer authors a machine synthesis, and must that observer be declared,
   keyed, and distinguishable from the human who approves or edits it?
4. Is an LLM output signed directly, countersigned after human review, or left
   unsigned until adoption? Which vertex's key custody applies when source and
   destination differ?
5. Which authorization model is canonical: persisted `ObserverDecl.grant`,
   engine `Grant`, or one dissolved shape? How does permission name the target
   vertex as well as the emitted kind?
6. How are Peer/Grant declarations persisted without an uncoordinated `_decl.*`
   vocabulary fork, and how are removals/versioning handled?
7. Does Digest use the existing slice/merge transport path, direct target
   `Vertex.receive`, or a new single-fact transport operation? What receipt proves
   the cross-store write?
8. Where does the nondeterministic summarizer live, how is it injected, and what
   model/prompt/input provenance is retained for replay and audit?
9. What constitutes coverage: explicit fact IDs, `(kind,key)` identities, typed
   edges, a tick/cursor window, or a combination? How are facts below an editable
   cutline kept uncovered?
10. Is coverage computed from close-fact backlinks or persisted separately, and
    how does it feed the third salience term without making age alone destructive?
11. What is the relationship among synthesized `close`, the existing CLI `close`
    boundary action, `seal`, recursive parent digests, and the Strata view?
12. What are failure and retry semantics for LLM failure, authorization refusal,
    target-store unavailability, duplicate synthesis, and partial signing/write?

## 11. Store-ratified partial answers

1. **Sequence and posture:** Digest is last, gets its own design pass, is
   non-deterministic, writes across vertices, and is intended as the first concrete
   Peer/Grant consumer (`facts-60d.txt:21,417`; `fold-current.txt:28,633`).
2. **Authorship substrate:** fact signatures are per-observer claims; the signer is
   `(observer, digest) -> signature | None`, undeclared/unkeyed observers can remain
   honestly unsigned, and verification binds the exact observer
   (`facts-60d.txt:937`; `fold-current.txt:83`; `libs/custody/src/custody/signing.py:103-155,
   158-191`).
3. **Observer ontology:** observer remains a bare string; declaration late-binds
   identity, grant, and key rather than introducing a human/non-human enum
   (`facts-60d.txt:324`; `fold-current.txt:93`; `libs/lang/src/lang/ast.py:638-654`).
   A non-human synthesizer therefore fits the current observer model mechanically.
4. **Persistence foothold:** `ObserverDecl.grant.potential` already serializes in
   `_decl.observer-defined`; a wholly new Peer/Grant kind is not yet justified
   (`libs/lang/src/lang/document.py:488-515`).
5. **Coverage safety property:** salience is ratified as
   `f(recency, inbound-refs, digest-coverage)`; coverage means represented in a
   close fact, and dissolution is safe only when covered—not merely old
   (`facts-60d.txt:416`; `fold-current.txt:137,202,1234`). Coverage belongs to
   identity/key salience (`facts-60d.txt:403`; `fold-current.txt:51`).
6. **Cross-store mechanics:** filtered facts can already move by slice and merge,
   preserving IDs and fact signatures while starting a new tick-custody context
   (`libs/store/src/store/slice.py:25-39,76-99`; `merge.py:32-42,73-110`).
7. **Composition precedent:** effects whose algorithms live elsewhere are injected
   into engine/store handles; apps compose them (`libs/custody/src/custody/signing.py:1-22`;
   `libs/engine/src/engine/sqlite_store.py:405-426`).

## 12. Implementation blockers / deferral conditions

Implementation should remain deferred while any of these are unresolved:

1. the two authorization paths remain divergent and production emits do not consume
   engine `Grant` (`facts-60d.txt:20`; `fold-current.txt:1331`);
2. target-vertex authorization has no representation—confirmed by the exact
   `Grant`/`Peer` shapes (`libs/engine/src/engine/peer.py:13-51`);
3. observer/signing/countersigning policy for synthesized facts is undecided;
4. the close-fact schema and coverage backlink are unspecified, so emitting a
   summary could falsely mark unsummarized facts covered;
5. any proposed `_decl.*` addition or payload change has not been coordinated with
   the Go oracle and protocol version (`libs/lang/src/lang/document.py:129-167`);
6. no design chooses between the existing store-transfer machinery and a new
   authorized single-fact write/receipt surface;
7. the LLM provider boundary, provenance/reproducibility record, and failure policy
   are undecided; and
8. recursive Digest/Strata depends on tick lineage that the audit says did not land
   (`facts-60d.txt:19`; `fold-current.txt:1332`).

## 13. Complete verbatim `-i digest` store ledger

For auditability, this is the complete, unedited line output of the requested grep—not a
curated subset. Each dump row is one complete rendered fact. It includes the four
cryptographic-hash false positives noted in §1.0 because omitting them would make the
literal-search record incomplete.

### `facts-60d.txt` — 19 matches

```text
6:high      04:54 [thread] 080-design-wave: OVERNIGHT RUN ENTERED 2026-07-16 (Kyle asleep, full delegation): run 0.8.0 through to the end. Pipeline: Opus/Sonnet implement, codex gpt-5.6-sol low<->high advise+review (smoke-tested alive, default model from ~/.codex/config.toml, effort via -c model_reasoning_effort), loops-claude arbitrates. Morning deliverable: review + retro. Sequence: grounding dossier -> design sessions 1-4 in forced order (cursor axis w/ Go-vector oracle check inside; daemon-shaped access; TUI integration; Digest) -> implementation in dependency order (fold-as-of + --diff mechanical once axis settles). Done-bar per slice: gates green + codex review + arbitration.
8:untiered  04:40 [seal] Session close 2026-07-16: 0.7.0 substrate cut shipped (decision:design/roadmap-070-substrate-cut, thread:release-070), TUI/cursor/Digest wave renumbered 0.8.0 with 4-session agenda banked (thread:080-design-wave), read-router temporal honesty guard landed. Next session enters at 0.8.0 session 1: the cursor axis.
10:high      04:39 [thread] 080-design-wave: NEXT SESSION ENTRY (agreed with Kyle 2026-07-16 at wrap): open with SESSION 1 — the cursor axis. The question: what does a temporal cursor position resolve to — ts (S5's ratified choice, epoch-seconds fold axis), witness order (SPEC 9.4's ordering authority; calls ts-as-of 'undefined within windows'), or tick anchor (Rewind mock's -vv: 'last tick before the mark', chain-verified)? Three authorities in live conflict. Run the loops-go-conformance-oracle vector check (do the 9.3/10 Go vectors assume a witness cursor?) INSIDE this session — it's the same decision. Everything downstream inherits the answer: fold-as-of, --diff, scrubber semantics, Watch's seq-N tail; building fold-as-of first would bake ts in de facto. Sessions 2-4 (daemon-shaped engine access; TUI shell integration; Digest) sequenced in this thread's prior emission. 0.7.0 substrate shipped 2026-07-16 (thread:release-070) — the wave now has a clean released floor under it.
11:tail      04:39 [friction] fts-grep-splits-punctuated-terms: --grep silently returns 0 results for punctuated terms: '0.7.0' (dot), 'digest-coverage' (hyphen), 'Peer/Grant' (slash) all tokenize apart in FTS5, so exact-phrase searches for version numbers, hyphenated names, and slashed concepts read as ABSENCE when the content exists (audit agents recovered each via single-word retries). Fix-shape: either quote-aware phrase queries on the FTS path, or a documented substring fallback when the term contains punctuation, or at minimum a rendered hint ('term tokenizes to X Y — searching as phrase') so absence claims are honest. Surfaced by the 0.7.0 design-state audit 2026-07-16 across three independent terms.
18:mid       04:17 [thread] release-070: strange-loops 0.7.0 shipped 2026-07-16. Pre-ceremony commits on main: 056dd5e (horizon total_unsealed distinct-fact union fix), 184dfce (read-router refuses temporal flags on fold route), be7755c (docstring 0.7.0->0.8.0 renumber sweep, incl. docs/CLI-CHEATSHEET.md caught by re-grep). Release commit 053ee87 (CHANGELOG stamp + pyproject version bump), tag v0.7.0. Gates: loops app 2020 passed/1 xfailed, atoms 418, engine 952, lang 540, sign 37, store 89, custody 13 (new lib, not in the skill's stale gate list -- ran it anyway), root ./dev check 8 passed. Wheel pre-flight green (sl --version, custody/engine.Receipt imports, live store read) -- no missing union dep (custody has zero third-party deps of its own). GitHub release https://github.com/kgruel/strange-loops/releases/tag/v0.7.0, workflow run 29554381323 succeeded in 20s. PyPI index showed 0.7.0 with no lag; fresh-venv install verified (sl --version + live sl read project). Local production sl reinstalled via uv tool install . -e --force. Deleted 4 fully-merged wave branches (feat/completion-prog-aliases, feat/completion-t3, feat/internal-table, feat/internal-table-hardening) local + origin remote (github ref also cleared via origin's multi-push). fix/discover-cascade untouched per design gate. CHANGELOG completeness sweep caught one real gap beyond the draft: the painted bump entry said '0.11 -> 0.12.1' but 0.6.0 shipped pinned <0.11, so the wave's own 6dd3f31 migration (render= -> renderer=(data,fidelity,width) contract, 19 run_cli sites) was the missing first hop -- corrected to '0.10.0 -> 0.12.1' with the renderer-contract detail folded in. Follow-up to report, not perform: /Users/kaygee/Code/tasked's floor-bump to >=0.7.0 (left untouched per constraint, has Kyle's uncommitted in-flight work). Rides 0.8.0: TUI shell + shared temporal cursor + Digest (the design wave ~4 sessions from code), fold-state-as-of (lifts the read-router refusal), rewound search index (vertex_search), --ontology-as-of unequal-cursors escape.
19:tail      04:10 [observation] architecture/strata-tick-lineage-unmet: decision:design/strata-cut-ratified (2026-07-04) fed forward a concrete requirement — 'the 0.7.0 internal table should carry parent_tick_id/child_vertex_ref on tick rows' — and the internal-table arc did NOT land it: the ticks schema is unchanged (sqlite_store.py ~281-293), _tick_to_fact still drops the child tick id, and the 'lineage' §9 added is DECLARATION lineage (genesis/own_lineage), a different concept. Strata is therefore doubly downstream in the 0.8.0 wave: it needs a tick-lineage schema design (post-freeze, coordinating with the Go oracle) AND its stacked view wants Digest output (recursive digests). No design fact exists yet for tick lineage as columns vs fact-borne events. Found by the 0.7.0 design-state audit 2026-07-16.
20:tail      04:10 [observation] architecture/parallel-authorization-paths: Two parallel authorization paths exist and only one is enforced: (a) lang-AST GrantDecl/ObserverDecl -> identity.py ObserverCheck (enforced at emit — 'forbidden' when decl.grant.potential excludes the kind); (b) engine.Peer/Grant frozen dataclasses with Vertex.receive(grant=) gating — ZERO production consumers (no CLI site constructs one; every receive() call is bare). Horizon (read-side visibility) is enforced NOWHERE. This is a dissolution candidate that must resolve BEFORE Digest builds on either path — Digest is chartered as the first in-repo Peer/Grant consumer, and building it on the unenforced path while the enforced path speaks a different schema would fork authorization semantics. Echoes convergence/consumer-more-substrate-aligned-than-substrate (2026-05-13): the substrate's own primitive still doesn't participate in the substrate. Found by the 0.7.0 design-state audit 2026-07-16.
21:high      04:10 [thread] 080-design-wave: The renumbered TUI/temporal-cursor/Digest wave (was roadmap-0.7.0). Design-state audit 2026-07-16 (7-agent workflow) sized the remaining design work at FOUR sessions in forced order: (1) CURSOR AXIS — gating, first: ts (S5 ratified) vs witness order (SPEC 9.4 grounds residence there, calls ts-as-of 'undefined within windows') vs tick anchor (Rewind mock's -vv) — three authorities in live conflict; run the loops-go-conformance-oracle vector check inside this session; building fold-as-of first would bake ts in de facto. (2) DAEMON-SHAPED ENGINE ACCESS — one seam counted three times: ticked's quadratic poll, Watch's change-detection, TUI live-refresh are the SAME missing primitive (long-lived VertexProgram handle, WAL-incremental refresh, receive() without reload, change feed into an event loop); one output contract serves all three; already sequenced before TUI per the Jul-17 convergence observation. (3) TUI SHELL INTEGRATION — the prototype is complete (layout/keys/composer/command-bar-honesty) but the seams are blank: lens-mount mechanism (8 view docs, 3 tabs, no mount path), entry+quit (mock q=zoom-out collides with store_app quit; entry seam overlaps thread:dispatch-default-subsumes-vertex-pre-router), store_app retirement first (fifth time fork), PAINTED TRIAGE the 'no upstream gate' claim never got (scrubber widget, toast, 17-slot theme roles vs Palette's 5, external-change feed into Surface), and ONE coordinated lens-signature migration instead of three (zoom unification + cursor threading + cross-lens-shared-row-renderer all rewrite the same seam — sequenced independently = 3x golden churn). (4) DIGEST — last, ratified: signing/observer of synthesized close facts, grant shape (Grant.potential has no target-vertex dimension), Peer/Grant persistence collides with frozen _decl vocab (Go-oracle coordination), no cross-store append path, LLM home vs DAG ratchet, coverage backlink, Dissolution counterpart. MECHANICAL once (1) settles: fold-as-of (vertex_facts until=T + Spec replay; --why replay_attribution is the per-key precedent), --diff (set difference of two reconstructions). STRATA: doubly downstream — tick-lineage columns (parent_tick_id/child_vertex_ref) never landed in the internal table AND the stacked view wants Digest output; end-of-wave at best.
23:mid       04:05 [decision] design/roadmap-070-substrate-cut: 0.7.0 = the substrate cut (Kyle 2026-07-16): the three waves on main since v0.6.0 — store-backed declarations (SPEC 9 + hardening), shell completion T3, libs/custody + engine Receipt write path — ship as strange-loops 0.7.0 NOW. The roadmap wave (TUI shell + shared temporal cursor + Digest) RENUMBERS to 0.8.0; roadmap-060-static-honest-wave's 0.7.0 allocation is superseded on that point only, its content unchanged. Rationale: tasked's entire dependency surface (Receipt, custody signers, loops_home) is on main but in no released wheel — its pyproject says 'bump past 0.6.0 the moment one exists' and rides an editable path; the design wave is ~4 design sessions away from code and holding the label would leave a consumer on a working-tree crutch for weeks. Cut executed by a delegated agent; sweep obligation: in-code docstring references to '0.7.0 work' (e.g. vertex_search rewound-index note) retarget 0.8.0 in the same change. Pre-cut riders: horizon union-count fix (in-tree, needs its CHANGELOG entry) + as-of-silent-drop fold-path guard. fix/discover-cascade stays out (design-gated by thread:discover-children-as-cascade-targets, same as it stayed out of 0.6.0).
324:mid       04:58 [decision] design/observer-typing-dissolves-to-declared-peer: RATIFIED (Kyle 2026-07-04): no observer-type enum. Observer is the base level — a bare string. 'Type' = whether the name resolves to a declared Peer and what that declaration says (horizon/potential; attested-vs-bare derivable from signing). Declaration is late-bound + retroactive per the typed-edges precedent: a peer declaration lights up historical facts by that observer at read time, no re-emit; undeclared observers stay inert bare strings. Confluence build-1 renders undeclared observers bare; declaration is the upgrade path — Confluence surfaces peer-declaration candidates the way reconcile surfaces edge-declaration candidates (read surface generates demand for the dormant Peer primitive, read-only, before Digest needs it for gating).
390:mid       00:47 [observation] design/store-type-portfolio: Store-shape portfolio as the domain-neutrality test suite (Kyle 2026-07-02): agent-attestation (exists, ref-heavy ideation), SillyTavern RP (consolidation-ticks-as-memory, no lifecycle, personas-as-observers), novel-writing (TWO time axes: wall vs fictional/canon; continuity=coverage), household management (multi-human + recurring timed/count boundaries — chores are loops), hlab (exists, boundary-rich ops), subtask-as-orchestrator (machine volume, worker fleet observers, ticks=completions), autoresearch (metric series, keep/discard folds, different lifecycle vocab), personal salience feed (ingested via Source/Parse, high-volume/disposable, recency-dominant, browser-history-as-attention — decay is the product), corp salience feed (+grants/federation), household tracking + jeeves (sensor ingestion + agent ACTUATION outward), cumulative deep research (digest-coverage's natural home). Sharpest stress tests: the feed (inverts every design-store default; behavioral attention ≈ inbound-refs — attention-events on an address is what ref already is, new SOURCE for existing concept) and the novel (fictional time = ordering axis in payload the grammar can't sort by). Validation: each 0.6.0 view has a natural home store none of which is the design vertex — Confluence→household/corp, Graph→attestation/research, Provenance→attestation/corp, Horizon→hlab/household, Strata→subtask/research.
394:mid       00:25 [decision] design/grammar-domain-neutrality: Kyle's catch (2026-07-02, echoing the painted semantic-renderer reframing): the grammar layer must not bake THIS vertex's domain vocabulary into rendering — 'status-aware ⊘' assumed a status=open lifecycle field that is our schema, not loops'. Data-equivalent of semantic staleness exists in two layers: (1) the three-term salience contract is already domain-neutral, and digest-coverage IS data-level staleness (dissolved when covered, not when old — identical for a design thread covered by a decision and a chat memory covered by a consolidation digest); (2) interim ⊘ follows the DECLARED-semantics pattern (fold keys, typed edges): a kind declares its lifecycle field (e.g. lifecycle "status" open="open,in-progress"), late-bound + retroactive; ⊘ = aged-while-open per declaration; undeclaring stores never rail ⊘. General principle: grammar consumes declared semantics, never assumes field vocabulary. Doc §5b amended.
404:high      21:59 [decision] design/static-grammar-hybrid-by-register: RATIFIED (Kyle 2026-07-02): 0.6.0 unified static grammar = the Static TTY study's hybrid, reframed BY REGISTER: TTY register = rail body (2c, salience+recency gutter ◆│·⊘) under a card header (2b — _statview.card generalized out from ls); piped register = ledger columns (2a — codifies the existing piped discipline into named columns). Salience pair ×n ←n + recency identical on both channels (information-faithfulness holds). Framing: finish generalizing what ls started, not adopt a new aesthetic — card + piped ledger extend outward from ls; the rail is the one net-new element, gated on extending the Surface spine (salience/inbound/window materialization) beyond fold to stream/ticks/ls. Known collisions to resolve: rail glyphs vs ls vertex-type glyphs ◆/◇/◈; ⊘ stale eventually wants digest-coverage, not pure age. Corpus: Static TTY study (3 directions, author leaned 2c; its 'undesigned piped form' was already answered by presentation-register-keys-on-channel).
416:mid       04:21 [decision] design/salience-three-term-contract: RATIFIED (Kyle 2026-07-01, from Dissolution View study): the salience contract is the three-term formula salience = f(recency, inbound-refs, digest-coverage). Recency + inbound-refs already live on Surface.salience; DIGEST-COVERAGE is the new term — 'is this fact represented in a close fact?' — and is the safety property that makes decay honest (things dissolve when COVERED, not when old; still addressable). Adopt the final shape NOW so the salience-lens migration fast-follow (session_start/identity_prompt/session_landing onto Surface.salience) targets it once, not twice. Fidelity ladder note: the corpus's four-step -q/default/-v/-vv maps 1:1 onto existing zoom levels — the disclosure contract is already the right one.
417:high      04:21 [decision] design/roadmap-060-static-honest-wave: RATIFIED (Kyle 2026-07-01): 0.6.0 = the STATIC-HONEST WAVE — Static TTY grammar unified across read/stream/ticks + the lens views that are pure functions over what exists (Horizon, Graph, Strata, Confluence, Provenance-as-why-drill: traversal/aggregation only, no cursor, no event loop). Covers the main case by far; still substantial design work against what exists now. 0.7.0 = everything needing design+discussion: TUI shell + shared temporal cursor (Rewind/Watch as ONE abstraction), gated on the internal table landing FIRST (rewind ships honest, never facts-through-today's-ontology — the responsible ordering; SPEC section-9.3). Digest last regardless (non-deterministic summarization + cross-vertex WRITE path — first concrete in-repo Peer/Grant consumer, own design pass). Corrections to prior framing: painted ALREADY HAS the interactive substrate (event loop etc., available now) — no upstream build gate; the TUI mocks are mocks, but the questions they raise drive refinement. Corpus: ~/Downloads/'Terminal UI for loops' (9 lens studies + shell + Static TTY + 7 palettes, all at 4 fidelity levels).
863:high      21:21 [thread] loops-go-conformance-oracle: SPEC §8 Attestation AUTHORED 2026-06-12 (uncommitted in ~/Code/loops-go, pending Kyle review): 8.1 JCS canonical bytes + payload-verbatim rule + incumbent migration note; 8.2 three envelope constructions (fact commitment content-only / fact row hash era-aware / tick envelope 10 fields) + window hash (incremental sha256 over hex row-hashes in witness order, empty commitment on unresolvable cursor); 8.3 Ed25519 RFC 8032, message = domain:hexdigest, domains loops-tick-v1/loops-fact-v1 protocol-normative regardless of hosting layer, wire formats, boolean verify semantics; 8.4 chain linkage + two-ordering-authorities as normative rule (receipt not chronology); 8.5 three eras, hash-inclusion-follows-data-presence as the generalizing rule; 8.6 verify + registry + strip tripwires + honest degradation; 8.7 owed conformance vectors incl. two-authorities late-arrival differential. Also §0.5 invariant 4: byte-exact tier carve-out (set-determinacy deliberately does not hold at the chain — witness order is attested behavior). PARALLEL: Opus on r2-replay-conformance branch doing Go-side R2+vectors. REMAINING from JCS decision: Python _canonical_bytes JCS impl + re-anchor ceremony (loops repo, separate task).
937:mid       18:19 [decision] design/fact-signing-per-observer-keys: Fact signatures are per-observer authorship claims, Kyle ratified 2026-06-12. Signer callable is (observer, digest) -> sig|None; key layout .loops/keys/<observer>/ed25519.key; verify maps fact.observer -> registry pubkey (the add-observer --key/--keygen registry from delta 2 already IS this mapping). Observers without keys emit unsigned — honest NULL becomes a PER-OBSERVER era, generalizing delta 2's per-store epoch. Layering note: this composes with shipped tick signing rather than replacing it — unsigned-author facts still sit under the vertex-key-signed window hash (custody claim); signed-author facts carry both claims. Custody honesty: on a single machine any local process can read any key in .loops/keys/, so observer separation is organizational not adversarial until keys live with their principals (transport/peer era). Companion mechanism: _fact_row_hash goes era-aware (includes signature only when non-NULL) so signature-stripping breaks the sealed window — delta-2 envelope trick, no re-anchoring of pre-signature rows.
1026:high      21:52 [thread] vouch-evidence-layer-collapse: DELTA 2 ENGINE LAYER LANDED (uncommitted): libs/sign gains ed25519 module (detached digest sigs, mandatory domain separation, raw-32-b64 registry format, 16 tests); engine SqliteStore gains signature column + tick_signer constructor injection (custody is a property of the store handle — signer rides __init__ not append_tick, small refinement of the decision's literal wording, same boundary intent) + verify_chain(verifier=) with two STRUCTURAL checks that run without any key: era-aware prev_hash commits to predecessor signature (strip = successor break) and signature era-monotonicity (unsigned-after-signed = break). Old head-unanchored boundary test FLIPPED: tampered signed head now detected via signature-invalid. New pinned boundary: total strip+recompute renders as honest unsigned history — test_total_strip_renders_as_unsigned_documented_boundary holds the line until registry tripwire (CLI layer, this session) and external witnessing (later delta). slice/merge already strip signature via explicit-column INSERT — zero changes needed, delta-1's schema-coupling fix paid off. 778 engine + 24 chain + 16 sign tests green. NEXT: CLI composition (init keygen, observer key field, store verify wiring).
1052:high      21:08 [decision] design/tick-key-custody-colocated: Ratified: private key lives at .loops/keys/ next to the store it signs — custody co-located, matching delta 1 semantics exactly (slice/merge strip chain → new custody context → key dies with the store's home). Chosen over ~/.config/loops/keys/ name-indirection; honesty over the committed-key failure mode, which is mitigated structurally: loops init owns gitignoring the keys directory as part of bootstrap (convenience is the mitigation, not discipline). Public key: observer declaration in the .vertex grows a key field (inline base64, ~44 chars) — the registry IS the vertex file, sl add project observer already the declarable. Algorithm: Ed25519 (deterministic per RFC 8032 — right property for tamper-evidence; RSA-PSS randomized; JWT layer was wrong shape anyway, detached-digest-signature is a new sign surface either way). Domain-separation prefix loops-tick-v1: baked in from the start. Primitive in libs/sign (new module, load_or_generate pattern). Engine boundary: INJECTION not import — append_tick takes optional signer callable, verify_chain takes optional key-lookup, apps/loops composes; preserves no-cross-lib-imports, makes progressive policy structural (no signer = legacy era), and answers May's vouch lib-boundary question by the same pattern.
```

### `designs-all.txt` — zero matches

```text
(no matches)
```

### `fold-current.txt` — 14 matches

```text
28:design/roadmap-060-static-honest-wave                               high   1   8  2026-07-02  RATIFIED (Kyle 2026-07-01): 0.6.0 = the STATIC-HONEST WAVE — Static TTY grammar unified across read/stream/ticks + the lens views that are pure functions over what exists (Horizon, Graph, Strata, Confluence, Provenance-as-why-drill: traversal/aggregation only, no cursor, no event loop). Covers the main case by far; still substantial design work against what exists now. 0.7.0 = everything needing design+discussion: TUI shell + shared temporal cursor (Rewind/Watch as ONE abstraction), gated on the internal table landing FIRST (rewind ships honest, never facts-through-today's-ontology — the responsible ordering; SPEC section-9.3). Digest last regardless (non-deterministic summarization + cross-vertex WRITE path — first concrete in-repo Peer/Grant consumer, own design pass). Corrections to prior framing: painted ALREADY HAS the interactive substrate (event loop etc., available now) — no upstream build gate; the TUI mocks are mocks, but the questions they raise drive refinement. Corpus: ~/Downloads/'Terminal UI for loops' (9 lens studies + shell + Static TTY + 7 palettes, all at 4 fidelity levels).
37:design/tick-key-custody-colocated                                   high   1   7  2026-06-09  Ratified: private key lives at .loops/keys/ next to the store it signs — custody co-located, matching delta 1 semantics exactly (slice/merge strip chain → new custody context → key dies with the store's home). Chosen over ~/.config/loops/keys/ name-indirection; honesty over the committed-key failure mode, which is mitigated structurally: loops init owns gitignoring the keys directory as part of bootstrap (convenience is the mitigation, not discipline). Public key: observer declaration in the .vertex grows a key field (inline base64, ~44 chars) — the registry IS the vertex file, sl add project observer already the declarable. Algorithm: Ed25519 (deterministic per RFC 8032 — right property for tamper-evidence; RSA-PSS randomized; JWT layer was wrong shape anyway, detached-digest-signature is a new sign surface either way). Domain-separation prefix loops-tick-v1: baked in from the start. Primitive in libs/sign (new module, load_or_generate pattern). Engine boundary: INJECTION not import — append_tick takes optional signer callable, verify_chain takes optional key-lookup, apps/loops composes; preserves no-cross-lib-imports, makes progressive policy structural (no signer = legacy era), and answers May's vouch lib-boundary question by the same pattern.
65:design/static-grammar-hybrid-by-register                            high   1   5  2026-07-02  RATIFIED (Kyle 2026-07-02): 0.6.0 unified static grammar = the Static TTY study's hybrid, reframed BY REGISTER: TTY register = rail body (2c, salience+recency gutter ◆│·⊘) under a card header (2b — _statview.card generalized out from ls); piped register = ledger columns (2a — codifies the existing piped discipline into named columns). Salience pair ×n ←n + recency identical on both channels (information-faithfulness holds). Framing: finish generalizing what ls started, not adopt a new aesthetic — card + piped ledger extend outward from ls; the rail is the one net-new element, gated on extending the Surface spine (salience/inbound/window materialization) beyond fold to stream/ticks/ls. Known collisions to resolve: rail glyphs vs ls vertex-type glyphs ◆/◇/◈; ⊘ stale eventually wants digest-coverage, not pure age. Corpus: Static TTY study (3 directions, author leaned 2c; its 'undesigned piped form' was already answered by presentation-register-keys-on-channel).
83:design/fact-signing-per-observer-keys                               mid    1   4  2026-06-12  Fact signatures are per-observer authorship claims, Kyle ratified 2026-06-12. Signer callable is (observer, digest) -> sig|None; key layout .loops/keys/<observer>/ed25519.key; verify maps fact.observer -> registry pubkey (the add-observer --key/--keygen registry from delta 2 already IS this mapping). Observers without keys emit unsigned — honest NULL becomes a PER-OBSERVER era, generalizing delta 2's per-store epoch. Layering note: this composes with shipped tick signing rather than replacing it — unsigned-author facts still sit under the vertex-key-signed window hash (custody claim); signed-author facts carry both claims. Custody honesty: on a single machine any local process can read any key in .loops/keys/, so observer separation is organizational not adversarial until keys live with their principals (transport/peer era). Companion mechanism: _fact_row_hash goes era-aware (includes signature only when non-NULL) so signature-stripping breaks the sealed window — delta-2 envelope trick, no re-anchoring of pre-signature rows.
93:design/observer-typing-dissolves-to-declared-peer                   mid    1   4  2026-07-04  RATIFIED (Kyle 2026-07-04): no observer-type enum. Observer is the base level — a bare string. 'Type' = whether the name resolves to a declared Peer and what that declaration says (horizon/potential; attested-vs-bare derivable from signing). Declaration is late-bound + retroactive per the typed-edges precedent: a peer declaration lights up historical facts by that observer at read time, no re-emit; undeclared observers stay inert bare strings. Confluence build-1 renders undeclared observers bare; declaration is the upgrade path — Confluence surfaces peer-declaration candidates the way reconcile surfaces edge-declaration candidates (read surface generates demand for the dormant Peer primitive, read-only, before Digest needs it for gating).
95:design/roadmap-070-substrate-cut                                    mid    1   4  2026-07-17  0.7.0 = the substrate cut (Kyle 2026-07-16): the three waves on main since v0.6.0 — store-backed declarations (SPEC 9 + hardening), shell completion T3, libs/custody + engine Receipt write path — ship as strange-loops 0.7.0 NOW. The roadmap wave (TUI shell + shared temporal cursor + Digest) RENUMBERS to 0.8.0; roadmap-060-static-honest-wave's 0.7.0 allocation is superseded on that point only, its content unchanged. Rationale: tasked's entire dependency surface (Receipt, custody signers, loops_home) is on main but in no released wheel — its pyproject says 'bump past 0.6.0 the moment one exists' and rides an editable path; the design wave is ~4 design sessions away from code and holding the label would leave a consumer on a working-tree crutch for weeks. Cut executed by a delegated agent; sweep obligation: in-code docstring references to '0.7.0 work' (e.g. vertex_search rewound-index note) retarget 0.8.0 in the same change. Pre-cut riders: horizon union-count fix (in-tree, needs its CHANGELOG entry) + as-of-silent-drop fold-path guard. fix/discover-cascade stays out (design-gated by thread:discover-children-as-cascade-targets, same as it stayed out of 0.6.0).
137:design/salience-three-term-contract                                 mid    1   3  2026-07-02  RATIFIED (Kyle 2026-07-01, from Dissolution View study): the salience contract is the three-term formula salience = f(recency, inbound-refs, digest-coverage). Recency + inbound-refs already live on Surface.salience; DIGEST-COVERAGE is the new term — 'is this fact represented in a close fact?' — and is the safety property that makes decay honest (things dissolve when COVERED, not when old; still addressable). Adopt the final shape NOW so the salience-lens migration fast-follow (session_start/identity_prompt/session_landing onto Surface.salience) targets it once, not twice. Fidelity ladder note: the corpus's four-step -q/default/-v/-vv maps 1:1 onto existing zoom levels — the disclosure contract is already the right one.
202:design/grammar-domain-neutrality                                    mid    1   2  2026-07-03  Kyle's catch (2026-07-02, echoing the painted semantic-renderer reframing): the grammar layer must not bake THIS vertex's domain vocabulary into rendering — 'status-aware ⊘' assumed a status=open lifecycle field that is our schema, not loops'. Data-equivalent of semantic staleness exists in two layers: (1) the three-term salience contract is already domain-neutral, and digest-coverage IS data-level staleness (dissolved when covered, not when old — identical for a design thread covered by a decision and a chat memory covered by a consolidation digest); (2) interim ⊘ follows the DECLARED-semantics pattern (fold keys, typed edges): a kind declares its lifecycle field (e.g. lifecycle "status" open="open,in-progress"), late-bound + retroactive; ⊘ = aged-while-open per declaration; undeclaring stores never rail ⊘. General principle: grammar consumes declared semantics, never assumes field vocabulary. Doc §5b amended.
633:080-design-wave                                         high    3   3  2026-07-17  open · OVERNIGHT RUN ENTERED 2026-07-16 (Kyle asleep, full delegation): run 0.8.0 through to the end. Pipeline: Opus/Sonnet implement, codex gpt-5.6-sol low<->high advise+review (smoke-tested alive, default model from ~/.codex/config.toml, effort via -c model_reasoning_effort), loops-claude arbitrates. Morning deliverable: review + retro. Sequence: grounding dossier -> design sessions 1-4 in forced order (cursor axis w/ Go-vector oracle check inside; daemon-shaped access; TUI integration; Digest) -> implementation in dependency order (fold-as-of + --diff mechanical once axis settles). Done-bar per slice: gates green + codex review + arbitration.
723:release-070                                             mid     1   2  2026-07-17  resolved · strange-loops 0.7.0 shipped 2026-07-16. Pre-ceremony commits on main: 056dd5e (horizon total_unsealed distinct-fact union fix), 184dfce (read-router refuses temporal flags on fold route), be7755c (docstring 0.7.0->0.8.0 renumber sweep, incl. docs/CLI-CHEATSHEET.md caught by re-grep). Release commit 053ee87 (CHANGELOG stamp + pyproject version bump), tag v0.7.0. Gates: loops app 2020 passed/1 xfailed, atoms 418, engine 952, lang 540, sign 37, store 89, custody 13 (new lib, not in the skill's stale gate list -- ran it anyway), root ./dev check 8 passed. Wheel pre-flight green (sl --version, custody/engine.Receipt imports, live store read) -- no missing union dep (custody has zero third-party deps of its own). GitHub release https://github.com/kgruel/strange-loops/releases/tag/v0.7.0, workflow run 29554381323 succeeded in 20s. PyPI index showed 0.7.0 with no lag; fresh-venv install verified (sl --version + live sl read project). Local production sl reinstalled via uv tool install . -e --force. Deleted 4 fully-merged wave branches (feat/completion-prog-aliases, feat/completion-t3, feat/internal-table, feat/internal-table-hardening) local + origin remote (github ref also cleared via origin's multi-push). fix/discover-cascade untouched per design gate. CHANGELOG completeness sweep caught one real gap beyond the draft: the painted bump entry said '0.11 -> 0.12.1' but 0.6.0 shipped pinned <0.11, so the wave's own 6dd3f31 migration (render= -> renderer=(data,fidelity,width) contract, 19 run_cli sites) was the missing first hop -- corrected to '0.10.0 -> 0.12.1' with the renderer-contract detail folded in. Follow-up to report, not perform: /Users/kaygee/Code/tasked's floor-bump to >=0.7.0 (left untouched per constraint, has Kyle's uncommitted in-flight work). Rides 0.8.0: TUI shell + shared temporal cursor + Digest (the design wave ~4 sessions from code), fold-state-as-of (lifts the read-router refusal), rewound search index (vertex_search), --ontology-as-of unequal-cursors escape.
1157:fts-grep-splits-punctuated-terms                        tail   1   0  2026-07-17  open · --grep silently returns 0 results for punctuated terms: '0.7.0' (dot), 'digest-coverage' (hyphen), 'Peer/Grant' (slash) all tokenize apart in FTS5, so exact-phrase searches for version numbers, hyphenated names, and slashed concepts read as ABSENCE when the content exists (audit agents recovered each via single-word retries). Fix-shape: either quote-aware phrase queries on the FTS path, or a documented substring fallback when the term contains punctuation, or at minimum a rendered hint ('term tokenizes to X Y — searching as phrase') so absence claims are honest. Surfaced by the 0.7.0 design-state audit 2026-07-16 across three independent terms.
1233:design/store-type-portfolio                                               mid    1   1  2026-07-03  Store-shape portfolio as the domain-neutrality test suite (Kyle 2026-07-02): agent-attestation (exists, ref-heavy ideation), SillyTavern RP (consolidation-ticks-as-memory, no lifecycle, personas-as-observers), novel-writing (TWO time axes: wall vs fictional/canon; continuity=coverage), household management (multi-human + recurring timed/count boundaries — chores are loops), hlab (exists, boundary-rich ops), subtask-as-orchestrator (machine volume, worker fleet observers, ticks=completions), autoresearch (metric series, keep/discard folds, different lifecycle vocab), personal salience feed (ingested via Source/Parse, high-volume/disposable, recency-dominant, browser-history-as-attention — decay is the product), corp salience feed (+grants/federation), household tracking + jeeves (sensor ingestion + agent ACTUATION outward), cumulative deep research (digest-coverage's natural home). Sharpest stress tests: the feed (inverts every design-store default; behavioral attention ≈ inbound-refs — attention-events on an address is what ref already is, new SOURCE for existing concept) and the novel (fictional time = ordering axis in payload the grammar can't sort by). Validation: each 0.6.0 view has a natural home store none of which is the design vertex — Confluence→household/corp, Graph→attestation/research, Provenance→attestation/corp, Horizon→hlab/household, Strata→subtask/research.
1331:architecture/parallel-authorization-paths                                 tail   1   0  2026-07-17  Two parallel authorization paths exist and only one is enforced: (a) lang-AST GrantDecl/ObserverDecl -> identity.py ObserverCheck (enforced at emit — 'forbidden' when decl.grant.potential excludes the kind); (b) engine.Peer/Grant frozen dataclasses with Vertex.receive(grant=) gating — ZERO production consumers (no CLI site constructs one; every receive() call is bare). Horizon (read-side visibility) is enforced NOWHERE. This is a dissolution candidate that must resolve BEFORE Digest builds on either path — Digest is chartered as the first in-repo Peer/Grant consumer, and building it on the unenforced path while the enforced path speaks a different schema would fork authorization semantics. Echoes convergence/consumer-more-substrate-aligned-than-substrate (2026-05-13): the substrate's own primitive still doesn't participate in the substrate. Found by the 0.7.0 design-state audit 2026-07-16.
1332:architecture/strata-tick-lineage-unmet                                    tail   1   0  2026-07-17  decision:design/strata-cut-ratified (2026-07-04) fed forward a concrete requirement — 'the 0.7.0 internal table should carry parent_tick_id/child_vertex_ref on tick rows' — and the internal-table arc did NOT land it: the ticks schema is unchanged (sqlite_store.py ~281-293), _tick_to_fact still drops the child tick id, and the 'lineage' §9 added is DECLARATION lineage (genesis/own_lineage), a different concept. Strata is therefore doubly downstream in the 0.8.0 wave: it needs a tick-lineage schema design (post-freeze, coordinating with the Go oracle) AND its stacked view wants Digest output (recursive digests). No design fact exists yet for tick lineage as columns vs fact-borne events. Found by the 0.7.0 design-state audit 2026-07-16.
```

## 14. Closing design gate

### (a) Questions Digest must answer

1. What source cut and selection does it summarize?
2. What close-fact kind, payload, provenance, and idempotency contract does it emit?
3. Which observer authors it, who may approve it, and which custody key signs it?
4. Which unified Grant model authorizes both the fact kind and destination vertex?
5. How is that model persisted without an uncoordinated `_decl.*` protocol fork?
6. Which existing or new cross-store write/receipt path carries it?
7. Where is the LLM effect composed, and what makes model/prompt/input auditable?
8. What backlink proves exact coverage without covering facts below the cutline?
9. How does coverage feed salience and Dissolution while remaining rewindable?
10. How do CLI `close`, `seal`, recursive Digest, and Strata relate?

### (b) Store-ratified partial answers already available

Digest is last and gets its own design pass; facts remain append-only; observers are
bare strings upgraded by declarations; fact signing is exact and per observer; grant
potential already persists inside `_decl.observer-defined`; coverage—not age—is the
ratified safety condition for dissolution; and filtered facts already move across stores
with IDs and authorship signatures preserved. These answers are grounded in §§11 and 13.

### (c) Blockers that defer implementation

Defer while authorization remains split, target-vertex permission is absent, synthesized
authorship/countersigning is undecided, close/coverage schemas are unspecified, any
`_decl.*` change lacks Go-oracle coordination, no Digest write/receipt route is chosen,
LLM provenance/failure policy is unset, or recursive Strata still lacks tick lineage.
Implementing before those decisions would risk forged attribution, an authorization fork,
or falsely declaring uncovered facts safe to dissolve.
