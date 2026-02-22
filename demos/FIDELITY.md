# Fidelity Pattern

This document describes the fidelity pattern implemented in the fidelis demo bench.

## General Pattern

CLI fidelity flags follow standard conventions:

| Flag | Meaning |
|------|---------|
| `-q, --quiet` | Minimal output, non-interactive |
| (default) | Normal operation |
| `-v` | More detail |
| `-vv` | Even more detail / debug info |

The flags are mutually exclusive: you cannot combine `-q` with `-v`.

## Navigation Fidelity

The demo bench expresses the general fidelity pattern as "navigation fidelity" - how much content you navigate through by default.

### Default Mode

Normal interactive slideshow with 2D navigation:
- **Left/Right**: Move between topics (sibling concepts)
- **Up/Down**: Move between depths (more/less detail)

Detail slides are "hidden" below parent slides - you must press down to see them.

```
intro -> cell -> style -> span -> ...
            |       |       |
        cell/   style/  span/
        detail  detail  detail
```

### Minimal Mode (-q)

Prints all slides inline and exits. No TUI, no interaction.

```bash
uv run python -m demos.bench -q
```

Use cases:
- Generating static documentation
- Quick content review
- Piping output to other tools

Interactive demos show as `[interactive demo: spinner]` placeholders.

### Styled Mode (-v)

Detail slides become part of the primary left/right navigation flow. The navigation graph is "inverted" so you see all content linearly:

```
intro -> cell -> cell/detail -> style -> style/detail -> ...
            ^                      ^
         up takes you back      up takes you back
```

This mode is useful when you want to see all content without needing to explore down.

### Interactive Mode (-vv)

Adds source view showing the code that builds each slide. Press `s` to toggle the source panel.

```bash
uv run python -m demos.bench -vv
```

This fulfills the "self-documenting slides" goal - the slides literally show how they're built.

## Implementation Details

### Graph Inversion (-v)

The inversion follows a convention:
- Parent slide `X` has `nav.down = "X/detail"`
- Child slide `X/detail` has `nav.up = "X"`

After inversion:
- Parent's `nav.right` points to detail
- Detail's `nav.left` points back to parent
- Detail's `nav.right` continues the main flow

### Source Capture (-vv)

Source code is captured at module load via `inspect.getsource()`. The `capture_slide_source()` function parses the `build_slides()` function to extract individual slide definitions.

The source panel uses the same syntax highlighting as code blocks in slides.

## The CLI → TUI Continuum

Fidelity can be understood as movement along an output sophistication spectrum:

```
Level 0: Plain text (no styling)
Level 1: Styled text (ANSI, inline)
Level 2: Composed layout (boxes, borders, still inline)
Level 3: Interactive TUI (alternate screen)
Level 4: Rich TUI (layers, modals, complex state)
```

The key insight: **fidelity isn't just "more text" - it can trigger mode transitions**.

```
print_block()  ←────────────────────→  Surface
   (inline)            -v/-vv             (TUI)
```

fidelis makes this transition smooth because the same primitives (Block, Span) work in both paths. Content is mode-agnostic; only the output path changes.

### Flow Triggers Beyond Fidelity

Other factors that might drive CLI → TUI transitions:

| Trigger | Pattern |
|---------|---------|
| **Duration** | Start inline, upgrade to TUI if > 2s |
| **TTY detection** | TUI if interactive, inline if piped |
| **Explicit flag** | `--tui` / `--no-tui` |
| **Content volume** | Inline if <20 lines, TUI if more |
| **Error state** | Inline for success, TUI for errors (to explore) |

### Fidelity Patterns by Domain

**Build/Task Runner**
```
-q  → "✓ 47 passed" (level 1, exit)
    → progress bar + summary (level 2, exit)
-v  → live task tree, expandable (level 3)
-vv → timing waterfall, dependency graph (level 4)
```

**Log Viewer**
```
-q  → "12 errors" (level 0)
    → formatted entries (level 2)
-v  → scrollable TUI with filtering (level 3)
-vv → TUI + raw/parsed toggle, regex debugger (level 4)
```

**Status Dashboard**
```
-q  → "3 healthy, 1 degraded" (level 1)
    → service grid (level 3)
-v  → expanded metrics panels (level 3+)
-vv → internal health checks, request tracing (level 4)
```

**API Client**
```
-q  → response body only (level 0, pipeable)
    → formatted response + status (level 2)
-v  → headers, timing (level 2)
-vv → request/response TUI, history, replay (level 3)
```

### Future Directions for fidelis

**Currently available:**
- Block/Span work for both CLI and TUI modes
- `print_block()` for inline output
- Surface for interactive TUI

**Potential additions:**
- `is_interactive()` helper (TTY detection)
- `OutputContext` that encapsulates mode decision
- Progressive render: start inline, transition to TUI if long-running
- Graceful degradation patterns

## Expressing Fidelity in Other Apps

The fidelity pattern can be expressed differently depending on the application:

| App Type | -q | default | -v | -vv |
|----------|----|---------|----|-----|
| Demo bench | Print inline | Interactive | Show all detail | Show source |
| Log viewer | Errors only | Warnings+ | Info+ | Debug |
| Build tool | Silent | Summary | Per-file | Commands |
| API client | Response only | Status + body | Headers | Raw HTTP |

The key insight: fidelity controls **how much information flows to the user**, but what "information" means varies by domain.

## Usage

```bash
# Default: interactive slideshow
uv run python -m demos.bench

# Minimal: print all slides
uv run python -m demos.bench -q

# Styled: detail slides in main flow
uv run python -m demos.bench -v

# Interactive: with source view (s to toggle)
uv run python -m demos.bench -vv

# Help
uv run python -m demos.bench --help
```
