# Bend Experiments

Proves the loops computational model works on interaction combinators.

## What this proves

The core loops cycle — Facts fold into state, a boundary fires, a Tick emits — produces identical results on two fundamentally different substrates:

1. **Python** (sequential, mutable, von Neumann machine)
2. **Bend** (parallel, immutable, interaction combinator net)

Same input, same fold, same output. The model is substrate-independent.

## Experiments

Each experiment has a Python reference (.py) and a Bend implementation (.bend) that produce the same result.

### 1. `fold_proof` — Basic fold and boundary

Six health-check facts fold into a map. When all three containers have reported, a tick emits with the sum of status values.

```
python3 experiments/bend/fold_proof.py      # => 3
bend run-rs experiments/bend/fold_proof.bend  # => Result: 3
```

**Proves:** The atomic operation — observe, accumulate, conclude — works on interaction combinators.

### 2. `multi_route` — Routing by kind

Eight facts with two kinds (health + metrics) are routed to different folds within the same vertex. Health facts upsert status per container. Metrics facts sum cpu values. Combined result returned.

```
python3 experiments/bend/multi_route.py      # => 252
bend run-rs experiments/bend/multi_route.bend  # => Result: 252
```

**Proves:** A vertex can route facts by kind to distinct fold logic — the dispatch pattern works on interaction combinators.

### 3. `boundary_reset` — Boundary fires, state resets, loop continues

Nine facts arrive in three batches. After every 3 facts, boundary fires: emit tick, reset state, keep folding. Three ticks emitted from one pass. Output encodes tick count and last payload.

```
python3 experiments/bend/boundary_reset.py      # => 3003
bend run-rs experiments/bend/boundary_reset.bend  # => Result: 3003
```

**Proves:** The LOOP in loops — not just fold once, but cycle: fold, conclude, reset, repeat. Modeled in Bend as a recursive function carrying accumulated tick state, since mutation is impossible.

### 4. `tick_composition` — Ticks become facts (nesting)

Stage 1: Fold health facts in batches of 3, emit ticks with health summary. Stage 2: Feed tick payloads into a second fold that counts how many ticks had all-healthy status.

```
python3 experiments/bend/tick_composition.py      # => 3
bend run-rs experiments/bend/tick_composition.bend  # => Result: 3
```

**Proves:** Ticks compose — output of one loop feeds as input to another. Same primitive at every level. This is the nesting property.

### 5. `parallel_fold` — Tree-structured parallel reduction

Generate 1024 health observations as a binary tree using Bend's recursive generation. Sum all values via tree fold — O(log n) depth instead of O(n). Both Python and Bend produce 512.

```
python3 experiments/bend/parallel_fold.py      # => 512
bend run-rs experiments/bend/parallel_fold.bend  # => Result: 512
```

**Proves:** Commutative folds can be tree-reduced. Bend parallelizes tree folds automatically across cores. This is the payoff: Spec properties (commutativity, associativity) aren't just mathematical decoration — they unlock automatic parallelism on interaction combinators.

## Progression

| # | Experiment | What it adds | Loops concept |
|---|---|---|---|
| 1 | `fold_proof` | Fold + boundary | Fact -> Spec.apply -> Tick |
| 2 | `multi_route` | Kind-based routing | Vertex routes by kind |
| 3 | `boundary_reset` | Cycle: fold/emit/reset | The loop in loops |
| 4 | `tick_composition` | Two-stage fold | Ticks compose (nesting) |
| 5 | `parallel_fold` | Tree reduction | Spec properties -> parallelism |

## Model mapping

| Loops concept | Python | Bend |
|---|---|---|
| Fact | `dict` with kind/container/status | `object Fact { kind, container, status }` |
| State accumulation | `dict` mutated in `for` loop | `Map` threaded through recursion |
| Fold | `for` loop calling `fold(state, fact)` | Recursive function or tree `fold` |
| Routing | `if fact["kind"] == ...` | `if facts.head.kind == ...` |
| Boundary + reset | `if count == N: reset` | Recursive call with fresh `{}` |
| Tick composition | Two sequential `for` loops | Two sequential fold functions |
| Parallel fold | `tree_sum(arr, lo, hi)` | `bend` to generate tree + `fold` to reduce |

## How to run all

```bash
# Python
python3 experiments/bend/fold_proof.py         # => 3
python3 experiments/bend/multi_route.py        # => 252
python3 experiments/bend/boundary_reset.py     # => 3003
python3 experiments/bend/tick_composition.py   # => 3
python3 experiments/bend/parallel_fold.py      # => 512

# Bend (Rust interpreter)
bend run-rs experiments/bend/fold_proof.bend         # => Result: 3
bend run-rs experiments/bend/multi_route.bend        # => Result: 252
bend run-rs experiments/bend/boundary_reset.bend     # => Result: 3003
bend run-rs experiments/bend/tick_composition.bend   # => Result: 3
bend run-rs experiments/bend/parallel_fold.bend      # => Result: 512

# Bend (C interpreter, faster)
bend run-c experiments/bend/fold_proof.bend          # => Result: 3
bend run-c experiments/bend/multi_route.bend         # => Result: 252
bend run-c experiments/bend/boundary_reset.bend      # => Result: 3003
bend run-c experiments/bend/tick_composition.bend    # => Result: 3
bend run-c experiments/bend/parallel_fold.bend       # => Result: 512
```

## Why this matters

Bend compiles to interaction combinator nets (HVM2). Every experiment producing the same result on both substrates means the loops model's operations — observe, accumulate, route, conclude, cycle, compose, parallelize — are not tied to sequential execution. They work on a massively parallel graph reduction substrate.

The progression reveals a deeper point: the model's algebraic properties (commutativity of folds, compositionality of ticks) aren't just mathematical aesthetics. On interaction combinators, they directly translate to parallelism. Spec describes *what* to fold; the substrate decides *how* to schedule it.
