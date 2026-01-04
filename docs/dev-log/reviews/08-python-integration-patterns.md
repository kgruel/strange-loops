# Addendum: Python Integration Patterns

**Context:** Detailed exploration of how the `ev` ecosystem integrates with existing Python CLI frameworks (Input) and Presentation libraries (Output).

## 1. Input Frameworks (The "Controller" Layer)

The `ev-runtime` layer is designed to be the universal adapter for any CLI framework.

### A. Typer / Click Integration
Typer is imperative. Integration happens via Dependency Injection or Context Managers.

**Pattern:** The `RuntimeContext` Dependency.

```python
import typer
from ev_toolkit import StandardContext

app = typer.Typer()

@app.command()
def deploy(
    stack: str,
    json: bool = False,
    verbose: int = typer.Option(0, "--verbose", "-v", count=True),
):
    # 1. Initialize Context (Wiring)
    ctx = StandardContext(json_flag=json, verbose_count=verbose)
    
    # 2. Resolve Resources
    stack_obj = ctx.require(stack, kind="stack")

    # 3. Execute with Emitter
    with ctx.emitter(target=stack) as emitter:
        result = do_deploy(stack_obj, emitter)
        emitter.finish(result)

    raise typer.Exit(ctx.exit_code(result))
```

### B. Cappa Integration (Declarative)
Cappa uses type-hinted data classes. This is the cleanest integration because `ev-runtime` can be a fast dependency.

**Pattern:** The `Annotated` Dependency.

```python
import cappa
from typing import Annotated
from ev_runtime import RuntimeContext

# Define a provider for cappa
def get_context(flags: GlobalFlags) -> RuntimeContext:
    return RuntimeContext(...)

@cappa.command
@dataclass
class Deploy:
    stack: str
    ctx: Annotated[RuntimeContext, cappa.Dep(get_context)]

    def __call__(self):
        # Usage is identical to Typer, but injection is automatic
        with self.ctx.emitter() as emitter:
            ...
```

### C. Argparse (Standard Library)
For zero-dependency scripts.

**Pattern:** The Manual Wiring.

```python
import argparse
from ev_toolkit import StandardContext

parser = argparse.ArgumentParser()
parser.add_argument("--json", action="store_true")
args = parser.parse_args()

ctx = StandardContext(json_flag=args.json)
# ... standard flow ...
```

---

## 2. Output Frameworks (The "View" Layer)

### A. Rich (The Canonical Backend)
This is the default target for `ev-present`.

**Pattern:** The `ev-toolkit` Adapter.
*   **Mechanism:** `ev-toolkit` provides a `RichEmitter`.
*   **Flow:** `Event` -> `StateLine` (Atom) -> `Render Function` -> `Line` (IR) -> `RichBackend` -> `rich.Text/Tree`.
*   **User Experience:** The user never imports `rich` directly. They just emit events. The `RichEmitter` handles the `Live` display loop, the Spinner animation, and the Progress Bar updates.

### B. Textual (The TUI App)
Textual owns the event loop, which conflicts with `ev`'s "Script" model.
However, `ev` can act as a **Data Source** for a Textual app.

**Pattern:** The `TextualWatcher` (Sidecar).
*   **Scenario:** You have a long-running background script (powered by `ev`) and you want a Textual dashboard to monitor it.
*   **Mechanism:**
    1.  Script runs with `FileEmitter("status.jsonl")` (or a socket).
    2.  Textual App runs `tail -f status.jsonl`.
    3.  Textual App parses `Event` objects.
    4.  Textual App updates its internal Reactive State (`self.progress = event.data['percent']`).

**Pattern:** The `Headless` Integration (Embedded).
*   **Scenario:** You are building a Textual app, but you want to reuse your `ev`-instrumented domain logic.
*   **Mechanism:**
    1.  Create a `TextualEmitter` that wraps the App's `post_message()`.
    2.  Pass this emitter to your domain function.
    3.  Domain function runs in a worker thread.
    4.  Textual Main Loop receives `Event` messages and updates widgets.

```python
# Textual Integration
class DeploymentWorker(Worker):
    def run(self):
        # Adapts ev calls to Textual messages
        emitter = TextualMessageEmitter(self.app)
        do_deploy(emitter)

class Dashboard(App):
    def on_ev_progress(self, event):
        self.query_one(ProgressBar).update(total=event.total, progress=event.current)
```

### C. Web / HTML (FastAPI + HTMX)
Since `ev-present` Atoms are semantic (`StateLine`, `WorkLine`), they map naturally to HTML components.

**Pattern:** The Server-Sent Events (SSE) Stream.
1.  **Backend:** `FastAPI` endpoint yields `Event.to_json()` lines as SSE.
2.  **Frontend:** HTMX connects to `/stream`.
3.  **Client-Side Rendering:** A tiny JS function (or Python template) maps:
    *   `kind="log"` -> `<div class="log-line">`
    *   `kind="progress"` -> `<progress value="...">`

---

## 3. The "Unified" Experience

By standardizing on `ev`, a Python developer gains a superpower: **"Write Once, Run Anywhere"** for operational logic.

*   **CLI:** `python deploy.py` -> Beautiful Rich UI.
*   **CI/CD:** `python deploy.py --json` -> Structured logs for Splunk/Datadog.
*   **Dashboard:** `textual run dashboard.py` -> Monitoring TUI.
*   **Web:** `fastapi run server.py` -> Remote status page.

The `ev` ecosystem effectively turns any Python script into an **Observable Operation** that fits natively into whatever environment it runs in.
