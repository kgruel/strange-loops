# Addendum: Primitive Atoms & The "Line" Abstraction

**Context:** Definition of the "Atoms" needed to make `ev-present` a complete content layer, replacing ad-hoc rendering logic.

## The Missing Primitives

Currently, `ev-present` only has `LogLine`. To be truly useful and standardize the "Content" layer, it needs to cover the 4 fundamental types of CLI sentences.

### 1. The Narrative Atom: `LogLine` (Existing)
*   **Purpose:** Storytelling. "What is happening right now?"
*   **Shape:** `message`, `source`, `level`, `timestamp`.
*   **Use Case:** Debug logs, general info, streaming events.

### 2. The State Atom: `StateLine` (New)
*   **Previous Name:** `StatusLine`
*   **Purpose:** Snapshot of an item's health or condition. This is the "Leaf Node" of your Trees.
*   **Shape:**
    *   `label`: "Database" (The subject)
    *   `state`: "healthy" | "error" | "warning" | "unknown" (Semantic state)
    *   `detail`: "5/5 connections" (Secondary info)
    *   `annotation`: "(0.5s)" (Meta info, e.g., duration)
*   **Why it's needed:** Replaces manual stitching of `Segment(icon)` + `Segment(text)` in app logic.

### 3. The Activity Atom: `WorkLine` (New)
*   **Previous Name:** `ProgressLine`
*   **Purpose:** Quantifiable work in progress.
*   **Shape:**
    *   `label`: "Downloading layer"
    *   `phase`: "extracting"
    *   `fraction`: `0.0` - `1.0`
    *   `unit`: "MB"
*   **Why it's needed:** Maps raw `Event.progress` to a standard "I am 50% done" model.
*   **Backend Rendering:**
    *   *Rich:* `ProgressBar` or `Spinner`.
    *   *Plain:* "50%".

### 4. The Data Atom: `FieldLine` (New)
*   **Previous Name:** `MetricLine`
*   **Purpose:** Key-Value facts.
*   **Shape:**
    *   `key`: "Uptime"
    *   `value`: "99.9%"
    *   `kind`: "identifier" | "numeric" | "text"
*   **Why it's needed:** For `inspect` commands or status details.
*   **Backend Rendering:**
    *   *Rich:* `Key: [bold]Value[/bold]`

### 5. The Emphasis Atom: `NoticeLine` (New)
*   **Purpose:** Alerts, Tips, or Summaries.
*   **Shape:**
    *   `title`: "Deploy Complete"
    *   `content`: "All stacks updated successfully."
    *   `severity`: "tip" | "note" | "warning"

## Solving the "Hybrid" Problem

With these atoms, the App's View Layer (`hlab/views.py`) stops being a "Translation Layer" and starts being a "Layout Layer."

**Before (Hybrid):**
```python
def build_tree(data):
    # Logic to pick icons, colors, and string concatenation lives here!
    if data['status'] == 'ok':
        icon = "[green]✓[/]"
    text = f"{icon} {data['name']}..."
    tree.add(text)
```

**After (With Atoms):**
```python
from ev_present import StateLine

def build_tree(data):
    # 1. Map to Atom (Pure Data)
    atom = StateLine(
        label=data['name'],
        state=data['status'], # "healthy", "error"
        detail=f"{data['count']} items"
    )

    # 2. Render Atom (Pure Presentation via Backend)
    line_ir = render_state_line(atom, config, state)

    # 3. Layout (Pure Structure)
    tree.add(to_rich(line_ir))
```

The App (`hlab`) owns the Tree. `ev-present` owns the Lines inside it.
