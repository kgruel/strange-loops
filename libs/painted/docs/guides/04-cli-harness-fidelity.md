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

<!-- docgen:begin py:painted.fidelity:Zoom#definition -->
```python
class Zoom(IntEnum):
    """Detail level for rendering."""

    MINIMAL = 0  # One-liner, counts only
    SUMMARY = 1  # Key information, tree structure
    DETAILED = 2  # Everything visible, nested expansion
    FULL = 3  # All fields, full depth
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.fidelity:OutputMode#definition -->
```python
class OutputMode(Enum):
    """Delivery mechanism."""

    AUTO = "auto"  # Detect from TTY/pipe
    STATIC = "static"  # print_block, scrolls away
    LIVE = "live"  # InPlaceRenderer, cursor control
    INTERACTIVE = "interactive"  # Surface, alt screen
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.fidelity:Format#definition -->
```python
class Format(Enum):
    """Serialization format."""

    AUTO = "auto"  # Detect from TTY
    ANSI = "ansi"  # Styled terminal output
    PLAIN = "plain"  # No escape codes
    JSON = "json"  # Machine-readable
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.fidelity:CliContext#definition -->
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

<!-- docgen:begin py:painted.fidelity:run_cli#signature -->
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
- painted owns *delivery* (static/live/interactive formatting and terminal behavior)

## Demo output (fidelity.py)

### Zoom.MINIMAL

<!-- outputgen:begin name="fidelity_minimal" -->
<pre class="painted-output">67% used (134.0G/200.0G)
</pre>
<!-- outputgen:end -->

### Zoom.DETAILED

<!-- outputgen:begin name="fidelity_detailed" -->
<pre class="painted-output">╭─ Disk: /home ─────────────────────────────────────────╮
│<span style="color: green"> 67.0% ████████████████████░░░░░░░░░░</span><span style="opacity: 0.6"> 134.0G/200.0G</span>    │
╰───────────────────────────────────────────────────────╯
                                                         
╭─ By Directory ────────────────────────────────────────╮
│<span style="font-weight: bold"> 45.0G</span> <span style="color: yellow">▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6"> 33.6%</span>  projects │
│<span style="font-weight: bold"> 28.0G</span> <span style="color: yellow">▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6"> 20.9%</span>  downloads│
│<span style="font-weight: bold"> 22.0G</span> <span style="color: cyan">▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6"> 16.4%</span>  .cache   │
│<span style="font-weight: bold"> 18.0G</span> <span style="color: cyan">▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6"> 13.4%</span>  documents│
│<span style="font-weight: bold"> 12.0G</span> <span style="color: cyan">▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6">  9.0%</span>  pictures │
│<span style="font-weight: bold">  9.0G</span> <span style="color: cyan">▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░</span> <span style="opacity: 0.6">  6.7%</span>  .local   │
╰───────────────────────────────────────────────────────╯
                                                         
<span style="color: green; font-weight: bold">  Free: 66.0G  </span>                                          
</pre>
<!-- outputgen:end -->
