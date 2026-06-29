---
description: "Reconcile cadence — the slower structural review: staleness lens, friction backlog, stale threads, hypothesis staleness. First-class work, not overhead."
argument-hint: "[vertex]"
---

Run the loops **reconcile** — the slower review tier (weekly-ish), a first-class
work session in its own right. Operate on the `project` vertex unless $ARGUMENTS
names another.

1. **Attention-need triage via the reconcile lens:**
   `sl read project --lens reconcile`
   Groups by attention need: this-session / needs-review / resolved.
   *(The `reconcile` lens is part of loops' user-global lens layer
   `~/.config/loops/lenses/reconcile.py`, not bundled with this plugin. If it
   isn't installed, this step errors with "lens not found" — skip it and use the
   kind-by-kind scan in steps 2–4, which covers the same ground without a lens.)*

2. **Friction backlog** — what pain is still open:
   `sl read project --kind friction --plain`
   For each: is the fix now clear, or has it been overtaken? Re-emit
   `status=resolved` where done; sharpen the message where the fix surfaced.

3. **Stale threads** — open arcs that may have died silently:
   `sl read project --kind thread --plain`
   Resolve (`status=resolved`) what's no longer live; re-anchor what is.

4. **Hypothesis staleness** — predictions left at `proposed` with no evidence:
   `sl read project --kind hypothesis --facts`
   Move each toward `confirmed` / `rejected` / `refined` with a ref to the
   evidence, or note why it's still open.

5. **Structural check** — does the `.vertex` still fit the work? Which namespaces
   sprawled, which kinds went unused, what does the salience graph say. Reconcile
   is where the vertex structure itself gets edited when it stops fitting.

Reconcile sessions are first-class work — schedule them, don't squeeze them.
