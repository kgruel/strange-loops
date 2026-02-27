# tests/golden/ — CLAUDE.md

## What This Is

Golden integration tests that exercise demos through the full render pipeline:
`data → render(ctx, data) → Block → plain text`. Each demo's output at every
zoom level is compared against committed golden files.

Golden files are the contract. When output changes legitimately,
`--update-goldens` regenerates them; the git diff is the review.

## The Pattern

Every `run_cli` demo exposes `_fetch()` and `_render(ctx, data)`. A golden
test imports the demo module via `importlib`, renders at each zoom level with
a fixed `CliContext` (STATIC, PLAIN, width=80), and asserts the plain-text
output matches.

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

## Adding a New Demo Test

1. Ensure the demo has deterministic `_fetch()` and `_render(ctx, data)` functions
2. Create `tests/golden/test_demo_<name>.py` following the pattern above
3. Bootstrap: `uv run --package painted pytest tests/golden/test_demo_<name>.py --update-goldens -q`
4. Commit the golden files — they're the regression contract

## Non-Deterministic Demos

When `_fetch()` uses real I/O (e.g., `shutil.disk_usage`, `datetime.now()`),
use the demo's exposed sample data directly instead. See `test_demo_fidelity.py`
which uses `SAMPLE_DISK` rather than calling `_fetch()`.

## Infrastructure

- `conftest.py` — `Golden` class + `golden` fixture (auto-discovered by pytest)
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
  test_demo_testing.py   # testing.py demo (TestSurface, emissions, layers)
  test_demo_live.py      # live.py demo (health checks, spinners, progress)
  test_demo_fidelity.py  # fidelity.py demo (disk usage, sample data)
  goldens/               # committed expected output
    test_demo_testing/
    test_demo_live/
    test_demo_fidelity/
```
