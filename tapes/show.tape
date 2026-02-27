# show() — zero-config display.
# Pass data in, painted picks the rendering.

Output tapes/show.gif

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

# --- Run it: auto-dispatches by data shape ---
Sleep 300ms
Type "# show() auto-dispatches by data shape"
Enter
Sleep 1.5s

Type "painted-demo show"
Enter
Sleep 4s

# --- Show the code: it's just show() calls ---
Type "# that's it — here's the code"
Enter
Sleep 1.5s

Type "cat demos/primitives/show.py"
Enter
Sleep 5s
