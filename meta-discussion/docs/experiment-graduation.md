# Experiment → Graduation Pipeline

How exploratory work becomes production code, and the lifecycle stages in between.

## The Lifecycle

```
experiments/  →  active experiment  →  graduation  →  libs/ or apps/
                                           ↓
                                    experiments/archive/
```

### Stage 1: Experiment

Lives in `experiments/`. Has its own context (sometimes its own CLAUDE.md,
pyproject.toml). Purpose is to *learn something*, not to ship something.

**Characteristics:**
- Quick and dirty is fine
- May duplicate code from libs (exploring alternatives)
- Tests optional (the experiment *is* the test)
- May have its own LOG.md for insights
- Named descriptively: `cadence_viz.py`, `peer_focus.py`, `fleet.py`

**Examples from loops:**
- `experiments/temporal/` — boundary triggering, fidelity traversal, fleet hierarchy
- `experiments/bend/` — interaction combinator proofs (3 experiments)
- `experiments/cadence_viz.py` — animated TUI proving timer cascade
- `experiments/nested_flow/` — sibling vertex fan-out

### Stage 2: Active Experiment

The experiment is teaching you something and you're iterating. It may have
multiple files, its own subdirectory, maybe fixtures. The LOG.md in
`experiments/` tracks what emerged.

**Signals you're here:**
- You're running the experiment repeatedly
- You're refining the interface
- Other code is starting to depend on patterns discovered here

### Stage 3: Graduation

The experiment stops teaching and starts doing real work. Time to move it.

**Graduation criteria (observed, not prescribed):**
- The API stabilized — you stopped changing the function signatures
- Other code wants to import it
- You're writing tests for it (not the experiment *as* test, but tests *of* it)
- The pattern appeared in 2+ experiments (it's general, not one-off)

**Where it goes:**
- `libs/<name>/` if it's a reusable primitive (atoms, engine, cells)
- `apps/<name>/` if it's a domain-specific tool (hlab, reader, strange-loops)

**What happens to the experiment:**
- Moves to `experiments/archive/` with its context preserved
- Or stays in `experiments/` if it's still useful as a demo/proof

### Stage 4: Archive

`experiments/archive/` preserves the experiment's context:
```
experiments/archive/
├── 01_cells_demo/          # numbered for chronology
│   ├── CLAUDE.md           # context at time of archival
│   └── ...
├── 02_spec_driven/
│   ├── CLAUDE.md
│   ├── pyproject.toml
│   └── framework/
└── 03_atomic_pipeline/
```

Numbered prefix gives chronological ordering. CLAUDE.md preserved so you can
reconstruct what the experiment was about.

## The Pattern's Value

The pipeline prevents two failure modes:
1. **Premature graduation** — moving code to libs before the API stabilizes,
   then thrashing on the interface while downstream code depends on it
2. **Permanent experimentation** — code that works but never leaves experiments/,
   duplicated by hand into real code, experiments rot

The archive prevents a third:
3. **Lost context** — experiments deleted once graduated, losing the *journey*
   that led to the current design. The archive is the fossil record.

## What's Missing

**No formal graduation checklist.** The criteria above are observed patterns,
not a documented process. Could be worth adding to the scaffold template:
"When moving from experiments/ to libs/, ensure: tests exist, API is stable,
CLAUDE.md written, old experiment archived."

**No experiment template.** Starting a new experiment means creating a directory
and maybe a pyproject.toml by hand. Could have a `./dev experiment <name>`
that scaffolds the minimal structure.

**No cross-experiment index.** `experiments/LOG.md` tracks insights but there's
no machine-readable index of experiments, their status, and what they proved.
The archive numbering is chronological but not semantic.
