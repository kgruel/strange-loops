# Fidelity spectrum.
# Same data, same render function, four zoom levels.

Output tapes/fidelity.gif

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

# --- Zoom 0: one line ---
Sleep 300ms
Type "# -q  →  one-line summary"
Enter
Sleep 1.5s

Type "painted-demo fidelity -q"
Enter
Sleep 2.5s

# --- Zoom 1: directory list ---
Type "# default  →  directory list"
Enter
Sleep 1.5s

Type "painted-demo fidelity"
Enter
Sleep 3s

# --- Zoom 2: styled bars ---
Type "# -v  →  styled bars"
Enter
Sleep 1.5s

Type "painted-demo fidelity -v"
Enter
Sleep 3.5s

# --- Zoom 3: full detail ---
Type "# -vv  →  full detail with children"
Enter
Sleep 1.5s

Type "painted-demo fidelity -vv"
Enter
Sleep 4s

# --- Interactive: TUI tree browser ---
Type "# -i  →  interactive TUI"
Enter
Sleep 1.5s

Type "painted-demo fidelity -i"
Enter
Sleep 2s

# Navigate the tree
Down
Sleep 400ms
Down
Sleep 400ms
Down
Sleep 400ms

# Expand a directory
Enter
Sleep 800ms
Down
Sleep 400ms
Down
Sleep 400ms

# Collapse it
Up
Sleep 400ms
Up
Sleep 400ms
Enter
Sleep 800ms

# Back up and quit
Up
Sleep 400ms
Up
Sleep 400ms
Type "q"
Sleep 1s

# --- JSON: same data, machine-readable ---
Type "# --json  →  same data for machines"
Enter
Sleep 1.5s

Type "painted-demo fidelity --json"
Enter
Sleep 3s
