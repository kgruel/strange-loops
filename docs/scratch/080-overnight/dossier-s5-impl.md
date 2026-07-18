# Dossier S5-impl — the Python incumbent's temporal machinery as it stands

*Grounding chapter for the 0.8.0 design wave (temporal cursor / daemon access / TUI / Digest).
Empirical survey of `/Users/kaygee/Code/loops` at main (post-v0.7.0, includes 184dfce and 056dd5e).
All quotes verbatim; citations are `file:line` against the working tree on 2026-07-17.*

One caveat up front: **SPEC §9's text is not in this repo.** Every "§9.3"/"§9.4" below is
quoted from code comments and docstrings that cite it. The build plan pins the SPEC's home:
"The 0.7.0 gate: SPEC §9 (loops-go `r2-replay-conformance`, ef013f1..94f7987)"
(`docs/dev/internal-table-build-plan-2026-07-11.md:3`). Downstream agents needing the SPEC
verbatim must read it in the loops-go repo.

---

## 1. The ontology-as-of resolver (internal-table slice S5)

### 1.1 The seam

Everything routes through one function, `libs/engine/src/engine/declaration.py:409`:

```python
def load_declaration(
    vertex_path: Path,
    *,
    as_of: float | None = None,
    store_timeout: float = 5.0,
    on_locked: str = "swallow",
):
    """Resolve a vertex's declaration — THE seam (SPEC §9.5).

    This is the single function every declaration-consulting site routes
    through instead of ``parse_vertex_file``. It returns the same
    ``VertexFile`` AST the parser returns, so callers are unchanged.
```

`as_of` is a **float epoch-seconds ts cutoff**, `None` = head. The provenance-carrying
variant is `load_declaration_status(vertex_path, *, as_of=None, ...) -> tuple[Any, str]`
(`declaration.py:365`), whose docstring says why it exists: "The bare seam erases the
``Unhistorized`` distinction (every caller gets an AST); surfaces that RENDER a historical
read need to say honestly which era the ontology came from — this is that channel"
(`declaration.py:373-376`). The four statuses (`declaration.py:354-362`):

```python
#: "store"            — folded store declaration (head or honest as-of)
#: "file-pre-genesis" — no lineage opened; the file is authoritative
#: "unhistorized"     — as_of predates genesis; AST is the GENESIS FLOOR
#:                      (earliest known state), not a true as-of resolution
#: "aggregate-head"   — storeless combine/discover: membership is CURRENT
#:                      FILE state regardless of as_of (aggregation internal
#:                      tables not yet built — honesty caveat, SPEC §9.5)
DECLARATION_STATUSES = ("store", "file-pre-genesis", "unhistorized", "aggregate-head")
```

### 1.2 The fold underneath

`resolve_declaration_documents(store_path, *, as_of=None, timeout=5.0, on_locked="swallow")
-> list[dict] | None | Unhistorized` (`declaration.py:209`). Mechanics, per its docstring
(`declaration.py:227-246`): locate the OWN genesis via the `store_meta.own_lineage` marker
(unmarked store with genesis rows → `UnadoptedLineage`; marker without row → corruption);
seed a document dict keyed `(kind, subject)` from the genesis payload; overlay every later
self-lineage `_decl.*` row within `as_of`; tombstones remove; unknown `_decl.*` kinds skip.
Genesis rows and overlay rows are both read `ORDER BY ts, id` (`declaration.py:253`, `:315`).

`Unhistorized` is a distinct return, not `None` (`declaration.py:141-154`):

```python
class Unhistorized:
    """At the requested ``as_of``, the store had not opened its lineage.

    Distinct from ``None``. ``None`` means "no genesis at all" (pre-genesis
    store — the file is authoritative). ``Unhistorized`` means "a genesis
    exists, but it is *later* than the ``as_of`` cutoff" — at that instant the
    store's ontology was not yet historized. Per SPEC §9.2 the honest answer
    for that era is **the genesis document set as the earliest known state**
    ("rendered honestly as legacy, never retro-claimed") — NOT the current
    file, which may have drifted since and would retro-claim history that was
    never recorded.
```

### 1.3 The cutoff and tie-break invariant (load-bearing for the 0.8.0 cursor axis)

The module docstring pins the exact rule, `declaration.py:50-61`:

```
- **Same-``ts`` tie-break: an edit is in force at its own ``ts``, inclusive.**
  The ``as_of`` cutoff is ``_ts <= as_of`` (a declaration edit at ``ts == as_of``
  participates), matching ``StoreReader.facts_between``'s inclusive upper bound
  (``ts <= until_ts``). With the equal-cursors default (``as_of = until_ts``,
  SPEC §9.3), the consequence is deterministic and explicit: **when a fact and a
  declaration edit share an exact float ``ts``, the fact folds under the NEW
  ontology** — the edit wins its own instant, regardless of physical append
  order. The tie-break is purely ``ts``-based (not witness/rowid order), so it is
  reproducible across runs and across a ``rebuild(dump(S))`` that reassigns
  rowids. Witness-order ("as of" the fact cursor) is the finer axis SPEC §9.4
  grounds fact-residence on; it is deferred (Q1) until a fact-cursor read surface
  exists — until then ``ts`` with this inclusive tie-break is the single axis.
```

Enforced at `declaration.py:322-327` (overlay loop):

```python
            # Inclusive cutoff (`> as_of`, not `>= as_of`): an edit AT `as_of`
            # is in force. With equal-cursors (`as_of == until_ts`) a fact and an
            # edit sharing an exact `ts` fold the fact under the NEW ontology —
            # the deterministic ts-axis tie-break (module docstring).
            if as_of is not None and _ts > as_of:
                continue
```

Genesis-boundary check at `declaration.py:302-303`: `if as_of is not None and genesis_ts > as_of:
return Unhistorized(...)` — a cursor exactly AT the genesis ts resolves the genesis (inclusive).

A second cursor-relevant invariant lives on the edit ceremony, `sqlite_store.py:718-723`
(`SqliteStore.absorb_edit`):

```
        3. Every row in the ceremony shares ONE effective ``ts``, stamped
           once — the ceremony is a single ontology transition. Without this,
           a historical ``as_of`` cursor could land *between* the rows of one
           edit and observe a half-applied ontology (e.g. a rename showing
           both old and new kinds) — transaction atomicity protects live
           readers, not rewound ones.
```

### 1.4 test_ontology_as_of.py — what the exit criterion actually proves

`libs/engine/tests/test_ontology_as_of.py` (262 lines, read in full). Its own framing
(`:1-19`): "The exit criterion is HONEST REWIND: a read at a cursor before a declaration edit
resolves under the OLD ontology; a head read under the new. The resolver's ``as_of`` cutoff is
proven in ``test_declaration_resolver.py``; this file proves the READ SURFACES thread it
correctly and with the equal-cursors default (§9.3)". The load-bearing scenario is an
S4-shaped `_decl.kind-defined` overlay moving `decision`'s fold key `topic → name`.

Test inventory:

| Class / test | Proves | Lines |
|---|---|---|
| `TestFoldKeyRewind.test_resolver_fold_key_rewinds_across_the_edit` | as_of before edit → `topic`; after → `name`; head → `name` | 126-135 |
| `.test_cursor_between_two_edits_picks_the_earlier` | topic→name (t1), name→title (t2); cursor in [t1,t2) sees the FIRST edit only | 137-160 |
| `.test_same_ts_edit_is_in_force_at_its_own_ts` | at exact shared float ts the NEW key wins, ×5 determinism loop; one epsilon (`edit_ts - 0.001`) earlier → OLD. Comment: "The tie-break is pure ts (not rowid/append order), so it is deterministic across runs." | 162-175 |
| `.test_genesis_never_excluded_below_its_own_ts` | cursor before genesis → genesis floor, "never Latest-resolved away" | 177-184 |
| `TestHeadEquivalence.test_vertex_facts_head_equals_now` | `vertex_facts(..., as_of=None)` byte-identical to `as_of=now`; genesis excluded from user facts (§9.4) | 193-204 |
| `.test_vertex_facts_reserved_exclusion_holds_under_as_of` | `_decl.*` ambient exclusion resolved at the as_of ontology too | 206-213 |
| `.test_vertex_search_head_equals_now` | search head ≡ now | 215-224 |
| `.test_vertex_ticks_head_equals_now` | as_of does not perturb the tick-window path | 226-233 |
| `TestTickFoldInterpretation.test_pre_edit_tick_types_under_old_key` | `vertex_tick_fold` types a pre-edit tick's snapshot under `key_field == "topic"`, post-edit under `"name"` (Q5) | 241-261 |

Why head-equivalence is the whole S5 compatibility argument (`:8-11`): "``as_of=None`` (head)
is byte-identical to the pre-S5 behavior, and — because nothing has a future ``ts`` —
identical to ``as_of=now``. That equivalence is why threading equal-cursors is a no-op
against current behavior."

Note the test's `_emit` helper (`:82-93`) inserts rows by raw SQL "at a controlled ``ts``
(bypasses live-now stamping)" — controlled-ts injection has no production API; tests go
straight to SQLite.

---

## 2. Fact-window primitives (`vertex_facts` until, etc.)

There is no `until=T` keyword on `vertex_facts` — the window is **two positional floats**:

```python
def vertex_facts(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
    observer: str | None = None,
    *,
    include_internal: bool = False,
    as_of: float | None = None,
) -> list[dict]:
```
(`libs/engine/src/engine/vertex_reader.py:1198-1207`)

Its docstring scopes what `as_of` touches (`vertex_reader.py:1221-1227`): "the equal-cursors
default is ``as_of = until_ts``, so a windowed read interprets its facts under the ontology in
force at the window's upper bound. ``None`` = head (identical to pre-S5 behavior). **Only the
store-resolution and reserved-namespace exclusion ride the cutoff here; the fact time window
itself is ``since_ts..until_ts`` as before.**" Note: the equal-cursors *default* is enacted by
the CLI caller (fetch layer, §6 below), not inside the engine — engine `as_of` defaults to
`None` (head).

The single-store window is `StoreReader.facts_between` (`store_reader.py:426-457`) —
**inclusive both ends, ordered by ts alone**:

```sql
SELECT id, kind, ts, observer, origin, payload FROM facts
WHERE ts >= ? AND ts <= ?{internal_clause} ORDER BY ts
```
(`store_reader.py:453-455`; kind-filtered variant adds `AND (kind = ? OR kind LIKE ?)` for
dot sub-kinds, `:447-449`.)

Sibling window surfaces:

- `vertex_ticks(vertex_path, since_ts, until_ts, name=None, *, with_envelope=False, as_of=None)`
  (`vertex_reader.py:1258-1266`); "``as_of`` (SPEC §9.3) resolves the declaration at a
  historical ``ts`` cutoff — equal-cursors default is ``as_of = until_ts``. ``None`` = head"
  (`:1277-1278`). Aggregates get empty envelopes: "attestation is a per-store property"
  (`:1272-1275`).
- `vertex_search(vertex_path, query, *, kind=None, since=None, until=None, limit=100,
  observer=None, as_of=None)` (`vertex_reader.py:1468-1478`) — here `since`/`until` ARE
  keywords (`ts >= since` / `ts <= until`, applied in `search_facts`, `store_reader.py:533-538`).
- `SqliteStore.between(start, end)` — `WHERE ts >= ? AND ts <= ? ORDER BY rowid`
  (`sqlite_store.py:951-958`), accepts datetime or float.
- Tick fidelity window: a `Tick` carries `ts: datetime` and `since: datetime | None`
  (`libs/engine/src/engine/tick.py:34,37`); the drill unions `[tick.since, tick.ts]`:
  `facts = vertex_facts(vertex_path, tick.since.timestamp(), tick_ts, as_of=tick_ts)` with the
  comment "Engine invariant: tick.since is always set to the period's first-fact timestamp"
  (`apps/loops/src/loops/commands/fetch.py:1406-1417`). `TickWindow` (atoms) restates the
  shape: "The tick's ``since → ts`` interval defines the *window*"
  (`libs/atoms/src/atoms/ticks.py:5`), fields `ts: float` / `since: float | None` epoch
  seconds (`ticks.py:45-46`).

**Aggregate asymmetry worth knowing:** `vertex_facts`' combined path does NOT forward `as_of`
to children — `_combined_facts(ast, vertex_path, since_ts, until_ts, kind, include_internal=...)`
takes no `as_of` (`vertex_reader.py:435`, call at `:1234-1237`); children are windowed and
`_decl.*`-GLOB-excluded only. `vertex_search` DOES forward: "``as_of`` is forwarded to each
child (SPEC §9.3). The AGGREGATE's own declaration resolves head (its member-set history is
not historized — a build-plan non-goal), but each child is a single store and MUST honor the
cursor for its own ``search`` fields" (`vertex_reader.py:641-645`). The S0-S5 closing review
flags the aggregate honesty gap directly: "storeless combine/discover vertices …
`--as-of` silently reads a historical fact window through today's aggregation membership"
(`docs/dev/internal-table-s0-s5-closing-review-2026-07-13.md:31`) — mitigated at the CLI by
the `aggregate-head` ontology_notice (§6.2 below).

---

## 3. `--why` replay attribution — the per-key replay precedent

### 3.1 The engine of it

`apps/loops/src/loops/provenance.py` — "Diff-replay provenance — per-field attribution for a
single fold key" (`:1`). Signature (`provenance.py:114-121`):

```python
def replay_attribution(
    fold_op: "FoldOp | None",
    source_facts: list[dict],
    *,
    kind: str,
    key: str,
    key_field: str | None,
) -> Provenance:
```

Contract (`provenance.py:9-13`): "Faithful by construction: it drives the actual
``Spec``/fold op (no parallel mirror to drift). ``source_facts`` is populated only for
Upsert-fold kinds (engine gates it there), so an Upsert replay is the live case; any other
fold op degrades to chronology-is-the-provenance (the fold order already IS the answer).
O(facts x fields) — fine for a single-key drill."

Mechanism (`provenance.py:150-190`): builds the real fold fn via
`atoms.engine.build_fold_fn(fold_op)`, replays the key's facts **in the given order**
(1-based `index`), snapshots the key's entry after each apply, and diffs against the prior
snapshot. Output is `Provenance` (`provenance.py:73-97`) with
`mode ∈ {"upsert", "collect", "empty"}`, per-field `FieldAttribution(field, value, setter,
priors)` (priors newest-first), and per-apply `ApplyDelta(index, total, ts, observer, changed,
status_to)` — "The trace's ``×n`` is facts-folded-so-far (``index``)" (`provenance.py:62-63`).
`to_dict` (`provenance.py:211`) is the `--json` shape.

### 3.2 The CLI wiring

`apps/loops/src/loops/cli/views/fold.py:550-598`. Requirements: "Requires an EXACT address —
a single, complete fold key (not a prefix, not a comma-OR set)" (`fold.py:551-552`); trailing
`/` prefix rejected (`:564-569`); exit 2 with guidance otherwise. Upsert path:

```python
    if isinstance(fold_op, Upsert):
        state = fetch_fold(
            vertex_path, kind=kind, key=key, observer=obs, retain_facts=True,
        )
        key, source = _lookup_source_facts(state, kind, key)
        prov = replay_attribution(
            fold_op, source, kind=kind, key=key, key_field=fold_op.key,
        )
```
(`fold.py:582-589`; the collect branch at `:590-598` "degrades to mode='collect'").

The source facts come from engine `vertex_fold(..., retain_facts=True)` which buckets raw
payloads into `source_facts["<kind>/<key_value>"]` (`vertex_reader.py:410-432`, population at
`:930-1003`, threaded into `FoldState` at `:1040-1043`). Fold-op resolution goes through the
declaration seam at head: `_resolve_fold_op` calls `load_declaration(vertex_path)` with **no
as_of** (`fold.py:618-631`) — `--why` is a head-only surface today.

**Why this is the temporal-cursor precedent:** it already replays one key's fact chronology
step-by-step through the real fold op and can name state after step *i* — exactly the
per-key half of a fold-state-as-of. What it lacks is a ts cutoff: replay always runs to the
end of the key's fact list, and the facts arrive in whatever order the retain_facts populate
saw (fold replay order, ts-then-id — see §5).

---

## 4. The read router's temporal-flag refusal (commit 184dfce)

`git show 184dfce` — "loops: read-router refuses temporal flags on the fold route"
(2026-07-16). Commit message, verbatim:

```
sl read <vertex> --as-of/--since/--id without --facts/--ticks used to
render head state with exit 0 — the pre-parser consumed the cursor and
the fold route never saw it, a silent anachronism against SPEC §9.3's
honesty posture (rewound reads must never silently lie). The router
now refuses with exit 2 and names the supported spellings (--facts
--since/--as-of/--id for event history, --ticks for tick windows).
fold-state-as-of is 0.8.0 temporal-cursor work.

Resolves friction:as-of-silent-drop-on-fold-path.
```

The guard as it now stands in `apps/loops/src/loops/cli/views/read.py:64-87`:

```python
    # Temporal flags without a temporal route: the folded read cannot
    # honor them yet, and silently dropping a cursor renders head state
    # as if it were T — a silent anachronism (SPEC §9.3's honesty
    # posture: rewound reads must never silently lie). Refuse until
    # fold-state-as-of ships (0.8.0 temporal-cursor work).
    dropped = [
        flag
        for flag, value in (
            ("--since", known.since),
            ("--as-of", known.as_of),
            ("--id", known.fact_id),
        )
        if value
    ]
    if dropped:
        flags = ", ".join(dropped)
        ctx.reporter.err(
            f"read: {flags} needs a temporal view — the folded read"
            " cannot honor it yet (fold-state-as-of is 0.8.0"
            " temporal-cursor work).\n"
            "  event history:  read <vertex> --facts --since/--as-of/--id …\n"
            "  tick windows:   read <vertex> --ticks --since/--as-of …"
        )
        return 2
```

Routing table above it (`read.py:6-9`): default → fold; `--ticks` → ticks; `--facts` +
(`--since`|`--as-of`|`--id`) → stream; bare `--facts` → fold with the facts visibility layer.
The ticks branch re-injects `--since`/`--as-of` (`read.py:50-59`) — that re-injection is
itself a repaired defect: closing review #7, "**High — CLI `--ticks --as-of` is silently
discarded**" (`docs/dev/internal-table-s0-s5-closing-review-2026-07-13.md:75-77`).

Tests: `apps/loops/tests/test_read_router_temporal_guard.py` (added in 184dfce, 90 lines) —
refusal for each flag alone and combined (exit 2, error contains "cannot honor" and
"--facts"), plus `TestTemporalRoutesStillCarryTheCursor` proving stream/ticks routes receive
the re-injected flags and the plain fold route is unaffected.

**Empirically verified on the installed CLI (2026-07-17):** `sl read project --as-of 30d` →
exit 2 with exactly the guard's message.

---

## 5. How ts is stored, compared, and ordered

### 5.1 Storage

- `Fact.ts` — "Epoch seconds (float) — when observed. Display formatting is caller's problem."
  (`libs/atoms/src/atoms/fact.py:52`). Stamped by `Fact.of(...)` as
  `ts if ts is not None else time.time()` (`fact.py:111-113`). Full wall-clock float
  resolution; no quantization.
- SQLite: `ts REAL NOT NULL` on both `facts` and `ticks`, each with a plain ts index
  (`sqlite_store.py:270-295`). `append()` writes `d["ts"]` verbatim (`sqlite_store.py:516-520`);
  there is no store-side re-stamping.
- IDs are ULIDs: "26-char Crockford base32, time-sortable (lexicographic order matches
  generation time), within-ms monotonic" (`sqlite_store.py:40-43`). History note: uuid4 rows
  from 2026-03-15..05-16 exist in old stores and "sort above every ULID"
  (`sqlite_store.py:64-65`) — id order is NOT trustworthy as chronology across that era.
- `Tick.ts` is a `datetime` in the dataclass (`tick.py:34`) but REAL epoch in the `ticks`
  table; `vertex_tick_fold` converts with
  `tick.ts.timestamp() if hasattr(tick.ts, "timestamp") else float(tick.ts)`
  (`vertex_reader.py:1069`).
- Read-surface shape split: `StoreReader._fact_row_to_dict` converts ts to
  `datetime.fromtimestamp(r[2], tz=timezone.utc)` (`store_reader.py:420`) while
  `facts_by_kind` returns the raw float (`store_reader.py:469-479`); `fetch_stream`
  ISO-stringifies datetimes for JSON (`fetch.py:413-416`).

### 5.2 The ordering ledger — three orders coexist, per surface

The store header pins the doctrine (`sqlite_store.py:59-71`):

```
# ORDERING AUTHORITY (observation design/event-order-vs-witness-order): window
# cursors are fact IDS (portable handles), but window MEMBERSHIP and hashing
# follow APPEND ORDER (rowid) — never id order. …
# Event order (ULID, fact.ts) remains the READ path's order; the two orders
# answer different questions and neither substitutes for the other.
```

And the replay contract (`sqlite_store.py:902-906`, `since_raw`):

```
        FOLD REPLAY ORDER is (ts, id) — event order, deterministic across
        custody contexts, so merge(A,B) and merge(B,A) re-fold to the same
        state. Witness order (rowid) remains the chain/window authority;
        the two orders answer different questions (see ORDERING AUTHORITY
        on append_tick).
```

Actual ORDER BY per read surface:

| Surface | ORDER BY | Cite |
|---|---|---|
| `SqliteStore.since` / `since_raw` / `replay_cursor` (fold replay) | `ts, id` | `sqlite_store.py:873,909,931` |
| `SqliteStore.between` (tick fidelity, engine-level) | `rowid` | `sqlite_store.py:957` |
| Tick chain window membership + hashing | `rowid` (witness) | `sqlite_store.py:1215` |
| Declaration genesis + overlay fold | `ts, id` | `declaration.py:253,315` |
| `StoreReader.facts_between` (CLI stream window) | **`ts` only — no id tie-break** | `store_reader.py:448,454` |
| `StoreReader.facts_by_kind` (CLI fold replay) | `ts, id` | `store_reader.py:466` |
| `StoreReader.recent_facts` / `search_facts` | `ts DESC` / `f.ts DESC` | `store_reader.py:503,548` |
| `StoreReader.resolve_entity_id` (latest per key) | `ts DESC, id DESC LIMIT 1` | `store_reader.py:494` |
| Combined (ATTACH) fold read | Python `rows.sort(key=lambda r: (r[2], r[0]))` — "fold-replay-ordered by (ts, id) … Store- and merge-order independent" | `vertex_reader.py:354-369` |
| Combined facts window | `ts, id` | `vertex_reader.py:465,476` |
| Combined ticks window | `ts` only | `vertex_reader.py:519,530` |
| `fetch_stream` final render sort | Python `f["ts"]` reverse (no tie-break) | `fetch.py:411` |

Two drift notes found while surveying (stated, not editorialized):

1. `facts_between` orders by bare `ts` — same-ts rows come back in SQLite's residual
   (effectively rowid/scan) order, unlike every replay path's `(ts, id)`. For a future
   fact-cursor this is the one window surface without a deterministic total order.
2. `facts_by_kind`'s docstring says "ordered by insertion (rowid ASC)"
   (`store_reader.py:460-462`) but its SQL is `ORDER BY ts, id` (`:466`) — docstring is stale;
   the SQL matches the fold-replay (ts, id) doctrine.

The deferred witness-order cursor is named exactly once as design debt
(`declaration.py:59-61`, quoted in §1.3): witness-order is "the finer axis SPEC §9.4 grounds
fact-residence on; it is deferred (Q1) until a fact-cursor read surface exists — until then
``ts`` with this inclusive tie-break is the single axis." This is the direct input to the
0.8.0 cursor-axis question (ts vs witness-order vs tick-anchor).

---

## 6. The CLI today: `--as-of`, and the `--ontology-as-of` that does not exist

### 6.1 What `--as-of` accepts

Parsing is `_parse_as_of` (`apps/loops/src/loops/commands/fetch.py:41-66`):

```python
def _parse_as_of(s: str, now: datetime) -> float:
    """Resolve an ``--as-of`` value to an anchor epoch ``ts`` (SPEC §9.3).

    The anchor is the read's upper bound: facts replay up to it and — the
    equal-cursors default — the ontology resolves at it. Accepts either a
    duration ("ago" from ``now``, same grammar as ``--since``: ``7d``/``24h``)
    or an absolute position (epoch seconds, or an ISO-8601 timestamp). Absolute
    forms matter for a precise rewind — a cursor landing strictly between two
    declaration edits — where a duration-from-now would be timing-fragile.
    """
```

Grammar: `^\d+[dhms]$` durations (d/h/m/s, `_parse_duration` at `fetch.py:30-38`), else
`float(s)` epoch seconds, else `datetime.fromisoformat` (naive → assumed UTC, `:64-65`).

### 6.2 Where it is wired (all epoch-float anchors, equal-cursors coupling done here)

- **Stream** (`--facts` route): `fetch_stream` (`fetch.py:344-458`). The coupling, verbatim
  (`fetch.py:384-389`):

  ```python
      # Equal-cursors (SPEC §9.3): one anchor is BOTH the fact-window upper bound
      # and the ontology-as-of cutoff. cursor=None (head) when --as-of is absent
      # keeps the equivalence property exact.
      anchor = _parse_as_of(as_of, now) if as_of else now.timestamp()
      cursor = anchor if as_of else None
      since_ts = anchor - since_secs
  ```

  The anchor feeds `vertex_facts(vertex_path, since_ts, anchor, ..., as_of=cursor)`
  (`:393-398`), the key-drill fold-key lookup (`:401-405`), and
  `load_declaration_status(vertex_path, as_of=cursor)` for fold_meta (`:423`). Honest-render
  callout (`fetch.py:441-457`): when `cursor is not None and decl_status != "store"`, the
  payload carries `ontology_notice` — "ontology unhistorized at this anchor — rendered under
  the genesis document (earliest known state)" / "aggregation membership is CURRENT file
  state…" / "no declaration lineage — ontology is the current file".
- **Ticks listing**: `fetch_ticks(vertex_path, *, since=None, as_of=None)` (`fetch.py:522-546`),
  same anchor/cursor pattern; "A tick DRILL (``--ticks <idx>``) interprets its own snapshot
  under ``as_of = tick.ts`` regardless — that lives in ``engine.vertex_tick_fold``, not here"
  (`fetch.py:536-539`). The ticks pre-parser comment agrees: "the flag only shifts the LIST
  window, not the per-tick interpretation" (`commands/ticks.py:49-52`).
- **Head-only by doctrine** (never rewound): the default folded read, `store summary`, and
  write/identity paths — "you cannot write or sign into the past"
  (`docs/CLI-CHEATSHEET.md:66-68`). Known caveats at head: tier glyphs (Q3, "present-session
  lens state", `fetch.py:368-369`), and FTS — "the FTS index itself is built at head; …
  a historical search is honest about *which facts* fall in the window but the *index* it
  queries is the head kind set. A fully rewound index is 0.8.0 work"
  (`vertex_reader.py:1496-1500`, Q2).

App-layer tests: `apps/loops/tests/test_stream_ontology_as_of.py` — fold_meta rewind, head
equivalence, same-ts fact folds under NEW ontology, key drilldown under as-of key, tick drill
under pre-edit ontology (`:107-163`).

### 6.3 `--ontology-as-of`: contradicting the prompt's framing

The prompt asks "what `--ontology-as-of` accepts on the CLI today." **It accepts nothing —
the flag does not exist.** Its only trace in the entire codebase is a comment in the stream
command's pre-parser (`apps/loops/src/loops/commands/stream.py:27-32`):

```python
    # --as-of (SPEC §9.3): rewind read to a historical anchor — facts up to it,
    # AND the ontology (fold keys/kinds) resolved at the SAME anchor
    # (equal-cursors default). Accepts a duration ("ago") or absolute epoch/ISO.
    # --ontology-as-of is RESERVED for the future unequal-cursors escape (0.8.0)
    # and deliberately NOT wired here — passing it errors as unknown.
    pre.add_argument("--as-of", default=None, dest="as_of")
```

Empirically verified: `sl read project --facts --ontology-as-of 30d` → argparse usage error,
exit 2. No test asserts this rejection (grep over `apps/loops/tests` finds only
`test_stream_ontology_as_of.py`, which never passes the flag).

### 6.4 What the "unequal-cursors escape" deferral means

Today a temporal read has two conceptual cursors but **one flag**: facts-as-of (which facts
replay) and ontology-as-of (which kinds/folds interpret them) are hard-coupled to the same
anchor. The cheatsheet states the model (`docs/CLI-CHEATSHEET.md:53-72`): "Once a store
historizes its declarations (`sl store absorb`), a temporal read has two cursors:
**facts-as-of** … and **ontology-as-of** … `--as-of <duration|epoch|ISO>` rewinds a `--facts`
or `--ticks` read to a historical anchor with the **equal-cursors default**: facts replay up
to the anchor AND the ontology resolves at the *same* anchor — reading last month's facts
reads them under last month's fold keys. … `--ontology-as-of` (unequal cursors — deliberate
reinterpretation) is reserved for 0.8.0, not yet wired."

So the escape = deliberately splitting the cursors: replay facts from window W while
interpreting them under the ontology in force at a *different* time (e.g. today's fold keys
over last quarter's facts, or vice versa). The build plan carried it as explicit-only from
day one: "read path grows the second cursor with **equal-cursors default** (§9.3); unequal =
explicit" (`docs/dev/internal-table-build-plan-2026-07-11.md:51`, the S5 row). The engine is
already shaped for it — every read surface takes `as_of` independently of its
`since_ts/until_ts` window, so unequal cursors need only a second CLI flag threaded to
`load_declaration`'s `as_of` while the window anchor stays separate. What's deliberately
missing is the *surface*, so that no spelling of a rewound read can be ambiguous about which
cursor moved.

Two exceptions to "as-of is a query property" already ship and constrain the 0.8.0 design:

1. `vertex_tick_fold` — "the snapshot is authoritative and is NEVER re-folded — but it is
   *interpreted* … under the ontology in force at the tick's own boundary, ``as_of =
   tick.ts``, not at head. … This is the one surface where 'as of' is a property of the
   datum, not of the query." (`vertex_reader.py:1062-1067`).
2. The edit ceremony's single-ts stamping (§1.3) exists solely to keep rewound cursors from
   observing half-applied ontologies.

---

## 7. Condensed invariant list (for citation by design sessions)

1. **Equal-cursors default**: one `--as-of` anchor is both fact-window upper bound and
   ontology cutoff; `as_of=None` (head) ≡ `as_of=now`, byte-identical to pre-S5
   (`fetch.py:384-389`; `test_ontology_as_of.py:8-11`).
2. **Inclusive cutoffs everywhere on the ts axis**: declaration `_ts <= as_of`; fact window
   `ts >= since AND ts <= until` (`declaration.py:50-53`; `store_reader.py:453-455`).
3. **Same-ts tie-break**: a declaration edit is in force at its own ts; a fact sharing that
   exact float ts folds under the NEW ontology; tie-break is pure ts, never rowid
   (`declaration.py:53-58`; `test_ontology_as_of.py:162-175`).
4. **Ts is the single temporal axis today**; witness-order cursor is deferred Q1 until a
   fact-cursor read surface exists (`declaration.py:59-61`).
5. **Fold replay order is (ts, id)**, merge-order independent; **chain/window membership is
   rowid** (witness); the two never substitute (`sqlite_store.py:59-71,902-906`).
6. **Pre-genesis honesty ladder**: no genesis → file authoritative; genesis later than cursor
   → `Unhistorized` genesis floor, "never retro-claimed"; aggregates → `aggregate-head` notice
   (`declaration.py:141-154,354-362`; `fetch.py:441-457`).
7. **Fold-state-as-of does not exist**: the fold route refuses `--since/--as-of/--id` with
   exit 2 (184dfce); `--why` replays per-key with no cutoff, at head ontology
   (`read.py:64-87`; `fold.py:582-589,618-631`).
8. **One edit ceremony = one ts**, so no cursor can land inside an ontology transition
   (`sqlite_store.py:718-723`).
9. **Snapshot interpretation is datum-anchored**: tick drills always use `as_of = tick.ts`
   (`vertex_reader.py:1062-1070`; `fetch.py:1406-1417`).
10. **Head-index caveats ride along**: FTS kind set (Q2) and tier glyphs (Q3) stay head under
    any rewind (`vertex_reader.py:1496-1500`; `fetch.py:368-369`).
