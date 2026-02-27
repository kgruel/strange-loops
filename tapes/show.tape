# show() — zero-config display, three output modes.

Output tapes/show.gif

Set Shell "bash"
Set FontSize 18
Set Width 900
Set Height 500
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms
Set BorderRadius 8

# Hidden preamble
Hide
Type "export PATH=$PWD/demos:$PATH"
Enter
Sleep 500ms
Show

# --- TTY: styled auto-detected ---
Sleep 500ms
Type "painted-demo show"
Sleep 300ms
Enter
Sleep 3s

# --- JSON ---
Type "painted-demo show --json"
Sleep 300ms
Enter
Sleep 3s

# --- Piped: plain text ---
Type "painted-demo show | cat"
Sleep 300ms
Enter
Sleep 2s
