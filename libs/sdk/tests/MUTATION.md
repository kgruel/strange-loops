# Mutation Testing Report: `libs/sdk`

- **Target Package**: `libs/sdk/src/sdk` (`declare.py`, `target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/sdk/tests/` — per-mutant net is the unit/contract/integration/property/conformance layers; the stateful suite (`test_stateful_sdk.py`) self-excludes under `MUTANT_UNDER_TEST` (sequence-level complement, not a per-mutant killer).
- **Last full run**: 2026-08-15, mutmut 3.x (see Final Results below).

## Initial results (2026-08-14, baseline before burn-down)

| Module | Mutants surviving | Notes |
| :--- | ---: | :--- |
| `types.py` | 0 | Fully killed. |
| `target.py` | 32 | |
| `declare.py` | 90 | |
| `kind.py` | 209 | |
| `emit.py` | 244 | |
| `read.py` | 1183 | Largest module, weakest kill net. Sample confirmed-real survivor: `read_summary`'s `include_internal=False` default flips to `True` unnoticed — no test pins default exclusion of internal kinds. |

Timeouts: 6. Total survived: 1752 of 3088 (57%).

A prior version of this report claimed "Hardened" per module in prose, with no
numbers; the 2026-08-14 baseline run falsified that for every module except
`types.py`. The 2026-08-14/15 burn-down (thread:sdk-coverage-arc, stages 5a–5f3)
then killed ~1,170 survivors and classified the rest; it also surfaced six real
product bugs (boundary-emission crash, fired-tick read crash, unsigned-count
mislabel, jsonl cursor pagination crash, sync_target hardcoded agreement,
plan_kind_mutation ValueError leak) — all fixed with regression tests.

## Final results (2026-08-15, post burn-down)

| Module | Surviving | Classification |
| :--- | ---: | :--- |
| `types.py` | 0 | Fully killed. |
| `target.py` | 8 | All classified (or/and-short-circuit, sorted-key-redundant, dead-dedup-guard, unreachable-without-race). |
| `declare.py` | 20 | All classified (encoding-casing, hasattr/getattr-dead, kwarg-equals-default). |
| `kind.py` | 43 | All classified (hasattr-on-NamedTuple, encoding-casing, unreachable-without-race, kwarg-equals-default). |
| `emit.py` | 65 | Classified by pattern (kwarg-equals-default, getattr-on-exception value-equal); findings: `_key_dir` dead constructor param, delta-count boundary needs engine-level fixture. Pattern arguments not individually re-verified — weakest classification depth of the set. |
| `read.py` | 447 | All classified — see the per-cluster tables below (259 cluster + 170 read_timeline + 14 sync_target + 4 _tick_as_dict). Findings: is_aggregate and/or convergence, discover-only-aggregate resolve_entity gap, preflight.store-is-None reachability, PreflightMode unobservable via SyncResult. |

Timeouts: 3. Equivalence classes are defined in the per-cluster sections below;
"finding" entries name the public-surface capability gap that blocks a killing
fixture and feed thread:sdk-coverage-arc.

## `read.py` cluster classification (2026-08-15): search_facts/read_summary/_compute_summary_stats/read_facts/read_state/_serialize_fold_item/resolve_entity/read_ticks/_serialize_fold_section/read_fact_by_id/_ensure_reader

Scope: the 261 survivors mutmut originally reported across these eleven
functions (`read_timeline` and `sync_target` are a separate cluster, tracked
elsewhere). 2 killed this pass via new tests in `test_read_mutants.py` /
`test_read_mutants_2.py`; the rest are CLASSIFIED against the taxonomy below,
each verified against `read.py` and its producers (`engine.store_reader`,
`engine.vertex_reader`, `engine.declaration`) — not asserted away.

Killed this pass (2): `_ensure_reader__mutmut_3` (mode kwarg pinned via a
`read_preflight` call-arg spy), `search_facts__mutmut_195` (bare-store
`limit=` forwarding pinned with a 3-match/limit=1 fixture).

| Function | Final survivors | Class breakdown |
| :--- | ---: | :--- |
| `search_facts` | 131 | hasattr-dead-branch 94; dead-.get-key-variant 24; payload-str-dead 6; kwarg-removal-equals-default 6; or-and-equal-operands 1 |
| `read_summary` | 37 | dead-.get-default 17; kwarg-removal-equals-default 9; unreachable-fallback-string 6; or-fallback-unreachable-in-branch 4; or-and-equal-operands 1 |
| `_compute_summary_stats` | 26 | dead-.get-default 17; isinstance-type-dead-branch 8; unused-default-value 1 |
| `read_facts` | 23 | FactPage-has-no-prev 14; kwarg-removal-equals-default 6; or-and-equal-operands 2; float-INF-case-insensitive 1 |
| `read_state` | 14 | unreachable-fallback-string 4; hasattr-dead-branch 4; getattr-default-dead 3; kwarg-removal-equals-default 2; isinstance-dict-dead-branch 1 |
| `_serialize_fold_item` | 10 | hasattr-dead-branch 10 |
| `resolve_entity` | 7 | or-and-equal-operands 2; dead-.get-default 2; finding (is_aggregate and/or) 1; finding (discover-only aggregate) 1; float-INF-case-insensitive 1 |
| `read_ticks` | 4 | float-INF-case-insensitive 2; or-and-equal-operands 1; finding (is_aggregate and/or) 1 |
| `_serialize_fold_section` | 4 | hasattr-dead-branch 4 |
| `read_fact_by_id` | 2 | or-and-equal-operands 1; finding (is_aggregate and/or) 1 |
| `_ensure_reader` | 1 | finding (preflight.store-is-None reachability) 1 |
| **Total** | **259** | |

### Class definitions (this pass)

- **hasattr-dead-branch** (established) — fact/search producers return plain
  dicts; `hasattr(m, "payload")`-style branches, and everything gated behind
  them (e.g. `_serialize_fold_item`/`_serialize_fold_section`'s
  `hasattr(item/section, "as_dict")`, `read_state`'s
  `hasattr(gen, "as_dict")` since `gen` is always a plain `{}`), are always
  False.
- **dead-.get-default** (established) — producer dicts always carry the keys
  read (`id`/`kind`/`ts`/`observer`/`origin`/`payload` on facts;
  `raw_summary["facts"]["total"|"kinds"]`, `stats["count"|"earliest"|"latest"]`
  on `reader.summary()`'s dict; `f.get("payload", {})` in `resolve_entity`'s
  aggregate loop), so `.get(key, default)` defaults never fire.
- **dead-.get-key-variant** (new, sibling of dead-.get-default) —
  `search_facts`'s `m.get("rank", 0.0)` / `m.get("snippet", "")` chain: the
  *default value* mutants are live and killed (existing `rank == 0.0` /
  `snippet == ""` pins), but the *key-string* mutants (`"rank"` →
  `"XXrankXX"`/`"RANK"`/`None`) are equivalent — real search-result dicts
  never carry a `"rank"` or `"snippet"` key at all, so any near-miss key
  still falls through to the same default.
- **payload-str-dead** (established) — `isinstance(payload, str)` is always
  False (payload arrives pre-decoded); the `contextlib.suppress(...)` /
  `json.loads(payload)` lines beneath it are dead code too.
- **kwarg-removal-equals-default** (established) — a removed/nulled
  constructor kwarg on an early-return or literal-construction site equals
  the dataclass field's own default (verified against `types.py`:
  `ReadSummary.fact_total=0`, `.tick_total=0`, `.latest_ts=None`,
  `.kinds=field(default_factory=dict)`, `.unfolded_kinds`,
  `.declaration_status=None`; `FactPageResult.items=field(default_factory=list)`,
  `.next_cursor=None`, `.prev_cursor=None`, `.truncated=False`;
  `FoldStateResult.generation=field(default_factory=dict)`,
  `.sections=field(default_factory=dict)`; `SearchResult.matches=field(default_factory=list)`,
  `.total_matches=0`; `SearchResultItem.rank=0.0`, `.snippet=""`).
- **unreachable-fallback-string** (established) — `decl_status or "unknown"`
  / `"aggregate-head"`: `load_declaration_status` never returns a falsy
  status, so the string-literal mutants on the right-hand side never fire.
- **or-fallback-unreachable-in-branch** (new) — `info.canonical_mode or
  "unknown"` *specifically inside* the normal-vertex and bare-store branches
  (not the early-return branch, which is reachable and already killed): by
  the time execution reaches these branches `info.canonical_mode` has
  already resolved to a concrete string (`"sqlite"`/`"jsonl"`), so the
  fallback literal is dead there.
- **or-and-equal-operands** (new) — `info.canonical_path or target_path` /
  `info.index_path or canonical` in every bare-store branch: for a bare
  (non-vertex) target, `probe_target` sets `canonical_path == target_path`
  (and `index_path == path` for the plain sqlite/jsonl cases reachable from
  `resolve_target`), so `or` and `and` return operands that are unequal in
  *identity* but equal in *value* — no observable difference through any
  sdk-surface assertion. (The one case where `index_path != canonical` —
  probing a derived-index sqlite file that sits beside its own `.jsonl`
  sibling — was not verified as constructible through the public sdk
  surface in this pass; flagged as a finding, not asserted equivalent,
  where it showed up as its own line item.)
- **isinstance-type-dead-branch** (new) — `_compute_summary_stats`'s
  `elif isinstance(latest_iso, (int, float))` / `elif isinstance(latest_iso, str)`
  branches: `StoreReader.fact_kind_stats` (the only real producer feeding
  this function) always returns `latest` as a `datetime`, so these branches,
  and the `contextlib.suppress(ValueError, TypeError)` / `datetime.fromisoformat`
  call beneath the `str` branch, are unreachable through the sdk surface.
- **isinstance-dict-dead-branch** (new) — `read_state`'s
  `if not isinstance(state_dict, dict): state_dict = {}`: `vertex_read`'s
  return type is always `dict[str, dict[str, Any]]`, so the branch is never
  taken and the literal it assigns is unobservable.
- **unused-default-value** (new) — `_compute_summary_stats(..., include_internal: bool = False)`:
  both call sites in `read_summary` always pass `include_internal=` explicitly;
  the parameter's own default is never relied upon through the sdk surface.
- **FactPage-has-no-prev** (established) — `getattr(page, "prev", None)` is
  always `None` for both `vertex_query_facts` and `StoreReader.query_facts`
  results, so `prev_cursor`/`prev_tok` and everything computed from
  `page.prev.fact_id or f"seq:{page.prev.seq}"` (including its `or`→`and`
  variant) are dead.
- **float-INF-case-insensitive** (established) — Python's `float()` parses
  `"inf"`/`"Inf"`/`"INF"` identically; the `until_ts=float("inf")` /
  `float("INF")` mutants are equivalent.
- **finding: is_aggregate `and`→`or`** (`read_ticks`, `read_fact_by_id`,
  `resolve_entity` — one mutant each) — `is_aggregate = decl_ast is not None
  and (decl_ast.combine is not None or decl_ast.discover is not None)`
  flipped to `or` is reachable and, in principle, observable (an ordinary
  single-store vertex would wrongly route through the aggregate branch).
  Empirically probed: `engine.vertex_reader.vertex_facts` (and, by the same
  construction, `vertex_ticks`/`vertex_fact_by_id`) treats a single
  non-aggregate vertex as a trivial one-member aggregate and returns
  identical results either way, so every fixture buildable through the sdk
  surface converges. Not asserted equivalent — flagged as a finding because
  distinguishing the two paths would require reaching past the sdk read
  contract into `vertex_reader`/store-staleness internals.
- **finding: discover-only aggregate on `resolve_entity`**
  (`resolve_entity__mutmut_15`, `decl_ast.discover is not None` →
  `... is None`) — reachable and observable in principle (a discover-only
  aggregate vertex would misroute), but no fixture exercising
  `resolve_entity` against a discover-only aggregate was built this pass;
  time-boxed out rather than asserted equivalent.
- **finding: `_ensure_reader`'s `preflight.store is not None` flip**
  (`__mutmut_6`) — `preflight.store` is `None` only when
  `engine.preflight._recover_then_open` hits its `not canonical.exists()`
  guard or one of its recovery-exception branches (`JsonlCanonicalUnsupported`,
  `JsonlCodecError`/`UnicodeDecodeError`, `sqlite3.Error`, `OSError`). A bare
  target's canonical path is guaranteed to exist by `resolve_target`'s own
  precondition, and probing a corrupt-`.jsonl` fixture through this pass's
  time budget did not reproduce a `JsonlCodecError` (the codec tolerated the
  malformed lines tried). Left as a finding rather than a verified
  equivalence claim.

No product bugs found in this cluster — every survivor traces to a
mutation of dead/equivalent code (types never seen at this call site) or a
value-equal fallback, with the four `finding` lines marked above as
genuinely open (reachable+observable, not proven equivalent, not killed).

## Running Mutation Tests

```bash
cd libs/sdk
uv run mutmut run
uv run mutmut results
uv run mutmut show <mutant-id>
```

SURVIVORS: 583 (all equivalent/finding)
