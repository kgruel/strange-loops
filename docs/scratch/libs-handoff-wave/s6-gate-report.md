# S6 Gate Report — slice/s6-lang-kdl-mutation

Independent verification (gate re-ran the oracle from scratch; implementation
report was not trusted). Branch head df95d099, merge-base with
libs-handoff-wave = a39028e8 (confirmed).

## Verdict table

| Oracle item | Verdict | Evidence |
|---|---|---|
| 1. Full lang suite | PASS | `uv run --package lang pytest libs/lang/tests`: **557 passed, 3 skipped** (0.74s) |
| 2. Corpus round-trip | PASS | Independent script (not their test): add_vertex_kind("gateprobe_kind") then remove → byte-identical for **all 12** tracked .vertex fixtures with a multiline loops block. The 3 hlab fixtures skipped per the oracle's own scoping — their loops blocks are single-line/absent, no multiline block to round-trip. |
| 3. Serializer reparse-equivalence | PASS | For **every kind def in the corpus** (25 kinds across 12 parseable fixtures): loop_def_to_kdl output re-embedded in a minimal vertex, reparsed, compared `==` to the original LoopDef — all equivalent. Extra probe: LoopDef with search+preview+edges+lifecycle and a float boundary condition (2.5) both reparse-equivalent. |
| 4. Adversarial probes | PASS (one caveat) | See below |
| 5. DAG check | PASS | `uv run pytest tests/` (repo-root architecture tests): **59 passed**. vertex_mutation.py imports only lang-internal modules (.ast, .population, .loader, .validator) — no engine symbols. |
| 6. Contract check (LIBS_CHANGES P1) | PASS with 3 recorded scoping deviations | See below |

**OVERALL: PASS**

## Item 4 detail — adversarial probes (all independent, beyond their tests)

| Probe | Result |
|---|---|
| Absent loops block: create then reparse | PASS — block created at EOF, new kind parses, `discover` line preserved |
| Kind name with quote / space / emoji / empty / leading digit / reserved `boundary` | PASS — all six **rejected with ValueError**, no corruption |
| Edit preserving comment ABOVE the kind | PASS — `// comment above` survives edit |
| Trailing comment ON the edited kind's own line | **LOST** — edit replaces the kind's lines wholesale. Gate judgment: acceptable — the contract requires preserving *unrelated* content; a comment on the replaced kind's own opening line is part of the replaced definition. Recorded, not a failure. |
| remove_vertex_kind on nonexistent kind | PASS — ValueError |
| add duplicate kind | PASS — ValueError ("already exists; use edit_vertex_kind") |
| All 9 fold ops in one LoopDef (count/latest/by/sum/max/min/avg/collect/window) | PASS — serialize→reparse equivalent |
| All 3 boundary forms (when+match+condition+run, after, every, after+run) | PASS — serialize→reparse equivalent |
| Single-line loops **edit** refuses | PASS — ValueError (claimed refusal is real) |
| Single-line loops **remove** refuses | PASS — ValueError (claimed refusal is real) |
| Single-line loops **add** expands (documented one-way) | PASS — both kinds parse after expansion |
| Last-kind removal refusal | PASS — ValueError via post-validation ("Missing required field: loops") |

Minor finding (not a failure): `add_vertex_kind` on text that does not parse
as a vertex at all (e.g. no loops block AND no discover) raises **ParseError**
from the `_kind_exists` precondition, not ValueError — an error-type
inconsistency on already-invalid input. Acceptable; worth a follow-up
normalization if the CLI wants one exception surface.

Script bug note for reproducibility: lang.ast uses a homegrown `_frozen`
decorator (not stdlib dataclasses) whose `__init__` **silently ignores unknown
kwargs** — my first script draft passed a bogus `name=` kwarg without error.
That is a lang-wide preexisting property, not introduced by this slice, but it
weakens constructor strictness; noted for the wave.

## Item 6 detail — contract (LIBS_CHANGES.md "P1: promote generic KDL vertex mutation")

| Required property | Status |
|---|---|
| Three-function API exported from lang | SATISFIED — add/edit/remove_vertex_kind + loop_def_to_kdl in `__all__` and lazy-import table |
| Preserve unrelated comments/whitespace/ordering | SATISFIED (with the trailing-comment-on-edited-kind caveat above — replaced lines are not "unrelated") |
| Handle absent, multiline, single-line loops blocks | DEVIATION (acceptable) — absent: created; multiline: full support; single-line: add expands (one-way), **edit/remove refuse** with ValueError instead of handling. Documented in module docstring; safe-refusal over silent corruption is the right trade. |
| Quote/escape or reject unrepresentable names | SATISFIED via the reject arm — conservative bare-identifier set, no escaping. Contract explicitly permits "or reject". |
| Parse and validate result before return | SATISFIED — `_validated()` on every mutation path (verified empirically by the last-kind refusal). |
| Round-trip to byte-identical text where possible | SATISFIED — all 12 multiline-corpus fixtures byte-identical. |
| Supported LoopDef→KDL serializer, no engine internals | SATISFIED with DEVIATION (acceptable) — per-kind `parse` pipelines raise ValueError ("author the parse block by hand") rather than serialize. Refuses loudly; the corpus contains zero per-kind parse pipelines, so no fixture is unserializable today. |

No required property is unsatisfied. The three deviations (single-line
edit/remove refusal, parse-pipeline serializer refusal, reject-over-escape)
are all explicit, documented, and fail-loud — real scoping choices, not gaps.
