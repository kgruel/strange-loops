# Addendum: ev vs. structlog

**Context:** A comparative analysis of `ev` and `structlog`, exploring their shared architectural DNA and their divergent goals (UX vs. Diagnostics).

## 1. The Shared DNA (Where they are the Same)

`ev` clearly learned its most important lessons from `structlog`.

**1. "Events are Data, not Strings"**
*   **Structlog:** `log.info("user logged in", user_id=123)` → `{"event": "user logged in", "user_id": 123}`
*   **ev:** `Event.log("user logged in", user_id=123)` → `Event(kind="log", data={"user_id": 123})`
*   **Shared Philosophy:** Defer rendering until the last possible moment. Don't bake `f-strings` into your logic. Let the "Renderer" (or "Processor") decide if it's JSON, text, or colored output.

**2. The Pipeline / Processor Concept**
*   **Structlog:** Uses a chain of "Processors" to mutate the event dict (add timestamps, format exceptions) before output.
*   **ev:** Uses "Adapters" (conceptually) to transform `Event` → `IR` → `Rich`. It’s the same "Pipe and Filter" architecture.

**3. Separation of Concerns**
*   Both libraries insist that the code *generating* the event shouldn't care *where* it goes (file, stdout, Sentry, or a TUI).

## 2. The Great Divergence (Where they Differ)

While the *mechanism* is similar, the *intent* is radically different.

### A. The Audience: "Why did it break?" vs "What is it doing?"

*   **Structlog (Diagnostics):**
    *   **Audience:** The Developer / Sysadmin.
    *   **Goal:** Post-mortem analysis. "Grep the logs to find why the DB connection failed."
    *   **Nature:** Append-only. A stream of discrete moments in time.
    *   **Cardinality:** High volume (debug logs).

*   **ev (Experience):**
    *   **Audience:** The End User (Human) or The Automation Script (Machine).
    *   **Goal:** Real-time situational awareness. "Is the deploy still running? Did it finish?"
    *   **Nature:** Stateful. A progress event *updates* previous knowledge; it doesn't just append to history.
    *   **Cardinality:** Curated volume (meaningful facts).

### B. The State Model: Implicit vs. Explicit

This is the biggest architectural difference.

*   **Structlog (Implicit / Context Vars):**
    *   Relies heavily on **Thread Locals** or **Context Vars** (`structlog.contextvars.bind_contextvars`).
    *   *Pattern:* You bind `request_id` at the start of a request, and magically every log function deep in the stack has it.
    *   *Why it works for logs:* You rarely pass a "Logger" object around; you just import `structlog.get_logger()`.

*   **ev (Explicit / Dependency Injection):**
    *   Relies on passing an **`Emitter`** object explicitly.
    *   *Pattern:* `command(ctx) -> operation(emitter) -> sub_task(emitter)`.
    *   *Why it's necessary:* CLIs are often structurally complex. You might be running 3 stacks in parallel. If you rely on global context vars, your "Progress Bar A" might accidentally receive updates meant for "Progress Bar B". Explicit handles (`Emitter`) guarantee that events go to the specific UI element representing that task.

### C. The "Live Update" Problem

*   **Structlog:** Has no concept of "updating" a log line. Once emitted, it is written.
    *   *Scenario:* Downloading a file.
    *   *Structlog:* Emits 100 lines: `Downloading 1%`, `Downloading 2%`... (Spam).

*   **ev:** Treats specific events as **State Patches**.
    *   *Scenario:* Downloading a file.
    *   *ev:* Emits 100 events. The **Backend** receives them and recognizes: "This is a progress update for task ID `download-1`. I should *redraw* the existing progress bar, not print a new line."
    *   *Insight:* `ev` is closer to **Redux** (stream of actions updating a state) than to standard logging.

## 3. Why structlog couldn't handle hlab

You *could* technically force `structlog` to do what `ev` does, but it fights the design.

**The "Kind" Problem:**
In `structlog`, everything is a log entry with a "level" (debug/info/error).
In a CLI, you have semantically distinct things:
1.  **Narrative:** "Connecting..." (Log)
2.  **Metric:** "Duration: 5s" (Data)
3.  **Artifact:** "Output saved to /tmp/x" (Result)
4.  **Signal:** "Stack is healthy" (State)

If you use `structlog`, you end up overloading the `level` or adding a magic `type` field that you have to parse out everywhere. `ev` promotes these to first-class citizens (`Event.kind`).

**The "Result" Problem:**
`structlog` has no concept of "Final Result" or "Exit Code". It just streams logs until the program stops.
`ev` introduces the **`Result`** contract. It forces the CLI command to return a specific, authoritative conclusion (`status="ok", data={...}`). This is crucial for the "Machine Readable" contract (e.g., `hlab status --json` needs to output *one* final JSON object, not a stream of JSON logs).

## 4. Summary

*   **`structlog`** is for the **Developer** to understand the **System** (Append-only, High Volume, Implicit Context).
*   **`ev`** is for the **User** to understand the **Operation** (Stateful, Low Volume, Explicit Context).

`ev` is what happens when you apply `structlog`'s rigorous "structured data" philosophy to the problem of "drawing a UI".