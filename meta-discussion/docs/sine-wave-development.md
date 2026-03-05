# Sine Wave Development

Development intensity follows a wave pattern, not a linear trajectory. Designing
for this instead of against it.

## The Observation

The loops commit history:

```
Jan 3-25   ████░░░░░░  Genesis — searching for vocabulary (~20 commits)
Jan 26-31  ██████████  Crystallization burst — model snaps (6 days, intense)
Feb 1-10   ███████░░░  Proving out — features, apps, steady building
Feb 11-23  ░░░░░░░░░░  Gap — no commits (processing, other projects)
Feb 24-28  ████████░░  Return — Bend experiments, session continuity
```

This isn't procrastination or inconsistency. It's a pattern:

1. **Accumulation** — gathering observations, reading, exploring
2. **Crystallization** — intense burst where the vocabulary shifts and the model
   restructures
3. **Proving** — steady work applying the crystallized model to real problems
4. **Rest** — gap where the next phase organizes itself (often working on other
   projects)
5. Repeat

## What It Implies for Tooling

### Session continuity matters more than velocity tracking

Sprints assume constant velocity. The sine wave means some weeks produce 50
commits and some produce zero. The important thing isn't "how many story points"
but "can I pick up where I left off?" Hence LOG.md, HANDOFF.md, `loops session`.

### HANDOFF.md is the critical document

When you return from a gap, HANDOFF.md is what you read first. It needs to
answer: what was I doing, what's next, what's deferred, what's the current
state. It's the bridge across the wave's trough.

### Named sessions enable context-switching

The gap isn't always idle — it's often working on a different project. Named
sessions (see session-continuity.md) let you have multiple active threads
without conflating their state. Return to `meta-discussion` after a week on
`strange-loops`, pick up exactly where you left off.

### The dev harness must be zero-friction

After a gap, you don't remember the build commands. `./dev check` and
`./dev -h` must work without consulting docs. The harness is muscle memory
that survives the wave's trough.

### Tests are the safety net across gaps

When you return after a gap, the first thing you do is run tests. If they pass,
the system is still coherent. Architecture tests are especially valuable here —
they confirm the *design* still holds, not just that individual functions work.

## Multi-Project Sine Waves

The gaps in one project often correspond to peaks in another:

```
loops:          ████░░░░████░░░░████
siftd:          ░░░░████░░░░████░░░░
painted:        ██░░░░░░████░░░░██░░
gruel.network:  ░░██░░░░░░██░░░░░░██
```

(Illustrative, not measured.) The development energy is roughly constant;
it moves between projects. This means:

- Cross-project patterns matter (what you learn in painted applies to loops)
- The scaffold template captures these patterns so each project benefits from
  all projects' learnings
- Session continuity per-project lets you context-switch without losing state

## What This Is NOT

This is not an argument for undisciplined work. The dev harness, architecture
tests, and session continuity are *structure* that makes the sine wave
productive. Without them, the troughs become restarts instead of continuations.

The sine wave is the observation. The tooling is the response.
