# Addendum: Operational Realities & Non-Functional Requirements

**Context:** Analysis of "Day 2" operational challenges (Concurrency, Safety, Performance, Ergonomics) and the architectural decisions required to handle them in `ev-toolkit`.

## 1. Concurrency & Asyncio

**The Challenge:**
In async environments, tasks interleave. If multiple tasks emit events concurrently, a linear output stream becomes unreadable chaos (`[A: Start]`, `[B: Start]`, `[A: 50%]`). Live Displays (like Rich) need to know which "Task" an event belongs to.

**The Solution: Hierarchical Emitters**
Borrowing from `structlog` and `tracing`:
*   `Emitter` must support a `.bind(**context)` method.
*   `.bind()` returns a lightweight **Proxy Emitter** that automatically injects the bound context into every emitted event.

```python
# Main flow
task_emitter = emitter.bind(task_id="download-1")
await download_file(task_emitter)
# Result: All events have data={'task_id': 'download-1', ...}
```

**Mandate:** `ev-toolkit` emitters must implement `.bind()`.

## 2. Error Handling: "Safe Mode"

**The Challenge:**
UI logic is fragile (terminal resizing, missing fonts, color themes). If the `RichEmitter` crashes during rendering, it must **never** take down the critical business logic (e.g., a database migration).

**The Solution: The "Ejection Seat"**
*   **Emission Never Raises:** The `emit()` method must be wrapped in a broad `try/except`.
*   **Fallback Strategy:**
    1.  Catch the render exception.
    2.  Disable the complex renderer (switch to "Safe Mode").
    3.  Dump the raw event to `stderr` (JSON/Text).
    4.  Log a warning (once).
    5.  Return control to the user's logic immediately.

**Mandate:** The `Emitter` is a "Best Effort" observer, not a critical path dependency.

## 3. Performance: The "Hot Loop" Tax

**The Challenge:**
A loop processing 1 million items might emit 1 million "progress" events.
*   1M Allocations + 1M Renders + 1M Writes = Massive slowdown.

**The Solution: Debouncing & Throttling**
Throttling belongs in the **Emitter**, not the User Logic.
*   The User Logic is allowed to emit at full speed (it is reporting the Truth).
*   The `RichEmitter` must cap screen refreshes (e.g., max 20Hz).
*   It should accumulate/aggregate events between frames and only draw the final state.

**Mandate:** `ev-toolkit` visual emitters must implement refresh rate limiting.

## 4. The "Global vs. Explicit" War

**The Challenge:**
Passing `emitter` arguments through 10 layers of function calls is high friction ("Boilerplate"). Libraries (e.g., database clients) may want to emit events without changing their function signatures.

**The Solution: Stick to Explicit (for v1.0)**
While `ContextVars` (Global State) allow "magic" logging, they introduce "Spooky Action at a Distance" in complex CLI tools (e.g., events appearing in the wrong progress bar).

*   **Decision:** We reject Globals for `v1.0`.
*   **Rationale:** The friction of dependency injection buys clarity and reliability.
*   **Escape Hatch:** If users revolt, a `get_current_emitter()` ContextVar can be added in `v1.1` as a secondary path, but Explicit Injection remains the primary design pattern.

## Summary of Operational Mandates

| Dimension | Policy | Implementation |
| :--- | :--- | :--- |
| **Concurrency** | **Task Identity via Binding** | `emitter.bind(task_id=...)` |
| **Safety** | **UI Failures are Non-Fatal** | `try/except` -> Fallback to stderr |
| **Performance** | **Decoupled Refresh Rate** | Debounce renders (e.g., 20fps) |
| **Ergonomics** | **Explicit Injection** | No global state (yet) |
