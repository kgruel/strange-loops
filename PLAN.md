# PLAN: Loop Pipeline Formalization

The implicit pipeline: **Peer → Fact → Vertex → Projection → state → Surface → emit → Fact**

This document maps each stage and identifies where each step happens in code.

---

## Pipeline Stages

### Stage 1: Observation (Peer → Fact)

**Question answered:** *Who observed what?*

**Where it happens:**
- `Surface.emit(kind, **data)` — `libs/cells/src/cells/app.py:113-116`
- `Fact.of(kind, **data)` — `libs/facts/src/facts/fact.py:38-45`

**Contract:**
- Input: A Peer with identity, a kind string, payload data
- Output: Fact(kind, ts, payload)
- Peer's `potential` gates what kinds can be emitted

**Current gap:** The Peer is not explicit in the pipeline. `Surface.emit()` doesn't require a Peer — it just calls `on_emit(kind, data)`. Peer enforcement happens at the composition layer (e.g., `review.py:289-292` checks `peer.potential`).

**Who is responsible:** The composition point (experiment/app) bridges Peer → Fact. The Peer is passed through payload (`{**data, "peer": self.peer.name}`).

---

### Stage 2: Ingress (Fact → Vertex)

**Question answered:** *Where does this fact go?*

**Where it happens:**
- `Vertex.receive(kind, payload)` — `libs/ticks/src/ticks/vertex.py:97-127`

**Contract:**
- Input: kind string, payload dict
- Output: Tick | None (if boundary fires)
- Side effects:
  - Appends to Store if attached (line 108-109)
  - Routes to matching fold engine (line 110-112)

**Key behavior:**
- Unregistered kinds pass through to store but don't fold (line 110-112)
- Kind-based routing is explicit via `register()` — no implicit dispatch
- Store append happens *before* routing (persistence first)

---

### Stage 3: Reduction (Vertex → Projection → state)

**Question answered:** *How does state accumulate?*

**Where it happens:**
- `Projection.fold_one(event)` — `libs/ticks/src/ticks/projection.py:66-76`
- Called by `Vertex.receive()` at line 112

**Contract:**
- Input: Current state, event payload
- Output: New state (via `apply()`)
- Side effects: Bumps `version` on state change, increments `cursor`

**The fold:**
```python
new_state = self.apply(self._state, event)  # pure
if new_state is not self._state:
    self._state = new_state
    self._version += 1
```

**Shape's role:** Shape declares the fold contract but experiments define their own fold functions and pass to `Vertex.register()`. Shape.apply() exists but isn't wired through Vertex currently.

---

### Stage 4: Boundary Check (state → Tick?)

**Question answered:** *Is this cycle complete?*

**Where it happens:**
- `Vertex.receive()` — `libs/ticks/src/ticks/vertex.py:114-127`

**Contract:**
- Input: The incoming kind, the fold engine's boundary config
- Output: Tick if boundary fires, None otherwise
- Side effects: Resets engine to initial state if `reset=True`

**Boundary mechanics:**
```python
# boundary_map: boundary_kind → fold_kind
fold_kind = self._boundary_map.get(kind)  # line 115
if fold_kind is None:
    return None
# ... create Tick from engine state, optionally reset
```

**Key insight:** Boundaries are *separate kinds*. The fold kind ("ack") and boundary kind ("review.complete") are distinct. A sentinel fact fires the boundary, not the data fact.

---

### Stage 5: Tick Emission (state → Tick)

**Question answered:** *What's the cycle's output?*

**Where it happens:**
- `Vertex.receive()` creates Tick — `libs/ticks/src/ticks/vertex.py:119-124`
- `Vertex.tick()` for manual snapshot — `libs/ticks/src/ticks/vertex.py:129-137`

**Contract:**
- Input: Engine state at boundary moment
- Output: Tick(name, ts, payload, origin)
- Tick's `origin` identifies the producing vertex

**Two paths:**
1. **Automatic:** `receive()` returns Tick when boundary kind arrives
2. **Manual:** `tick(name, ts)` snapshots all engines (not boundary-triggered)

---

### Stage 6: Routing (Tick → downstream)

**Question answered:** *Where does the tick go next?*

**Where it happens:**
- Composition layer (experiments)
- `Stream.emit(tick)` — `libs/ticks/src/ticks/stream.py:44-50`

**Contract (Stream):**
- Input: Tick
- Output: Fan-out to all tapped consumers
- Consumers implement `async consume(event)` protocol

**Current implementations:**
- `cascade.py:229-231` — `tick_stream.emit(tick)` routes to `SummaryConsumer`
- `review.py:303-310` — Direct storage in `review_ticks` list, no Stream

**Key insight:** Tick routing is a composition concern. The Vertex doesn't know where its Ticks go. The caller decides (store them, stream them, both).

---

### Stage 7: Rendering (state → Surface → observer)

**Question answered:** *What does the observer see?*

**Where it happens:**
- `Surface.render()` — `libs/cells/src/cells/app.py:107-108` (override point)
- `Surface._flush()` — `libs/cells/src/cells/app.py:161-169`

**Contract:**
- Input: State (read from `vertex.state(kind)`)
- Output: Terminal cells via Buffer
- The Surface doesn't own state — it reads from Vertex

**Data flow:**
```
Vertex.state(kind) → render() reads state → Block/Buffer → terminal
```

---

### Stage 8: Interaction (observer → Surface → Fact)

**Question answered:** *What did the observer do?*

**Where it happens:**
- `Surface.on_key(key)` — `libs/cells/src/cells/app.py:110-111` (override point)
- `Surface.emit(kind, **data)` — `libs/cells/src/cells/app.py:113-116`

**Contract:**
- Input: Raw keypress
- Output: Fact via `on_emit` callback

**The loop closes:**
```
keypress → on_key() → emit("focus", index=n) → on_emit → vertex.receive()
```

---

## Summary Table

| Stage | Question | Where | Input | Output |
|-------|----------|-------|-------|--------|
| 1. Observation | Who observed? | `Surface.emit()` | Peer + kind + data | Fact |
| 2. Ingress | Where does it go? | `Vertex.receive()` | kind + payload | routing + storage |
| 3. Reduction | How does state fold? | `Projection.fold_one()` | state + event | new state |
| 4. Boundary | Cycle complete? | `Vertex.receive()` | kind + boundary config | Tick or None |
| 5. Emission | What's the output? | `Vertex.receive()` | engine state | Tick(name, ts, payload, origin) |
| 6. Routing | Where next? | `Stream.emit()` | Tick | fan-out to consumers |
| 7. Rendering | What's shown? | `Surface.render()` | Vertex state | terminal cells |
| 8. Interaction | What happened? | `Surface.on_key()` | keypress | Fact via emit() |

---

## Gaps and Ambiguities

### 1. Peer is implicit

**Current:** Peer enforcement lives in the composition layer. The pipeline has no Peer-aware stage.

**Observation:** `review.py` checks `peer.potential` before calling `vertex.receive()`. The Peer name is stuffed into payload, not tracked as metadata.

**Question:** Should Vertex accept a Peer argument? Or is composition-layer enforcement the right design?

### 2. Shape vs manual fold

**Current:** Experiments define their own fold functions and pass to `Vertex.register()`. Shape.apply() exists but isn't used.

**Observation:** Shape declares `input_facets`, `state_facets`, `boundary`, and `folds`. The Vertex could consume a Shape directly.

**Question:** Is this a missing wire (Shape → Vertex) or intentional flexibility (manual folds for experiments)?

### 3. Tick routing is ad-hoc

**Current:** Each experiment wires tick routing differently:
- `review.py`: Stores in lists, no Stream
- `cascade.py`: Stream connects vertices

**Question:** Is this healthy flexibility or missing infrastructure?

### 4. Fact atom underused

**Current:** The `Fact` dataclass exists but experiments pass `(kind, payload)` tuples directly. `Vertex.receive()` takes `kind, payload`, not `Fact`.

**Question:** Should Vertex accept Fact objects? Would this add Peer/ts metadata tracking?

---

## Where does X happen?

Quick reference for "where does X happen?" questions:

| X | Answer |
|---|--------|
| Kind registration | `Vertex.register(kind, initial, fold, boundary=...)` |
| Fact storage | `Vertex.receive()` → `store.append()` before routing |
| State fold | `Projection.fold_one()` via `Vertex.receive()` |
| Boundary trigger | `Vertex.receive()` checks `boundary_map[kind]` |
| Tick creation | `Vertex.receive()` or `Vertex.tick()` |
| Tick routing | Composition layer (Stream or direct) |
| Peer enforcement | Composition layer (checks `peer.potential`) |
| State rendering | `Surface.render()` reads `vertex.state()` |
| Input emission | `Surface.emit()` → `on_emit` callback |

---

## Recommendations

1. **Document the current design** — The pipeline works. Formalize it before changing.

2. **Consider Shape → Vertex wire** — Shape already declares everything Vertex needs. A `Vertex.register_shape(shape, fold)` method could reduce boilerplate and ensure consistency.

3. **Standardize tick routing** — Stream exists and works. Experiments that don't use it may be missing composition opportunities.

4. **Peer as first-class** — If Peer enforcement matters, consider `Vertex.receive(peer, kind, payload)` or a wrapper that validates before delegating.

5. **Fact object through pipeline** — Using Fact objects (not tuples) would preserve ts and enable Peer metadata. Tradeoff: verbosity.

---

*This document answers "where does X happen?" for the current codebase. It does not prescribe changes.*
