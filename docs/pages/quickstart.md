# Quickstart

Five copy/paste steps: install → first `Block` → first composition → first `print_block` → first `run_cli`.

---

## 1) Install

```bash
pip install painted
```

---

## 2) First `Block`

Create a `Block` (an immutable rectangle of styled cells):

```python
from painted import Block, Style

block = Block.text("deploy OK", Style(fg="green", bold=True))
```

---

## 3) First composition

Compose blocks into a small “card” using functions like `join_vertical` and `border`:

```python
from painted import Block, Style, border, join_vertical, ROUNDED

header = Block.text(" api-gateway ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 2/3 ready", Style(fg="yellow")),
    Block.text("  /health:  200  12ms", Style(fg="green")),
)
card = border(join_vertical(header, status), chars=ROUNDED)
```

---

## 4) First `print_block`

Print a `Block` to stdout. When stdout is a TTY, painted emits ANSI styles; when piped, it emits plain text.

```python
from painted import print_block

print_block(card)
```

---

## 5) First `run_cli`

Use `run_cli()` when you want one entrypoint that can produce quiet/verbose output, JSON, and/or an interactive TUI.

```python
import sys
from painted import Block, CliContext, run_cli

def render(ctx: CliContext, data: dict) -> Block:
    return Block.text(f"status: {data['status']}")

def fetch() -> dict:
    return {"status": "ok"}

if __name__ == "__main__":
    run_cli(sys.argv[1:], render=render, fetch=fetch)
```

Run it:

```bash
python myapp.py
python myapp.py --json
python myapp.py -q
python myapp.py -v
python myapp.py -i
```

