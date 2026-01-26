---
name: vhs
description: Record terminal GIFs using Charmbracelet VHS. Use when asked to record, demo, or create GIFs of CLI programs.
disable-model-invocation: true
argument-hint: "[command-or-tape-file] [output.gif]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task, AskUserQuestion
---

# VHS GIF Recording

Record terminal GIFs using [Charmbracelet VHS](https://github.com/charmbracelet/vhs).

## Arguments

`$ARGUMENTS` is either:
- A `.tape` file path to run directly
- A command/script to record (you'll create the tape)
- Empty — ask the user what to record

## Workflow

### 1. Understand the target

If given a script or command (not a .tape file):
- **Read the source** to understand what it does, its key bindings, and its output
- For interactive TUI apps: identify navigation keys, quit key, interesting states to showcase
- For non-interactive scripts: understand the output and how long it runs

### 2. Create the tape file

Write a `.tape` file. Name it after the thing being recorded (e.g., `bench.tape`, `demo.tape`).

**Template:**

```tape
# <description>

Output <name>.gif

Require <dependencies>

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 10
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set PlaybackSpeed 1
Set TypingSpeed 40ms

# Setup (hidden) — cd to correct directory, clear screen
Hide
Type "cd <project-root> && clear"
Enter
Sleep 1s
Show

# Launch
Type "<command>"
Sleep 500ms
Enter
Sleep <startup-time>

# <scripted interaction — keystrokes, typing, pauses>

# Quit
Type "q"
Sleep 1s
```

**Key rules:**
- Use `Hide`/`Show` to hide setup commands (cd, clear, env vars)
- Give generous `Sleep` after launch — `uv run` needs 3-5s for workspace resolution
- Interactive demos: pause 2s per slide/state so viewers can read
- Comment each section describing what's happening
- End with the quit sequence for the app

**VHS command reference:**

| Command | Usage |
|---------|-------|
| `Type "<text>"` | Type characters into terminal |
| `Enter`, `Space`, `Tab` | Press key |
| `Up`, `Down`, `Left`, `Right` | Arrow keys |
| `Ctrl+<key>` | Control combos (e.g., `Ctrl+C`) |
| `Escape` | Escape key |
| `Backspace [n]` | Backspace n times |
| `Sleep <duration>` | Pause (e.g., `500ms`, `2s`, `5s`) |
| `Hide` / `Show` | Hide/show subsequent commands from output |
| `Type@<speed> "<text>"` | Type with custom speed per character |

**Settings reference:**

| Setting | Default | Notes |
|---------|---------|-------|
| `Set FontSize` | 22 | 16 works well for dense TUI content |
| `Set Width` | 600 | 1200 for wide apps |
| `Set Height` | 300 | 700 for tall TUI apps |
| `Set Theme` | — | `"Catppuccin Mocha"`, `"Dracula"`, `"Tokyo Night"` |
| `Set WindowBar` | — | `Colorful`, `Rings`, `ColorfulRight` |
| `Set Framerate` | 50 | Lower = smaller file |
| `Set PlaybackSpeed` | 1 | >1 speeds up, <1 slows down |
| `Set TypingSpeed` | 50ms | Delay between typed characters |
| `Set Padding` | 0 | Padding inside terminal frame |
| `Set LoopOffset` | 0% | Where the GIF loop restarts |

### 3. Record

Run from the project root:

```bash
cd <project-root> && vhs <tape-file>
```

### 4. Verify

Extract a frame from the middle of the recording to confirm content rendered:

```bash
ffmpeg -y -i <output>.gif -vf "select=eq(n\,<mid-frame>)" -vframes 1 -update 1 /tmp/vhs_verify.png
```

Use `ffprobe` to get frame count first:

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames,duration \
  -of default=nokey=1:noprint_wrappers=1 <output>.gif
```

Then read `/tmp/vhs_verify.png` to visually confirm the content.

If the mid-frame is blank or shows only the shell prompt, the app likely didn't start in time — increase the post-launch `Sleep` and re-record.

### 5. Report

Tell the user:
- Output path and file size
- Frame count and duration
- What the recording shows
- How to re-record: `vhs <tape-file>`
