# The ev Ecosystem: Architecture Review & Roadmap

**Date:** January 4, 2026
**Status:** Strategic Review

## 1. The Core Insight: The "Missing Middle"

The Python CLI landscape currently has a structural void between **Logic** (Domain Code) and **Output** (Rich/Textual). Most CLIs couple these tightly via `print()`, making testing and reuse impossible.

`ev` fills this void by introducing a **ViewModel** layer:
*   **Logic** emits semantic **Events** (Facts).
*   **Presentation** interprets Facts into **Display Models**.
*   **Backend** renders Models to the terminal.

👉 **Deep Dive:** [01-landscape-research.md](./01-landscape-research.md) (PowerShell/Rust/AWS comparisons)

---

## 2. Current State Assessment

We have successfully built the **Raw Materials**:

1.  **`ev`**: The Contract (Event/Result). Stable.
2.  **`ev-present`**: The IR (Line/Segment). Early.
3.  **`ev-runtime`**: The Wiring (Mode/Context). Beta.

### The "Uncanny Valley" Problem
While architecturally pure, the current setup has **high friction** ("Activation Energy").
*   **Partial Contract:** `ev-present` handles logs, but Apps (`hlab`) still own Trees/Layouts.
*   **Four-Layer Mapping:** Data travels Domain → Event → IR → Backend → View.
*   **Assembly Required:** Users must wire everything themselves.

👉 **Deep Dive:** [02-architecture-critique.md](./02-architecture-critique.md) (Structural weaknesses analysis)
👉 **Deep Dive:** [04-api-surface-review.md](./04-api-surface-review.md) (Technical critique of `ev-runtime`)
👉 **Deep Dive:** [10-final-red-team.md](./10-final-red-team.md) (Red team analysis of inconsistencies)

---

## 3. The Unification Vision: `ev-toolkit`

To solve the friction, we need a "Battery-Included" framework.

**Proposed Name:** `ev-toolkit` (or `ev-rich`)

**Responsibilities:**
1.  **The Adapter:** Maps `ev.Event` → `ev-present` Atoms.
2.  **The Default Backend:** Maps Atoms → `rich` renderables.
3.  **The Standard Context:** A concrete `RuntimeContext` pre-wired with the Default Backend.

This allows `ev`, `ev-present`, and `ev-runtime` to remain pure/neutral, while the Toolkit provides the "FastAPI-like" experience.

### The Missing Atoms
To make `ev-present` capable of supporting this toolkit, it needs to expand beyond `LogLine`.

*   **`StateLine`**: For health/condition (Stacks, Services).
*   **`WorkLine`**: For activity/progress (Deploys).
*   **`FieldLine`**: For data/metrics (Info).
*   **`NoticeLine`**: For alerts (Summaries).

👉 **Deep Dive:** [03-primitive-atoms.md](./03-primitive-atoms.md) (Detailed definitions of new atoms)

---

## 4. Context & Opportunities

We have explored how this ecosystem compares to other tools and what new capabilities it unlocks.

*   **vs Structlog:** `ev` is for User Experience (Stateful), `structlog` is for System Diagnostics (Append-only).
*   **vs TUI Frameworks:** `ev` is for Linear Scripts (You own the loop), Bubble Tea/Textual are for Apps (Framework owns the loop).
*   **Multi-Modal Output:** The architecture allows simultaneous broadcasting to UI, Log Files, Databases, and Web Dashboards.

👉 **Deep Dive:** [05-structlog-comparison.md](./05-structlog-comparison.md)
👉 **Deep Dive:** [06-tui-comparison.md](./06-tui-comparison.md)
👉 **Deep Dive:** [07-render-opportunities.md](./07-render-opportunities.md)
👉 **Deep Dive:** [08-python-integration-patterns.md](./08-python-integration-patterns.md)

---

## 5. Operational Mandates

To survive in production, `ev-toolkit` must adhere to strict non-functional requirements.

*   **Concurrency:** Support `emitter.bind()` for task identity.
*   **Safety:** UI rendering failures must never crash the app.
*   **Performance:** Visual emitters must throttle/debounce updates.
*   **Ergonomics:** Stick to explicit injection for v1.

👉 **Deep Dive:** [09-operational-realities.md](./09-operational-realities.md)

---

## 6. Implementation Roadmap

### Phase 1: Harden the Foundation
*   [ ] **API Review:** Fix `ev-runtime` TTY detection split and Exit Code precedence.
*   [ ] **Clarify Scope:** Update `ev-present` docs to disclaim ownership of "Layouts".

### Phase 2: Expand the Atoms (`ev-present`)
*   [ ] Add `StateLine`, `WorkLine`, `FieldLine`, `NoticeLine`.

### Phase 3: Build the Unifier (`ev-toolkit`)
*   [ ] Create `ev-toolkit` package.
*   [ ] Implement **Standard Adapters** (Event → Atom).
*   [ ] Implement **Rich Backend** (Atom → Rich).
*   [ ] Implement **Standard Context** (Pre-wired).

### Phase 4: Adoption
*   [ ] Migrate `hlab` to use `ev-toolkit`.
*   [ ] Delete `hlab`'s internal backend and context code.

---

*"The goal is not to hide the complexity of the terminal, but to manage it through semantic layers."*
