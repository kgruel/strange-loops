# Addendum: ev vs. TUI Frameworks (Bubble Tea / Textual)

**Context:** Comparison of the `ev` ecosystem against dominant TUI (Terminal User Interface) frameworks like Charm's Bubble Tea (Go) and Textual (Python).

## 1. The Paradigm Shift: "The Component Loop" vs. "The Event Pipeline"

**Bubble Tea / Textual (The App Frameworks)**
Built on **The Elm Architecture (TEA)**.
*   **Model:** The single source of truth for application state.
*   **Update:** A pure function: `(Model, Message) -> (NewModel, Cmd)`.
*   **View:** A pure function: `Model -> UI`.
*   **Control:** The framework owns the main loop. Inversion of Control is absolute.

**ev (The Script Architecture)**
*   **Model:** Distributed in your domain logic (variables in functions).
*   **Update:** Procedural. Your function executes step-by-step.
*   **View:** Deferred. The `Emitter` collects facts; the `Renderer` draws them.
*   **Control:** *You* own the control flow. The "UI" is a side-effect of your logic running.

## 2. The Critical Difference: "Application" vs. "Script"

*   **TUI Frameworks are for Interactive Applications.**
    Best for long-lived sessions: Dashboards, Editors, File Managers. Writing a linear script ("Do A, then B") requires managing a complex state machine.

*   **ev is for Scripts (that look like Applications).**
    Best for linear procedures: Deploy Scripts, Build Tools, Migrations. You keep control of the flow. `ev` enables **Rich UI (Spinners, Progress)** without the **Inversion of Control** required by TUI frameworks.

## 3. Comparison: Handling "Progress"

**The Scenario:** Download 3 files sequentially.

**In Bubble Tea (The "Hard" Way):**
1.  Define `Model` with `currentFileIndex`.
2.  Define `Msg` types (`DownloadStarted`, `Finished`).
3.  Write `Update` state machine.
4.  Write `View` logic.
5.  *Result:* High boilerplate for simple sequences.

**In ev (The "Easy" Way):**
1.  Just write your code:
    ```python
    for file in files:
        emitter.emit(Event.progress(f"Downloading {file}"))
        # ... do work ...
        emitter.emit(Event.progress(f"Done {file}"))
    ```
2.  *Result:* The Emitter handles the visual state.

## 4. Integration Potential

`ev`'s "Atom" concept (`StateLine`, `WorkLine`) aligns with the **View** layer of Bubble Tea.

You could theoretically write a **Bubble Tea application** that *consumes* an `ev` event stream. This confirms that `ev-present` is essentially a **"Headless UI"** library. It defines the *What* (Atoms), which can be rendered by `rich` (current plan) OR by a full TUI framework if you ever built a persistent dashboard.

## Summary

| Feature | Bubble Tea / Textual | ev Ecosystem |
| :--- | :--- | :--- |
| **Primary Goal** | Interactive Applications | Observability for Scripts |
| **Control Flow** | Framework owns the loop | You own the loop |
| **State** | Centralized `Model` | Implicit in flow |
| **Complexity** | High (State Machines) | Low (Function calls) |

**Conclusion:** `ev` is not "Bubble Tea for Python." `ev` is **"Rich for Architecture."** It provides visual fidelity without forcing a rewrite of linear scripts.
