# Project: experiments

## Branching

- **`wip`** — where we work. Commits, experiments, living docs, uncommitted changes all live here.
- **`main`** — clean merge target. Subtasks merge here without friction.
- Subtasks always draft with `--base-branch main`.
- After subtask merges, rebase wip onto main: `git rebase main` (from wip branch).
- Never stash to merge. If main needs to be clean, we're on the wrong branch.

## Subtask Workflow

1. Design/discuss on wip (or in conversation)
2. Draft subtask with `--base-branch main`
3. Send worker, review output
4. Merge to main (no stash needed — we're on wip)
5. `git rebase main` to pick up changes on wip

## Architecture

Two layers — see `docs/render-layer.md` for the render layer reference:

- `framework/` — event routing, projections, signals (what to show)
- `render/` — cells, buffers, styled blocks, components, app lifecycle (how to show it)

## Conventions

- Components are frozen value objects (state + transitions + render function)
- Composition is spatial and explicit (no flex, no constraints)
- State flows down, StyledBlocks flow up
- Side effects only at the terminal boundary (Writer)
