# The same code, three ways.
# One script. painted adapts to context.

Output tapes/three-ways.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 500
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set BorderRadius 8

# Hidden: activate venv, cd to scripts
Hide
Type "source .venv/bin/activate 2>/dev/null"
Enter
Sleep 1s
Type "cd tapes/scripts"
Enter
Sleep 300ms
Show

# Show the code
Sleep 400ms
Type "cat app.py"
Enter
Sleep 3s

# Run 1: TTY → styled tree
Type "python app.py"
Enter
Sleep 2.5s

# Run 2: pipe → plain text
Type "python app.py | cat"
Enter
Sleep 2s

# Run 3: JSON
Type "python app.py --json"
Enter
Sleep 2s
