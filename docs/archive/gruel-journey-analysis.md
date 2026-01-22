# The Evolution of gruel.network Scripts

## A Real-World Case Study in Tooling Evolution: From Bash to Generator-Driven Python

This document traces the evolutionary journey of the homelab scripting infrastructure at gruel.network, from ad-hoc bash scripts through a mature, componentized generator system. It's a story of discovering repeating patterns, building abstractions, and scaffolding complexity.

---

## Stage 1: The Bash Era (Historical)

**Problem:** A homelab with multiple stacks (infra, media, dev, minecraft, etc.) needed centralized operational scripts. Tasks like backups, deployments, and health checks were frequent, manual, and error-prone.

**Solution:** Shell scripts with common helpers.

### Evidence

**Key artifacts:**
- `/scripts/lib/common.sh` — Bash helper functions (colors, host resolution from Ansible inventory, YAML metadata lookups)
- `/scripts/*.sh` — Operational scripts like:
  - `rebuild-lab.sh` — Destructive VM rebuild (Terraform destroy → apply → Ansible bootstrap)
  - `deploy-docs.sh` — Documentation deployment via rsync
  - `emergency-backup.sh` — Safety backoff before destructive operations
  - `media-stack-recover.sh` — NFS cascade recovery
  - `bootstrap-dns.sh` — Technitium DNS setup
  - `sync-homeassistant.sh` — HAOS deployment sync

### Patterns

Each bash script:
1. Sources `lib/common.sh` for color output and host resolution
2. Resolves IPs/users from Ansible inventory (`yq` queries on `ansible/inventory.yml`)
3. Runs SSH commands against stack hosts
4. Outputs colored status messages
5. Implements script-specific logic inline (lots of repetition)

### Limitations Discovered

- **No structured output:** Scripts output text only; hard to integrate with monitoring/alerting
- **Repetitive boilerplate:** Every script re-implements SSH connection logic, error handling, host resolution
- **No type safety:** Bash has no schema checking for data passed between components
- **Hard to test:** Logic is embedded in shell scripts; extracting testable units is awkward
- **CLI is ad-hoc:** Each script has its own flag parsing; no unified command structure

---

## Stage 2: Early Python Migration (Jan 5 - Jan 20, 2025)

**Problem:** Bash couldn't scale to more complex logic. Media audit/fix operations needed:
- HTTP API calls to Radarr (REST API)
- SSH remote execution with ffprobe/ffmpeg analysis
- Rich terminal UI with live updates
- Structured data processing and filtering

**Solution:** Rewrite in Python while maintaining script-centric model.

### Evidence

**Key artifacts (v1):**
- `status.py` (Jan 6) — Health check of homelab stacks via SSH + docker compose ps
- `logs.py` (Jan 6) — Log aggregation
- `sync-uptime-kuma.py` (Jan 5) — Sync Uptime Kuma monitors declaratively
- `media-fix.py` (Jan 20) — Fix corrupt/mislabeled movies in Radarr
- `media-audit.py` (Jan 20) — Deep scan media library for corruption
- `alert-status.py` (Jan 20) — Aggregate alerts from Prometheus + Grafana
- `lint_ingress.py` (Jan 6) — Ingress config validation
- `scaffold_vm.py` (Jan 6) — VM provisioning helper

### Key Characteristics

**Each script still:**
1. Does its own argument parsing (`argparse`)
2. Implements its own Rich UI
3. Imports Rich directly for tables/progress bars/text styling
4. Has inline error handling with `try/except`

**But now:**
- Use httpx for async HTTP calls to APIs (Radarr, Uptime Kuma, Prometheus)
- SSH via `subprocess` + ffmpeg/ffprobe for media analysis
- Rich library for formatted output

### Example: media-fix.py (v1)

```python
#!/usr/bin/env python3
"""Fix mislabeled or corrupt movie files in Radarr."""

@dataclass
class RadarrConfig:
    host: str
    api_key: str
    def get(self, endpoint: str, **params) -> dict | list:
        # HTTP API call boilerplate
    def delete(self, endpoint: str, **params) -> None:
        # More boilerplate

def load_config() -> RadarrConfig:
    # Inline config loading
    return RadarrConfig(
        host="192.168.1.40:7878",
        api_key="38f9f156c694487baf2bfb9f4355a02d",  # ⚠️ Hardcoded!
    )
```

### Emerging Patterns

- **Output discipline:** "Events/UI → stderr, Result JSON (when --json) → stdout"
- **Mode detection:** Check for `--json` flag to decide between Rich UI and JSON output
- **Data structure:** Each script collects results and can emit them as JSON

### Limitations Still Present

- **Still ad-hoc:** No unified framework. Each script reinvents CLI patterns.
- **Boilerplate copy-paste:** If you want async HTTP + SSH + Rich UI, you're copying structure from media-fix to the next script
- **No signal discipline:** Output events are inconsistent across scripts
- **Schema-less:** No way to define what signals a script emits; documentation is prose or comments

---

## Stage 3: The "ev" Framework Era (Jan 5 - Jan 21, 2025)

**Problem:** Repeating patterns of CLI scripts created an opportunity for abstraction. The user had been developing `ev` (a separate project in `/Users/kaygee/Code/ev`) — a structured event contract for CLI tools.

**Solution:** Adopt the `ev` library to add:
1. Structured event/signal types
2. Multiple output modes (JSON, Rich, Plain) automatically
3. Result type for consistent success/error returns
4. Event recording for debugging/replay

### Evidence

**Key artifacts:**
- `_common.py` (Jan 22) — Shared utilities extracting patterns from individual scripts
  - `BaseRichEmitter` — Base class for Rich-based emitters
  - `BasePlainEmitter` — Base class for plain text emitters
  - `StatusRenderer` — Generic renderer for status-style UIs
  - `live_tree()` — Context manager for live-updating tree UI

- `lib/__init__.py` — Marks lib as importable Python package
- `lib/jinja_parser.py` (Jan 21) — Jinja2 AST parser for Home Assistant state machine logic

### Key Refactoring: status.py → status.py (with ev)

**Before (v1):**
```python
from rich.console import Console

def main():
    console = Console(stderr=True)
    # Manual mode detection
    # Manual Rich/plain output
    # Inline error handling
```

**After (v1 with ev):**
```python
from ev import Emitter, Event, Result
from ev_toolkit import add_standard_args, signal
from _common import StatusRenderer, live_tree

async def operation(emitter: Emitter, args: argparse.Namespace) -> Result:
    """The actual operation — separated from CLI wiring."""
    # Logic returns Result.ok(...) or Result.error(...)
    # Emits signals via emitter.emit(Event.log_signal(...))

if __name__ == "__main__":
    raise SystemExit(
        run(
            operation,
            add_args=add_args,
            description="Check health of homelab stacks",
            prog="status",
        )
    )
```

### What ev Adds

1. **Emitter abstraction:** `from ev_toolkit import run` auto-handles:
   - `--json` → JsonEmitter (structured JSON to stdout)
   - `--plain` → PlainEmitter (text to stderr)
   - TTY detection → Rich UI (styled text to stderr)
   - `--record file.jsonl` → Event recording for debugging

2. **Result type:** All operations return `Result.ok(summary, data={...})` or `Result.error(msg, data={...})`

3. **Event types:** `Event.log()`, `Event.log_signal()` — structured event emission

4. **Signal discipline:** Distinguish between:
   - Lifecycle events (started, completed) — brackets the operation
   - Notable events (errors, attention-worthy items) — selective emission
   - Data schemas — TypedDicts for Result data

### Example: status.py (v1 with ev)

```python
from ev_toolkit import run, signal

async def operation(emitter: Emitter, args: argparse.Namespace) -> Result:
    emit_started = signal(emitter, "status.started")
    emit_unhealthy = signal(emitter, "stack.unhealthy")

    # Lifecycle signal
    emit_started(stacks=stacks, concurrency=args.concurrency)

    results = await check_all(stacks)

    # Notable signals only for unhealthy stacks
    for stack_result in results:
        if stack_result["status"] == "unhealthy":
            emit_unhealthy(
                stack=stack_result["stack"],
                healthy_count=stack_result["healthy_count"],
                total_count=stack_result["total_count"],
                unhealthy_services=[...],
            )

    return Result.ok("status check complete", data={"stacks": results, "counts": {...}})
```

### Dead Ends and Experiments

**Alert-status.py (v1):**
- 918 lines, hand-written
- Fetches alerts from Prometheus, renders Grafana dashboard state
- Uses Rich tables and styled output
- **Problem:** Inconsistent signal usage; no schema for what signals it emits
- **Result:** Abandoned in favor of v2 (see next stage)

**status.py (v1):**
- Integrated ev framework
- But signals still informal; schema is commented prose

---

## Stage 4: The Generator Wave (Jan 21 - Jan 22, 2025)

**Insight:** Even with `ev`, each script still hand-writes boilerplate:
1. TypedDict schemas for signal types (repetitive type hints)
2. `signal(emitter, "name")` emitter creation
3. Argument parsing setup
4. Operation signature + frame code

**Solution:** Create a **code generator** that reads declarative specs and scaffolds the entire CLI harness.

### Evidence

**Key artifacts:**

- **gruel_gen.py** (810 lines, Jan 21) — The scaffold generator
  - Reads `.cli.kdl` specs (KDL = KDL Document Language, a config format)
  - Outputs fully scaffolded Python scripts with:
    - PEP 723 metadata (uv runnable)
    - TypedDict signal schemas
    - Argument parser setup
    - Signal emitter stubs
    - TODO comments for implementation
  - Validates signal names, detects collisions, enforces reserved flags

- **specs/*.cli.kdl** — Declarative specs for tools:
  - `example.cli.kdl` — Simple template
  - `media-fix-v3.cli.kdl` — Full example with lifecycle/notable signals
  - `media-audit-v3.cli.kdl` — Async operation with data schemas
  - `status-v2.cli.kdl` — Complex multi-signal tool
  - `sync-uptime-kuma-v2.cli.kdl` — HTTP API tool
  - `alert-status-v2.cli.kdl` — Multi-source aggregator

### The KDL Spec Format

**Example: media-fix-v3.cli.kdl**

```kdl
name "media-fix"
about "Fix mislabeled or corrupt movie files in Radarr"
version "3.0.0"

// Dependencies
dep "httpx>=0.27"

// Arguments
arg "<query>" help="Movie title to search for" required=false

// Flags
flag "-n --dry-run" help="Show what would happen..."
flag "-y --yes" help="Skip confirmation prompts"
flag "--auto" help="Auto-fix all issues"

// Lifecycle signals - emit once at start/end
lifecycle "fix.started" {
    mode "str"
    query "str?"
    dry_run "bool"
}

lifecycle "fix.completed" {
    mode "str"
    deleted "int"
    relabeled "int"
}

// Notable signals - emit only when notable
notable "fix.movie_found" {
    title "str"
    year "int?"
    has_file "bool"
    quality "str?"
}

// Data schemas - in Result, no emitters
data "movie.details" {
    title "str"
    quality "str"
}

// Result shape
result {
    mode "str"
    deleted_count "int"
    relabeled_count "int"
}
```

### Generated Output

Running `uv run gruel_gen.py specs/media-fix-v3.cli.kdl` produces:

```python
#!/usr/bin/env python3
"""
media-fix
Fix mislabeled or corrupt movie files in Radarr
Version: 3.0.0

Output discipline:
  Events/UI → stderr
  Result JSON (when --json) → stdout
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "ev @ file:///Users/kaygee/Code/ev",
#     "httpx>=0.27",
# ]
# ///

from typing import TypedDict

class FixStartedSignal(TypedDict, total=False):
    """Schema for fix.started (lifecycle)."""
    mode: str
    query: str | None
    dry_run: bool

class FixCompletedSignal(TypedDict):
    """Schema for fix.completed (lifecycle)."""
    mode: str
    deleted: int
    relabeled: int

def add_args(parser: argparse.ArgumentParser) -> None:
    """Add tool-specific args/flags."""
    parser.add_argument("<query>", ..., help="Movie title to search for")
    parser.add_argument("-n", "--dry-run", action="store_true", ...)

def operation(emitter: Emitter, args: argparse.Namespace) -> Result:
    """
    Fix mislabeled or corrupt movie files in Radarr

    Signal emitters below, ready to call with your data.
    Replace the TODO section with your logic.
    """
    show_ui = not bool(getattr(args, 'json', False))
    console = Console(stderr=True) if show_ui else None

    # Lifecycle signals - emit once at operation start/end
    emit_started = signal(emitter, "fix.started")
    emit_completed = signal(emitter, "fix.completed")

    # Notable signals - emit only when something worth attention happens
    emit_movie_found = signal(emitter, "fix.movie_found")

    # ============================================================
    # TODO: Implement your operation
    # ============================================================
    # ...decision flowchart comment...

    emitter.emit(Event.log('TODO: implement operation()', level='info'))

    return Result.ok(
        'TODO: summary message',
        data={
            'mode': '',
            'deleted_count': 0,
            'relabeled_count': 0,
        },
    )
```

### The Three Versions Pattern

For complex scripts, the user created versioned iterations:

1. **media-audit.py (v1, Jan 20):** Hand-written, direct Rich UI
2. **media-audit-v2.py (Jan 21):** Refactored with ev framework
3. **media-audit-v3.py (Jan 21):** Generated from KDL spec via gruel_gen

Each version is **not a replacement** — they coexist. This allows:
- Running different versions for comparison/testing
- Preserving old implementations while experimenting
- Gradual adoption of the generator pattern

### Signal Discipline Formalized

The generator enforces conceptual clarity through three signal kinds:

**lifecycle** — Emit once at operation start/end; brackets the operation
```python
emit_started(total_movies=count, quality_filter=quality)
# ... operation runs ...
emit_completed(total=count, suspicious=sus_count, corrupt=cor_count)
```

**notable** — Emit only when something warrants attention (NOT for every item)
```python
# ✗ BAD: Noisy recording
for movie in all_movies:
    emit_movie(title=movie.title, ...)  # Creates huge recording

# ✓ GOOD: Only notable events
for movie in all_movies:
    if movie.status in NOTABLE_STATUSES:
        emit_movie(title=movie.title, status=movie.status, ...)
```

**data** — Schema-only TypedDicts; no emitters. Put in Result.data instead:
```python
# This is data, not an event:
return Result.ok("audit complete", data={
    "all_movies": [movie_details],  # Put collection in Result
    "summary": audit_stats,          # Not as signals
})
```

The generator includes this decision flowchart in every generated script:

```
SIGNAL vs DATA decision:
  Is this something that HAPPENS, or something I'm COLLECTING?
    |
    +-- COLLECTING (rules, history, items)
    |     -> Define as `data` in spec, put in Result
    |
    +-- HAPPENS (alert fired, target down)
          -> Is EVERY occurrence attention-worthy?
               |
               +-- NO: gate it
               |     if item.status in NOTABLE_STATUSES:
               |         emit_item(...)
               |
               +-- YES: rare, but ok (lifecycle start/end)
```

### Shared Library: _common.py

As scripts generalize, common patterns extracted to a shared module:

```python
class BaseRichEmitter:
    """Base class for Rich-based emitters."""
    def _on_emit(self, event): raise NotImplementedError
    def _render(self): raise NotImplementedError

class StatusRenderer(Generic[T]):
    """Generic renderer for status-style UIs."""
    def get_key(self, result: T) -> str: ...
    def get_status(self, result: T) -> str: ...
    def get_counts(self, result: T) -> tuple[int, int]: ...
    def render_complete(self, item: str, result: T) -> Any: ...

@contextmanager
def live_tree(items, on_result, renderer, console, *, title="Status"):
    """Live-updating tree UI for async operations."""
    # Handles Rich Live plumbing; you provide renderer
```

This enables status-like scripts (health checks, audit results) to share UI logic while providing their own data interpretation.

---

## Stage 5: Current State (Jan 22, 2025)

### What Exists Today

1. **Mixed Portfolio:**
   - 6 bash scripts (operational/destructive tasks)
   - 18 Python scripts (data processing/monitoring)
     - v1 hand-written: status.py, logs.py, media-fix.py, alert-status.py (~22-33KB each)
     - v2 ev-refactored: status.py has ev imports but pre-dates generator
     - v3 generator-driven: media-fix-v3.py, media-audit-v3.py, alert-status-v2.py, status-v2.py

2. **Generator Maturity:**
   - `gruel_gen.py` is fully functional, well-documented
   - KDL spec format is extensible (supports async, deps, all signal kinds)
   - Specs directory organized by tool
   - README.md documents patterns (signal discipline, progress bars, lifecycle signal UIs)

3. **Emerging Shared Infrastructure:**
   - `_common.py` (478 lines) — Emitter base classes, StatusRenderer, live_tree
   - `lib/jinja_parser.py` (561 lines) — Specialized parser for Home Assistant
   - `lib/common.sh` — Still used by bash scripts

### The "Groping Toward" Nature

The evolution is visible in the file timestamps and commit messages:

```
Jan 5  - sync-uptime-kuma.py (first ev-powered script, 351 lines)
Jan 6  - status.py (675 lines, complex async operation)
Jan 6  - logs.py (671 lines)
Jan 20 - media-audit.py, media-fix.py (first media tools, hand-written)
Jan 20 - alert-status.py (918 lines, complex aggregation)
Jan 21 - media-audit-v2.py, media-fix-v2.py (minimal refactor to ev)
Jan 21 - gruel_gen.py (810 lines, the breakthrough)
Jan 21 - media-audit-v3.py, media-fix-v3.py (first generated scripts)
Jan 21 - alert-status-v2.py (generator-driven version)
Jan 21 - status-v2.py (regenerated, cleaner than v1)
Jan 22 - _common.py (componentized reusable patterns)
```

### Current Pain Points & Next Frontiers

**What's Working:**
- Generator reduces boilerplate from ~700 lines → ~500 lines (25% reduction)
- Signal discipline makes outputs uniform and testable
- KDL specs are human-readable "contracts" for tools
- Multiple output modes (JSON, Rich, Plain) work automatically
- Event recording (`--record file.jsonl`) enables debugging/replay

**What's Not Yet Solved:**

1. **Rich UI Componentization:**
   - `StatusRenderer` is generic, but each tool still writes custom render logic
   - There's no "menu" of pre-built UI patterns (progress bar, tree, table, spinner)
   - Generator could emit Rich UI stubs based on signal shape

2. **Shared Library Discovery:**
   - Common utilities in `_common.py` are great, but not yet a "standard library"
   - Tools still import inconsistently (some use StatusRenderer, some write custom)
   - Could formalize as PyPI package or uv-runnable library

3. **Async Orchestration:**
   - Generator supports `async true`, but concurrency patterns aren't templated
   - Each async tool (status.py, sync-uptime-kuma) has its own `asyncio.gather` logic
   - Could template semaphore management, retry logic, timeout patterns

4. **Error Handling & Retries:**
   - SSH timeouts, HTTP errors, file I/O — each script handles ad-hoc
   - No standard retry decorator or error context
   - Generator could emit try-catch skeletons

5. **Testing:**
   - No test framework for generated scripts
   - Hard to test "did this emit the right signal?"
   - Could add test fixture generation

---

## Key Insights

### 1. Patterns Emerge Through Repetition

The user didn't start with a grand architecture. Instead:
- Write bash scripts → discover common host resolution logic
- Port to Python → discover common Rich UI patterns
- Write 5 Python scripts → extract BaseRichEmitter, StatusRenderer
- Write 10 scripts → generator becomes obvious

### 2. Versioning as Exploration

Rather than breaking changes, the user versions scripts (v1, v2, v3):
- Preserves working code
- Allows side-by-side comparison
- Supports gradual adoption of new patterns
- Real experimentation with low risk

### 3. The Generator is the Breakthrough

Before: Each script reinvented argument parsing, signal setup, output modes.

After: Declarative spec → boilerplate-free scaffold. The user focuses on `operation()` logic, not CLI wiring.

### 4. Signal Discipline is Conceptual, Not Technical

The generator enforces it through comments and type hints, but the real power is the **decision flowchart**: "HAPPENS vs COLLECTING?"

This mental model propagates consistency without runtime checks.

### 5. Shared Libraries Follow, Not Lead

`_common.py` didn't exist initially. It emerged after status-v2.py, media-audit-v3.py, and alert-status-v2.py all needed the same UI patterns. Only then was it extracted.

---

## The Evolutionary Path Visualized

```
Stage 1: Bash Era
├─ lib/common.sh (shared host resolution, colors)
├─ rebuild-lab.sh, deploy-docs.sh, media-stack-recover.sh, etc.
└─ Problem: No structured output, repetitive SSH logic

Stage 2: Early Python (ad-hoc CLI scripts)
├─ status.py (Jan 6, 675 lines, hand-written Rich UI)
├─ logs.py (Jan 6, 671 lines)
├─ media-fix.py (Jan 20, 695 lines, hardcoded config)
├─ media-audit.py (Jan 20, 534 lines)
├─ alert-status.py (Jan 20, 918 lines, complex!)
└─ Problem: Each script reinvents arg parsing, output modes, error handling

Stage 3: ev Framework Adoption (structured events)
├─ ev (external dependency: Result, Emitter, Event, output modes)
├─ ev-toolkit (run(), signal(), add_standard_args())
├─ status.py (refactored with ev imports)
└─ Problem: Still hand-written boilerplate; no schema for signals

Stage 4: Generator + KDL Specs
├─ gruel_gen.py (810 lines, reads .cli.kdl → generates scaffold)
├─ specs/media-fix-v3.cli.kdl (declarative tool contract)
├─ specs/status-v2.cli.kdl (async, multiple signals)
├─ media-fix-v3.py (generated, 693 lines, 25% less boilerplate)
├─ media-audit-v3.py (generated, 497 lines, cleaner)
├─ status-v2.py (generated, 491 lines, cleaner than v1)
└─ Problem: UI patterns not yet templated; shared lib informal

Stage 5: Componentization (current frontier)
├─ _common.py (478 lines, BaseRichEmitter, StatusRenderer, live_tree)
├─ lib/jinja_parser.py (561 lines, specialized parser)
└─ Next: UI component library, standard retry/timeout patterns, test fixtures
```

---

## The Story in Code

### From Bash to Python to Generator

**Bash (Stage 1):**
```bash
#!/bin/bash
source lib/common.sh
IP=$(resolve_ip "media")
ssh "$IP" "docker compose ps" | process_output
```

**Python v1 (Stage 2):**
```python
import argparse
import httpx
from rich.console import Console

def main():
    parser = argparse.ArgumentParser()
    # ... parse args ...
    console = Console(stderr=True)
    # ... manual mode detection ...
    results = [fetch_and_audit(m) for m in movies]
    for r in results:
        console.print(...)  # Rich rendering
```

**Python v1 + ev (Stage 3):**
```python
from ev import Result, Emitter
from ev_toolkit import run, signal

async def operation(emitter: Emitter, args: argparse.Namespace) -> Result:
    emit_started = signal(emitter, "audit.started")
    emit_movie = signal(emitter, "audit.movie")

    emit_started(total_movies=len(movies))
    results = [audit(m) for m in movies if is_notable(m)]
    for r in results:
        emit_movie(...)

    return Result.ok("audit complete", data={"movies": results})
```

**Python v3 + Generator (Stage 4 & 5):**

Spec:
```kdl
name "media-audit"
lifecycle "audit.started" { total_movies "int" }
notable "audit.movie" { title "str", status "str" }
result { movies "list" }
```

Generated + Implemented:
```python
# ← Generator created all this boilerplate ↓

def operation(emitter: Emitter, args: argparse.Namespace) -> Result:
    """Your implementation here."""
    emit_started = signal(emitter, "audit.started")
    emit_movie = signal(emitter, "audit.movie")

    # ← You write only the logic ↓
    emit_started(total_movies=len(movies))
    results = [audit(m) for m in movies if is_notable(m)]
    for r in results:
        emit_movie(title=r.title, status=r.status)

    return Result.ok("audit complete", data={"movies": results})
```

---

## Lessons for Building Evolving Tooling Systems

1. **Start with ad-hoc scripts:** Wait for patterns to emerge; don't over-design upfront.

2. **Extract when you copy-paste:** Once you've written the same boilerplate 3+ times, extract it.

3. **Version, don't replace:** Keep old versions around. Migrations are easier when both paths work.

4. **Use declarative specs for repetition:** When you're generating a lot of similar code, consider a DSL.

5. **Separate concerns clearly:**
   - Infrastructure (signal emission, output modes, errors) ← Generator handles this
   - Business logic (what the script does) ← You write this
   - UI components (how results look) ← Shared library handles this

6. **Signal discipline is powerful:** A clear conceptual model (HAPPENS vs COLLECTING) can enforce consistency without enforcement mechanisms.

7. **Gradual adoption:** Don't rewrite everything at once. Keep old patterns working while new patterns mature.

---

## What's Left to Explore

This journey isn't over. Frontier areas:

1. **CLI-as-a-library:** Could each script be run as a Python module? Enable programmatic calls?
2. **UI component library:** Pre-built Progress, Tree, Table, Spinner components that emit signals
3. **Standardized retries/timeouts:** Decorator patterns for resilience
4. **Test fixture generation:** Generate mock emitters and test cases from KDL specs
5. **Self-documenting:** Generate man pages, help texts, YAML schemas from specs
6. **Distributed execution:** Run scripts on remote hosts; aggregate results
7. **Script composition:** Chain scripts together; pass signals between them

The evolution shows how real-world tooling ecosystems mature: through experimentation, pattern extraction, and incremental abstraction.
