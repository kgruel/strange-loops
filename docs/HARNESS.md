# Harness Design — Findings

Research into worker continuity, run_cli adoption, and harness conventions.

## 1. Worker Continuity

### The Gap

When a worker exhausts max-turns and we re-send work to the same task, the new
worker spawns fresh. The store holds all prior `worker.output` facts — the
facts ARE the memory — but nothing pipes them to the new invocation.

`harness.spawn()` receives `path` (store), `task_name`, `worktree`, `prompt`.
It has everything needed to query prior context before spawning.

### Options

**A. Prepend prior output to prompt**
Concatenate last-run `worker.output` lines into the prompt string. Simple,
harness-agnostic. Problem: inflates the shell command line (OS limits ~2MB,
but escaped text multiplies size), and doesn't distinguish "context block"
from "new instruction" — prompt is unstructured.

**B. Write CONTEXT.md into the worktree (recommended)**
Before spawning, query `worker.output` facts since the most recent
`worker.started` and write them to `<worktree>/CONTEXT.md`. AI harnesses read
files naturally; the model will encounter CONTEXT.md when it explores the
worktree. Shell harnesses ignore it. Cleanup: overwrite on each resume, remove
on `task close`.

This fits the loops model cleanly: the fact record drives the context file,
not an ad-hoc prompt extension.

**C. `claude --resume <session_id>` (claude harnesses only)**
`claude -p --resume <session_id>` continues a specific conversation thread,
including tool-call history. Requires:
1. Switching to `--output-format stream-json` to capture the `session_id`
   emitted in streaming events
2. Storing session_id as a `worker.session_id` fact after each run
3. Passing `--resume $(last_session_id)` to the next invocation

This is strictly better for claude harnesses (preserves full context, not just
text output) but adds parsing complexity in `harness.py`. Feasible as a
follow-on once stream-json is adopted (see §3).

**D. `claude --continue`**
Continues the most recent conversation in the working directory. Since workers
run with `cwd=worktree`, this would find the previous session for that
worktree automatically — no session_id tracking needed. Unclear whether
`--continue` works with `--print` (`-p`); the docs only guarantee `--resume`
with `--print`. Needs verification before use.

### Recommended Approach

**Now: CONTEXT.md for general continuity.**

```python
# In harness.py, run_harness() — before building the command:
def _write_context(path: Path, task_name: str, worktree: Path) -> None:
    """Write last-run worker output to CONTEXT.md in the worktree."""
    from engine import StoreReader
    with StoreReader(path) as reader:
        all_facts = reader.facts_between(0, float("inf"), kind="worker.output")
    task_facts = [f for f in all_facts if f["payload"].get("task") == task_name]
    if not task_facts:
        return
    # Find facts from the most recent run (since last worker.started)
    with StoreReader(path) as reader:
        started_facts = reader.facts_between(0, float("inf"), kind="worker.started")
    task_starts = sorted(
        [f for f in started_facts if f["payload"].get("task") == task_name],
        key=lambda f: f["ts"],
    )
    last_start_ts = task_starts[-1]["ts"].timestamp() if task_starts else 0
    last_run = [
        f for f in task_facts
        if (f["ts"].timestamp() if hasattr(f["ts"], "timestamp") else f["ts"]) > last_start_ts
    ]
    if not last_run:
        return
    lines = [f["payload"].get("line", "") for f in last_run]
    context = "\n".join(lines)
    (worktree / "CONTEXT.md").write_text(
        f"# Prior Run Context\n\nOutput from previous worker run:\n\n```\n{context}\n```\n"
    )
```

`_write_context()` is called in `run_harness()` before building the command,
only when prior `worker.output` facts exist for the task.

**Later: `--resume` for claude harnesses.**

Adoption path:
1. Add `format "stream-json"` to claude .loop files
2. harness.py parses stream-json lines, extracts session_id, emits
   `worker.session_id` fact
3. `_build_command()` reads last session_id from store and appends
   `--resume <id>` when present

### What Context to Include

Last run only, not all history. Prior runs may have explored dead ends.
Hardcap at 500 lines (~50K chars) to avoid context budget blowout — truncate
from the top, keep the end (most recent output is most relevant).

---

## 2. run_cli as Universal Status Pattern

### What run_cli Provides

`painted.run_cli(args, render, fetch, fetch_stream=..., ...)` handles:
- Zoom dispatch (`-q` / `-v` / `-vv` → MINIMAL/SUMMARY/DETAILED/FULL)
- Mode dispatch (`--static` / `--live` / auto-detect from TTY)
- Format dispatch (`--json` / `--plain`)
- Graceful error rendering
- Consistent `--help` output

Dashboard uses it with `default_mode=LIVE` overridden to STATIC (run-and-exit
default, `--live` for persistent view).

### Which Commands Should Adopt run_cli

**Yes — status commands** (pure read → render loops):
- `session status` — fetch store stats, render block
- `task status` — fetch fold state, render task table
- `project status` — fetch project store, render decisions/threads/plans

What migrating gains:
- `task status --live` → auto-refreshing task table (today's dashboard is
  task-list only; a `task status --live` would show per-task detail)
- `task status -q` → one-liner count
- `--json` handled by framework, not ad-hoc `if use_json: json.dumps(...)`
- Zoom-aware render opens richer detail levels per status command

**No — action commands** (emit facts, side effects):
- `task create`, `task assign`, `task send`, `task run`, `task close`,
  `task merge`, `task stop`
- `session start`, `session end`
- `project emit`, `note`

These emit facts and print confirmations. They don't have a "render state"
to zoom. The `show(Block.text(...))` pattern is correct for them.

**Borderline — task log**
`task log --follow` has a manual polling loop. run_cli's `fetch_stream`
could house it — but `task log` is append-only streaming (new lines only),
not snapshot-replace like dashboard. The InPlaceRenderer would overwrite
prior lines. Not a fit unless there's a scrollback-aware renderer.

Keep `task log --follow` as a manual poll loop. It's correct for the use case.

### Migration Sketch for task status

```python
# commands/task.py
def run_task_status(argv: list[str]) -> int:
    from painted import run_cli

    def fetch() -> list[dict]:
        sp = store_path()
        require_store(sp)
        from engine import StoreReader
        with StoreReader(sp) as reader:
            return fold_all_tasks(reader)

    async def fetch_stream():
        import asyncio
        while True:
            try:
                yield fetch()
            except FileNotFoundError:
                pass
            await asyncio.sleep(2.0)

    def render(ctx, tasks):
        return _render_task_list_zoom(ctx.zoom, tasks, ctx.width)

    return run_cli(
        argv,
        render=render,
        fetch=fetch,
        fetch_stream=fetch_stream,
        default_mode=OutputMode.STATIC,  # run-and-exit by default
        description="Task status",
        prog="strange-loops task status",
    )
```

The existing `_render_task` and `_render_task_list` become zoom-aware by
checking `ctx.zoom`:
- MINIMAL: `N tasks: 2 working, 1 closed`
- SUMMARY: current table (name + status + activity)
- DETAILED: add harness, worktree path
- FULL: add base branch, worker exit code

---

## 3. Harness Output Format: text vs stream-json

### Current: --output-format text

All claude harnesses emit final text only. harness.py reads stdout line-by-line,
each line becomes a `worker.output` fact with `{"task": ..., "line": ...}`.
Simple, readable in `task log`.

### stream-json

`--output-format stream-json` emits newline-delimited JSON objects:
- `{"type": "text", "content": "...", "session_id": "..."}`
- `{"type": "tool_use", "name": "Bash", "input": {"command": "..."}}`
- `{"type": "result", "subtype": "success", "session_id": "..."}`

**What you gain:**
- Intermediate visibility: tool calls appear in `task log --follow` as they happen
- `session_id` in the output → `--resume` becomes possible
- `--include-partial-messages` for text streaming within a turn

**What it costs:**
- harness.py needs JSON parsing per line and format-aware dispatch
- `worker.output` facts become richer (multiple kinds: output, tool_call, session)
- `task log --follow` output changes (currently pure text, would show JSON-decoded events)

**Recommendation**: Add `format "stream-json"` support to claude harnesses as a
second step, after CONTEXT.md continuity is landed. The .loop format field
already exists — harness.py just needs a `format == "stream-json"` branch.

Suggested fact kinds when parsing stream-json:
- `worker.output` — text content (same as now, text extracted from JSON)
- `worker.tool_call` — tool invocations (`name`, `input`)
- `worker.session_id` — emitted once per run, enables `--resume`

---

## 4. Harness Convention Recommendations

### Current State

| Harness | env CLAUDECODE= | max-turns | model | tool allowlist |
|---------|-----------------|-----------|-------|----------------|
| sonnet | ✓ | 50 | `sonnet` (alias) | Bash,Read,Edit,Write,Glob,Grep |
| opus | ✓ | none | `claude-opus-4-5-20250514` (hardcoded) | Bash,Read,Edit,Write,Glob,Grep,Notebook |
| codex | — | — (--full-auto) | `codex-mini-latest` | n/a |
| gemini-flash | — | — (--yolo) | `gemini-2.5-flash` | n/a |
| shell | — | n/a | n/a | n/a |

### Recommendations

**1. All claude harnesses must have max-turns**
Opus currently has no `--max-turns`. Without it, a runaway task burns budget
indefinitely. Add `--max-turns 50` (or a harness-specific value).

**2. Use model aliases, not full model strings**
Opus uses `claude-opus-4-5-20250514`. The model will age. Use `opus`:
```
source #"env CLAUDECODE= claude -p --model opus ..."#
```

**3. allowedTools must be explicit on all claude harnesses**
Implicit tool access is a security and budget risk. Every claude harness should
declare `--allowedTools`. The standard set (read + edit code):
`Bash,Read,Edit,Write,Glob,Grep`

Harnesses that need more (notebooks, MCP, browser) declare it explicitly and
document why.

**4. auto-commit stays in harness.py, not per-harness**
The current approach — `git add -A && git commit` on exit code 0 in `run_harness()`
— is correct. Commit hygiene is a system concern. Making it per-harness config
adds complexity without clear benefit.

**5. output-format: keep text until stream-json is adopted**
Don't mix formats in the same system before harness.py supports both.

### Proposed Corrections

`opus.loop`:
```
source #"env CLAUDECODE= claude -p --model opus --output-format text --allowedTools 'Bash,Read,Edit,Write,Glob,Grep,Notebook' --max-turns 50 {{prompt}}"#
kind "worker.output"
observer "opus"
format "lines"
```

### Future Harness Design Template

```
source #"env CLAUDECODE= claude -p \
  --model <alias> \
  --output-format text \
  --allowedTools '<tools>' \
  --max-turns <N> \
  {{prompt}}"#
kind "worker.output"
observer "<alias>"
format "lines"
```

Non-claude harnesses (codex, gemini): keep minimal — they own their own
safety model (--full-auto, --yolo). Don't impose claude conventions on them.

---

## Open Questions (Human Decisions Required)

**Q1: When to write CONTEXT.md?**
Options: (a) always on resume (when prior `worker.output` exists), (b) only
when prior run was `status=exhausted`, (c) only when explicitly requested with
a `--resume` flag on `task send`. Option (b) is conservative and fits the
exhaustion-recovery use case. Option (a) is "every resume has context", which
may pollute short tasks.

**Q2: CONTEXT.md size cap?**
500 lines suggested. Real tasks may produce 2000+ lines. Too little context
misses important history; too much burns the context window before the model
even starts working. The right cap depends on typical task size — collect data
before hardcoding.

**Q3: Should `task status` migrate to run_cli before `--live` mode is wanted?**
The migration is non-trivial. If `task status --live` isn't needed now, the
current `_render_task` + `show()` pattern is sufficient. Migrate when the
feature gap becomes real, not speculatively.

**Q4: stream-json before `--resume`, or `--resume` before stream-json?**
These are coupled: `--resume` needs session_id, session_id comes from
stream-json. Either land both together or neither. CONTEXT.md continuity is
independent and can land first.

**Q5: Is `claude --continue` safe with `-p`?**
Untested. `--continue` would be simpler than `--resume` (no session_id
tracking) if it works in print mode. Worth a quick experiment in an isolated
worktree before building session_id infrastructure.
