# Characterization Ledger — the loops core

- **Instrument**: `benchmarks/characterize.py`, version 1
- **Measured**: 2026-08-15, one machine, AC power, arms run back to back
- **Question**: what does the core cost, and what shape does that cost have as a store grows
- **Not**: a regression gate. See *What this ledger cannot see*.

---

## What this ledger can and cannot see

An instrument that does not state its resolution gets quoted for things it never
measured.

**It can see** complexity class — whether an operation's cost is flat or grows
with store depth — and large constant-factor gaps between layers. Those are the
failures that compound: an operation that is linear where you assumed it was
constant is invisible at 1,000 facts and fatal at 1,000,000.

**It cannot see** small differences. On its first run this instrument reported a
`+14.5%` delta on `cli_cold_version` against a `±0.6%` noise floor. Direct
re-measurement put that at `+2.6%`, with identical `import loops` cost in both
arms. Two probes whose code is byte-identical across arms (`store_append`,
`store_scan_all`) also cleared their floors. **Treat every sub-10% delta in the
comparison table as unproven.** The verdict column says where to look, not what
is true.

**It is not portable.** These are absolute numbers from one laptop. A CI
runner's numbers are not comparable to them, and neither is another machine's.
The chain is extended by re-measuring the reference arm alongside the new one in
one sitting — never by comparing a fresh arm against the digits recorded here.

---

## Method

Two git worktrees, each with its own venv, so the arms could not contaminate each
other through a shared editable install. (They would have: the repo's `.venv`
carries stale `_editable_impl_*.pth` entries across branch switches, and
`libs/sdk/src/sdk` survived as an empty namespace package, so `import sdk`
succeeded on a checkout containing no sdk at all.) The instrument was verified
byte-identical across arms by diff before every run.

Arms run sequentially, never concurrently — two arms measuring at once contend
for CPU and each ends up measuring the other.

| Arm | Branch | Commit | Role |
| :--- | :--- | :--- | :--- |
| `main-prior-to-sdk` | `perf/characterization-ledger` | `66a0cc79` | reference |
| `libs-sdk` | `perf/ledger-sdk` | `b3b2ad37` | candidate |
| `main-prior-to-sdk-repeat` | `perf/characterization-ledger` | `66a0cc79` | bracket |

Each depth band fills a fresh vertex through a **held** handle, so the cost of
opening a vertex and the cost of receiving into one can be told apart rather than
averaged into one per-op number. Read probes run before write probes so reads see
exactly the nominal depth.

Probes assert what they measured: a CLI exiting non-zero raises rather than
recording `0.0`, a search matching nothing raises rather than reporting a fast
search, a scan returning the wrong row count raises. Absence of work is not
speed — the instrument this one replaced scored a completely broken CLI as a
100% improvement.

---

## Findings

### 1. Every write re-folds the entire history

`VertexHandle.receive` commits the fact and then calls `_refresh_locked`, which
falls through to `_reconstruct` — *"full replay in `(ts, id)` order"*
(`handle.py:909`). The fast paths in `_refresh_locked` are guarded on
`not has_new_facts`, and a receive always adds a fact, so every write replays
everything before it.

This is deliberate and the reason is documented (`handle.py:1300`): a fact may
arrive with a timestamp that sorts *before* facts already folded, and it must
fold at its `(ts, id)` position rather than at the live tail. Replaying from zero
is the obviously-correct way to guarantee that.

`open_vertex` pays the same cost for the same reason. Measured directly, with
only the declaration changed:

| Declaration | depth 1,000 | depth 4,000 | growth |
| :--- | ---: | ---: | ---: |
| `note` declared with `fold` | 3.155 ms | 8.454 ms | 2.7x |
| `note` admitted undeclared | 1.475 ms | 1.835 ms | 1.2x |

Facts of an undeclared kind are skipped by reconstruction. Facts of a declared
kind are replayed every time. Fold *retention size* is not the driver —
`collect 10` and `collect 100` scale identically (7.903 ms vs 8.454 ms at depth
4,000) — it is the replay itself, not what the fold keeps. A declared loop cannot
opt out: `lang` rejects a loop with no fold declarations.

### 2. Therefore ingest is quadratic, and it is the dominant cost in the system

Because each receive is linear in depth, filling *n* facts costs O(n²). This is
not a projection — it is why the original 1k/10k/100k sweep was abandoned mid-run:
the 100k band alone was tracking to roughly 90 minutes of fill per arm.

| Layer | 1,000 | 5,000 | 20,000 | growth over 20x depth |
| :--- | ---: | ---: | ---: | ---: |
| `store_append` (raw SQLite) | 0.020 ms | 0.022 ms | 0.020 ms | **1.0x — flat** |
| `engine_receive_held` | 2.731 ms | 10.306 ms | 45.326 ms | 16.6x |
| `sdk_emit_fact` | 8.004 ms | 28.945 ms | 123.311 ms | 15.4x |

The raw store is O(1) per append and stays at 20 microseconds regardless of
depth. Everything above it is linear. At 20,000 facts a single `emit_fact` costs
**123 ms against the store's 0.022 ms** — a factor of ~5,600, widening linearly.

Extrapolating the fitted line to 100,000 facts (extrapolation, not measurement,
and it assumes linearity holds): ~225 ms per `receive`, ~610 ms per `emit_fact`,
and roughly 3 hours to ingest 100,000 facts into a single declared kind.

### 3. The read path is fine

This is the good news and it is worth stating as plainly as the bad:

| Probe | 1,000 | 5,000 | 20,000 | growth |
| :--- | ---: | ---: | ---: | ---: |
| `sdk_read_page_100` | 0.686 ms | 0.809 ms | 1.192 ms | **1.7x — near flat** |
| `sdk_read_summary` | 0.641 ms | 1.215 ms | 3.635 ms | 5.7x |
| `sdk_search` | 1.038 ms | 3.179 ms | 11.280 ms | 10.9x |

Bounded pagination barely moves across a 20x depth increase. A CLI or TUI built
on the read surface is not standing on the problem. The write path is.

### 4. The SDK's stateless surface is a constant tax, not a scaling one

`emit_fact` calls `open_vertex` internally on every invocation, so each emit pays
a full vertex open — roughly 1.5 ms at shallow depth, about 45% of a shallow
emit. That is a real cost, but it is *constant*; the scaling underneath it is the
engine's. Fixing the SDK's per-call open would not change the curve's shape.

### 5. Search is invisible unless declared and reindexed

FTS covers only kinds the declaration marks `search`, and `vertex_reindex` is its
sole writer — `receive` never maintains the index. A search against an undeclared
kind returns zero matches, quickly. The replaced benchmark searched an undeclared
kind *and discarded the result*, so it recorded a timing for a search that could
never have matched anything.

The rebuild is linear: `engine_reindex_fts` runs 3.588 → 13.872 → 59.746 ms
across the sweep (16.7x over 20x depth).

### 6. Receipt-order fold-in-place collapsed the held-handle write path — findings 1 and 2 are superseded there, and only there

Measured by `characterize-ab.yml` on PR #8 (`e017c0e8` → `72b318f7`, same
runner, A B A B A, arms committed under `ledger/ab-receipt-order-pr8/`).
`decision:design/replay-receipt-order` made fold order = receipt order, so a
new fact is a fold *suffix* and `VertexHandle` folds it onto a held checkpoint
instead of replaying history (`docs/RECEIPT_ORDER_FOLD.md`).

| Probe @ depth | base | head | delta | verdict |
| :--- | ---: | ---: | ---: | :--- |
| `engine_receive_held@1000` | 7.708 ms | 2.376 ms | **−69.2%** | above noise |
| `engine_receive_held@5000` | 29.048 ms | 3.929 ms | **−86.5%** | above noise |

The growth class is the finding: base held-receive grew 3.8x across the 5x
depth sweep (finding 2's quadratic signature); head grows 1.65x. The residue is
not the fold — it is `visible_domain_count`'s `COUNT(*)` and the witness
position resolve, both still linear-ish per refresh and named at implementation
time, not discovered after.

Two boundaries, stated as plainly as the win:

- **`sdk_emit_fact` did not move** (+1.3% / +4.7%, within or near noise). The
  SDK emit path cold-opens per call (finding 4), and a cold open's *seeding*
  replay is still the full prefix. Fold-in-place fixes every consumer that
  holds a handle; a process-per-emit consumer still pays O(n) per emit and
  O(n²) per fill. The fix for that shape is a persisted checkpoint or a
  held-session consumer — a design decision for the SDK-facing CLI rebuild,
  not a missing line in the engine.
- **`store_scan_all` improved −13% above noise**, which disqualifies it as the
  negative control it was cast as: `since()` moved from `ORDER BY ts, id` to
  `ORDER BY rowid` (natural table order, sort eliminated), so the movement has
  a mechanism and is expected. `store_append` stayed flat (−3.7% / +6.0%),
  and remains the honest control.

---

## Cost curves

### `main-prior-to-sdk` @ `66a0cc79`

| Probe | Layer | n=1,000 | n=5,000 | n=20,000 | growth |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `cli_cold_version` | cli | 61.333 | — | — | n/a |
| `store_scan_all` | store | 1.232 | 6.132 | 28.260 | 22.9x |
| `store_append` | store | 0.020 | 0.022 | 0.020 | 1.0x |
| `engine_summary` | engine | 0.097 | 0.466 | 2.068 | 21.3x |
| `engine_replay_fold` | engine | 1.919 | 9.286 | 43.418 | 22.6x |
| `engine_open_vertex_cold` | engine | 2.729 | 10.251 | 46.390 | 17.0x |
| `engine_reindex_fts` | engine | 3.588 | 13.872 | 59.746 | 16.7x |
| `engine_receive_held` | engine | 2.731 | 10.306 | 45.326 | 16.6x |

### `libs-sdk` @ `b3b2ad37`

| Probe | Layer | n=1,000 | n=5,000 | n=20,000 | growth |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `cli_cold_version` | cli | 70.224 | — | — | n/a |
| `store_scan_all` | store | 1.242 | 6.365 | 28.866 | 23.2x |
| `store_append` | store | 0.022 | 0.024 | 0.022 | 1.0x |
| `engine_summary` | engine | 0.096 | 0.461 | 2.266 | 23.7x |
| `engine_replay_fold` | engine | 1.835 | 9.449 | 44.233 | 24.1x |
| `engine_open_vertex_cold` | engine | 2.749 | 10.729 | 47.889 | 17.4x |
| `engine_reindex_fts` | engine | 3.515 | 14.245 | 60.518 | 17.2x |
| `sdk_read_summary` | sdk | 0.641 | 1.215 | 3.635 | 5.7x |
| `sdk_read_page_100` | sdk | 0.686 | 0.809 | 1.192 | 1.7x |
| `sdk_search` | sdk | 1.038 | 3.179 | 11.280 | 10.9x |
| `engine_receive_held` | engine | 2.880 | 11.345 | 53.298 | 18.5x |
| `sdk_emit_fact` | sdk | 8.004 | 28.945 | 123.311 | 15.4x |

---

## Reference vs candidate

**The sdk branch does not change the shape of anything.** Every engine probe
tracks its reference across all three bands. Read the full table via:

```bash
uv run python benchmarks/characterize.py \
    --compare benchmarks/ledger/arm-main.json benchmarks/ledger/arm-sdk.json \
    --bracket benchmarks/ledger/arm-main-bracket.json
```

One delta was worth chasing: `engine_receive_held` came back `+10.1%` at 5,000
and `+17.6%` at 20,000 — consistent in direction and magnitude across bands,
which the control probes were not. Twelve direct re-measurements at depth 5,000,
alternating arms in both orders to cancel thermal drift:

| Arm | measurements (ms) | median |
| :--- | :--- | ---: |
| `main-prior-to-sdk` | 9.377, 9.638, 9.567, 9.462, 9.544, 10.344 | 9.556 |
| `libs-sdk` | 9.502, 10.040, 10.760, 9.474, 10.444, 10.116 | 10.078 |

About 5%, holding in both orders — but the ranges overlap heavily and this is
below what the instrument can separate. **Recorded as unresolved.** The candidate
explanation is the two-line `handle.py` change on the boundary-emission path;
neither confirmed nor excluded here.

Order matters more than expected: in the first pass the sdk arm ran second every
time and climbed monotonically (9.50 → 10.04 → 10.76). Interleaving arms is not
enough — the *order* has to alternate too.

---

## Open question this raises

The invariant behind finding 1 is real: a backdated fact must fold at its
`(ts, id)` position, and appending to the tail of the fold would publish state in
arrival order. But the cost is paid on every write to buy correctness for the
rare one, and the common case is an append that sorts after everything already
folded. A left-fold over a sorted sequence only needs replay **from the insertion
point** — O(1) for an append, and for a genuinely backdated fact, replay from
where it lands rather than from zero. The handle already computes the position.

Two things to check before treating that as the answer, neither settled here:
boundary/tick firing may depend on the fold being recomputed whole, and a
partial replay would have to reproduce identical tick decisions; and `collect` is
order-sensitive but bounded, so it genuinely only needs a tail, while another
fold operator may not have that property — which would make the optimization
per-operator rather than global.

---

## The CI series

`.github/workflows/characterize.yml` records one arm per commit that lands on
main, stamped with its SHA, published to the run summary and kept as an artifact
for 90 days. It is a **recorder, not a gate** — it never fails a build on a slow
number, because a threshold on a hosted runner fires on noise and then gets
muted, which is worse than no gate at all.

What that series is good for is **shape** — the growth column, which is a ratio
within one arm on one machine and therefore machine-independent.

What it is *not* good for is comparing one arm against another, and the first
two arms proved it. `121b709f` and `0b558c43` landed on different runners
(fingerprints `c5bf9b955fce` and `7d7b461e7e2a`), and `store_append` — O(1),
byte-identical code, untouched by the merge between them — read 0.047 ms on one
and 0.024 ms on the other. Every engine probe moved −41% to −51%, which is that
same ~2.1x machine difference and nothing else. A per-commit series cannot show
progression, because every push gets a fresh machine.

### Progression comes from `characterize-ab.yml`

That workflow measures the merge base and the head of a pull request **on one
runner, in one job**, ordered A B A B A so that both arms average the same
position and linear thermal drift cancels. The head's instrument is copied into
the base worktree and diffed before anything runs, so a PR that edits the
instrument cannot end up comparing two different instruments.

The difference is stark. The same base/head pair, measured across two runners,
showed deltas of −41% to −55%; measured in one job, −3.4% to +1.8%.

That run also calibrated the instrument's floor. With two reference repeats,
`store_append` — a guaranteed control — still came out at −2.9% against a ±2.4%
floor and would have been reported. `MIN_MEANINGFUL_DELTA_PCT` is 5.0 because of
that measurement: a delta must clear both the measured floor and 5% before it is
worth a second look. Sub-5% movement on this instrument is not a signal, however
tight a given run's floor happens to look.

The A/B reports; it does not gate. Its false-positive rate on real changes is
still unmeasured, and the honest order is to accumulate runs first and gate
second.

Arms committed here carry an opaque `machine_fingerprint` rather than a hostname
and CPU model. The comparison only ever needed to answer "same machine?", and a
hash answers it without putting machine identity in a public repository.

## Reproduce

```bash
# Measure this checkout
uv run python benchmarks/characterize.py --record arm.json

# Extend the chain: re-measure the reference beside the new arm, same sitting,
# alternating order, and supply at least two repeats
uv run python benchmarks/characterize.py --compare arm-reference.json arm-new.json \
    --bracket arm-reference-repeat-1.json --bracket arm-reference-repeat-2.json
```

Comparisons are refused across instrument versions and warn across machines.
Below two repeats, every delta above the floor is labelled `candidate` — a place
to go re-measure, never a finding.
