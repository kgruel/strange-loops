# Experiments

Integration layer — wires libs together to explore the loops model.

## By Concept

### Observer — who observes
The observer is first-class. Facts carry observer identity.

| Experiment | What it explores |
|------------|------------------|
| observer/capability.py | Event-sourced potential via Shape |
| observer/observe.py | User interactions as Facts with peer gating |
| observer/observer_flow.py | Observer model: Fact.observer, Vertex.to_fact(), Grant |
| observer/peer_aware_vertex.py | Potential gating, observer-state ownership |
| observer/peer_focus.py | Per-peer state eliminates cursor conflicts |
| observer/peer_surface.py | Full TUI integration with peer model |
| observer/simultaneous_peers.py | Why shared focus breaks with concurrency |

### Temporal — when cycles complete
Boundaries mark time. Ticks close loops.

| Experiment | What it explores |
|------------|------------------|
| temporal/boundary.py | Data-driven boundaries (health resets, deploy self-completes, audit accumulates) |
| temporal/cascade.py | Live tick flow between connected vertices |
| temporal/fleet.py | Three-level hierarchy: VM → region → global |
| temporal/loop_explicit.py | Explicit Loop + Projection API |
| temporal/review.py | Timer-driven health + peer-driven review cycles |
| temporal/summary.py | Ticks as input to next loop (nesting proof) |

### Network — where loops meet
Vertices compose across process boundaries.

| Experiment | What it explores |
|------------|------------------|
| network/network_boundary.py | Tick serialization, queue as network model |
| network/network_boundary_extended.py | Discovery, failure, ordering, backpressure |
| network/network_observer.py | Observer identity across network boundaries |

### Presentation — how state renders
Lens projects state to view.

| Experiment | What it explores |
|------------|------------------|
| presentation/lens_code.py | Lens primitive (zoom + scope), Projection duality |
| presentation/review_lens.py | Lens integrated with review app |

### Daemon
Smallest running loop.

| Experiment | What it explores |
|------------|------------------|
| daemon/mill.py | stdin JSON → Shape fold → stdout Ticks |

### Fidelity
CLI→TUI spectrum.

| Experiment | What it explores |
|------------|------------------|
| fidelity/ | Fidelity flags (-q, -v, -vv) for CLI tools |

## Archive

Historical experiments in `archive/`. Pre-date current model but preserved for reference.

## Running

```bash
uv run python experiments/{folder}/{name}.py
```

Most experiments are interactive TUI apps. Press `q` to quit.
