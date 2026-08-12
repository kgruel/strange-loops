# S4 implementation report — cite vertex slot + all-refs-drop error

Slice: S4 of design/implementation/cli-honesty-wave (ratified).
Driving friction: friction:cite-verb-first-lacks-vertex-slot.
Agent: s4-impl. Branch: worktree-agent-a2bd6127c4f74d6a8 (worktree off 17783fd).

## What changed

1. **Vertex slot in verb-first cite** (`apps/loops/src/loops/cli/views/cite.py`)
   — grammar is now `sl cite [vertex] REF... [-m ...]`. When
   `ctx.vertex_path` is None (verb-first dispatch), the view peels
   `refs[0]` as the vertex **iff `_resolve_vertex_for_dispatch` resolves
   it** (path-like `.vertex` paths included). The peel runs BEFORE the
   ambiguous-local-vertex refusal, so an explicitly named vertex needs no
   local tie-break. A named vertex with zero remaining refs is a hard
   error (exit 2, stderr) — better than letting the name fall through as
   an unresolvable ref. Vertex-first dispatch (`sl <vertex> cite`) sets
   `ctx.vertex_path` and no peel runs — unchanged.

2. **All-refs-drop escalates to an error**
   (`apps/loops/src/loops/commands/emit.py`, `cmd_emit`) — gate:
   `kind == "cite" and unresolved_refs and not resolved_refs` → per-ref
   `ERROR: ref '…' did not resolve` lines + a summary ERROR on stderr,
   exit 2, nothing stored. Placed with the strict-refuse block, before
   the dry-run branch, so `--dry-run` reports the same refusal the real
   emit would. Partial drops keep the existing WARN + typed-pin behavior
   (confirmed: at least one resolved ref → stored, `(refs: N resolved)`).

3. **Grammar declaration + completion**
   (`apps/loops/src/loops/cli/cite_args.py`,
   `apps/loops/src/loops/cli/completers.py`) — cite_args docstring/help
   updated (`[vertex] REF...`); new `complete_cite_refs` completer offers
   vertex names for the empty first slot (parity with
   `complete_emit_tokens`'s first slot) and defers `[]` afterwards.
   Stale "cite never takes a vertex positional" prose swept in the same
   change (dissolution-residue discipline).

## Grammar choice + rationale

- **Peel-by-resolution, not emit's bare-`"/"` rule.** Emit classifies a
  leading token with `"/"` as the vertex because kinds are bare
  identifiers. For cite that rule is wrong: the legacy slash-form ref
  `thread/arc-name` is a legal positional (pinned by
  `test_cite_emit_ref_parity.py`). Resolution is the discriminating
  check — a `kind:key` address never resolves as a vertex. Residual
  collision (a bare ULID that happens to name a real vertex) is
  implausible (26-char Crockford vs. vertex names) and fails loud (zero
  refs → error), never silent.
- **Backward compat: the no-vertex form KEEPS working**, resolving
  exactly like emit's no-vertex path: `ambiguous_local_vertex_refusal`
  (refuse-to-guess on multi-vertex local tier), then
  `_find_local_vertex` — which IS `.loops/`-aware. The friction's
  "doesn't look in .loops/" claim was already fixed by an earlier slice
  (`_find_local_vertex` prefers `.loops/.vertex`, then `.loops/*.vertex`,
  then cwd, and refuses ambiguity by construction). The no-vertex form
  therefore inherits emit-parity resolution as-is — **no arbiter
  escalation needed**; the "genuinely ambiguous?" question resolves to no.
- **Exit 2 for the all-refs-drop refusal** — parity with cmd_emit's other
  validation refusals (strict refuse, missing kind, reserved namespace);
  exit 1 stays for runtime errors. NON-NEGOTIABLE honored: every new
  error path is nonzero with the error on stderr.
- **Kind-level, not verb-level, refusal.** The contract sentence ("a cite
  whose refs ALL drop is an error") is a property of the cite KIND, so
  the gate lives in `cmd_emit` — the verb-first view, vertex-first
  dispatch, and the raw `sl emit <v> cite ref=…` spelling all refuse
  identically. No new detection machinery: the gate reads resolution
  OUTPUT that already existed (`unresolved_refs`/`resolved_refs`), so it
  naturally skips paths where resolution never ran (no store), and a
  cite emitted with no refs at all stays out of the claim's scope
  (narrow claim, per contract).

## Files touched

- `apps/loops/src/loops/cli/views/cite.py` — vertex peel + no-refs guard
- `apps/loops/src/loops/cli/cite_args.py` — grammar docs + completer hook
- `apps/loops/src/loops/cli/completers.py` — `complete_cite_refs`
- `apps/loops/src/loops/commands/emit.py` — all-refs-drop refusal in `cmd_emit`
- `apps/loops/tests/test_cite_vertex_slot.py` — NEW, 12 tests (slot, ambiguity
  bypass, `.loops/` no-vertex compat, no-peel under vertex-first, slash-ref
  not mistaken for vertex, all-drop error incl. dry-run, partial-drop WARN,
  emit-path uniformity)
- `apps/loops/tests/test_cite_emit_ref_parity.py` — unresolved-parity class
  rewritten as parity-in-refusal + partial-drop-pin parity
- `apps/loops/tests/test_ambiguous_local_vertex.py` — hint text updated to the
  new grammar (`sl cite <vertex> REF ...`); two tests seed their referent
  (their subject is vertex resolution, not ref semantics)
- `apps/loops/tests/test_emit.py` — cite regression tests seed referents
  (subject is ref capture)
- `apps/loops/tests/test_verb_completion_t4.py` — completion pin inverted:
  first slot now offers vertex names; new defer-after-first-token test

## Test evidence

- Baseline (worktree tip 17783fd, changes stashed):
  `uv run --package loops pytest apps/loops/tests -q` → **2442 passed, 1 xfailed**
- With S4: → **2456 passed, 1 xfailed** (+14 tests, zero collateral)
- `./dev check` (repo root) → pass
- Live (throwaway store under scratchpad `/private/tmp/...`, isolated
  `LOOPS_HOME`, via `uv run --package loops loops`, never `sl`):
  1. `loops cite t thread:arc` → rc 0, `(refs: 1 resolved)` in t's store
  2. `loops cite t thread:absent` → rc 2, both ERROR lines on stderr, nothing stored
  3. `loops cite t thread:arc thread:absent` → rc 0, WARN + typed pin
  4. `loops cite thread:arc` (no vertex, single `.loops/t.vertex`) → rc 0
  5. `loops cite t` (vertex, no refs) → rc 2, usage error

## Deviations / notes

- **Suite-count mismatch vs. task prompt**: prompt cited baseline
  2467 passed; this worktree's actual baseline is 2442 (measured by
  stash-and-run). Delta is upstream of S4 — flagging, not chasing.
- **Template-qualifier residue**: emit's `vertex/template` split
  (`parent/native` → vertex + template_qualifier, handled in cmd_emit's
  config fallback) is not replicated in cite's peel;
  `_resolve_vertex_for_dispatch` covers plain, path-like, `.loops/`,
  cwd, config, and combine-alias names. Named as accepted residue.
- **Multi-line refusal rendering**: the "vertex named but no refs" message
  uses an embedded `\n` via `reporter.err`, which painted flattens to a
  space on output — same shape as the pre-existing "no local vertex
  found" message (friction:block-text-multiline-passthrough-broke-on-040
  territory), so consistent, not new.
- Prior pinned behavior intentionally changed (per contract): a cite
  whose refs all drop used to store an empty attention signal with
  WARN — four existing tests pinned pieces of that and were updated to
  the new contract (listed above), each preserving its original subject.
