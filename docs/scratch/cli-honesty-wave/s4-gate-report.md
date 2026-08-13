# S4 gate report — cite vertex slot + all-refs-drop refusal

Gated against the MERGED wave branch in the main checkout
(`/Users/kaygee/Code/loops`, branch `cli-honesty-wave`, tip `0bc22ac`;
S4 commits `28b7a20` + `d36f119`). Oracle re-run from scratch; implementer
verdicts not consulted (only the report's "Files touched" list, per task).
All CLI via `uv run --project /Users/kaygee/Code/loops --package loops loops`.
Read-only on code; nothing committed; live stores under `/tmp/gate-s4`.

**VERDICT: GATE PASS (9/9).** One documented-behavior probe (check 7b) plus
two residue notes below; neither breaks the contract.

| # | Check | Verdict |
|---|-------|---------|
| 1 | Diff scope | PASS |
| 2 | Fresh tests, both cwds (plus a third) | PASS |
| 3 | Vertex slot live, three forms identical | PASS |
| 4 | All-refs-drop → exit 2, stderr, nothing stored (incl. --dry-run) | PASS |
| 5 | All-inert → stores, exit 0, provenance-only | PASS |
| 6 | Partial resolve → WARN, exit 0, good ref typed | PASS |
| 7 | Peel probe (a) non-vertex ref (b) adversarial slash-name vertex | PASS (documented) |
| 8 | Named vertex, zero refs → loud exit 2 on stderr | PASS |
| 9 | Emit receipts: two findings fixed @ d36f119 | PASS |

---

## 1. Diff scope — PASS

`git diff 17783fd..cli-honesty-wave --stat` over the four gated source files:

```
apps/loops/src/loops/cli/cite_args.py  | 24 ++++++----
apps/loops/src/loops/cli/completers.py | 18 ++++++++
apps/loops/src/loops/cli/views/cite.py | 81 ++++++++++++++++++++++++----------
apps/loops/src/loops/commands/emit.py  | 38 ++++++++++++++++
```

`git diff --stat 793c798..0bc22ac` (the S4 commit range) adds exactly, and only,
the S4 test files plus the impl report:

- `apps/loops/tests/test_cite_vertex_slot.py` (NEW, +253)
- `apps/loops/tests/test_cite_emit_ref_parity.py`, `test_emit.py`,
  `test_ambiguous_local_vertex.py`, `test_verb_completion_t4.py`
- `docs/scratch/cli-honesty-wave/s4-impl-report.md`

Every one appears in the report's claimed file list. **Nothing S4-attributed
falls outside the gated set.** I read the four adapted test diffs looking for
weakened assertions and found none: `test_ambiguous_local_vertex` and
`test_emit` seed referents (their subjects are vertex resolution and ref
capture, not resolution failure) and add `monkeypatch.chdir(tmp_path)` for
hermeticity; `test_cite_emit_ref_parity`'s unresolved class is rewritten to
assert parity *in refusal* (both views nonzero, nothing stored) plus a new
partial-drop parity test; `test_verb_completion_t4` inverts the completion pin
per the new grammar and adds a defer-after-first-token test. Each keeps or
strengthens its original subject.

## 2. Fresh tests — PASS

| Run | Result |
|-----|--------|
| `test_cite_vertex_slot.py` + `test_emit.py::TestCite` + `test_cite_emit_ref_parity.py` | 26 passed |
| Full `apps/loops/tests` from the main checkout cwd | **2485 passed, 1 xfailed** |
| Full suite from `/tmp` (.loops-free), `--project` form | **2485 passed, 1 xfailed** |
| Full suite from a scratch `.loops`-bearing cwd (`/tmp/gate-s4/proj`) | **2485 passed, 1 xfailed** |

Counts match across all three cwds — the hermeticity fix holds. The impl
report's 2459 was measured on the pre-merge branch (based on main, without
S1–S3); 2485 is the merged wave. Not a discrepancy.

## 3. Vertex slot live — PASS

Throwaway `gatex` vertex at `/tmp/gate-s4/work/gatex.vertex`, isolated
`LOOPS_HOME=/tmp/gate-s4/home`, `thread:arc` seeded.

```
loops cite gatex thread:arc -m "gate check 3a"   → rc 0, "(refs: 1 resolved)"
loops gatex cite thread:arc -m "gate check 3b"   → rc 0, "(refs: 1 resolved)"
loops emit gatex cite ref=thread:arc message=... → rc 0, "(refs: 1 resolved)"
```

Store read confirms three equivalent rows in **gatex's** store, each with a
resolved typed ref:

```
{'kind': 'cite', 'payload': {'message': 'gate check 3a', 'ref': 'thread:arc',
                             'ref_ref': '01KZVYF7GNX5NXWTD0YZ23YW82'}}
```
(3b and 3c identical apart from the message.) The three forms are
indistinguishable in the store.

Local-resolution paths still behave, with the hint text updated to the new
grammar: ambiguous cwd → `cite: 2 local vertices and none named — refusing to
guess (alpha, beta). name it explicitly: sl cite <vertex> REF ...` (rc 2); no
local vertex → `no vertex specified and no local vertex found … hint: use
`sl cite <vertex> REF ...`` (rc 1). A named vertex bypasses the ambiguity
refusal (verified in the two-vertex dir).

## 4. All-refs-drop — PASS

```
$ loops cite gatex thread:absent thread:alsoabsent -m "should refuse"
ERROR: ref 'thread:absent' did not resolve
ERROR: ref 'thread:alsoabsent' did not resolve
ERROR: cite refused — all 2 entity ref(s) failed to resolve; a cite with zero
       resolved entity refs is an empty attention signal; nothing stored
rc=2
```

- **stderr routing**: rerunning with `2>/dev/null` prints nothing, rc 2.
- **nothing stored**: cite row count 3 before, 3 after (and again after the
  dry-run and mixed probes).
- **--dry-run**: same two ERROR lines, rc 2, no preview emitted, count unchanged.
- **Mixed (2 declared-kind fail + 1 inert pin)**: message discloses both counts —
  `all 2 entity ref(s) failed to resolve; 1 inert pin(s) dropped with the refusal`.
- **No-inert case**: the inert clause is absent (first excerpt above).
- **Extra probe** — comma accumulation (`"thread:absent,thread:absent2,madeupkind:x"`
  as one positional) produces the identical mixed message with the same
  2-entity/1-inert counts, so the count derivation is not syntax-sensitive.
- **Emit-path uniformity**: `loops emit gatex cite ref=thread:absent message=x`
  refuses identically (rc 2, stderr).
- **Claim narrowness holds**: a non-cite kind with an all-dropping ref still
  WARNs and stores (`emit gatex thread name=probe ref=thread:absent` → rc 0),
  and a cite emitted with no refs at all via raw emit stores (rc 0) — both
  explicitly out of the claim's scope per the code comment.

## 5. All-inert — PASS

```
$ loops cite gatex madeupkind:one otherkind:two -m "all inert"
stored: cite/<no-fold> @ 01KZVYFXGK546S0B3951N6VVA4    rc=0
payload: {'message': 'all inert', 'ref': 'madeupkind:one,otherkind:two'}
```
Raw addresses carried in `ref`; no `ref_ref`, no `_unresolved_refs` — stored as
provenance-only, exactly the arbiter's ruling.

## 6. Partial resolve — PASS

```
$ loops cite gatex thread:arc thread:absent -m "partial"
WARN: ref 'thread:absent' did not resolve — stored as typed unresolved pin
stored: cite/<no-fold> @ ...  (refs: 1 resolved)    rc=0
payload: {'ref': 'thread:arc,thread:absent',
          'ref_ref': '01KZVYF7GNX5NXWTD0YZ23YW82',
          '_unresolved_refs': [{'field': 'ref', 'addr': 'thread:absent',
                                'kind': 'thread', 'key': 'absent'}]}
```
Good ref typed, bad ref a typed pin, WARN on stderr (vanishes under
`2>/dev/null`), exit 0.

## 7. Peel ambiguity probe — PASS (documented behavior)

**(a) Ref that looks like a vertex name but isn't.**
`loops cite gatex nosuchvertex` → rc 0, stored with no typed ref:
`nosuchvertex` is not a resolvable vertex, so it stays a positional and lands
as an inert provenance pin (the check-5 rule). Correspondingly
`loops cite thread:arc -m "…"` from the gatex cwd does **not** peel the
colon-address — local resolution picks gatex and the ref resolves. Peel-by-
resolution behaves as ruled.

**(b) Adversarial: a vertex literally named `thread/arc`.**
`_resolve_vertex_for_dispatch` checks `cwd/<name>.vertex`, so writing
`/tmp/gate-s4/work/thread/arc.vertex` creates a vertex whose name is a legal
slash-form ref shape.

```
$ loops cite thread/arc thread:arc -m "adversarial peel"
ERROR: ref 'thread:arc' did not resolve
ERROR: cite refused — all 1 entity ref(s) failed to resolve; …; nothing stored
rc=2
```
The **vertex reading wins** (resolution-first grammar, as designed) and the
mis-target is disclosed loudly here because `thread:arc` exists in gatex, not
in arc. Follow-up probe where the second ref *does* resolve in the peeled
vertex (`thread:x` seeded in arc):

```
$ loops cite thread/arc thread:x -m "which store?"
stored: cite/<no-fold> @ 01KZVYH2PG1X86C4XW76G8DMTQ  (refs: 1 resolved)   rc=0
→ landed in thread/arc.db, not gatex.db
```

Not a mis-store (the peel is deterministic, documented, and the cite is
correct for the vertex reading), but note the receipt line does not name the
target vertex, so a shadowed cite is not *visibly* attributed. That receipt
shape is pre-existing for all emits (`emit gatex thread …` prints the same
un-attributed `stored:` line), so it is wave residue, not S4 regression.
Recording as documented behavior per the task's instruction.

## 8. Zero refs with a named vertex — PASS

```
$ loops cite gatex
cite: vertex 'gatex' named but no refs given — cite requires at least one ref   usage: sl cite <vertex> REF ...
rc=2
```
Nothing on stdout (`2>/dev/null` → silent, rc 2). The embedded newline is
flattened to spaces by painted — the impl report names this as consistent with
the pre-existing "no local vertex found" message; confirmed identical shape
there. Cosmetic residue, not a contract breach.

## 9. Emit receipts — PASS

```
chw-s4-test-hermeticity        status=fixed  slice=S4  commit=d36f119
chw-s4-refusal-message-inert-pins status=fixed slice=S4 commit=d36f119
```
(Also present: `chw-s4-cite-vertex-slot` completed @ 2cbd315, and
`chw-s4-deviation-branch-base-is-main` dismissed per arbiter.)

## Residue noted (non-blocking)

1. `stored:` receipts do not name the target vertex, so a peel-shadowed cite
   (check 7b) is correct but not visibly attributed. Pre-existing across emit.
2. Multi-line CLI error messages are flattened to one line by painted
   (friction:block-text-multiline-passthrough-broke-on-040 territory).
3. `loops emit gatex cite message=x` (raw emit path, **zero** refs) stores with
   rc 0 — a cite with no refs at all is literally an empty attention signal,
   the thing the refusal targets, reached via a path the arbiter scoped out.
   Not a gate failure: the contract's claim is "refs ALL drop", which
   presupposes refs, and the cite verb enforces >=1 positional via
   `nargs="+"`. Named here as the one hole an adversarial re-review would poke.
