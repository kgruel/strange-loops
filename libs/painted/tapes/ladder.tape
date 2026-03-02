# Climb the ladder.
# show() → compose → card

Output tapes/ladder.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 580
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8
Set LoopOffset 70%

# Hidden: venv + cd + start from show version
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts && cp .app_painted.py app.py"
Enter
Sleep 300ms
Show

# --- Act 1: show() is step one ---
Sleep 300ms
Type "# show() gets you this."
Enter
Sleep 1s

Type "python app.py"
Enter
Sleep 2.5s

# --- Act 2: compose it ---
Type "# want more? compose it."
Enter
Sleep 1.5s

Hide
Type "cp .app_composed.py app.py"
Enter
Sleep 300ms
Show

Type "cat app.py"
Enter
Sleep 3s

Type "python app.py"
Enter
Sleep 3.5s
