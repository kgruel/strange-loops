---
description: "Session-wrap sweep — scan this session's reroutes/logs, promote repeat patterns to friction, update thread statuses, emit the session-arc, then seal."
argument-hint: "[vertex]"
---

Run the loops **sweep** — the fast session-wrap tier. Capture happens at reflex
speed during the session (the `log` kind + the Stop-hook backstop); the sweep is
where that raw capture gets triaged at review speed. Operate on the `project`
vertex unless $ARGUMENTS names another.

1. **Scan this session's reroutes and unresolved moments.**
   `sl read project --kind log --plain --since 1d`
   Read what was logged at reflex speed.

2. **Promote repeat patterns to friction.** A reroute that recurred — or names a
   real tooling/process pain with a fix now in view — becomes a named friction:
   `sl emit project friction name=<short-handle> status=open ops=<arc> message="<pain + the fix in view>"`
   One-offs stay as `log` history and age out of the collect window — do **not**
   promote them.

3. **Update thread statuses.** For each thread touched this session, re-emit with
   its current status so the fold reflects reality:
   `sl emit project thread name=<name> status=<open|resolved|parked> message="<where it landed>"`

4. **Emit the session-arc** — one observation capturing the session's shape: what
   got built/decided, the calibration note, and the next entry point.
   `sl emit project observation topic=session/<YYYY-MM-DD>-<handle> message="<arc>"`

5. **Then seal** (the SessionEnd hook seals automatically on close; seal now only
   if you want the boundary before then):
   `sl seal project -m "<sweep note>"`

The sweep **precedes** the seal. Capture at reflex speed (log), triage here at
review speed — never the reverse.
