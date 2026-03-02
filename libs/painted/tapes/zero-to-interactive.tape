# Zero to interactive.
# Same render function. Four fidelity levels.

Output tapes/zero-to-interactive.gif

Set Shell "bash"
Set FontSize 16
Set Width 900
Set Height 520
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 60%

# Hidden: add wrapper to PATH
Hide
Type "export PATH=$PWD/demos:$PATH"
Enter
Sleep 500ms
Show

# --- Narration ---
Sleep 300ms
Type "# one render function. painted picks the output."
Enter
Sleep 2s

# --- Level 0: one line ---
Type "painted-demo fidelity -q"
Enter
Sleep 2s

# --- Level 1: standard ---
Type "painted-demo fidelity"
Enter
Sleep 2.5s

# --- Level 2: styled ---
Type "painted-demo fidelity -v"
Enter
Sleep 3s

# --- Level 3: interactive ---
Type "# add -i"
Enter
Sleep 1s

Type "painted-demo fidelity -i"
Enter
Sleep 1.5s
Down
Sleep 400ms
Down
Sleep 400ms
Down
Sleep 400ms
Up
Sleep 400ms
Up
Sleep 800ms
Type "q"
Sleep 1s
