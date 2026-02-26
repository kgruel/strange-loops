# show(data) — Zero-Config Display Entry Point

**Date:** 2026-02-25
**Status:** Approved

## Problem

fidelis has all the pieces for "call one function, get appropriate output":
`shape_lens` renders any Python value, `print_block` outputs a Block,
`detect_context` resolves TTY/pipe/format. But there's no single function
that composes them. The simplest path today requires 3-4 imports and
manual context detection.

## Design

### Signature

```python
def show(
    data: Any,
    *,
    zoom: Zoom = Zoom.SUMMARY,
    lens: Callable[[Any, int, int], Block] | None = None,
    format: Format = Format.AUTO,
    file: TextIO = sys.stdout,
) -> None:
```

### Parameters

- `data` — any Python value, or a pre-built `Block`
- `zoom` — detail level (default SUMMARY)
- `lens` — render function override (default: `shape_lens`; ignored when data is a Block)
- `format` — force output format (default: auto-detect from TTY)
- `file` — output stream (mirrors `print()` convention)

### Behavior (three paths)

1. **Block passthrough** — `isinstance(data, Block)` → `print_block(data)` directly
2. **JSON** — piped or `format=Format.JSON`, and data is not a Block → `json.dumps(data, default=str)`
3. **Rendered** — `lens(data, zoom, width) → Block → print_block(block, use_ansi=...)`

### Location

`fidelis/__init__.py`, exported as `from fidelis import show`.

### What it doesn't do

- No CLI arg parsing (use `run_cli`)
- No live/interactive modes (use `CliRunner`)
- No streaming (use `fetch_stream`)
- Returns nothing — side effect only, like `print()`

## Motivation

The narrative debugging sessions (2026-02-25) independently surfaced
`show(data)` as the value proposition: "call show, the stack figures out
the rest." This composes the existing rendering pipeline into the
simplest possible API for script output with progressive format adaptation.
