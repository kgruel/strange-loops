# loops app tests — conventions

## Channel-parity tests (register-split lenses)

`parity.py` is the harness for the bug CLASS in
`friction:two-surface-claims-lack-parity-tests`: two surfaces assert the same
truth with no cross-check, so the green suite passes while each drifts in
isolation. It has bitten the `sl ls` arc repeatedly (piped register dropping
`signed`/`share`/`span`; `width` truncation clipping the agent channel).

### The invariant

For a lens rendered over **one** fetch, every *load-bearing token* — counts,
entity names, relative timestamps, and numeric flags (signed ratio, share %,
span) — must appear in the chrome-stripped text of **both** registers:

- the **terse** register (`piped=True`, width-free / agent channel), and
- the **rich** register (`piped=False`, styled, width-bounded / TTY).

Plus: the piped render must never truncate (no `…`), because the agent channel
inherits `COLUMNS` and a width-driven clip silently drops information.

It is **not** byte equality. The two registers may *encode* the same fact
differently (type word `instance` vs glyph `◆`; `updated 2h ago` vs bare
`2h ago`). Parity is over the shared load-bearing set — the tokens both
registers are contracted to carry. `information_text()` strips ANSI,
box-drawing, meters, sparklines, containment glyphs and alignment padding so
what remains is comparable content.

### Adopting parity for a new register-split lens (~3 lines)

A register-split lens has the signature
`(data, zoom, width, *, piped: bool) -> Block`. To cover it:

```python
from .parity import assert_register_parity

def test_mylens_parity():
    data = {...}                      # a representative fetch dict
    assert_register_parity(mylens_view, data, load_bearing=["proj", "42", ...])
```

`load_bearing` is the pragmatic content set. Either hand-list it, or write a
small `mylens_tokens(data)` extractor next to the ones in `parity.py`
(`ls_root_tokens`, `decl_header_tokens`, `kind_stat_tokens`) that derives the
tokens from `data` — then the invariant becomes literally "one fetch, both
channels agree." Format numbers the way the lens does (`_format_count` →
`1.5k`, not `1523`).

For an **end-to-end** check that also guards the *fetch* path (not just the
lens), build a real store and pass the real fetch output — see
`test_parity.py::TestLsVertexParity::test_end_to_end_over_real_store`.

For non-register-split lenses, `assert_render_carries` is the single-channel
variant — use it for plain-vs-`--json` parity (`--json` serialises the fetch
dict by construction; the plain render must carry the same dict-derived
tokens).

## Shared fixtures & builders

- `conftest.py` — pytest fixtures (`loops_home`, `boundary_vertex`, …).
- `builders.py` — importable builders/helpers (no pytest needed):
  - `StorePopulator` — write `Fact`s straight into a `SqliteStore`.
  - `write_boundary_vertex(dir)` / `emit_fact(vpath, kind, **parts)` — the one
    shared boundary-vertex + real-emit path
    (`friction:cli-smoke-needs-shared-boundary-vertex-fixture`). Emit a
    `session status=closed` fact to trigger a boundary → tick. Prefer these over
    re-rolling ad-hoc vertex KDL in a slice.
