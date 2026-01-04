# Addendum: Architecture Critique & The "Uncanny Valley"

**Context:** A deep dive into the structural weaknesses of the current state, specifically the "Partial Contract" problem and the complexity of the "Four-Layer Mapping".

## The "Uncanny Valley" of Abstraction

You have successfully decoupled "Logic" from "Presentation," but in doing so, you have introduced significant **friction** and **incomplete abstractions**.

### 1. The "Partial Contract" Problem (The Biggest Risk)
You extracted `LogLine` and `Line` to `ev-present` to be "backend neutral."
**BUT:** Your `hlab` views (`views.py`) still import `rich.Tree`, `rich.Spinner`, and `rich.Text`.

*   **The Issue:** You are effectively lying to yourself about being "backend neutral."
    *   Simple logs are neutral (`ev-present`).
    *   Complex UI (Trees, Tables, Layouts) is still hard-coupled to Rich.
*   **The Consequence:** If you ever wanted to port this to a web dashboard or a different TUI library, `ev-present` works, but your *Views* blow up. You haven't actually solved the coupling problem for the hard stuff (structure), only for the easy stuff (text lines).

### 2. The "Four-Layer Mapping" Tax
To print a single line of status output, data now travels through four distinct shapes:

1.  **Domain Model:** `Stack(name="media", status="healthy")`
2.  **Event (Fact):** `Event(kind="metric", data={"stack": "media", ...})`
3.  **IR (Model):** `LogLine(message="media healthy", level="info")` -> `Line(Segment(...))`
4.  **Backend (View):** `rich.Text("media healthy", style="green")`

*   **The Issue:** Every time you add a field (e.g., "uptime"), you have to touch:
    *   The Domain Emitter (to emit it).
    *   The Render Function (to map it to IR).
    *   The Backend Adapter (if it requires new styling hints).
*   **The Consequence:** Simple features become "plumbing" tasks. The cognitive load of remembering "which layer handles the color green?" increases.

### 3. Loss of Type Safety at the Boundary
`ev` Events rely on `data: dict[str, Any]`.

*   **The Issue:** Your domain code is typed (`mypy` happy). Your render code receives `Any`.
*   **The Consequence:** If you rename a field in your domain emitter from `service_name` to `svc_name`, your render function won't know until runtime when it crashes or prints `None`. You have severed the static analysis link between "Producer" and "Consumer."

### 4. The "Least Common Denominator" Trap
By creating `ev-present` as a generic IR, you risk limiting your UI to only what your IR supports.

*   **The Issue:** Rich has amazing features: Gradients, Hyperlinks, Markdown, Syntax Highlighting, Emojis, Spinners.
*   **The Consequence:** If `ev-present` doesn't have a semantic concept for "Hyperlink," you can't use it easily without breaking the abstraction (e.g., passing raw Rich markup in the `text` field, which defeats the purpose of the IR).

### 5. Debugging the Debugger
You are building a tool (`hlab`) to debug your homelab.
`ev` is the tool to debug `hlab`.
Who debugs `ev`?

*   **The Issue:** When you rely on `print()`, it works even if the app is crashing. When you rely on an async event bus with multiple layers of transformation, a bug in the *emitter* can swallow errors.
*   **The Consequence:** If `ev-runtime` fails to wire the emitter correctly, or if `ev-present` raises an exception during rendering, you might get **silent failures** or empty output.

## The Verdict: Accept the Coupling

The architecture works **if and only if** you accept that `ev-present` is for *content*, and the app (`hlab`) is for *structure*.

*   **Correct:** `ev-present` handles text, logs, labeling, coloring concepts.
*   **Correct:** `hlab` handles layout, widgets, trees, interactivity (using Rich directly).

If you accept that `hlab` owns the "View" (Rich Trees) and `ev-present` owns the "ViewModel" (LogLines/Text), the friction is manageable and the testability gains are worth it.
