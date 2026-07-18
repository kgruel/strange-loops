# Dossier: Digest — design state and the six named collisions

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

> "The compression is **not deletion** — append-only means the 142 facts remain,
> addressable: Provenance proves the summary from them, Rewind visits the window."

The `-vv` mechanism panel:

> "digest = summarize( fold( facts in window ) )
> result is itself a fact — kind=close · refs the window it summarizes
> flows to loops/roadmap — appended as 01JQ9K… · seq +1
> recurses — parent folds it in; its own digest compresses further → Strata
> additive — 142 facts remain; the digest layers on top — nothing overwritten"

The `-v` panel establishes the cutline semantics: "ranked by salience — the digest keeps
the top of the window … below the cutline isn't lost — it stays in the store and
re-competes next window." And the closing TUI note: "digest is the **close** action itself
— resolve a tick and it emits the synthesis **you can edit** before it flows up."

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

### 5.2 What exists today (all of it whole-store, none of it per-fact)

`libs/store/` is "slice, merge, search, transport" (store CLAUDE.md). The complete
cross-store surface:

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
- **receive_store** (`receive.py:29-46`): "Create-or-merge: receive a source store into a
  target location" — file copy or merge, validated by SQLite magic bytes.
- **push_store / pull_store** (`transport.py:51,96`): slice local → transport → remote
  receive. "Cursor tracking is the caller's responsibility (libs/store is stateless)"
  (store CLAUDE.md).
- **slice_store**: extract subsets into a NEW file ("Target must not exist").

**There is no API that appends one fact into another store.** The CLI emit path resolves
exactly one vertex and calls `program.receive(fact)` against it (emit.py:782). `loops sync`
is "cadence-gated source execution" (sync.py:1) plus aggregation-vertex fan-out — sources
write into their own vertex's store; aggregation (`combine`) is a *read-path* property.

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

- **Any lib** would require a new `_LIB_ALLOWED_RUNTIME` entry (libs default to
  forbidden-everything) plus a third-party dependency in that lib — no lib currently
  carries an effectful network client; `sign` is kept deliberately "loops-agnostic"
  (custody CLAUDE.md: "Depends on `sign` (loops-agnostic Ed25519 — keep it that way)").
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

> "a fact dissolves only when its meaning is **covered elsewhere** — **digest coverage** is
> the safety check, **not age**. this is why Digest makes dissolution possible"

> "coverage — folded → 0 ok — once in a close, salience may reach 0 safely"

> "It's the counterpart to **Digest** — coverage is what makes fading safe — and to Rewind:
> dissolved is never gone, scrub back and it's bright again."

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

Every collision the task named exists as stated, with one refinement: the prompt's item (3)
said "the reserved-kind constants from internal-table S0" live behind the collision — true,
but the sharper code fact is that **grant persistence already exists** in the frozen vocab
(`_decl.observer-defined` payload carries `grant: {potential: [...]}`, document.py:493-502;
Go SPEC table: "public key, grant, scope") — the collision is specifically about *engine's*
Peer/Grant shape (horizon + any new target-vertex dimension) not fitting that persisted
schema, on top of the new-kind freeze. And item (6)'s "coverage backlink" has *no* design
fact anywhere — the term's only occurrence in the store is the 080 thread's collision list
itself; its content had to be reconstructed from the two corpus mocks.
