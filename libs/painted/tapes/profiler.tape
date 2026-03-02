# Self-profiling.
# painted introspects its own rendering performance.

Output tapes/profiler.gif

Set Shell "bash"
Set FontSize 16
Set Width 900
Set Height 600
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: add wrapper to PATH
Hide
Type "export PATH=$PWD/demos:$PATH"
Enter
Sleep 500ms
Show

# --- Help: what does it do? ---
Sleep 300ms
Type "painted-demo profiler --help"
Enter
Sleep 3.5s

# --- Minimal: summary stats ---
Type "# -q  →  summary stats"
Enter
Sleep 1.5s

Type "painted-demo profiler -q"
Enter
Sleep 2.5s

# --- Default: emission traces ---
Type "# default  →  emission traces"
Enter
Sleep 1.5s

Type "painted-demo profiler"
Enter
Sleep 3.5s

# --- Detailed: frame chart + flame graph ---
Type "# -v  →  frame cost chart + flame graph"
Enter
Sleep 1.5s

Type "painted-demo profiler -v"
Enter
Sleep 4s

# --- Full: frame-by-frame breakdown ---
Type "# -vv  →  frame-by-frame detail"
Enter
Sleep 1.5s

Type "painted-demo profiler -vv"
Enter
Sleep 4.5s
