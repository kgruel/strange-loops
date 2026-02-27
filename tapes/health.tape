# Zero to interactive.
# Same render function. Health dashboard at every fidelity level.

Output tapes/health.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 400
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set BorderRadius 8
Set LoopOffset 0%

# Hidden: venv + alias + warm cache
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "alias health='python demos/patterns/fidelity_health.py'"
Enter
Sleep 200ms
Type "health -q >/dev/null 2>&1"
Enter
Sleep 1s
Type "clear"
Enter
Sleep 200ms
Show

# --- Narration ---
Sleep 500ms
Type "# one render function. four ways to see it."
Enter
Sleep 3s

# --- Quiet: one line ---
Type "health -q"
Enter
Sleep 3s

# --- Standard ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "health"
Enter
Sleep 3.5s

# --- Verbose: styled table ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "health -v"
Enter
Sleep 4s

# --- Live: in-place updates ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "# --live. same table, updating in place."
Enter
Sleep 3s

Type "health --live -v"
Enter
Sleep 7s

# --- Interactive TUI ---
Hide
Type "clear"
Enter
Sleep 300ms
Show

Type "# -i"
Enter
Sleep 2s

Type "health -i"
Enter
Sleep 2s
Type "j"
Sleep 600ms
Type "j"
Sleep 600ms
Type "j"
Sleep 600ms
Type "k"
Sleep 600ms
Type "k"
Sleep 1s
Type "q"
Sleep 1s
