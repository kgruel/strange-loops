# VHS Demo Recordings

Terminal GIF recordings using [charmbracelet/vhs](https://github.com/charmbracelet/vhs) to showcase painted's progressive fidelity story.

## Goal

Three tapes, three stories:

| Tape | Story | Duration | Use |
|------|-------|----------|-----|
| `hero.tape` | Progressive fidelity: same data, escalating presentation | ~30-40s | README hero GIF |
| `show.tape` | `show()` zero-config: TTY, JSON, pipe auto-detection | ~10-15s | Docs, sharing |
| `components.tape` | Visual richness: widgets, big text, color | ~20s | Docs, sharing |

## Wrapper Script

`demos/painted-demo` — dispatcher that maps short names to demo scripts. Keeps tape commands readable.

```bash
painted-demo fidelity -q     # → demos/patterns/fidelity.py -q
painted-demo show --json     # → demos/patterns/show.py --json
painted-demo widgets         # → demos/apps/widgets.py
```

VHS tapes add `demos/` to PATH in a hidden preamble.

## Hero Tape Sequence

```
painted-demo fidelity -q       → one-line summary
painted-demo fidelity          → multi-line with ✓/✗ marks
painted-demo fidelity -v       → styled borders, colors, durations
painted-demo fidelity -i       → full TUI, navigate j/k, quit with q
```

## Show Tape Sequence

```
painted-demo show              → styled auto-detected output
painted-demo show --json       → JSON serialization
painted-demo show | cat        → plain text, no ANSI
```

## Components Tape Sequence

```
painted-demo widgets           → spinners, progress, list, text input
painted-demo big-text          → block characters with color cycling
```

## Style

- Typed commands with realistic speed — feels like someone exploring
- Pauses between commands to let output breathe
- Hidden preamble for PATH setup
- Terminal theme: consistent across all tapes
