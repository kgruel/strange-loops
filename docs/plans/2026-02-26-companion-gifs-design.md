# Companion GIFs for README

Five purpose-built VHS tapes, one per README section. Small, single-concept, 5-8 seconds each. No narration — commands speak for themselves.

## GIF Map

| GIF | README Section | Duration | Script |
|-----|---------------|----------|--------|
| `hero.gif` | Top (show) | ~7s | `app.py` |
| `styled.gif` | Print styled output | ~5s | `plain.py`, `styled.py` |
| `compose.gif` | Compose | ~5s | `compose.py` |
| `zoom.gif` | CLI harness | ~8s | `fidelity_health.py` |
| `tui.gif` | Full TUI | ~5s | `fidelity_health.py -i` |

## Tape Designs

### 1. `hero.tape` — show() three contexts

Three runs of the same 2-line script. The code doesn't change — the context does.

```
python app.py              → styled tree (TTY detected)
python app.py | cat        → plain text (pipe detected)
python app.py --json       → JSON serialization
```

Script (`tapes/scripts/show_hero.py`):
```python
from painted import show
show({"cpu": 67, "mem": 82, "disk": 45})
```

Hidden clear between each run. LoopOffset 0%.

### 2. `styled.tape` — print → print_block

Visual contrast between plain print and styled print_block.

```
python plain.py            → "deploy OK" in default terminal color
python styled.py           → "deploy OK" in green bold
```

Script `plain.py`:
```python
print("deploy OK")
```

Script `styled.py`:
```python
from painted import Block, Style, print_block
print_block(Block.text("deploy OK", Style(fg="green", bold=True)))
```

Hidden clear between runs.

### 3. `compose.tape` — Block composition

Single command. The output is the wow — a bordered card.

```
python compose.py          → bordered card with reverse header + colored status
```

Script `compose.py`:
```python
from painted import Block, Style, border, join_vertical, print_block, ROUNDED

header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
    Block.text("  /health:  200  12ms", Style(fg="green")),
)
print_block(border(join_vertical(header, status), chars=ROUNDED))
```

### 4. `zoom.tape` — CLI harness zoom spectrum

Three zoom levels of the same health dashboard.

```
health -q                  → one-liner summary
health                     → multi-line with icons
health -v                  → styled table with borders and timing
```

Uses existing `demos/patterns/fidelity_health.py`. Hidden alias + clear between runs.

### 5. `tui.tape` — interactive TUI flash

Quick alt-screen flash with navigation.

```
health -i                  → alt screen, dashboard appears
j, j, k (navigate)
q (quit, back to terminal)
```

Uses existing `fidelity_health.py -i`.

## Shared Settings

All tapes:
- Shell: bash
- Theme: Catppuccin Mocha
- FontSize: 16 (hero: 18)
- Width: 800, Height: 400-500
- Padding: 16
- BorderRadius: 8
- TypingSpeed: 35-40ms
- LoopOffset: 0%

Hidden preamble pattern:
```
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Type "export PATH=$PWD/demos:$PATH"
Enter
Type "cd tapes/scripts"  # for script-based tapes
Enter
# Warm cache run if needed
Type "python show_hero.py >/dev/null 2>&1"
Enter
Type "clear"
Enter
Show
```

## File Layout

```
tapes/
  hero.tape          → hero.gif
  styled.tape        → styled.gif
  compose.tape       → compose.gif
  zoom.tape          → zoom.gif
  tui.tape           → tui.gif
  scripts/
    show_hero.py     # show() with 3-key dict
    plain.py         # print("deploy OK")
    styled.py        # print_block with green bold
    compose.py       # bordered card composition
```

Zoom and TUI tapes use existing `demos/patterns/fidelity_health.py` via the `painted-demo` wrapper (or alias).

## Relationship to Existing Tapes

The 7 existing narrative tapes (paint-it, ladder, three-ways, hero, show, components, health) remain as standalone demos. The companion GIFs are shorter, README-specific, and may overlap in concept but differ in format (no narration, tighter pacing, single concept per GIF).
