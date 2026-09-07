# Primary triage: C9 setup correction

Verdict: **ACCEPT**. Fable-low accepted the correction; primary agrees. B1 is
closed. The only production change after the initial review adds TypeError
to the specific SDK custody failure tuple. Dedicated custody families retain
their earlier ordering, input checks remain before mutation, and arbitrary
unexpected exceptions/process-control exceptions are not broadly swallowed.
The initial full review and this correction together cover the final slice.

Actual malformed pending/intent JSON tests and a post-marker injected TypeError
retain unknown phase and exact request coordinates. The CLI regression checks
status 6 and unchanged files. A native in-memory negative control restores the
old tuple without changing files: 3 TypeError cases fail, OSError passes.
The corrected full SDK599, CLI30, scoped Ruff and modular-wheel workflow pass;
all four changed installed production files match final hashes. Prior unchanged
architecture101/custody31 remain valid. The optional absent legacy candidate
recovery case now has an explicit SDK assertion.

The review's optional observations do not require implementation changes:
assertion failures or unexpected KeyError are not promised typed lifecycle
outcomes; refusal can still have token-index publication effects; invariance
claims are bounded by the actual tests. We do not broaden these into a general
zero-effects or arbitrary-corruption recovery guarantee.

Frozen sources matched at launch and closure. Only maintained status and
handoff documentation changes afterward. No live store migration, legacy
retirement, commit, or push occurred. No jobs remain after review closure.
