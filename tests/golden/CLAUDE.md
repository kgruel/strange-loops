# tests/golden/ — CLAUDE.md

## What This Is

Golden integration tests that exercise demos through the full render pipeline:
`data → render(ctx, data) → Block → plain text`. Each demo's output at every
zoom level is compared against committed golden files.

Golden files are the contract. When output changes legitimately,
`--update-goldens` regenerates them; the git diff is the review.

## Two Shapes

**run_cli demos** (testing, live, fidelity) expose `_fetch()` and
`_render(ctx, data)`. Parametrize over zoom levels, render to Block, compare.

**Direct-output demos** (rendering) have standalone functions that write to
stdout via `print_block`/`show`. Capture stdout with `redirect_stdout`, compare.

## The run_cli Pattern

Each test file is self-contained with three small helpers:

```python
import importlib.util, io, sys
from pathlib import Path
from painted import Block, CliContext, Zoom
from painted.fidelity import Format, OutputMode
from painted.writer import print_block

# Import demo without sys.path mutation
_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_<name>", _PROJECT / "demos" / "patterns" / "<name>.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render

def _block_to_text(block: Block) -> str:
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()

def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(zoom=zoom, mode=OutputMode.STATIC, format=Format.PLAIN,
                      is_tty=False, width=80, height=24)

@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_<name>_demo(golden, zoom):
    data = _fetch()
    block = _render(_ctx(zoom), data)
    golden.assert_match(_block_to_text(block), "output")
```

## The stdout-capture Pattern

For demos that call `print_block`/`show` directly:

```python
from contextlib import redirect_stdout
from io import StringIO

_DEMOS = {"explicit": _mod.demo_explicit, "custom": _mod.demo_custom, ...}

def _capture(fn) -> str:
    buf = StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()

@pytest.mark.parametrize("mode", list(_DEMOS.keys()))
def test_rendering_demo(golden, mode):
    golden.assert_match(_capture(_DEMOS[mode]), "output")
```

## Adding a New Demo Test

1. Ensure the demo has deterministic output (no real I/O in the render path)
2. Create `tests/golden/test_demo_<name>.py` following whichever pattern fits
3. Bootstrap: `uv run --package painted pytest tests/golden/test_demo_<name>.py --update-goldens -q`
4. Commit the golden files — they're the regression contract

## Non-Deterministic Demos

When `_fetch()` uses real I/O (e.g., `shutil.disk_usage`, `datetime.now()`),
use the demo's exposed sample data directly instead. See `test_demo_fidelity.py`
which uses `SAMPLE_DISK` rather than calling `_fetch()`.

## Infrastructure

- `conftest.py` — `Golden` class + `golden` fixture (auto-discovered by pytest)
- `_reset_ambient` autouse fixture — resets icon/palette ContextVars before
  each test so test execution order doesn't matter (demos can mutate these)
- `--update-goldens` flag — registered in root `tests/conftest.py` (pytest
  requires early hook registration, before collection reaches subdirectories)
- Demo imports use `importlib.util.spec_from_file_location` — no `sys.path`
  mutation, but must register in `sys.modules` for `dataclass` module lookup

## Commands

```bash
# Run golden tests only
uv run --package painted pytest tests/golden/ -q

# Regenerate all golden files
uv run --package painted pytest tests/golden/ --update-goldens -q

# Bootstrap one new demo
uv run --package painted pytest tests/golden/test_demo_<name>.py --update-goldens -q

# Full suite (unit + golden)
uv run --package painted pytest tests/ -q
```

## File Layout

```
tests/golden/
  CLAUDE.md              # this file
  conftest.py            # golden fixture + shared helpers
  test_demo_testing.py   # testing.py (TestSurface, emissions, layers)
  test_demo_live.py      # live.py (health checks, spinners, progress)
  test_demo_fidelity.py  # fidelity.py (disk usage, sample data)
  test_demo_rendering.py # rendering.py (lens API, custom lens, palette)
  goldens/               # committed expected output
    test_demo_testing/
    test_demo_live/
    test_demo_fidelity/
    test_demo_rendering/
```
