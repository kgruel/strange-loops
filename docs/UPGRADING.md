# Upgrading

Release-coupled upgrade notes for the `strange-loops` package (`sl` / `loops`).
Newest first. Read the sections between the version you are on and the version
you are moving to.

Upgrade the package the usual way:

```bash
uv tool upgrade strange-loops     # or: pip install -U strange-loops
```

---

## Unreleased — CLI honesty wave

*(Version header stamped at release. Behavior deltas below are deliberate
breaking changes: every one replaces a lying success with an honest failure.)*

### Breaking: error paths now exit nonzero with errors on stderr

If a script parses stdout or checks `$?` on these invocations, it was being
lied to before and will now see the failure:

- `sl ls <unknown-vertex>` — was: error text on **stdout**, exit **0**. Now:
  error + did-you-mean suggestions on stderr, exit 1.
- `sl ls <vertex> --kind <undeclared>` — was: a plausible empty section, exit
  0. Now: the same undeclared-kind error `sl read` gives (byte-identical),
  exit 2. `--key` no longer changes the answer.
- Bare `sl ls` / `sl store` with no config root — was: error on stdout, exit
  1. Now: same message, **stderr**, exit 1.
- `sl cite` / `sl emit <v> cite` with refs that all fail to resolve — was:
  WARN + an empty cite stored, exit 0. Now: refuses with exit 2, **nothing
  stored**. This includes zero-address cites (`message=` only), malformed
  tokens (`ref=:x`, `ref=kind:`, prose, bare separator-less keys), and
  addresses supplied in non-ref fields (a resolvable address in `-m` no
  longer rescues a cite). Cites whose refs are valid-but-undeclared addresses
  (inert pins, e.g. `nosuchkind:zzz`) still store as provenance-only;
  malformed tokens alongside a storing cite WARN and stay raw in the payload.

### New: `sl read --status <value>`

Payload-equality filter on the fold row (`--status open`, comma-OR
`--status open,parked`), composable with `--kind`/`--key`. Honesty rules:
if **no** fetched kind carries a status field the command refuses (exit 2)
rather than rendering a plausible empty; mixed fetches note the statusless
kinds on stderr and filter the rest; a status-bearing kind with no matching
rows is an honest empty at exit 0. Custom-lens, live/interactive, windowed
`--facts`, and `--ticks` reads refuse the flag rather than ignoring it.

### New: `sl cite [vertex] REF...`

Verb-first cite gains a vertex slot (parity with `emit`): first positional is
the vertex iff it resolves as one. The no-vertex form keeps working with
emit-parity local resolution.

### Also

- `sl orient` gains a reconcile-staleness line: `last reconcile: Nd ago`
  (`— RECONCILE OVERDUE` past 10d, from the newest `reconcile-*` thread), or
  `no reconcile on record`.
- The FTS staleness hint now names its target: `run \`sl store reindex
  <vertex>\`` — the bare form it used to suggest just refuses.

---

## 0.10.0 (2026-08-12) — JSONL-canonical store

### You don't have to migrate

`.db`-canonical stores remain fully supported. `loops init` still declares a
`.db`, existing vertices behave exactly as they did on 0.9.0, and `sl store
verify` prints the same rows and exits 0. The JSONL flip below is opt-in, per
vertex, and reversible.

### The flip, in three steps

Why: the log becomes a diffable, git-trackable text artifact, and the sqlite
file drops to a derived index you can lose without losing anything.

```bash
# 1. Export the log beside the store (read-only on the source)
sl store export <vertex>            # writes <store>.jsonl next to the .db

# 2. Edit the vertex declaration — the extension IS the mode switch
#    store "data/name.db"    ->    store "data/name.jsonl"

# 3. Read once. The existing .db is rebuilt in place as the derived index.
sl read <vertex>
```

Nothing to delete. The first read after the flip finds an index with no
consumed-offset marker, so it rebuilds the whole index from the log into that
same `.db` file, printing a `jsonl-canonical: rebuilt N fact(s), M tick(s)`
notice.

`sl store export` also accepts a path (`sl store export ./path/to/name.vertex`)
and an explicit target as a second positional. Add `--json` for a machine
receipt (`lines` / `facts` / `ticks`).

### Verify the round-trip

```bash
# Before committing to the flip: rebuild a throwaway index from the log
sl store export <vertex> --rebuild /tmp/roundtrip.db

# After the flip
sl store verify <vertex>            # adds a `canonical` row: offset · counts · last line
sl store verify <vertex> --deep     # streams every log line against the index, O(log)
```

`--deep` re-derives the tick chain from canonical content. It refuses on a
plain `.db` store (exit 2) — one artifact has nothing to disagree with.

A lagging index reports `INDEX BEHIND THE LOG` with the fix (`loops read
<vertex>` to catch it up, or `--deep` to rule out tampering) and exits 1. That
is a location claim, not a tamper verdict.

### What changes after the flip

- `sl store absorb` (absorb-edit and absorb-genesis) and `sl store reanchor`
  **refuse** with `JsonlCanonicalUnsupported` — they would rewrite sqlite rows
  the log does not account for.
- `sl store merge` / `receive` / `rebirth` / `compact` write the `.db`
  directly. They are *detected on the next open* (the store refuses to open),
  not prevented. Do not run them on a JSONL-canonical vertex.
- The `.jsonl` is now the artifact to back up or track in git. Add `data/*.db`
  to `.gitignore`; the `.db` is disposable and rebuilds on read.
- To go back: re-point the `store` line at the `.db`.

### Breaking: custom lenses no longer receive `piped`

Affects only vertices declaring their own lens module (`lens { fold "…" }` —
see `apps/loops/src/loops/lenses/CLAUDE.md` for the lens contract). The CLI stopped passing the kwarg, so a lens with `piped: bool
= False` now always sees `False` and renders TTY-style into a pipe — it fails
silently, not loudly.

Remove `piped` from your `fold_view` / `diff_view` / `why_view` signatures and
replace every `if piped:` with `if width is None:` — a viewportless
destination is offered `width=None`, and that is now the only channel signal.

### Also in this release

- `sl read <vertex>` prints a live-edge staleness warning when the oldest
  unsealed fact is more than 7 days old: `⚠ live edge: N facts unsealed, oldest
  Nd`. A disclosure, not an error — if you emit and never seal, it appears on
  every read.
- `sl sync` status lines drop the trailing "ago" (`last run 15m, cadence 30m`).
  Cosmetic; matters if you grep it.
- `sl store verify` errors keep the `{"error": "…"}` shape under `--json`.
- Claude Code plugin (repo-distributed, not in the wheel): the manifest's
  redundant `hooks` key is gone — it had been hard-failing the manifest and
  silently unloading the plugin. Pull the repo to pick it up.

---

## 0.9.0 (2026-07-26) — consumer evidence

### Breaking: bare vertex resolution refuses when ambiguous

`sl emit`, `cite`, `read`, `close`, `seal`, `orient`, and `store ticks` used to
break a tie between multiple local instance vertices **alphabetically**. They
now refuse with exit 2.

Name the vertex explicitly:

```bash
sl emit <vertex> <kind> field=value
sl read <vertex>
sl close <vertex> <kind> <name>
```

Or collapse the ambiguity: an explicit `.loops/.vertex` wins outright and is
never ambiguous. Repos with a single instance vertex — or one instance plus
aggregation vertices — are unaffected; aggregations don't count.

### Run reindex once

Reads no longer build or refresh the FTS index. `sl store reindex` is the sole
writer; until you run it, `--match` falls back to a substring scan for kinds
whose index is missing or stale (results still come back, with the gap
disclosed).

```bash
sl store reindex <vertex>          # add --json for a machine receipt
```

Re-run it whenever a read discloses a stale index and after editing a kind's
`search` declaration. The target must be the `.vertex` (name or path), not the
raw `.db`. Aggregates recurse per child. Because reindex is a full
drop-and-rebuild against current declarations, a newly declared `search` field
becomes searchable over facts written before the declaration existed.

### Opt-in: `lifecycle` declaration

A kind can declare which payload field carries its status and which values are
active; entities outside that set are hidden from the **default fold view**
only.

```kdl
lifecycle "status" active="open,in-progress"
```

Exactly one positional field name and a non-empty `active=` set — anything else
is a load error. After adopting, `sl read <vertex> --all` (or an explicit
`status=<value>` predicate) shows the hidden entities. Inbound salience,
`--refs` reachability, `--facts` history, and `--review` are unaffected.

### Also in this release

- `sl read <vertex> --review` — deterministic, diffable JSON snapshot of folded
  state. Composes with `--kind`/`--key`/`--at`/`--as-of`; refuses every other
  flag (rc 2) rather than dropping it silently.
- `sl read --lens graph --edge <predicate>` narrows the graph cut to selected
  predicates (comma-OR). Graph output now labels hops with their predicate,
  reports an SCC census, and splits the old single `dangling` number into
  `dangling` / `filter_excluded` / `keyless` — expect dangling counts to fall
  sharply.
- `sl read --json` gains a top-level `cut` key (seal-cut provenance). Additive.
- `--refs` walks every ref the graph counts as an edge, so its output can be
  larger than before; slash-form refs that previously reported nothing are now
  walked.
- `--key` no longer alters what the fold claims (it used to drop fields added
  since the filter was written).
- `--facts` never hides — the lifecycle projection is fold-view only.

---

## 0.8.1 (2026-07-18) and 0.8.0 (2026-07-18) — no action required

- **0.8.1** — packaging only: the `painted` cap widens to `<0.14`. No code
  changed.
- **0.8.0** — additive temporal cursor on the fold read: `sl read VERTEX --at
  <address>`, `--as-of <ts>`, `--diff A..B`. No store, config, or output
  changes. Note the pin: 0.8.0 still requires `painted>=0.12.1,<0.13`; if your
  environment needs painted 0.13, install 0.8.1 instead. If you maintain a
  custom composition lens with its own `fold_view` fetch, it must declare
  `at=`/`as_of=` params (or `**kwargs`) before you pass the new flags — the CLI
  refuses loudly (exit 2) rather than answering at head.

---

## 0.7.0 (2026-07-16) — store-backed declarations

### Breaking: the `sloop` entry point is gone

Replace `sloop …` with `sl …` (or `loops …`) in scripts, aliases, cron entries,
and editor tasks. If a stale shim survives the upgrade:

```bash
uv tool install strange-loops --force     # or: pip install --force-reinstall strange-loops
```

### Breaking: temporal flags on a folded read now refuse

`sl read <vertex> --since …` / `--id …` without `--facts` or `--ticks` used to
exit 0 rendering head state. It now refuses with a non-zero exit. Add the mode
flag the query needs:

```bash
sl read <vertex> --facts --since 7d      # event history
sl read <vertex> --ticks --since 7d      # tick windows
```

### Breaking: `$NAME` param values resolve from the environment

In `.loop`/`.vertex` template params, a value that is exactly `$NAME` is now
environment indirection resolved at compile time. An unset variable is a hard
compile error; a **set** one substitutes silently, so a param that was
literally the text `$USER` now compiles to that user's name.

```bash
grep -rn '=\$' ~/.config/loops .loops --include='*.loop' --include='*.vertex'
```

For values that must stay literal, double the dollar: `$$NAME`. For intended
indirection, export the variable before running `sl`. Partial interpolation
inside a longer string is not supported and is left untouched.

### Opt-in: store-backed declarations (`sl store absorb`)

A store can hold its own vertex declaration as signed history. Nothing changes
until you run the genesis ceremony.

```bash
sl store absorb <vertex> -n     # dry-run: what would be absorbed
sl store absorb <vertex>        # the genesis ceremony (requires a signing key)
```

An unsigned absorb refuses with exit 2 — resolve your observer key first (`sl
whoami`). Afterwards the store, not the `.vertex` file, is the authority, and
your edit loop changes: editing the file no longer takes effect on its own,
re-run `sl store absorb` to re-emit changed subjects (`-n` shows which diverge;
nothing is auto-absorbed). Absorb also pins referenced `.loop`/params files by
content hash, so editing a pinned source afterwards makes runs refuse with "has
drifted from its declaration pin" — re-absorb to clear. If the store already
contains a genesis row it did not mint (a merged foreign store), claim identity
explicitly with `sl store adopt <vertex>`.

### Regenerate your shell completion

Completion now covers `sl` as well as `loops`, plus vertex-name / `--lens` /
`--kind` / `--key` completers. Installed glue is stale.

```bash
loops completion zsh > "${fpath[1]}/_loops"
exec zsh
```

The regenerated first line is `#compdef loops sl` — that is what makes `sl
<TAB>` complete instead of falling back to filename completion.

### Also in this release

- New `--as-of <duration|epoch|ISO>` on temporal reads (`--facts`/`--ticks`),
  which (once a store has absorbed its declarations) rewinds the ontology to
  the same anchor. `--since` composes as the lower bound. Head-only surfaces
  never rewind.
- The `painted` floor moves to `>=0.12.1,<0.13`, pulled in automatically.
  Piped output now takes its width from painted's native `width=None` offer —
  expect wrapping and column widths of piped output to shift.
- `sl emit` gained `--plain`; it no longer prints a `stored:` receipt when the
  engine refused the write (prints `refused: …`, exits 2).
- The `_decl.*` kind prefix is reserved: validation errors on it, `sl emit`
  refuses it, and those rows are excluded from read surfaces.
- Opening an existing 0.6.0 store is unchanged — no schema migration on read or
  emit. The new `store_meta` table is created only inside the opt-in
  ceremonies, so a user who never absorbs keeps a byte-compatible store.

---

## 0.6.0 (2026-07-11) — the static-honest wave

No CLI verbs, flags, config keys, or store formats were removed or changed.

### Opt-in: declared typed edges

An existing payload field carrying an entity address can be lifted into the
graph by declaring it on its kind. Read-time projection: retroactive over all
historical facts, no re-emit, no store rewrite.

```kdl
loops {
  decision {
    fold { items "by" "topic" }
    edge "stakeholder" targets="person"
  }
}
```

Then `sl read <vertex> --refs` and `-v` show the edges with predicate labels
and inbound counts. `sl read <vertex> --lens reconcile` lists undeclared
address-shaped fields as candidates. Semantics are overlay/last-set-wins
(`field=a,b` is a multi-valued set, `field=` clears) — unlike `ref=`, which
stays the one union edge. Undeclared fields keep working exactly as before.

### Opt-in: tick-signing backfill for pre-signing-era vertices

A vertex created before the signing era (or bootstrapped only via `loops add <v>
observer <human>/<agent> --keygen`) has no flat self-observer key, so its ticks
sealed **silently unsigned**.

```bash
loops add <vertex> observer <name> --keygen     # or re-run: loops init <name>
sl orient <vertex>                              # warns about undeclared observers
```

This mints `.loops/keys/ed25519.key`, gitignores the keys dir, and splices the
public key into the vertex's `observers` block, backfilling an existing keyless
stem node. Existing facts and ticks are untouched — only future seals become
signed.

### Behavior worth knowing

- **A vertex declaring more than one vertex-level `boundary` now arms every
  declared trigger.** Previously last-declaration-wins silently dropped all but
  the final one, so such a vertex will seal more often with no config change.
- Read output looks different on a terminal: a shared static grammar (salience
  rail, header card) across fold/stream/ticks, with two registers keyed on the
  channel. Piped bytes were held golden-stable, so scripts are unaffected.
- `sl ls <vertex> --kind NAME` changed meaning: it now descends into that kind
  and lists its entries one level down, rather than narrowing the declarations
  view to one entry. `--key PREFIX/` drills a namespace, `-1` gives terse names
  for scripting. The positional form still works.
- An emit-time `ref=` that resolves nowhere is persisted as a typed unresolved
  pin instead of being dropped; the warning text changed accordingly.
- New: `sl orient <vertex>`, `--lens confluence`, `--lens graph`, `--lens
  horizon`, `sl read <vertex> <kind>/<key> --why`. `sl completion <shell>`
  works now (it previously errored).
- `sl … | head` exits cleanly (status 141) instead of a BrokenPipeError
  traceback.
- The `painted` floor moves to `>=0.10.0,<0.11`, resolved automatically.

---

## 0.5.0 (2026-06-28) — the structured-surface read wave

### Breaking: `sl read --diff` removed

The synthesized field-delta render (`status: open → refined`) is gone. Use the
fact-history event stream instead; there is no flag that restores the delta
render.

```bash
sl read <vertex> --kind K --key <key> --facts
```

### Breaking: content search on `sl stream` removed

The first positional to `stream` is a vertex name only — no search-query
fallback, and the second query positional is gone.

```bash
sl read <vertex> --match <query>      # was: sl stream <vertex> <query>
```

`stream` keeps `[vertex] --kind --since --id`.

### Breaking: `sl read --json` changed shape

It now emits the structured `Surface` encoding — a dict with top-level
`vertex`, `rows`, `schema`, `unfolded`, `source_facts`, `window` — instead of a
raw dump of the fetched FoldState. It also implies `--static`.

Read the row list from the `rows` key (each row addressed with
kind/key/payload/salience). There is no flag to restore the old encoding.

### Breaking: `sl read --max-chars` / `--max-lines` removed

Invocations using them now fail with an unrecognized-argument error. Drop them
and truncate downstream (`| head -n N`), or bound output natively with the zoom
levels (`-q` / `-v` / `-vv`) and `--limit N` / `--last N`.

### Also in this release

- **Plain output is the default whenever stdout is not a TTY**, or when
  `NO_COLOR` is set. Scripts that piped and stripped ANSI now see clean text
  without doing so.
- Emitting with an undeclared observer no longer hard-refuses — it WARNs and
  stores the fact. It still refuses under `--strict` or a vertex-level `strict
  true`. Capability-gated refusals remain hard.
  `sl emit … --declare-observer` prints the `observers { … }` KDL snippet and
  the file to paste it into (print, never write).
- New read query grammar: `--match/--grep`, `--full`, `--fields a,b`,
  `--limit N`, `--last N`, `--count`, `--by FIELD`, comma-OR `--key`, and bare
  `field=value` row predicates. Inert on custom-lens vertices and under
  `--lens`, with a stderr note when a transform is dropped that way.
- Entity refs in the canonical `kind:key` (colon) form now resolve at emit time
  and count toward inbound salience — previously only the slash form did.
  Existing stores are not rewritten; only new emits resolve.
- `sl emit` with an explicit `message=` now wins over a trailing bareword
  message (previously the bareword silently clobbered it).
- New: `sl --version`, `sl store ticks`, `sl store stats`. `sl store verify`
  output is rebuilt into three labeled axes — chain, coverage, authorship.
- Zoom flags (`-q`/`-v`) and mode flags (`-i`/`--static`/`--live`) are now
  mutually exclusive; passing two of a group errors instead of silently
  picking one.
- The `painted` floor moves to `>=0.4.1,<0.5`.

---

## 0.4.0 (2026-06-14) — federated attestation substrate

Your existing `.db` migrates itself on first open — new chain and signature
columns are added by `ALTER TABLE`. No dump/reload, no manual step. No verbs or
flags a 0.3.1 user actually had were removed.

### Breaking: fold upsert merges instead of replacing

Re-emitting a fact with the same fold key (`sl emit project thread name=x
status=resolved`) now **overlays** onto the existing entry: fields you don't
re-supply are preserved instead of dropped. Any workflow relying on
omission-clears-the-field now silently keeps stale values.

No action to keep emitting. To change a field, re-emit it with a new value. To
blank one, re-emit with an empty value (`sl emit <vertex> <kind> name=x
notes=`), which sets it to the empty string — it overwrites to `""`, it does
not remove the key; 0.4.0 has no unset mechanism. Audit any script that
re-emitted partial payloads expecting the old entry to be discarded.

### Opt-in: adopt signing

0.4.0 adds Ed25519 tick and per-observer fact signatures, tamper-evident tick
hash chains, and the `sl seal` boundary verb. A store upgraded from 0.3.1 has
no keys and no chain, and keeps working unsigned — an honest pre-signature era.
Adopting is a deliberate ceremony:

```bash
loops init                                       # idempotent; mints .loops/keys/ed25519.key
loops add <vertex> observer <NAME> --keygen      # additional observers
sl store verify [target] [-v] [--json]
```

To use `sl seal`, add a `boundary when="seal"` declaration to the `.vertex` —
`seal` refuses on a vertex that declares none.

**Consequence once adopted:** after the first signed and chained tick exists,
running seal/close/emit-with-a-boundary *without* the key present fails with
`UnsignedTickInSignedEra` (exit 1 — facts are stored, the tick is deferred).
Keep `.loops/keys/ed25519.key` present, or re-seal once keyed.

### Optional: ULID id migration

Only if your store predates the ULID revert (ids emitted roughly 2026-03-15 to
05-16 are hex uuid4 and sort above every ULID). 0.4.0 already fixed the
practical symptoms by ordering folds and reads by `(ts, id)` and walking the
chain in append order, so skipping this is safe.

```bash
sl store rebirth <source> <target> --rule ulid-migration
sl store rebirth <source> <target> --check       # verify the reconstruction
# then point the vertex's `store` locator at the new file
```

### Also in this release

- `sl read --refs` output changed shape: it no longer filters the item list
  down to referencing items — it renders all items plus a separate `## REFS`
  section. Anything parsing that output needs re-checking.
- `loops add` / `rm` / `ls` now edit the same local `.loops/<name>.vertex` the
  read and emit verbs operate on. Previously they could silently edit the
  global config-level template — if you have same-named global and local
  vertices, these commands now write to a different file than before.
- New read-path grammar on `sl read`: positional `<kind>/<key>`, `--key
  <prefix>/` prefix scan, `--diff`, `--refs [N]`.
- New verbs, all additive: `sl seal`, `sl store verify|rebirth|reanchor`,
  declarative `loops add|rm <vertex> kind|observer|combine|row`, `loops ls
  <vertex>`. `sl emit` gains `--stdin FIELD` and `--file FIELD=PATH`.
- Folds are now deterministic and merge-order-independent: rows order by
  `(ts, id)`, canonical bytes are JCS/RFC 8785, and wall-clock fallbacks are
  gone — `merge(A,B)` and `merge(B,A)` re-fold identically.
- Malformed payloads are counted, not coerced or crashed: they land in a
  `{target}_rejected` counter visible in the fold. CLI-emitted facts are
  unaffected.
- The `sqlite-ulid` C extension is no longer required or loaded; dependencies
  move to `python-ulid>=3.0`, `rfc8785>=0.1.4`, and `painted>=0.2.0,<0.3`.
- `reanchor` and store-path refusals print a one-line error instead of a
  traceback.

<!--
UNVERIFIED — maintainer review needed. Miner-flagged uncertainties, kept out of
the visible doc.

0.10.0
- PARTIALLY DISCHARGED (maintainer, 2026-08-12): the monorepo's own project
  store — 111 MB, tick-sealed, signed era plus pre-0.4.0 unsigned history —
  went through the export/flip ceremony at 0.10.0 S4 and runs JSONL-canonical
  daily. The codec's NaN/Infinity/null-signature refusals (CHANGELOG S1)
  remain untested against a store that actually contains such rows.
- Whether the sqlite→JSONL flip is safe for a vertex reached through a
  `combine` block. The resolver follows combine → first constituent with a
  store, but a combine-declared vertex with a flipped constituent was not
  exercised.

0.9.0
- Whether an FTS index carried over from 0.8.1 is usable at all after upgrade.
  `vertex_reindex` DROPs and recreates `fts_state`, and coverage checks a
  declaration fingerprint pre-0.9.0 indexes do not carry, so an existing index
  most likely certifies stale until one reindex — not confirmed against a real
  0.8.1 store.
- No dependency-floor change was found for 0.9.0 (repo diff shows only the
  version bump); the published wheel's pinned floor was not separately checked.

0.8.0
- CHANGELOG bills `VertexHandle` as a headline feature, but it is an in-process
  Python API with no CLI surface in 0.8.0. No user action; the release notes'
  framing may suggest otherwise.
- Golden fixtures were added for many render paths; output should be
  byte-stable, but this was verified by diff inspection, not by running 0.7.0
  and 0.8.0 side by side.

0.8.1
- Rendering could shift for users whose widened cap pulls in painted 0.13, but
  nothing in the release selects 0.13 surface. Any difference comes from
  painted's own release.

0.7.0
- Whether upgrading in place actually removes the `sloop` shim from an existing
  tool venv, or leaves a dangling script — depends on the installer, not the
  diff. The force-reinstall is safe either way.
- `loops completion <shell>` may also support an `--install` flag; the only
  evidence in the v0.7.0 tree is that it prints glue to stdout. The observed
  `--install` came from a newer installed CLI. The redirect form documented
  above is what 0.7.0 provably supports.
- Rendering deltas from the painted 0.10 → 0.12.1 jump beyond the piped-width
  change: goldens shifted 2–5 lines, but the visible before/after per lens was
  not reconstructed.

0.6.0
- Whether the painted floor bump can break anyone in practice: it only bites if
  painted is pinned below 0.10 in the same environment (a shared venv, not
  `uv tool install`). No such supported setup was confirmed.
- Whether the multi-boundary fix changes sealing frequency for any real user
  config depends on whether they declared two or more vertex-level `boundary`
  nodes. The semantics change is proven; the affected population is not.
- The `sl ls` reshape spans a lot of new output structure; the flag surface is
  additive/back-compatible, but not every rendered section was diffed — a
  script parsing the old TTY `ls` layout may need adjusting.

0.5.0
- Whether anyone actually had `--max-chars`/`--max-lines` in scripts: they were
  registered in 0.4.0 but never documented in the cheatsheet, so the break may
  be theoretical.
- Whether the `--json` shape change affects vertices with custom lenses
  (identity, comms, session): the dispatch code keeps a legacy raw-JSON path
  for non-FoldState shapes, so those may be unchanged — not executed to compare.
- Facts emitted before 0.5.0 with `ref=kind:key` still carry unresolved refs in
  existing stores. No backfill/re-resolve verb appeared in the diff.
- If you pinned `painted` yourself to `<0.4` alongside strange-loops, the new
  floor conflicts at resolve time; no documented workflow doing this was found.

0.4.0
- `sl store reanchor <vertex>` is documented as the migration for "JCS canon
  migration invalidates pre-existing chains" but no case was constructible
  where a 0.3.1 store needs it — v0.3.1's ticks table has no chain or signature
  columns. It appears to matter only for unreleased mid-development chain eras.
  Not documented above for that reason; say the word if it should be.
- painted 0.1.1 → 0.2.0 is claimed drop-in with zero golden drift; rendering
  was not verified byte-for-byte. Custom lenses importing painted APIs directly
  are exposed to painted's own 0.2.0 changes.
- The plain `loops store <file>` inspection view's output format was not diffed
  against 0.3.1.
-->
