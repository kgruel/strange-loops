# Changelog

## 0.8.0 — 2026-07-18

Two arcs from the overnight design wave: the **temporal cursor**
(`feat/temporal-cursor`, SPEC §9.3 session 1) — a read-path cursor over
witness order, plus the explicit event-time projection and a structural
diff built on top of both — and **VertexHandle** (`feat/vertex-handle`),
the daemon-shaped engine access primitive. A golden byte-coverage safety
net for the upcoming TUI lens migration rode along (test-only).

### Added
- **engine: `WitnessPosition` — the read-path temporal cursor.** A cursor
  denotes the inclusive witness PREFIX a store had received at a position
  (`rowid <= resolved`), never a `ts` cutoff — a backdated/merged arrival
  lands at a *later* witness position even though it sorts earlier under
  `(ts, id)` replay, so an earlier position never gets silently rewritten.
  `resolve_witness_position` resolves `head` / a full fact id / the empty
  sentinel by primary-key lookup only (ids are never ordered or parsed);
  `seq:N` / `tick:ID` / wall-clock address forms resolve at the CLI layer
  (`resolve_seq`/`resolve_tick_cursor`/`resolve_tick_floor`) down to a fact
  id or rowid the engine seam takes directly.
- **engine: `vertex_fold(at=)` — fold-state-as-of.** Full reconstruction at
  a witness position: the prefix is selected, ontology resolves from the
  SAME prefix (equal cursors), facts replay in `(ts, id)` order. Returns a
  `WitnessFold` envelope (fold + position + mode + honesty status) so the
  answering mode is a machine-readable field, not only rendered prose.
  `vertex_fold(as_of=)` is the sibling event-time projection (`ts <= T`,
  mutually exclusive with `at=`) — allowed on aggregates (current
  membership, each member's facts cut by the same cutoff), where `at=` is
  refused (witness order is per-store, no shared order across members).
- **engine: durable lineage-qualified handles.** An adopted store's
  position serializes to a portable `fact:<lineage>/<id>` handle that
  re-resolves safely against any store sharing that lineage (re-resolving
  the id in the TARGET store's own append order, never reusing a source
  rowid). An unadopted store's position has no durable handle — durable
  serialization is refused rather than inventing a surrogate id.
- **engine: `VertexHandle` — daemon-shaped access without a daemon.** An
  in-process long-lived handle per consumer ("orchestration dissolves
  daemon"): compiled ontology, store connections, an immutable fold
  snapshot, and facts/ticks cursors held across operations.
  `open()`/`snapshot()`/`refresh()` with atomic snapshot swap;
  `receive()` writes through with operation-fresh credentials and no
  ontology reload; `changes()` iterators with coalescing and idle wake;
  transaction-free between probes (a parked handle holds no read txn).
  Refresh is incremental via the rowid cursor, then a full `(ts, id)`
  reconstruction per coalesced receipt group — the same replay contract
  as a cold fold. Validated by a 10k-fact refresh benchmark; consumer
  cutover rides a later checkpoint slice.
- **`sl read VERTEX --at <address>`** — the witness-cursor read. Address
  grammar: `head`, `fact:ID` (exact or an unambiguous prefix, plus the
  durable `fact:<lineage>/<id>` form), `seq:N` (receipt ordinal), `tick:ID`,
  or an ISO date/datetime (snaps to the last sealed tick at-or-before the
  mark — never a silent ts-approximation; no usable tick refuses, naming
  `--as-of`). A position landing inside an atomic declaration-edit ceremony
  refuses for exact forms (`fact:`/`seq:`) and snaps to just before the
  ceremony for floor-derived forms (`tick:`/wall-clock). Refused outright
  on aggregate (combine/discover) vertices, with teaching tailored to the
  address form.
- **`sl read VERTEX --as-of <ts>`** — the explicit event-time projection on
  the fold route (duration/epoch/ISO grammar, same as the shipped
  `--facts --as-of`), mutually exclusive with `--at`.
- **`sl read VERTEX --diff A..B`** (or `--at A --diff B`) — two independent
  full reconstructions plus a key-level structural diff per kind section
  (added/removed/changed; a keyless collect-fold degrades honestly to a
  before/after count). Reports interval honesty info a payload diff alone
  cannot see: late (backdated) arrivals between the two positions, and
  whether the declaration itself changed in the interval.
- **Honesty disclosure (mode-line + JSON `cursor` field).** Every `--at`/
  `--as-of` answer — and each `--diff` endpoint — carries its resolved mode,
  status (the honesty-ladder: `store`/`file-pre-genesis`/`unhistorized`/
  `aggregate-head`), position (fact id, seq, tick anchor), and
  portable/unadopted state, in BOTH the rendered text (a prepended mode
  line, injected even for a render-only custom lens whose own signature
  doesn't declare it) and the structured `--json` payload.

### Changed
- The 0.7.0 fold-route refusal for `--as-of`/`--since`/`--id` now teaches
  `--at`/`--as-of` as the two supported cursor flags; `--since`/`--id`
  still have no fold-route meaning and stay refused.

## 0.7.0 — 2026-07-16

Three waves since 0.6.0: store-backed declarations (SPEC §9,
`feat/internal-table` + hardening), shell completion T3, and the custody
extraction that made the signing format a lib below every writer.

### Added
- **Declaration documents & absorb ceremony (SPEC §9)** — declaration
  document form in lang (AST ↔ per-subject JSON), `store absorb` as the
  atomic genesis primitive (era opening, `_decl` reservation), store-backed
  declaration resolver in engine (the vertex file dissolves to locator +
  ingress), edit ceremony re-absorbing diffs at subject granularity,
  ontology-as-of resolution, `_decl.*` excluded from read surfaces, and the
  closing-review hardening wave (identity adoption, rewind honesty, pin
  enforcement, ingress safety).
- **Shell completion T3** — the completer seam (`complete_via`),
  vertex-name/`--lens`/`--kind`/`--key` completers, the emit and store
  walks, cite/seal/close/sync in the walk; `sl` registered in the
  completion glue (aliases through `run_app`).
- **`libs/custody`** — signing composition promoted out of the CLI app:
  the `loops-tick-v1`/`loops-fact-v1` domain constants, `keys/` custody
  layout, signer/verifier builders, `ensure_signing_key`. Consumer-forced
  extraction (tasked is the second writer); the architecture ratchet pins
  the domain constants to the lib.
- **engine: Receipt write path** — the write path returns a `Receipt` and
  owns store lifecycle.
- **Template-param secrets policy** — `$VAR` env indirection resolved at
  compile time (engine, lang).
- **`./dev check`** — root gate for the architecture ratchet (it was
  running on nobody).

### Changed
- **painted 0.10.0 → 0.12.1** — migrated all 19 `run_cli` sites off the
  deprecated `render=` param onto the `renderer=(data, fidelity, width)`
  contract (`fidelity_from_args` shadow deleted with its residue, piped
  width now flows from painted's native non-TTY `width=None` offer), then
  rode the 0.11 → 0.12 render= deprecation gate and 0.12.1's completion
  glue alias registration.
- Dropped the `sloop` entry point — unused alias; `sl` and `loops` remain.

### Fixed
- **Temporal flags no longer silently drop on folded reads** — `sl read
  <vertex> --as-of/--since/--id` without `--facts`/`--ticks` used to render
  head state with exit 0 (the router pre-parser consumed the cursor and the
  fold route never saw it). The router now refuses with the supported
  spellings; fold-state-as-of is 0.8.0 temporal-cursor work.
- **Horizon `total_unsealed` no longer double-counts overlapping windows**
  — the header total is now a distinct-fact union, not a sum of per-row
  window counts (a vertex-scope window contains every kind-scoped one; a
  session read 32 when 16 facts existed). Plus consequence-side wording on
  boundary rows ("seals on next `<kind>`", "N facts since last seal") and
  a top-3 kind mix on vertex-scope rows at default zoom.

## 0.6.0 — 2026-07-11

The **static-honest wave** (`feat/static-honest-spine`): a unified TTY/piped
rendering grammar (spine G0–G6) plus four new read-side views built on it —
Confluence, Graph, Provenance, and Horizon.

### Added
- **Static grammar spine** — rail salience tiers, card headers, and the two
  presentation registers (TTY vs piped, keyed on channel not width) unified
  across the fold/stream/ticks render paths.
- **`sl read <vertex> --lens confluence`** — the observer cut: who's active,
  kind mix, tier, composable with `--kind`/`--observer`.
- **`sl read <vertex> --lens graph`** — the ref/edge cut: HUBS (inbound-count
  sinks with per-predicate mix, surfacing typed edges), CHAINS (longest
  directed ref paths, cycle-guarded), and ORPHANS (isolated nodes). Pure
  projection over `Surface` edges — zero new engine SQL.
- **`sl read <vertex> <kind>/<key> --why`** — per-field provenance drill:
  replays the kind's fold fn over its source facts and attributes each field
  to the fact that last set it. Sibling of `--facts`, exact-address only;
  collect kinds degrade to labeled chronology; `-v` carries superseded history.
- **`sl read <vertex> --lens horizon`** — the boundary cut: each armed loop's
  open window against its next seal. Count-based boundaries render `n/N` with
  a meter; kind-based boundaries render "waiting on `<kind>`" with no fake
  meter; never-ticked loops render "never sealed". Loops uncovered by *any*
  declared trigger roll up into a single unarmed segment (silent accumulation
  named, not census noise) — a vertex-level boundary covers every loop under
  it, so the unarmed segment appears only where no vertex boundary exists.
- **Declared typed edges** (`feat/typed-edges`) — any payload field declared
  `edge "<field>" targets="<kind>"` on its kind becomes an overlay graph edge
  at read time (last-set wins, `field=` clears, `field=a,b` is a multi-valued
  set). The declaration is late-bound and retroactive: it lights up historical
  facts with no re-emit. Undeclared address-shaped fields stay inert
  provenance pins; `--lens reconcile` surfaces them as declaration candidates.
- **`sl orient <vertex>`** — a real orientation command (the session-open
  hook's grep-scrape of read output dissolved, with a versioned fallback):
  honest counts plus seal warnings for undeclared observers.
- **`loops add <vertex> observer --keygen` backfills keyless nodes** — mints
  the flat self-observer tick key with fail-atomic ordering and slashed-name
  stem registration, so a pre-signing-era vertex can enter the signed era
  without hand-built key directories.

### Changed
- **`-q` (MINIMAL) rollup unified**: `rollup_line()` in `_grammar.py` is now
  the one authority for the `vertex · stat · stat` one-liner. fold, stream,
  `store ticks`/`stats`, and `--match` migrated off their legacy comma-list
  renders and gained the vertex lead; confluence refit onto the same helper
  (keeping its local top-name shedding).
- **painted dependency bumped to `>=0.10.0,<0.11`** (from `0.4.1`, via the
  interim `0.7.0` target), picking up declared vocabularies + `Theme(roles=)`
  (0.6.0), ref deliveries (0.7.0), `paint()` (0.8.0), inline prompts (0.9.0),
  and the semantic doc tree — `painted.publish`, the exported doc vocabulary,
  `Span.ref`, section anchors, and the uniform width contract (0.10.0/0.10.1).
  Full suite + goldens green against the 0.10.1 wheel; no API breaks.
- **`show()` → `paint()`** across every command render site (~45 calls in
  `cli/output.py` + `commands/`): painted 0.8 deprecated `show()` (removed at
  1.0), and `paint()`'s Block passthrough is a drop-in for loops' usage. The
  suite's 1164 `DeprecationWarning`s drop to zero.
- **width-None spacer workarounds dissolved** (painted 0.10.1 applies the
  width contract uniformly): the store lens's conditional
  `Block.text("", Style())`-vs-`Block.empty(width, 1)` spacers collapse to
  `Block.empty(width, 1)`, and `vertices.py`'s `_spans_block` helper — a dodge
  around `Line.to_block` refusing `width=None` — deletes in favor of direct
  `Line.to_block(width)` calls (the piped register strips styling at the sink,
  so bytes are unchanged; goldens byte-stable).

- **Cross-store `ref=` resolution is explicit**: an emit-time ref that
  resolves in another store of the selected topology binds there, and one that
  resolves nowhere persists as a *typed unresolved pin* — no silent drop, and
  never ambiguity guessing between candidate stores.

### Fixed
- **`sl completion <shell>` now dispatches.** The command was advertised in
  `sl --help` (painted injects it into every `run_app` roster) but the loops
  pre-router's `known` set was built only from loops' own commands, so
  `completion` fell through to the vertex shorthand and errored. The injected
  name is now mirrored into `known`.
- **Multi-boundary vertices arm every declared trigger** — the KDL loader's
  last-declaration-wins silently dropped all but the final vertex-level
  `boundary`; declarations now accumulate.
- **`emit -v` prints its receipt again** (the inbound-delta line had gone
  silent); guarded by a CLI-path regression test.
- **Clean exit 141 on downstream pipe close** (`sl … | head`, `grep -m`) —
  no more `BrokenPipeError` traceback.

## 0.5.0 — 2026-06-28

The **structured-surface read/emit wave** (`feat/surface-build1`): a typed,
addressable `Surface` projection behind the default read path, an agent-grade
read grammar, a plain-by-default output inversion, and the restored attestation
read surface — plus ref-resolution fixes found dogfooding it.

### Added
- **Read grammar:** `--match/--grep QUERY` (FTS5 for indexed kinds, substring
  fallback), `--full` (force whole-body on every row), `--fields a,b`, `--limit N`
  (top-N by salience), `--last N` (newest-N by ts), `--count`, `--by FIELD`,
  comma-OR `--key design/,architecture/`, and `field=value` row predicates
  (`status=open`, comma-OR `status=open,refined`). These apply to the default
  fold path — they are inert on custom-lens vertices and under `--lens` overrides,
  and a stderr note now flags when a transform is dropped that way (interim until
  the salience-lens migration routes custom lenses through the `Surface`).
- **`sl --version` / `-V`** — report the installed release version (the tagged
  root `strange-loops` distribution; the `loops` sub-package version is unsynced).
- **`sl store ticks <vertex> [--chain]`** — the tick series; `--chain` projects
  the per-tick attestation envelope (chain linkage, signature presence, window
  cursor). Requires a `.vertex`; refused on combine aggregates.
- **`sl store stats <vertex> [--by-kind]`** — store totals; `--by-kind` adds a
  count-descending per-kind tally. Works on a `.db` or `.vertex`.

### Changed
- **Plain output is the default** when stdout is not a TTY (or `NO_COLOR` is set);
  styled output now requires a TTY (or `FORCE_COLOR`). `--plain` force-disables on
  a TTY.
- **`--json`** on read now emits the structured `Surface` encoding
  (`to_dict(surface)` — addressed rows with kind/key/payload/salience; implies
  `--static`).
- **Entity refs honor the canonical `kind:key` (colon) form** in emit-time
  resolution and inbound-salience. Previously only the `kind/key` (slash) form
  resolved, so colon refs — the documented convention — silently never resolved
  (write-time typo/stale-ref WARN, `ref_ref` materialization, `-v` inbound-delta)
  nor counted toward inbound salience.
- **`sl store ticks --help`** renders help instead of erroring; an invalid target
  surfaces as a return code + message rather than a raised exception.
- **`sl store ticks --since <window>`** distinguishes an empty window ("No ticks
  in the last <window>.") from an empty store.
- **Store-verb existence/exit-code parity** (`store ticks`/`stats`/`verify`): an
  absent target reads as a clean "X does not exist" instead of a raw `[Errno 2]`;
  a present `.vertex` whose `.db` was never written surfaces "store … not yet
  materialized — no facts emitted" (RC=1) — `store ticks` no longer reports it as
  an empty store (RC=0), matching its siblings. Under `--json` these errors emit a
  parseable `{"error": …}` for all three verbs (`store verify` previously emitted
  plain text on the error path).
- **`emit` explicit `message=` wins** over a trailing bareword (previously the
  bareword silently clobbered it); the ignored words are surfaced as a WARN.
- **`sl store verify` output rebuilt** on painted callout/Severity — the
  covered-vs-signed conflation de-conflated into three labeled orthogonal axes:
  **chain** (hash-chain integrity), **coverage** (facts sealed under a tick), and
  **authorship** (per-fact signatures).
- **`painted`** pinned `>=0.4.1,<0.5`.

### Removed
- **`read --diff`** — removed; measured cold (32 uses in its ship month, 0
  after). Entity-lifecycle viewing is served by **`--facts`** (the fact-history
  event stream: `read <vertex> --kind K --key key --facts`); the synthesized
  field-delta render (`status: open → refined`) is gone. (`--diff` shipped in
  0.4.0, removed by this wave.)
- **Content search on `stream`** — re-bound onto `read --match`; the dead
  query branch and the orphaned `trace` snapshot/lens residue are swept.

### Fixed
- **Multi-line CLI output** (`store verify`, `reanchor`, `emit --dry-run`)
  composes real rows again — painted 0.4.0's cell-level C0 neutralization had
  flattened the raw-`\n` `Block.text` calls these relied on to a single line.

## 0.4.0 — 2026-06-14

The dominant arc is a **federated attestation substrate**: tamper-evident tick
hash chains, Ed25519 tick + per-observer fact signatures, JCS/RFC 8785
canonicalization, and a verifiable `store rebirth`. Second arc: a **CLI
architecture refactor** (cli/ package + Operation IR pilot) and **read-path
grammar overhaul** (`trace` dissolved into `read`). Validated against
**painted 0.2.0** (pin moved to `>=0.2.0,<0.3`; drop-in — full loops suite green,
zero golden drift).

### Added
- **`sl seal [vertex] [-m] [--observer] [--dry-run] [-q]`** — draws an attestation
  boundary (requires `boundary when="seal"`). Emit receipt discloses
  `tick: <name> · signed|unsigned`.
- **Sign-on-emit** — `emit`/`close`/`sync` inject tick + fact signers; honest
  pre-signature era when no key is present.
- **Per-observer fact signatures** + **Ed25519 tick signatures** (domains
  `loops-tick-v1`/`loops-fact-v1`) via `libs/sign`'s `sign.ed25519`.
- **`loops add <vertex> observer <NAME> --key <b64>` / `--keygen`**; **`loops init`**
  bootstraps a keypair at `.loops/keys/ed25519.key`, gitignores `keys/`, and
  self-registers the vertex as a keyed observer (idempotent upgrade).
- **`sl store verify [target] [-v] [--json]`** — verifies chain, fact-window
  commitments, and signatures; strip-attack tripwire.
- **`sl store rebirth <source> <target> [--rule identity|ulid-migration] [--check]`**
  and **`sl store reanchor <vertex>`** (JCS canon-migration ceremony).
- **Read-path:** positional `sl read [vertex] <kind>/<key>`, `--diff` (field-delta
  lifecycle), `--refs [N]` (ref-graph walk), `--key <prefix>/` (prefix scan).
- **Declarative vertex management:** `loops add/rm <vertex> kind|observer|combine|row`,
  `loops ls <vertex>` (KDL-splice, re-parse before write).
- **Emit ergonomics:** `--stdin FIELD`, `--file FIELD=PATH`; `sl cite` accumulate+dedup.
- **Fold rendering:** per-kind `preview` fields; attestation line in stream/tick.

### Changed
- **Fold upsert is now merge, not replace** — re-emitting a changed field overlays;
  un-supplied fields preserved (clear via explicit `field=` sentinel).
- **Fact ids are ULIDs again** (26-char Crockford, time-sortable).
- **Fold/read row ordering is `(ts, id)`** — `merge(A,B)` and `merge(B,A)` re-fold
  identically.
- **Canonical bytes are JCS / RFC 8785** for every commitment.
- **`main.py` is a 61-line back-compat shim**; entry point `loops.cli.app.main`
  (new `cli/` package: app/registry/operation/dispatch/output/context/views).
- Numeric folds + Latest **record off-type/missing-`_ts` rejections** in
  `{target}_rejected` counters instead of coercing/crashing.

### Breaking
- **Keyless `seal`/`close`/emit-with-boundary REFUSES on a signed-era store**
  (`UnsignedTickInSignedEra`, exit 1, facts stored / tick deferred). Migration:
  ensure the signing key is present (`loops init`), or re-seal once keyed. Only
  `rebirth` genesis is exempt.
- **JCS canon migration invalidates pre-existing chains/signatures** — old
  attestations report CHAIN BROKEN until `sl store reanchor`.
- **Latest fold rejects payloads missing `_ts`**; **numeric folds reject off-type**
  (bool excluded).
- **Store schema gained attestation columns** (`facts += signature`;
  `ticks += prev_hash, window_start, fact_cursor, window_hash, signature`); both
  `id` PKs dropped `DEFAULT (ulid())` — ids supplied at INSERT.
- **Dependency swap:** `sqlite-ulid` → `python-ulid>=3.0`, plus `rfc8785>=0.1.4`.
  **painted pin → `>=0.2.0,<0.3`.**
- **`Store.append` signature** → `append(event, *, id_override=None) -> Any`.
- **`trace` verb removed** (capabilities live on `read`). **`read --refs` no longer
  FILTERS** — renders all items + a separate `## REFS` section.
- **pop-fact machinery retired**; **`.claude/` no longer tracked** (bring-your-own
  hooks/agents/settings).

### Fixed
- **Fold determinism (R2):** removed all wall-clock fallbacks from `engine.py`;
  fold is a pure function of the fact stream (restores `rebirth --check`).
- **Global/local vertex resolution unified local-first.**
- **Chain witness order is append order (rowid), not id order** — fixes false
  tamper alarms in mixed-id-era stores.
- `reanchor`/store-path refusals render as clean one-line errors, not tracebacks.

## 2026-05-19

### cite: ref-stealing bug fixed + implicit universal loop

Two bugs in `sl cite` closed together.

- **`sl-cite-malformed-kind`** — the optional `vertex (nargs="?")` positional in
  `cite.py` was greedily absorbing the first ref-arg into the vertex slot. `sl cite
  REF1 REF2 -m MSG` was storing only REF2; REF1 silently became the vertex name.
  Fix: drop the vertex positional entirely. When `ctx.vertex_path` is not set (verb-first
  dispatch), the vertex is now resolved via `_find_local_vertex()`. Vertex-first form
  (`sl project cite REF1 REF2`) is unchanged — that path already sets `ctx.vertex_path`
  before the cite view is called.
- **`cite-kind-not-implicitly-universal`** — vertices that didn't explicitly declare
  `cite {}` stored cite facts without folding them and emitted a WARN on every cite.
  Fix: `materialize_vertex()` in `compiler.py` now injects an implicit cite loop
  (collect semantics, unbounded) when the compiled vertex has no explicit cite entry.
  `classify_emit_status()` short-circuits for `kind == "cite"` so no WARN fires.
  Every vertex now silently accepts cite without a `.vertex` declaration.

Six new tests: `TestCiteVerbRegression` (3, cite.py dispatch paths),
`TestImplicitCiteLoop` (2, compiler implicit injection), `TestCiteImplicitlyUniversal`
(1, no-warn receipt path).

### ls: `preview_fields` surfaced in kind introspection

Closes the preview-ls asymmetry named in `design/lenses-consume-declared-properties`:
spec-declared `preview "field"` properties now flow all the way through to
`sl ls <vertex> --kind`.

- **`_summarize_kinds`** — includes `preview_fields: tuple[str, ...]` in each
  kind dict (empty tuple when undeclared). The `(no fold)` branch also carries
  it for consistency.
- **`_render_kind` at DETAILED+** — renders `preview=message,status` alongside
  `target` and `fold_op`. Mirrors the `grants=read,write` format in
  `_render_observer`. SUMMARY stays narrow (name + fold_op only).
- Three new tests in `TestPreviewFieldsSurfaced` covering fetch shape, DETAILED
  render presence, and SUMMARY omission.

### trace: `_DIFF_SKIP_FIELDS` replaced with `_is_diff_skip` predicate

The old frozenset `{"_ts", "_observer", "_origin", "_id", "ref"}` carried four
dead entries — those are top-level `Fact` columns, never present in
`fact["payload"]`. Only `ref` did real work.

- **`_is_diff_skip(key)`** — `key.startswith("_") or key == "ref"`. The `_*`
  branch is structurally correct and future-proof; the old named entries would
  never have matched. `ref` documented explicitly as the unprocessed input form
  of `_refs` (consumed by fold into a union-set; rendering it as +/- deltas
  conflates write-receipt with temporal-query).
- **`test_fact_payload_never_contains_column_fields`** — anchors the invariant:
  `_ts`, `_observer`, `_origin`, `_id` are column-level fields, never payload
  keys. Makes the dead-code analysis structural rather than asserted-in-prose.

### fold: degenerate namespace breakdown falls back to flat

`_has_namespaces` fired on any item with `/` in its key, routing an entire
section to grouped rendering even when 2 namespaced items sat among 173 flat
ones — producing `autoresearch/ (1)  substrate-friction/ (1)  (ungrouped: 173)`
and burying the actual index.

- **`_should_group_by_namespace`** replaces `_has_namespaces` at the
  `_render_section` dispatch point. Ratio guard: when ungrouped >
  `_NAMESPACE_DEGENERATE_RATIO` (2) × namespaced, fall back to flat. The
  namespaced items still appear — salience-sorted, full key shown — just not
  behind group headers that hide everything else.
- Six predicate unit tests (`TestShouldGroupByNamespace`) covering the no-
  namespace, all-namespaced, balanced, degenerate, boundary, and one-over
  cases. One rendering test confirming the concrete failure mode is fixed.
- Closes `friction:thread-namespace-breakdown-degenerate`.

## 2026-05-17

### Read: trace dissolves into read --diff [--refs N]

The `trace` verb shipped 2026-05-16 retires this session — its
capabilities absorbed entirely into `read`. Five-phase landing per
decision `design/trace-dissolves-into-read-with-unified-refs`. Trace
hadn't shipped externally, so this is a clean cut with no deprecation.

- **`--refs [N]` unified** (A1) — bare `--refs` walks depth 1 and
  decorates inbound/outbound edges; `--refs N` walks N hops. Replaces the
  pre-existing render-side `--refs` toggle (which filtered to ref-having
  items only — that behavior is retired; orphans now render unchanged).
  Single semantic, fetch-side walk + render-side decoration.
- **Walk semantics in `fetch_fold`** (A2) — new `atoms.WalkedItem` lives
  parallel to primary sections in `FoldState.walked` (back-compat
  default = empty tuple). Walked items carry `via_anchor` and `depth` so
  the lens renders the lineage chain. Cycle-protected, cross-kind
  capable. Lens renders walked items under a `## REFS (N)` section with
  `┄ via → kind/anchor-key` markers attributing every walked row to its
  parent — resolves `friction:trace-refs-no-visual-marker`.
- **Positional `kind/key` on `read`** (B) — `sl read project
  decision/design/foo` parses as the equivalent of `--kind decision
  --key design/foo`. Disambiguates against file-path vertices via
  `_looks_like_vertex_path()` heuristic (absolute, `./`-relative, or
  `.vertex` suffix → path; otherwise slash means entity). The B
  implementation caught a 21-test cascade on first attempt where file
  paths were misclassified as entities — fixed and locked with new
  `TestLooksLikeVertexPath` regression tests.
- **`--diff` routing** (C) — `sl read project kind/key --diff` renders
  the entity's cumulative field-deltas (status: open → partial, refs:
  +added -removed). Routes through `fetch_trace` + `trace_view` with
  `_diff=True` — the lens code stayed; only the verb wrapper went away.
  Under `--diff --refs N`, the diff accumulator partitions per entity.
- **`trace` verb deleted** (D) — removed `_run_trace` (171 LOC) and
  `lenses/trace_index.py` entirely. Removed from `_VERBS`, `_VERTEX_OPS`,
  verb-first dispatch, vertex-op dispatch, and main help. `lenses/trace.py`
  (the diff renderer) kept — read invokes it directly.
- **`arcs-block.py` hook updated** — `sl trace project thread/X --diff
  --plain` → `sl read project thread/X --diff --plain`. One-line swap as
  predicted in the dissolution-test report.

The friction list cleared along the way: `default-read-flow-too-limiting`
(read is now the primary access verb with full ergonomic coverage),
`trace-refs-no-visual-marker` (graph-render with via-markers),
`refs-flag-unification-and-propagation` (both render-side and fetch-side
collapsed into one `--refs [N]` semantic).

Regression bar: 14 new tests added across `TestExtractRefsDepth`,
`TestRunFoldRefsBothPaths`, `TestLooksLikeVertexPath`, and
`TestFetchFoldRefsWalk`. The asymmetric-pair pattern from yesterday's
exercising-catches-coherence-gaps growing edge fired three times during
landing: once on `_is_static_plain` checking already-stripped rest
(caught immediately), once on file-path-as-entity misclassification
(caught by 21 cascading test failures), and once on `--diff` needing an
entity (caught at design time). All locked with regression tests.

Net diff: +442 / -283 lines on the trace dissolution itself; one new
atom (`WalkedItem`); one deleted lens (`trace_index.py`); zero new CLI
verbs (one removed).

## 2026-05-16

### Substrate: ULID id generation restored

- **`engine._gen_id()` → `str(ULID())`** — restores time-sortable
  (lexicographic order matches generation time) and within-millisecond
  monotonic id generation via `python-ulid` (pure Python, no C extension,
  ~2.3μs per id). The prior `uuid.uuid4()` implementation produced random
  ids — `ORDER BY id` was meaningless, breaking cross-store interleaving
  and any downstream consumer that assumed id-as-chronological-key. Single-
  store ordering survived only because `since()`, `replay_cursor`, and
  `facts_by_kind` all sort by `rowid` (captured as observation
  `architecture/rowid-is-load-bearing-for-single-store-ordering`).
- **Schema cleanup** — dropped vestigial `DEFAULT (ulid())` from engine and
  store schemas. All INSERTs supply id explicitly (engine via `_gen_id()`,
  store via `SELECT * FROM src.facts` through `ATTACH DATABASE`) so the
  SQL-callable `ulid()` function is no longer needed.
- **`sqlite-ulid` dep removed** — from `libs/engine`, `libs/store`, and
  top-level `pyproject.toml`. 15 transitive packages purged. python-ulid
  was already a top-level dep (used by `libs/sign` for JTI generation).
- **Regression bar added** — engine `TestIdGenerationContract` (3 tests:
  ULID format, within-store id-order matches emission order, cross-store
  id-order interleaves chronologically). Store `TestMergeViaProductionEmitPath`
  (3 tests exercising merge through `SqliteStore.append()` rather than
  via test fixtures that previously bypassed the production id path —
  the structural gap that hid the prior regression).
- **Existing stores** — facts emitted prior to this change keep their
  original ids (no migration). Mixed-format histories are tolerated; new
  emits restore the time-sortable property going forward. A future
  migration may rewrite legacy ids if downstream consumers need uniform
  chronological-by-id semantics across the full history.

Resolves `friction:ulid-regressed-to-uuid4-in-sqlite-store`. See decision
`architecture/id-primitive-python-ulid` for rationale.

### Lens: deliberation depth (structural overfit detector)

- **`--lens deliberation`** — reads `--facts` for status-bearing kinds
  (hypothesis, thread, friction, task) and counts status transitions per
  fold key. Status entries that landed at a terminal state with one or
  fewer transitions surface as SUSPICIOUS — too clean to be real
  deliberation. Captures the "suspicious-cleanness as overfit-check"
  principle (peer-converged with alcove 2026-05-10) as a structural
  read-path feature rather than a manual noticing skill.
- **Calibration** — initially flagged `emit_count<=2` then tightened to
  `<=1` after advisor-driven re-inspection showed legitimate one-hop
  resolutions were getting false-flagged.

### Session-start: ARCS context + surface trim

- **ARCS section injected** — `.claude/hooks/arcs-block.py` (invoked by
  `session-start.sh`) renders the top 2 multi-fact open threads via
  `sl trace --diff`, capped at 30 lines per arc. First session where the
  session prompt context is composed by sl trace verb output — three-
  layer recursion: trace verb shipped this session renders the diff that
  becomes next session's context.
- **Discipline lenses co-located** — moved from `~/.config/loops/lenses/`
  to repo-local `<repo>/.loops/lenses/` (with symlinks back at originals
  for back-compat). Session-landing and reconcile lenses now version-
  controlled with the code that consumes them.
- **Surface trim** — pruned redundant sections from session-start prompt
  to make room for ARCS without inflating total context.

### Trace: kind/key lifecycle as a top-level verb

- **`sl trace <kind>/<key>`** — walks a single fold-key entity's source
  facts in ASC order (changelog-style, oldest first). Built on
  `vertex_fold(retain_facts=True)` and `FoldState.source_facts`, which
  already grouped raw facts by fold position — trace is mostly wiring,
  not new fetch infrastructure. Works both verb-first (`sl trace
  decision/design/foo`) and vertex-op (`sl project trace ...`).
- **`--refs`** — walks the outbound ref graph one hop. Each fact's `ref`
  field (`kind:key,kind:key`) names entities to pull into the trace.
  Cycle-protected via visited set keyed on `kind/key` addresses.
- **`--depth N`** — recurses N hops along the ref graph (`--refs` is
  shorthand for `--depth 1`). At depth=2 a single thread surfaces its
  full causal subgraph — design decisions, frictions, hypotheses, all
  the entities it references transitively.
- **`--diff`** — renders cumulative field-deltas instead of full
  snapshots. First fact shows `field: . → value`; subsequent facts show
  only `field: old → new` for changed scalars and `+added / -removed`
  for ref-set deltas. Under `--refs`, the diff accumulator partitions
  per entity — each entity's facts diff against its own prior, not the
  merged stream. Works because fold-merge means each emit's payload IS
  the patch it applied.
- **Empty handling** — trace has no time-window; "no lifecycle found
  for kind/key" rather than the misleading "no facts in the given time
  range" that `stream_view` would emit.
- **Combine aggregator transparency** — `_combined_read` extended with
  `return_payloads` so `retain_facts=True` flows through the combine
  branch of `vertex_fold`. From cwd, `sl trace thread/foo` walks the
  `.loops/.vertex` aggregator end-to-end without needing the explicit
  child-vertex form. The previously-planned `--all` flag dissolves —
  the aggregator IS the cross-vertex mechanism.
- **Engine bug fix in passing** — `fetch_fold` previously stripped
  `source_facts` when filtering by `--key`, making `retain_facts=True +
  key=…` a silent no-op. Regression test pinned.
- **`observation` kind declared on project vertex** — runbook lists it
  as a valid intent; vertex didn't declare it; recovered 30+ orphaned
  observations into the fold via single-line vertex change.

Resolves `friction:lineage-view-missing` (all in-scope strands) and
`friction:trace-combine-vertex-silent-empty`. 749 engine tests + 1056
loops tests pass (7 new this campaign).

### Emit Receipt + Fold Merge

- **`emit-receipt-on-write`** — every `sl emit` prints a receipt to stderr:
  success line `stored: kind/key @ <ulid>` plus WARN lines for
  kind-not-declared, fold-key-missing, and unresolved refs. Closes the
  verify-as-you-emit gap — silent-loss bugs that previously took a session
  boundary to surface are now visible in-moment. `-q/--quiet` suppresses
  the success line only; WARN/ERROR always print.
- **Vertex-declared strict** — `strict true` in a `.vertex` spec makes all
  emits refuse on validation failure (exit 2, fact not stored). No CLI
  override. `LOOPS_EMIT_STRICT=1` and `--strict` provide per-call /
  per-session opt-in for vertices that don't declare it.
- **Fold-merge default** — `_make_upsert` flipped from replace to merge
  semantics. Re-emit with subset payload preserves prior fields. Dissolves
  the patch-emit friction entirely: `sl emit project friction name=foo
  status=resolved` works as a partial patch with no new subcommand.
  Touches every fold-by kind across the codebase — load-bearing semantic
  change. Trade-off: cannot unset a field by omission (use explicit
  clear sentinel).
- **`observation` kind** added to meta vertex. Runbook updated with the
  `friction-emits-in-moment` principle.

## 2026-05-15

### Read-path access primitives

- **`--key <prefix>`** on `loops read` — kind-aware fold-key filter, prefix
  matching (case-insensitive). Works with or without `--kind` (cross-kind
  filters every section by its own declared `key_field`). Full key matches
  exactly its own item (degenerate prefix case).
- **`--kind kind/key` embedded syntax** now does prefix matching too
  (back-compat: equality is the degenerate prefix case — existing exact-match
  usages unchanged).
- **`call_lens_fetch`** in `lens_resolver` — inspects lens fetch signature;
  passes only kwargs the lens declares. Symmetric to `call_lens` on render
  side. Real `TypeError` from lens body propagates instead of being swallowed.

## 2026-03-22

### Autoresearch: Test Coverage Campaign (#001)

218 autonomous experiments across 4 libraries. Monorepo coverage: 75.4% → 98.5%.

| Package | Before | After | Miss |
|---------|--------|-------|------|
| loops | 60.3% | 100.0% | 0 |
| atoms | 92.1% | 99.1% | 8 |
| engine | 87.1% | 95.1% | 129 |
| lang | 90.2% | 99.5% | 6 |
| store | 99.6% | 99.6% | 1 |

- 2,432 tests, 25,236 test LOC, 4.3s total runtime
- 44 dead code lines removed from source (9 files)
- Test infrastructure: `VertexTopologyBuilder`, shared fixtures, `builders.py`
- `autoresearch.sh` timing/coverage separation (1.7x instrumentation overhead fix)
- Campaign archive: `docs/autoresearch/`

### CLI Architecture

- **Extract commands from main.py** — `main.py` 3,469 → 1,411 lines. `emit`, `init`, `sync`,
  `devtools`, `resolve` extracted to `commands/`. CLI error hierarchy added.
- **Session startup rebuild** — `session_start` lens + ticks listing for hook context.

## 2026-03-19

### Fold Lens Redesign

- **Namespace grouping** — items grouped by `kind/namespace` prefix, sorted by salience.
- **Salience windowing** — high-touch items (n > 1) and connected items (refs) surface first.
- **FoldPalette** — semantic color roles instead of hardcoded styles.
- **Block composition** — lens builds `Block` tree instead of string concatenation.

### Visibility Layers

- **`--refs`** — filter to connected items, show edge badges (→N), ref graph tree.
- **`--facts`** — inline source facts from fold replay, filter to sections with compression history.
- **`--ticks`** — tick dashboard with compression bars, density sparkline, boundary info.
- **Metadata badge** — `[×N ←N recency]` as consistent indicator pattern across layers.

### FoldItem Extensions

- **`n` (observation count)** — how many facts compressed into each keyed entry. Surfaced as ×N.
- **`refs` (outbound references)** — accumulated from `ref=` payload values. Comma-separated emit syntax.
- **Unfolded kinds** — surface what the store has but the vertex doesn't declare.

## 2026-03-15

### Performance

- **Fast read path** — bypass CLI framework for `--static --plain` fold reads.
- **Lazy imports** — `cmd_emit` import cost 88ms → 3.5ms (95% reduction).
- **SQL batching** — `_combined_read` single query, `vertex_fold` removes ORDER BY.
- **Deferred imports** — Tick, StoreReader, argparse, painted deferred until needed.
- **painted fast paths** — ASCII and width-1 Unicode fast paths in `row_visible_text`.

### Infrastructure

- **Workspace topology** — root `.vertex` aggregation + local vertex resolution.
- **Named combine entries** — `as=` alias for child vertex access in combine blocks.
- **Worktree-safe run clauses** — boundary `run` commands work in isolated worktrees.
- **Layer boundary enforcement** — store must not access projection internals (static analysis tests).

## 2026-03-01

### painted Extraction

- **Standalone repo** — painted extracted to git submodule, published to PyPI.
- **GitHub Actions** — publish workflow for PyPI trusted publisher.

## 2026-02-25

### CLI & Rendering

- **Store lens** — facts-first fidelity levels, palette, content gist.
- **Interactive TUI** — `store -i` explorer, `dashboard -i` live refresh.
- **Session tracking** — `session.vertex` for project-level session facts.
- **strange-loops** — zoom-aware lenses for all 6 display commands.
- **Progressive CLAUDE.md** — level-based agent discovery for each lib/app.

### Sources & Ingestion

- **Telegram + Discord archivers** — polling-based message ingestion.
- **Runner fairness** — `yield_every` prevents burst source starvation.
