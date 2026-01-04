# Addendum: Landscape Research & "The Missing Middle"

**Context:** Analysis of where `ev` fits in the broader software landscape, validated against patterns in Rust, PowerShell, and Enterprise CLIs.

## 1. The Python Landscape: A "Coupled" Ecosystem

The current state of Python CLI development looks like this:

| Layer | Tools | Status |
| :--- | :--- | :--- |
| **Input (Controller)** | Typer, Click, argparse | **Solved.** Excellent DX for parsing args. |
| **Logic (Model)** | Your Domain Code | **Solved.** Python standard library. |
| **Wiring (ViewModel)** | **(The Void)** | **Missing.** Ad-hoc `print()` statements. |
| **Output (View)** | Rich, Textual | **Solved.** Beautiful rendering engines. |

**Where `ev` fits:**
`ev` sits in "The Void". It prevents your Logic layer from importing `rich`. Instead of "printing", your logic "records facts" (`ev`). Instead of "formatting", your presentation layer "interprets facts" (`ev-present`).

**Competitors:**
*   **`structlog` / `loguru`:** The closest pattern match. They emit structured events. However, they are culturally and technically tuned for *developer diagnostics* (debugging), not *user UX* (progress bars, tables, artifacts).
*   **`textual`:** A full application framework (TUI). It owns the whole loop. `ev` is lighter—it's just the *pipeline* for standard CLIs.

## 2. The Cross-Language "Pattern Match"

Your architecture aligns strongly with advanced patterns seen in other ecosystems, validating the approach.

### A. The "PowerShell Pattern" (Windows)
PowerShell is unique because it pipes **.NET Objects**, not text.
*   **PowerShell:** `Get-Process | Where-Object ... | Format-Table`
*   **`ev` Equivalent:** `Operation yields Events -> Emitter collects -> Renderer formats`
*   **Validation:** You are essentially building a "Python Object Pipeline" for CLI output. This allows the *user* (via `OutputMode`) to decide if they want a Table (Rich) or Raw Data (JSON) *after* the operation has finished.

### B. The "Tracing Subscriber" Pattern (Rust)
In Rust, the `tracing` ecosystem separates "instrumentation" from "subscription".
*   **Rust:** Libraries emit "spans" and "events" without knowing who is listening. A `tracing-indicatif` subscriber can listen to these events and draw progress bars automatically.
*   **`ev` Equivalent:** Your `Emitter` is the Subscriber. Your `Event` is the Span.
*   **Validation:** This proves that decoupling "progress updates" from "progress bar rendering" is a scalable, modern architecture.

### C. The "React Render Tree" (Web)
`ev-present` is a "Reconciliation" layer.
*   **React:** `Data` -> `Virtual DOM` -> `Real DOM`
*   **`ev-present`:** `Event` -> `Line/Segment IR` -> `Rich Text / Plain Text`
*   **Validation:** By creating an Intermediate Representation (IR) of "semantic lines" (`ev-present`), you allow the "backend" to be swappable (Rich vs. Plain vs. HTML) just like React allows React Native or Web.

## 3. The "Hidden" Enterprise Standard

You aren't the first to build this, but others hide it as "Implementation Details."

*   **AWS & Azure CLIs:**
    *   These tools strictly separate "API Result" from "Output Format".
    *   Internally, they have an engine that takes a raw JSON response, applies a `JMESPath` query (filter), and *then* sends it to a formatter (Table, Text, JSON).
    *   **The Difference:** They hardcode this pipeline for their specific APIs. You are democratizing it as a general-purpose library (`ev-runtime`).

*   **HashiCorp (Terraform/Vault):**
    *   Famous for having distinct "Human" vs "Machine" output modes.
    *   They treat their JSON output as a **Stable Contract** (versioned schema), while the Human output is allowed to change. This mirrors your `Result` (Contract) vs `Event` (Narrative) split perfectly.

## Summary Table

| Concept | The `ev` Ecosystem | The Industry Equivalent |
| :--- | :--- | :--- |
| **Data Flow** | **`ev` (Events)** | **PowerShell** (Object Pipeline) |
| **Separation** | **`ev-present` (IR)** | **React** (Virtual DOM) |
| **Wiring** | **`ev-runtime` (Context)** | **AWS CLI** (JMESPath/Output Formatters) |
| **Observability** | **`ev.Emitter`** | **Rust** (`tracing-subscriber`) |
