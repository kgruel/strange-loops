# TUI.md — Persistent Dashboard Specification

Spec for a persistent alt-screen dashboard for strange-loops.
Audience: the implementer. Read after studying `dashboard.py`, `lifecycle.py`, and `painted/src/painted/`.

---

## Architecture decision

Two rendering tiers:

| Invocation | Mode | Zoom | Mechanism |
|---|---|---|---|
| `dashboard -q` | LIVE/STATIC | MINIMAL | `InPlaceRenderer`, one-liner counts |
| `dashboard` | LIVE | SUMMARY | `InPlaceRenderer`, columnar table (current) |
| `dashboard -i` | INTERACTIVE | DETAILED | `Surface`, full alt-screen |
| `dashboard -i -v` | INTERACTIVE | FULL | `Surface`, with worker output in detail pane |

Live mode is unchanged. This spec targets INTERACTIVE mode only.

The wiring is: `run_cli(..., handlers={OutputMode.INTERACTIVE: _run_interactive})`. When `-i` is passed,
`CliRunner._dispatch` invokes the handler. `_run_interactive(ctx: CliContext) -> int` creates the
Surface and runs it via `asyncio.run(DashboardSurface(ctx).run())`.

`Surface` is in `painted/src/painted/app.py`, exported as `painted.tui.Surface`.
`painted` is already a dependency (`pyproject.toml:21`). No new dependencies.

---

## 1. Layout spec

ASCII mockup at 120 × 30 (numbers are approximate):

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ strange-loops  session: active  14 facts             j/k select  r refresh  q quit         14:32:05                   │  ← header (row 0)
├────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤  ← separator (row 1)
│ Tasks (3)                          │ tui-design — working                                                              │  ← pane headers (row 2)
│                                    ├────────────────────────────────────────────────────────────────────────────────── │  ← pane sub-sep (row 3)
│  Task           Status    Chg  Age │  14:30 [task.created]  name=tui-design title=Design TUI layout                   │  ← table header (row 4)
│  ─────────────────────────────     │  14:31 [task.assigned] harness=sonnet worktree=.worktrees/tui-design              │  ← table sep (row 5)
│  tui-design     working  +23   2m  │  14:32 [worker.started] pid=12345                                                │  ← task rows (row 6+)
│    └ Design TUI layout             │  14:32 [worker.output]  output=Research started                                  │
│  auth-rework    completed +89   1h │  14:33 [worker.output]  output=Reading painted docs                              │
│    └ Auth rework                   │                                                                                   │
│  ci-cleanup     created    —    3h │                                                                                   │
│    └ CI cleanup                    │                                                                                   │
│                                    │                                                                                   │
│                     (scrollable)   │                                              (scrollable)                         │
│                                    │                                                                                   │
├────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────┤  ← separator (h-2)
│ Project — 47 facts  3 decisions  2 threads  1 plan                                   updated 14:32:03                  │  ← status bar (h-1)
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Regions

Computed in `DashboardSurface.layout(w, h)`, stored as `Region` instances:

| Field | x | y | width | height | Notes |
|---|---|---|---|---|---|
| `_header_region` | 0 | 0 | w | 1 | Session status + key hint + clock |
| `_hsep` | 0 | 1 | w | 1 | Horizontal separator `─ * w` |
| `_tasks_region` | 0 | 2 | `tasks_w` | `h - 4` | Left pane, scrollable task table |
| `_vsep_x` | `tasks_w` | 2 | 1 | `h - 4` | Vertical `│` separator column |
| `_detail_region` | `tasks_w + 1` | 2 | `w - tasks_w - 1` | `h - 4` | Right pane, selected task detail |
| `_status_region` | 0 | `h - 2` | w | 1 | Project summary + last-updated |
| `_bsep` | 0 | `h - 3` | w | 1 | Horizontal separator before status |

`tasks_w` default split: `w * 2 // 5` (40% left, 60% right). Rationale: log lines are long.
Min usable `tasks_w`: 38 (fits 4 columns). Min terminal width: 80. Below 80, collapse to stacked layout.

`Region` is `painted.tui.Region` (`painted/src/painted/region.py`). It has `.view(buffer) -> BufferView`.

---

## 2. Data sources

### DashboardState (extended from current)

```python
@dataclass(frozen=True)
class DashboardState:
    tasks: tuple[TaskRow, ...]
    project: ProjectSummary | None
    fact_total: int
    session_active: bool           # NEW: derived from session.start/session.end
    session_fact_count: int        # NEW: total facts in task store
    selected_task: int             # NEW: index into tasks (for Surface state — see below)
    detail_facts: tuple[dict, ...] # NEW: facts for selected task (last N entries)
    last_fetched: float            # NEW: monotonic time of last fetch
```

`selected_task` is UI state (not data). Keep it on `DashboardSurface` directly, not in `DashboardState`.
`DashboardState` stays a data snapshot — pure facts. The Surface holds selection index as `self._selected`.

### Per-region data sources

#### Header region
- **Facts queried**: `session.start`, `session.end` from `tasks.db`
- **Query**: `reader.facts_between(since_ts, now, kind="session.start")` and same for `session.end`
- **Derivation**: `session_active = last_start_ts > last_end_ts` (or no end fact)
- **Display**: session status + `reader.fact_total` + current clock (updated each render, not each fetch)
- **Static vs dynamic**: `fact_total` and session status updated at fetch; clock updates every render frame (monotonic)

#### Tasks region (left pane)
- **Facts queried**: all kinds in `tasks.vertex` — the full spec fold
- **Functions**: `fold_all_tasks(reader)` → `list[dict]` (already in `lifecycle.py:104`)
- **Per-task**: `_task_activity(all_facts, name)` (already in `dashboard.py:143`), `_changes_summary(worktree)` (already in `dashboard.py:107`)
- **State**: task rows are data; scroll/selection is `TableState` (from `painted.tui` — but not yet imported into strange-loops; see Open Questions)
- **TaskRow fields used for display**: `name`, `title`, `status`, `changes`, `activity`

#### Detail region (right pane)
- **On task selected**: fetch facts for that task
- **Facts queried**: `reader.facts_between(0, inf)` → filter via `_filter_task_facts(facts, name)` (already in `task.py:533`)
- **For running tasks**: include `worker.output` facts (kind filter is optional — show all task facts)
- **Display**: chronological, most recent N lines = `detail_region.height - 2` (leaving room for pane header)
- **Scroll**: `detail_scroll: int` offset on Surface, scrolled with `[`/`]` or `PageUp`/`PageDn` when detail pane focused

#### Status region (bottom bar)
- **Facts queried**: `project.db` via `_project_summary()` (already in `dashboard.py:162`)
- **Also**: `reader.fact_total` for "N facts" count, `self._last_fetched` for "updated Xs ago"
- **Display**: `Project — N facts  D decisions  T threads  P plans   updated Xs ago`

---

## 3. Components

### Header (1 row)

```python
# painted.compose.join_horizontal + Block.text
# painted.palette.current_palette()

def _render_header(surface: DashboardSurface, w: int) -> Block:
    p = current_palette()
    session_label = "session: active" if surface._state.session_active else "session: ended"
    facts_label = f"{surface._state.fact_total} facts"
    hint = "j/k select  r refresh  q quit"
    clock = datetime.now().strftime("%H:%M:%S")

    left = Block.text(f" strange-loops  {session_label}  {facts_label}", p.accent, width=w // 2)
    right = Block.text(f"{hint}  {clock} ", p.muted, width=w - w // 2)
    return join_horizontal(left, right)
```

### Tasks pane (left)

Two sub-regions within `_tasks_region`:
1. Pane header: `"Tasks (N)"` — 1 row, `p.accent`
2. Sub-separator: 1 row
3. Column headers: `"  Task    Status    Chg   Age"` — 1 row, `Style(bold=True)`
4. Separator line: `"  ─ * (tasks_w - 2)"` — 1 row
5. Task rows: each task is 2 rows (name+status+chg+age row, then `"  └ title"` row), scrollable

**Column widths** (current in `dashboard.py:26-29`, reuse directly):
```python
_COL_TASK = 26   # name
_COL_STATUS = 14  # status
_COL_CHANGES = 12 # +N -N
_COL_ACTIVITY = 12 # Xs/Nm/Hh ago
# total: 64 — fits in tasks_w=38+ (omit changes or activity at narrow widths)
```

At `tasks_w < 64`: drop `_COL_CHANGES` column. At `tasks_w < 52`: drop `_COL_ACTIVITY` too.

**Selection highlight**: selected row uses `Style(reverse=True)`. Implemented by passing `is_selected` to each row's render function.

**Scrolling**: `self._task_scroll: int` offset. Visible rows = `detail_h - 4` (minus pane header, sub-sep, col header, sep). Arrow keys (`j`/`k`) move `self._selected`, then clamp `self._task_scroll` to keep selected in view.

**Primitive**: `join_horizontal` + `Block.text` per cell, `join_vertical` for all rows — same pattern as `_render_summary` in `dashboard.py:282`. The cells `table()` component (`painted.tui` doesn't export it directly) has this but requires `Line`/`Span` types and is more complex. Stick with the existing join pattern unless scrolling complexity warrants the switch.

### Detail pane (right)

```python
# Two sections stacked via join_vertical:
# 1. Pane header: "task-name — status" in p.accent (1 row)
# 2. Separator (1 row)
# 3. Fact log: chronological, each fact is 1 row via render_log_entry logic

def _render_detail(state: dict | None, facts: tuple[dict, ...], w: int, h: int, scroll: int) -> Block:
    p = current_palette()
    if state is None:
        return Block.text("No task selected.", p.muted, width=w)

    header = Block.text(f" {state['name']} — {state.get('status', '?')}", p.accent, width=w)
    sep = Block.text(" " + "─" * (w - 2), p.muted, width=w)

    # Log lines: apply scroll, fit to available height
    available_h = h - 2  # subtract header + sep rows
    log_rows: list[Block] = []
    sorted_facts = sorted(facts, key=lambda f: f["ts"])  # chronological
    visible = sorted_facts[scroll : scroll + available_h]
    for f in visible:
        log_rows.append(_render_fact_row(f, w, p))

    while len(log_rows) < available_h:
        log_rows.append(Block.text("", p.muted, width=w))

    return join_vertical(header, sep, *log_rows)
```

`_render_fact_row` follows the format in `store.render_log_entry` (`store.py:98`):
```
  HH:MM [kind]  k=v k=v ...
```
No `show()` call — returns `Block` directly.

### Status bar (1 row)

```python
def _render_status(surface: DashboardSurface, w: int) -> Block:
    p = current_palette()
    proj = surface._state.project
    proj_str = _project_header(proj) if proj else "No project store"  # _project_header from dashboard.py:191
    age = int(time.monotonic() - surface._state.last_fetched)
    updated = f"updated {age}s ago"
    left = Block.text(f" {proj_str}", p.muted, width=w - len(updated) - 1)
    right = Block.text(updated + " ", p.muted, width=len(updated) + 1)
    return join_horizontal(left, right)
```

---

## 4. Refresh model

### What is static vs dynamic

| Data | Update trigger | Notes |
|---|---|---|
| Task list (TaskRow) | Poll every 2s | `fold_all_tasks` on fresh `StoreReader` |
| Task detail facts | Poll every 2s + on selection change | `reader.facts_between(0, inf)` filtered |
| Project summary | Poll every 2s | `_project_summary()` |
| Session status | Poll every 2s | `session.start/end` facts |
| Clock in header | Every render frame | `datetime.now()` — no fetch needed |
| "updated Xs ago" in status | Every render frame | `time.monotonic() - last_fetched` |
| Changes (`+N -M`) | Poll every 2s | `_changes_summary()` spawns subprocess |
| Selection highlight | On keypress | Pure UI state, no fetch |

### Poll implementation

```python
# On DashboardSurface:
_POLL_INTERVAL = 2.0

def update(self) -> None:
    """Called every frame by Surface.run(). Advance timers."""
    now = time.monotonic()
    if now - self._last_poll >= _POLL_INTERVAL:
        self._last_poll = now
        new_state = _fetch_with_detail(self._selected_name())
        if new_state.fact_total != self._state.fact_total:
            self._state = new_state
            self.mark_dirty()
    # Clock always needs repaint (1-second granularity is enough)
    if int(now) != int(self._last_clock_tick):
        self._last_clock_tick = now
        self.mark_dirty()
```

`_fetch_with_detail(name: str | None) -> DashboardState` does one `StoreReader` open, pulls all facts,
folds tasks, and if `name` is not None also filters facts for the selected task. Single open/close per poll.

**Note on `_changes_summary`**: spawns `git diff --shortstat` per task. At poll interval 2s with N tasks,
this is N subprocess calls per 2s. Acceptable for <10 tasks. If perf is a problem: cache per `(worktree, last_mtime)`.

### Repaint budget

`Surface` caps at 60fps (`fps_cap=60`). The dashboard only marks dirty on:
1. Keypress (immediate)
2. Poll yielding new data (every 2s)
3. Clock tick (every 1s)

Net: ~1 frame/s at idle, bursts on keypresses. Very cheap.

---

## 5. Lens integration

The existing lens/zoom pattern (`Zoom.MINIMAL`, `SUMMARY`, etc.) applies to the LIVE path only.
INTERACTIVE mode bypasses the `_render(ctx, state) -> Block` dispatch:

```python
# In run_dashboard (dashboard.py):
return run_cli(
    argv,
    render=_render,                      # zoom-aware: MINIMAL and SUMMARY
    fetch=_fetch,
    fetch_stream=_fetch_stream,
    handlers={OutputMode.INTERACTIVE: _run_interactive},  # NEW
    description="Task dashboard",
    prog="strange-loops dashboard",
)
```

`_render` is unchanged — it handles `-q` and default zoom for LIVE mode.

`_run_interactive(ctx: CliContext) -> int` is new. It uses `ctx.zoom` to configure the Surface's initial detail level (e.g., FULL zoom → detail pane shows worker output stream vs just log entries).

**Zoom in INTERACTIVE mode** (maps to detail pane behavior):

| `ctx.zoom` | Detail pane shows |
|---|---|
| `MINIMAL` | Not applicable (minimal implies STATIC) |
| `SUMMARY` | Last 10 log entries for selected task |
| `DETAILED` | Last 30 log entries + worker info header |
| `FULL` | All log entries + worker.output lines interspersed |

The Surface itself does not export a lens — it owns its render. The zoom hint from `ctx` is a config value passed into `DashboardSurface.__init__`.

---

## 6. Progressive disclosure

### MINIMAL (`-q`, LIVE)
```
3 tasks, 1 working, 2 completed
```
Source: `_render_minimal` (`dashboard.py:264`). Unchanged.

### SUMMARY (default, LIVE)
```
Project — 47 facts | 3 decisions | 1 plan

  Task                    Status        Changes      Activity
  ────────────────────────────────────────────────────────────
  tui-design              working       +23           2m ago
    └ Design TUI layout
  auth-rework             completed     +89 -12       1h ago
```
Source: `_render_summary` (`dashboard.py:282`). Unchanged.

### DETAILED (`-i`, INTERACTIVE)

Full multi-region layout as shown in Section 1 mockup.
- Header: session status + fact count + key hints + clock
- Left pane: scrollable task table with title subtitle row
- Right pane: last 30 log entries for selected task
- Status bar: project summary + last-updated age

### FULL (`-i -v`, INTERACTIVE)

Same as DETAILED but:
- Detail pane: all facts including `worker.output` lines (not just structured facts)
- Detail pane header shows: `"task-name — status  pid=N  exit=N"`
- Clock includes seconds (already there)

---

## 7. Keyboard bindings

Handled in `DashboardSurface.on_key(key: str)`:

| Key | Action |
|---|---|
| `j` / `↓` (`\x1b[B`) | Move selection down in tasks pane |
| `k` / `↑` (`\x1b[A`) | Move selection up in tasks pane |
| `r` | Force re-fetch immediately |
| `q` / `Ctrl-C` | Quit (`self.quit()`) |
| `Tab` | Toggle focus: tasks pane ↔ detail pane |
| `[` / `PageUp` | Scroll detail pane up (when detail focused) |
| `]` / `PageDown` | Scroll detail pane down (when detail focused) |
| `gg` / `Home` | Jump to first task |
| `G` / `End` | Jump to last task |

`Focus` state: `self._focus: Literal["tasks", "detail"] = "tasks"`. Focused pane border is highlighted (not yet designed — see Open Questions).

---

## 8. Surface class skeleton

```python
# src/strange_loops/commands/dashboard.py (additions)

import asyncio
import time
from painted.tui import Surface
from painted.compose import join_horizontal, join_vertical
from painted.block import Block
from painted import Zoom, CliContext, OutputMode


class DashboardSurface(Surface):
    """Alt-screen persistent dashboard."""

    def __init__(self, ctx: CliContext):
        super().__init__(fps_cap=60)
        self._ctx = ctx
        self._state: DashboardState = _fetch()         # Initial sync fetch
        self._selected: int = 0                         # Selected task index
        self._task_scroll: int = 0                      # Task pane scroll offset
        self._detail_scroll: int = 0                    # Detail pane scroll offset
        self._focus: str = "tasks"                      # "tasks" | "detail"
        self._last_poll: float = time.monotonic()
        self._last_clock_tick: float = time.monotonic()
        # Regions — set by layout()
        self._tasks_w: int = 0
        self._main_h: int = 0

    def layout(self, w: int, h: int) -> None:
        self._tasks_w = max(38, w * 2 // 5)
        self._main_h = h - 4  # header + hsep + bsep + status

    def update(self) -> None:
        now = time.monotonic()
        if now - self._last_poll >= _POLL_INTERVAL:
            self._last_poll = now
            selected_name = self._selected_name()
            new_state = _fetch_with_detail(selected_name)
            if new_state.fact_total != self._state.fact_total:
                self._state = new_state
                self.mark_dirty()
        if int(now) != int(self._last_clock_tick):
            self._last_clock_tick = now
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return
        w, h = self._buf.width, self._buf.height
        p = current_palette()

        # Header (row 0)
        _render_header(...).paint(self._buf, 0, 0)
        # HSep (row 1)
        Block.text("─" * w, p.muted).paint(self._buf, 0, 1)
        # Tasks pane (rows 2..h-3)
        _render_tasks_pane(...).paint(self._buf, 0, 2)
        # VSep
        for y in range(2, h - 2):
            self._buf.put(self._tasks_w, y, "│", Style(dim=True))
        # Detail pane (rows 2..h-3)
        _render_detail_pane(...).paint(self._buf, self._tasks_w + 1, 2)
        # BSep (row h-2) — not needed if status bar is distinct enough; optional
        # Status bar (row h-1)
        _render_status_bar(...).paint(self._buf, 0, h - 1)

    def on_key(self, key: str) -> None:
        if key in ("q", "\x03"):  # q or Ctrl-C
            self.quit()
        elif key in ("j", "\x1b[B"):
            self._move_selection(1)
        elif key in ("k", "\x1b[A"):
            self._move_selection(-1)
        elif key == "r":
            self._state = _fetch_with_detail(self._selected_name())
            self.mark_dirty()
        elif key == "\t":
            self._focus = "detail" if self._focus == "tasks" else "tasks"
        elif key in ("[", "\x1b[5~"):  # [ or PageUp
            if self._focus == "detail":
                self._detail_scroll = max(0, self._detail_scroll - 1)
        elif key in ("]", "\x1b[6~"):  # ] or PageDown
            if self._focus == "detail":
                self._detail_scroll += 1
        self.mark_dirty()

    def _selected_name(self) -> str | None:
        if not self._state.tasks:
            return None
        idx = max(0, min(self._selected, len(self._state.tasks) - 1))
        return self._state.tasks[idx].name

    def _move_selection(self, delta: int) -> None:
        n = len(self._state.tasks)
        if n == 0:
            return
        self._selected = max(0, min(n - 1, self._selected + delta))
        # Scroll task pane to keep selected visible
        visible_h = self._main_h - 4  # header + sep + col header + sep rows in pane
        rows_per_task = 2  # name row + title row
        visible_tasks = visible_h // rows_per_task
        top = self._task_scroll
        bot = top + visible_tasks - 1
        if self._selected < top:
            self._task_scroll = self._selected
        elif self._selected > bot:
            self._task_scroll = self._selected - visible_tasks + 1


def _run_interactive(ctx: CliContext) -> int:
    surface = DashboardSurface(ctx)
    asyncio.run(surface.run())
    return 0
```

---

## 9. New fetch function

`_fetch()` already exists. Add `_fetch_with_detail(name: str | None)`:

```python
def _fetch_with_detail(name: str | None) -> DashboardState:
    """Extend _fetch() to include detail facts for selected task + session status."""
    sp = store_path()
    require_store(sp)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        tasks = fold_all_tasks(reader)
        all_facts = reader.facts_between(0, float("inf"))
        fact_total = reader.fact_total

        # Session status
        session_facts = [f for f in all_facts if f["kind"] in ("session.start", "session.end")]
        session_facts.sort(key=lambda f: f["ts"])
        session_active = False
        if session_facts:
            last = session_facts[-1]
            session_active = last["kind"] == "session.start"

        # Detail facts for selected task
        detail_facts: tuple[dict, ...] = ()
        if name:
            task_facts = _filter_task_facts(all_facts, name)  # from task.py:533
            task_facts.sort(key=lambda f: f["ts"])
            detail_facts = tuple(task_facts)

    rows: list[TaskRow] = []
    for task in tasks:
        rows.append(TaskRow(
            name=task["name"],
            title=task.get("title", ""),
            status=task.get("status", "unknown"),
            worktree=task.get("worktree"),
            activity=_task_activity(all_facts, task["name"]),
            changes=_changes_summary(task.get("worktree")),
        ))

    return DashboardState(
        tasks=tuple(rows),
        project=_project_summary(),
        fact_total=fact_total,
        session_active=session_active,
        session_fact_count=fact_total,
        selected_task=0,       # not used; selection lives on Surface
        detail_facts=detail_facts,
        last_fetched=time.monotonic(),
    )
```

`_filter_task_facts` is currently in `task.py:533`. Move it to `store.py` or `lifecycle.py`
so both `task.py` and `dashboard.py` can import it without a circular dep.
(`task.py` imports `lifecycle.py`; `dashboard.py` imports `lifecycle.py`; `store.py` imports neither — cleanest target.)

---

## 10. File changes required

| File | Change |
|---|---|
| `src/strange_loops/commands/dashboard.py` | Add `DashboardState` fields, `_fetch_with_detail`, `DashboardSurface`, `_run_interactive`, wire into `run_dashboard` via `handlers=` |
| `src/strange_loops/store.py` | Move `_filter_task_facts` here from `task.py` (or duplicate — smaller change) |
| `src/strange_loops/commands/task.py` | Update import of `_filter_task_facts` after move |
| `tests/test_dashboard.py` | Add tests for `DashboardState` new fields, `_fetch_with_detail`, Surface smoke test |

No new modules. No new dependencies. Surgical additions to existing files.

---

## 11. Design decisions (resolved)

1. **Focus indication**: Bold pane header. No border() calls needed — keeps region offsets simple.

2. **Worktree paths**: Always absolute. Confirmed — `str(wt_path)` in `cmd_task_assign`.

3. **`worker.output` in FULL zoom**: Works. Harness emits `payload["task"] == name` on every `worker.output` fact. `_filter_task_facts` matches correctly.

4. **Detail pane scroll clamp**: Yes. Clamp to `max(0, len(detail_facts) - available_h)` in `_move_detail_scroll` helper.

5. **`DashboardState.selected_task` field**: Remove. Selection lives on Surface, not in the data snapshot.

6. **`_changes_summary` performance**: Fine for <10 tasks. Defer caching until it's measurably slow.

7. **Minimum terminal size**: Fallback to LIVE/SUMMARY mode below 80 columns. Don't error — degrade gracefully.

8. **`run_cli` INTERACTIVE flag**: Already handled. `CliRunner` infers supported modes from `self.handlers`.

9. **`asyncio.run` inside `run_cli`**: Fine for CLI use. No nested event loop concern.

10. **Tick flash**: Not needed for v1. Status fold already reflects completion.
