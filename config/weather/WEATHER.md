# Weather — vertex development journal

A real weather monitoring domain built incrementally to exercise the full
.vertex vocabulary. Each stage adds primitives, and this document captures
what each addition reveals about the DSL and runtime.

## Stage 1: One source, one kind, one fold

**Files**: `weather.vertex`, `sources/current.loop`

The simplest useful vertex. One source (Open-Meteo API for Austin, TX),
one kind (`reading`), one fold (`collect 48` — keep last 48 readings,
one per 30min = 24 hours of history).

```
weather.vertex          current.loop
  reading                 curl → json
    collect 48              project → flat fields
    count inc               kind "reading"
    updated latest          origin "open-meteo"
```

**What this exercises**:
- Instance vertex with store
- Single source path reference
- `format "json"` (whole response as one record)
- `parse { project { field path="nested.path" } }` for flattening
- `origin` declaration on source
- Three fold ops: collect, count, latest

**What this revealed**:

1. **`project` syntax is `field path="json.path"`, not `"field" "path"`.**
   The KDL property syntax (`name path="value"`) is more verbose than a
   bare mapping but consistent with how KDL works. First real use of
   `project` against a live API — the dot-path notation (`current.temperature_2m`)
   works cleanly for one level of nesting.

2. **Generic lens renders `temp_f: humidity` (first two fields).**
   The collect fold stores the full payload; the generic lens picks the
   first field as label and second as value for MINIMAL/SUMMARY. For weather
   data this produces "65.0: 83" — technically correct, not meaningful.
   This is the exact gap custom lenses fill: domain meaning requires domain
   rendering. The generic lens is adequate for orientation ("there's one
   reading with these values") but not for comprehension.

3. **`collect 48` is a design choice.** We could have used `items "by" "observed_at"`
   (upsert per timestamp) but readings come every 15min from the API, so
   upsert would give us one reading forever (always the latest). Collect
   preserves history — the fold IS the time series buffer. The choice between
   by-key and collect is the choice between "what's current" and "what happened."

4. **No cadence yet.** `current.loop` has no `every` declaration, so
   `loops sync weather` runs it unconditionally (Cadence.always()). Adding
   `every "30m"` would make it skip if the last reading is recent. But for
   Stage 1, manual sync is fine — it's one curl.

**Try it**:
```bash
loops sync weather --force     # fetch current conditions
loops read weather             # MINIMAL: "65.0: 83"
loops read weather -v          # DETAILED: all fields
loops read weather -vv         # FULL: + _id, _ts, _observer, _origin
loops test sources/current.loop -v  # preview without storing
```

## Stage 2: Named folds, boundary design, uniform vocabulary

**Files**: `weather.vertex` (updated), `sources/current.loop` (unchanged)

Renamed fold targets from generic `items`/`count`/`updated` to
`last24h`/`total`/`latest_at`. No code change needed — only one
production site references "items" by name and it falls back.

**What this revealed**:

1. **Named fold targets are the interface for boundaries.**
   `condition "high" ">=" 80` references a fold target by name. The name
   isn't cosmetic — it's the binding point between fold state and boundary
   conditions. `items` can't serve this role.

2. **Loop-level boundaries dissolve `when`.**
   A boundary inside the `reading` block already knows it fires on reading
   facts. `when="reading"` is redundant from nesting. Only vertex-level
   boundaries need `when` (to specify which kind).

3. **Uniform vertex vocabulary.**
   Every declaration type follows the same pattern:
   `plural-container { named-item { config } }`. Sources already work this
   way (inline/path/template). `fold → folds`, `boundary → boundaries`
   extends the pattern. The .vertex becomes a uniform container.

4. **Bidirectional factoring.**
   Everything inline in .vertex must be expressible as an external file,
   and vice versa. Start inline, extract when complexity justifies. Today
   inline sources can't express the full .loop vocabulary — that's the
   concrete gap to close first.

5. **Predicate boundaries are genuinely new.**
   `BoundaryCondition(target, op, value)` can't dissolve into existing
   primitives. But the fold state IS accessible at boundary-check time
   (fold runs before boundary check in vertex.py). Minimal extension:
   one dataclass, one eval function, wired at the existing check point.
