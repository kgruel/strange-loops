# Hero: Progressive Fidelity
# Same build data, four presentations — painted's core story.

Output tapes/hero.gif

Set Shell "bash"
Set FontSize 18
Set Width 900
Set Height 500
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms
Set BorderRadius 8

# Hidden preamble: add wrapper to PATH
Hide
Type "export PATH=$PWD/demos:$PATH"
Enter
Sleep 500ms
Show

# --- Level 0: Minimal ---
Sleep 500ms
Type "painted-demo fidelity -q"
Sleep 300ms
Enter
Sleep 2s

# --- Level 1: Standard ---
Type "painted-demo fidelity"
Sleep 300ms
Enter
Sleep 3s

# --- Level 2: Styled ---
Type "painted-demo fidelity -v"
Sleep 300ms
Enter
Sleep 4s

# --- Level 3: Interactive TUI ---
Type "painted-demo fidelity -i"
Sleep 300ms
Enter
Sleep 2s
Down
Sleep 600ms
Down
Sleep 600ms
Down
Sleep 600ms
Up
Sleep 600ms
Up
Sleep 1s
Type "q"
Sleep 1s
