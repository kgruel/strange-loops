# Companion GIFs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Five tight VHS companion GIFs for README sections — one per ladder rung plus hero.

**Architecture:** Small purpose-built scripts in `tapes/scripts/`, VHS tapes in `tapes/`, recorded with `vhs`. No tests — this is visual demo infrastructure.

**Tech Stack:** VHS (charmbracelet/vhs), painted Python API, bash

---

### Task 1: Write companion scripts

**Files:**
- Create: `tapes/scripts/show_hero.py`
- Create: `tapes/scripts/plain.py`
- Create: `tapes/scripts/styled.py`
- Create: `tapes/scripts/compose.py`

**Step 1: Create `tapes/scripts/show_hero.py`**

```python
from painted import show

show({"cpu": 67, "mem": 82, "disk": 45})
```

**Step 2: Create `tapes/scripts/plain.py`**

```python
print("deploy OK")
```

**Step 3: Create `tapes/scripts/styled.py`**

```python
from painted import Block, Style, print_block

print_block(Block.text("deploy OK", Style(fg="green", bold=True)))
```

**Step 4: Create `tapes/scripts/compose.py`**

```python
from painted import Block, Style, border, join_vertical, print_block, ROUNDED

header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
    Block.text("  /health:  200  12ms", Style(fg="green")),
)
print_block(border(join_vertical(header, status), chars=ROUNDED))
```

**Step 5: Verify all scripts run**

```bash
cd tapes/scripts
uv run python show_hero.py
uv run python plain.py
uv run python styled.py
uv run python compose.py
```

Expected: Each produces output without errors. `show_hero.py` shows a styled tree, `plain.py` shows plain text, `styled.py` shows green bold text, `compose.py` shows a bordered card.

**Step 6: Commit**

```bash
git add tapes/scripts/show_hero.py tapes/scripts/plain.py tapes/scripts/styled.py tapes/scripts/compose.py
git commit -m "feat: companion GIF scripts for README"
```

---

### Task 2: Write hero.tape (show three contexts)

**Files:**
- Create: `tapes/hero.tape` (overwrites existing)

**Step 1: Write the tape**

```
# Hero: show() adapts to context.
# Same script — TTY, pipe, JSON.

Output tapes/hero.gif

Set Shell "bash"
Set FontSize 18
Set Width 800
Set Height 400
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + cd + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts && python show_hero.py >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

# --- TTY: styled ---
Sleep 400ms
Type "python show_hero.py"
Enter
Sleep 2.5s

# --- Pipe: plain ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "python show_hero.py | cat"
Enter
Sleep 2.5s

# --- JSON ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "python show_hero.py --json"
Enter
Sleep 2s
```

**Step 2: Record and visually verify**

```bash
vhs tapes/hero.tape
open tapes/hero.gif
```

Expected: ~7s GIF showing styled tree, plain text, JSON output. Clean transitions.

**Step 3: Commit**

```bash
git add tapes/hero.tape tapes/hero.gif
git commit -m "feat: hero companion GIF — show() three contexts"
```

---

### Task 3: Write styled.tape (print → print_block)

**Files:**
- Create: `tapes/styled.tape`

**Step 1: Write the tape**

```
# Styled: print() → print_block()
# The visual pop.

Output tapes/styled.gif

Set Shell "bash"
Set FontSize 18
Set Width 800
Set Height 300
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + cd + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts && python styled.py >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

# --- Plain ---
Sleep 400ms
Type "python plain.py"
Enter
Sleep 2s

# --- Styled ---
Type "python styled.py"
Enter
Sleep 2.5s
```

**Step 2: Record and visually verify**

```bash
vhs tapes/styled.tape
open tapes/styled.gif
```

Expected: ~5s GIF. Plain "deploy OK" then green bold "deploy OK". Clear visual contrast.

**Step 3: Commit**

```bash
git add tapes/styled.tape tapes/styled.gif
git commit -m "feat: styled companion GIF — print vs print_block"
```

---

### Task 4: Write compose.tape (Block composition)

**Files:**
- Create: `tapes/compose.tape`

**Step 1: Write the tape**

```
# Compose: Blocks → card.
# The composition jump.

Output tapes/compose.gif

Set Shell "bash"
Set FontSize 18
Set Width 800
Set Height 350
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + cd + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts && python compose.py >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

# --- Card ---
Sleep 400ms
Type "python compose.py"
Enter
Sleep 3s
```

**Step 2: Record and visually verify**

```bash
vhs tapes/compose.tape
open tapes/compose.gif
```

Expected: ~4s GIF. Bordered card with reverse header, colored status. Single command, immediate wow.

**Step 3: Commit**

```bash
git add tapes/compose.tape tapes/compose.gif
git commit -m "feat: compose companion GIF — Block composition"
```

---

### Task 5: Write zoom.tape (CLI harness zoom spectrum)

**Files:**
- Create: `tapes/zoom.tape`

**Step 1: Write the tape**

Uses existing `demos/patterns/fidelity_health.py` via alias.

```
# Zoom: same render, three detail levels.
# The fidelity spectrum.

Output tapes/zoom.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 450
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + alias + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "alias health='python demos/patterns/fidelity_health.py'"
Enter
Sleep 200ms
Type "health -q >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

# --- Quiet: one line ---
Sleep 400ms
Type "health -q"
Enter
Sleep 2s

# --- Standard ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "health"
Enter
Sleep 3s

# --- Verbose: styled table ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "health -v"
Enter
Sleep 3.5s
```

**Step 2: Record and visually verify**

```bash
vhs tapes/zoom.tape
open tapes/zoom.gif
```

Expected: ~9s GIF. One-liner → multi-line → styled table. Clear zoom escalation.

**Step 3: Commit**

```bash
git add tapes/zoom.tape tapes/zoom.gif
git commit -m "feat: zoom companion GIF — CLI harness spectrum"
```

---

### Task 6: Write tui.tape (interactive TUI flash)

**Files:**
- Create: `tapes/tui.tape`

**Step 1: Write the tape**

```
# TUI: interactive dashboard flash.
# Alt screen, navigate, quit.

Output tapes/tui.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 450
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + alias + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "alias health='python demos/patterns/fidelity_health.py'"
Enter
Sleep 200ms
Type "health -q >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 300ms
Show

# --- Interactive ---
Sleep 400ms
Type "health -i"
Enter
Sleep 2s
Type "j"
Sleep 500ms
Type "j"
Sleep 500ms
Type "k"
Sleep 500ms
Type "q"
Sleep 1s
```

**Step 2: Record and visually verify**

```bash
vhs tapes/tui.tape
open tapes/tui.gif
```

Expected: ~5s GIF. Alt screen dashboard appears, cursor moves through service list, detail panel updates, clean exit.

**Step 3: Commit**

```bash
git add tapes/tui.tape tapes/tui.gif
git commit -m "feat: tui companion GIF — interactive dashboard"
```

---

### Task 7: Final review and cleanup

**Step 1: Review all GIFs together**

Open all five GIFs and assess:
- Consistent sizing and pacing
- Clean loop points
- Visual contrast between the five
- File sizes reasonable (target <300K each)

```bash
ls -lh tapes/{hero,styled,compose,zoom,tui}.gif
open tapes/hero.gif tapes/styled.gif tapes/compose.gif tapes/zoom.gif tapes/tui.gif
```

**Step 2: Note any adjustments needed**

Timing, sizing, or content tweaks get applied per tape and re-recorded.

**Step 3: Update HANDOFF.md and LOG.md**

Add companion GIFs entry to completed work.
