# Paint it.
# The transformation: print() → show()

Output tapes/paint-it.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 520
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 80%

# Hidden: venv + cd + reset app to v1
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts && cp app.py .app_orig.py"
Enter
Sleep 300ms
Show

# --- Act 1: the usual way ---
Sleep 300ms
Type "# you have a script. it has data."
Enter
Sleep 1.5s

Type "cat app.py"
Enter
Sleep 2.5s

Type "python app.py"
Enter
Sleep 2.5s

# --- Act 2: the swap ---
Type "# ...swap one line."
Enter
Sleep 1.5s

Hide
Type "cp .app_painted.py app.py"
Enter
Sleep 300ms
Show

Type "cat app.py"
Enter
Sleep 2.5s

Type "python app.py"
Enter
Sleep 3s

# --- Act 3: it adapts ---
Type "# pipe it. it knows."
Enter
Sleep 1s

Type "python app.py | cat"
Enter
Sleep 2.5s

# --- Restore ---
Hide
Type "cp .app_orig.py app.py"
Enter
Show
