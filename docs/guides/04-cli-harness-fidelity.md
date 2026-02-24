# CLI Harness (fidelity)

The fidelity layer standardizes a common CLI UI spectrum:

- **STATIC**: print once and exit (scrolls away)
- **LIVE**: in-place updates with cursor control
- **INTERACTIVE**: a full TUI loop (alt screen + keyboard input)

It also standardizes:
- **Zoom** (`-q`, `-v`, `-vv`) as “detail level”
- **Format** (`--plain`, `--json`) as “serialization”

See also:
- `CLAUDE.md`: current API reference (`../../CLAUDE.md`)

---

## Core types

<!-- docgen:begin py:fidelis.fidelity:Zoom#definition -->
```python
class Zoom(IntEnum):
    """Detail level for rendering."""

    MINIMAL = 0  # One-liner, counts only
    SUMMARY = 1  # Key information, tree structure
    DETAILED = 2  # Everything visible, nested expansion
    FULL = 3  # All fields, full depth
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.fidelity:OutputMode#definition -->
```python
class OutputMode(Enum):
    """Delivery mechanism."""

    AUTO = "auto"  # Detect from TTY/pipe
    STATIC = "static"  # print_block, scrolls away
    LIVE = "live"  # InPlaceRenderer, cursor control
    INTERACTIVE = "interactive"  # Surface, alt screen
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.fidelity:Format#definition -->
```python
class Format(Enum):
    """Serialization format."""

    AUTO = "auto"  # Detect from TTY
    ANSI = "ansi"  # Styled terminal output
    PLAIN = "plain"  # No escape codes
    JSON = "json"  # Machine-readable
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.fidelity:CliContext#definition -->
```python
@dataclass(frozen=True)
class CliContext:
    """Resolved runtime context."""

    zoom: Zoom
    mode: OutputMode  # Resolved (never AUTO)
    format: Format  # Resolved (never AUTO)
    is_tty: bool
    width: int
    height: int
```
<!-- docgen:end -->

## Entry point

`run_cli()` is the intended “one call” entry point.

<!-- docgen:begin py:fidelis.fidelity:run_cli#signature -->
```python
def run_cli(
    args: list[str],
    render: Callable[[CliContext, T], "Block"],
    fetch: Callable[[], T],
    *,
    fetch_stream: Callable[[], "AsyncIterator[T]"] | None = None,
    handlers: dict[OutputMode, Callable[[CliContext], R]] | None = None,
    default_zoom: Zoom = Zoom.SUMMARY,
    description: str | None = None,
    prog: str | None = None,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
) -> int:
```
<!-- docgen:end -->

---

## Pattern: state → Block, decoupled from I/O

The harness keeps a strict separation:

- your code owns *state fetching* (`fetch` / `fetch_stream`)
- your code owns *rendering* (`render(ctx, state) -> Block`)
- fidelis owns *delivery* (static/live/interactive formatting and terminal behavior)
