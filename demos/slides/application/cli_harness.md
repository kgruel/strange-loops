---
id: cli_harness
title: CLI Harness
group: application
order: 5
align: center
---

# CLI Harness

[spacer]

[zoom:0]

`run_cli()` is the “one call” entry point for CLI tools

[spacer]

you provide `fetch` and `render(ctx, data) -> Block` — fidelis chooses delivery

[spacer]

delivery axes: `OutputMode` (STATIC / LIVE / INTERACTIVE) and `Format` (ANSI / PLAIN / JSON)

[spacer]

zoom is a first-class input: `Zoom.MINIMAL → Zoom.FULL`

[spacer]

↓ for more detail

[zoom:1]

*the contract (shape only)*

[spacer]

```python
def render(ctx: CliContext, data: T) -> Block: ...
def fetch() -> T: ...

run_cli(args, render=render, fetch=fetch)
```

[spacer]

optionally:

```python
run_cli(
    args,
    render=render,
    fetch=fetch,
    handlers={OutputMode.INTERACTIVE: lambda ctx: MySurface().run()},
)
```

[zoom:2]

*where to look next*

[spacer]

`src/fidelis/fidelity.py` defines `run_cli`, `CliContext`, `Zoom`, `OutputMode`, and `Format`.

