# Mode Resolution Rules

How `CliRunner` resolves the output mode when the user doesn't explicitly choose one.

## The Three Axes

```
ZOOM (what to show)              OUTPUT MODE (how to deliver)
├─ 0: MINIMAL (-q/--quiet)       ├─ STATIC: print and scroll
├─ 1: SUMMARY (default)          ├─ LIVE: cursor-controlled updates
├─ 2: DETAILED (-v)              └─ INTERACTIVE: alt screen + keyboard
└─ 3: FULL (-vv)

FORMAT (serialization)
├─ ANSI: styled terminal (TTY default)
├─ PLAIN: no styles (pipe default)
└─ JSON: machine-readable (--json)
```

Zoom, mode, and format are orthogonal in principle. Mode resolution is where
they interact — certain zoom/format choices constrain which modes make sense.

## Mode Resolution

When the user passes `--static`, `--live`, or `-i`, that's final. Resolution
only applies to AUTO (no explicit flag).

### Rule: Capability Filtering

`CliRunner` infers which modes the CLI actually supports:

| Config present | Modes registered |
|----------------|-----------------|
| (always) | STATIC |
| `fetch_stream` | + LIVE |
| `handlers[INTERACTIVE]` | + INTERACTIVE |

Only supported modes get argparse flags. A CLI without `fetch_stream` never
shows `--live` in `--help`.

### Rule: AUTO Collapse

When mode is AUTO, certain conditions force STATIC:

| Condition | Why |
|-----------|-----|
| `--json` | Machine-readable output; cursor control would corrupt JSON |
| `--plain` | No ANSI codes; cursor control requires ANSI escape sequences |
| `-q` (MINIMAL) | One-liner output; animation overhead is wasteful |
| Pipe (not TTY) | No terminal to animate; print and exit |

Otherwise AUTO resolves to the highest supported mode:
- TTY with LIVE available → LIVE
- TTY without LIVE → STATIC

### Resolution Order

```
User passes explicit mode flag?
  yes → use it (--static, --live, -i)
  no  → AUTO
         │
         ├─ --json?   → STATIC
         ├─ --plain?  → STATIC
         ├─ -q?       → STATIC
         ├─ pipe?     → STATIC
         └─ TTY?      → LIVE (if supported) or STATIC
```

### Rule: Flag Visibility

`--help` only shows flags for modes the CLI supports. This prevents user
confusion ("why does `-i` do nothing?").

| CLI capabilities | Flags shown |
|-----------------|-------------|
| Static only | (no mode flags) |
| Static + Live | `--static`, `--live` |
| Static + Interactive | `-i`, `--static` |
| Static + Live + Interactive | `-i`, `--static`, `--live` |

`--static` appears whenever LIVE or INTERACTIVE is available — it's the
"force no animation" escape hatch.

## Design Rationale

### Why MINIMAL implies STATIC

`-q` produces a one-liner (e.g., `4/6 healthy  1 degraded  1 down`). Firing
up `InPlaceRenderer` for a single line that never changes is pure overhead.
The output is already minimal — animation adds nothing.

### Why PLAIN implies STATIC

`--plain` strips ANSI codes. Cursor-controlled rendering (`InPlaceRenderer`)
works by writing ANSI escape sequences to move the cursor and overwrite
previous output. Without ANSI, the cursor stays put and each "frame" appends
below the last — producing garbage. PLAIN and LIVE are mechanically
incompatible.

### Why capability filtering exists

Without filtering, every CLI shows `-i`, `--live`, and `--static` regardless
of whether those modes do anything. A user passing `-i` to a CLI with no
interactive handler gets silently downgraded to LIVE — confusing. Better to
not offer what you can't deliver.

## Non-Rule: Format Never Implies Mode (Except for Collapse)

`--plain` collapses AUTO to STATIC, but it doesn't prevent `--plain --live`
if the user explicitly asks. Explicit flags are respected even when the
combination is unusual. The collapse rules only govern AUTO resolution.
