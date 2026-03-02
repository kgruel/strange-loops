# Live streaming.
# Parallel health checks with spinners that resolve in real time.

Output tapes/live.gif

Set Shell "bash"
Set FontSize 16
Set Width 900
Set Height 550
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

# --- Default: live service list with spinners ---
Sleep 300ms
Type "# live spinners resolve as checks complete"
Enter
Sleep 1.5s

Type "painted-demo live"
Enter
Sleep 4s

# --- Minimal: one-line counter ---
Type "# -q  →  one-line live counter"
Enter
Sleep 1.5s

Type "painted-demo live -q"
Enter
Sleep 3.5s

# --- Detailed: full dashboard ---
Type "# -vv  →  bordered dashboard with progress bar"
Enter
Sleep 1.5s

Type "painted-demo live -vv"
Enter
Sleep 4.5s

# --- Static: final snapshot ---
Type "# --static  →  skip animation, print result"
Enter
Sleep 1.5s

Type "painted-demo live --static"
Enter
Sleep 2.5s

# --- JSON ---
Type "# --json  →  machine-readable"
Enter
Sleep 1.5s

Type "painted-demo live --json"
Enter
Sleep 3s
