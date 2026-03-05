# Test Architecture Layers

How to layer testing so that design invariants are enforced, not just hoped for.

## The Three Tiers

Observed across siftd, painted, and loops — three distinct kinds of
architectural enforcement, each at a different grain.

### Tier 1: Package Boundaries (structural)

**What:** Separate packages with declared dependencies. If lib A doesn't
depend on lib B, it can't import it. The Python module system enforces this.

**Where it exists:** loops monorepo (4 libs, each with own pyproject.toml).
`lang` depends only on `ckdl`. `engine` depends on `atoms` and `lang`. DAG
enforced by the packaging system itself.

**Strengths:** Zero config, zero tooling. The constraint is real, not declared.
**Gaps:** No intra-package enforcement. No static detection (fails at import
time, not lint time). Can't express "TYPE_CHECKING only" as a constraint.

### Tier 2: Import Boundary Enforcement (static analysis)

**What:** Declare which modules may import which, enforce statically.
Finer-grained than packaging — works within a single package.

**Tools evaluated:**

| Tool | Language | Config | Approach | Extras |
|------|----------|--------|----------|--------|
| **tach** | Rust | TOML | Modules + layers + interfaces | `tach sync`, `tach show`, strict mode (`__all__`) |
| **import-linter** | Python | INI/TOML | Contracts (layers, forbidden, independence) | Custom contract types |
| **pytest-archon** | Python | Test code | Fluent rule API | Transitive dep checking |
| **PyTestArch** | Python | Test code | ArchUnit-inspired fixtures | Layered architecture support |
| **Hand-rolled AST** | Python | Test code | Custom AST walkers | Full control, high maintenance |

**Current recommendation: tach.** Rust (fast), TOML config (declarative, not
code), fits the uv/ruff/ty toolchain family. `tach sync` bootstraps from existing
code. `tach check` drops into `./dev check`. Layers express the DAG. Interface
enforcement via `__all__` + strict mode.

**What tach replaces:** The ~230 lines of AST-walking infrastructure in siftd's
`test_imports.py` (`ALLOWED_DEPS` manifest, `get_siftd_imports()`,
`group_for_module()`, relative import resolution). The *manifest* is valuable;
the *machinery* is what tach handles.

**What tach doesn't replace:** Domain invariants (tier 3). Tach is purely about
import boundaries and interfaces.

**Open question:** Does loops need intra-lib enforcement? Currently, the
cross-lib DAG is enforced by packaging. Within a lib (e.g., "engine.compiler
must not import engine.store"), there's no enforcement. This matters more as
libs grow.

### Tier 3: Domain Invariants (hand-rolled, always)

**What:** Project-specific architectural rules that no generic tool can express.
These test *your* design decisions.

**Examples from siftd:**
- stderr hygiene: `print("Tip:...")` must use `file=sys.stderr`
- Bundled SQL validity: all `.sql` files pass `EXPLAIN` against schema
- Adapter interface compliance: all built-in adapters pass `validate_adapter()`
- Formatter registration: all registered formatters are callable with `.format()`
- No raw SQL in CLI modules (AST scan for `execute()` calls, `# arch: allow-sql` escape hatch)
- Known violations ratchet: `len(KNOWN_VIOLATIONS) <= N`, can only decrease

**Examples from painted:**
- Frozen dataclass enforcement: named classes + `*State` suffix → `@dataclass(frozen=True)` (both AST and runtime check)
- Encapsulation: `Block._rows` not accessed outside `block.py`
- Public/private boundary: public modules can't import `_private` sibling symbols (exception allowlist)
- Defensive copying: `Block` freezes rows on construction (behavioral test)

**Examples loops should have (currently missing):**
- Frozen dataclass enforcement (Fact, Spec, Tick are all frozen — test it)
- Spec naming convention: Spec name matches the Fact kind it folds
- Kind namespacing: infrastructure facts prefixed, domain facts bare
- Atom completeness: every atom has `to_dict`/`from_dict` round-trip
- Store schema: idempotent migrations don't break existing DBs

**The pattern:** These are always pytest tests in `tests/architecture/` (siftd)
or `tests/unit/test_architecture_invariants.py` (painted). They use AST analysis
for static checks and runtime imports for behavioral checks. They run early in
`./dev check` because they catch design violations, not logic bugs.

## The Gate Ordering

How `./dev check` should sequence:

```
tach check           → tier 2: import boundaries (fast, static)
pytest tests/arch/   → tier 3: domain invariants (fast, mostly static)
ty + ruff            → lint: types + style
pytest tests/        → unit + integration tests
```

Architecture first because if the structure is wrong, everything else is noise.
Lint before tests because formatting/type errors are cheaper to fix than test
failures.

## Testing Philosophy

### Factories over mocks

Build real objects in controlled environments. A `Fact.of("health", cpu=0.5)`
is better than `Mock(spec=Fact)`. Mocks test that you called something; factories
test that something works.

**Where this is stated:** strange-loops CLAUDE.md, loops CLAUDE.md (implicit).
**Where it's violated:** strange-loops has mock-based tests in its scaffold.
Should be replaced with factory fixtures as real code lands.

### Integration over simulation

Test through real code paths. `Source.run()` should actually execute a subprocess
(with a trivial command), not mock `subprocess.run`. The loops engine tests do
this well — real Vertex instances, real Fact objects, real fold execution.

**The line:** Mock at system boundaries you don't own (network, filesystem in
some cases). Don't mock your own code.

### Behavior-grouped test classes

Group tests by what they prove, not by what code they touch:

```python
class TestConstruction:      # can I build one?
class TestFrozen:            # is it immutable?
class TestSerialization:     # does round-trip work?
class TestBoundaryFiring:    # does the boundary trigger correctly?
```

### Fixtures as building blocks

From engine's conftest.py: "provide building blocks, not pre-wired scenarios."
Fixtures give you atoms; tests compose them for intent. No god-fixtures that
set up entire systems.

## Prior Art & References

- [tach](https://github.com/tach-org/tach) — Rust-based Python dependency enforcement
- [import-linter](https://pypi.org/project/import-linter/) — Contract-based import validation
- [pytest-archon](https://github.com/jwbargsten/pytest-archon) — Fluent rule API for pytest
- [PyTestArch](https://github.com/zyskarch/pytestarch) — ArchUnit-inspired for Python
- [Protecting Architecture with Automated Tests in Python](https://handsonarchitects.com/blog/2026/protecting-architecture-with-automated-tests-in-python/) — PyTestArch walkthrough
- [6 ways to improve architecture with import-linter](https://www.piglei.com/articles/en-6-ways-to-improve-the-arch-of-you-py-project/) — Practical techniques

## Concrete Next Steps

1. **Add tach to loops monorepo** — `tach init`, configure `source_roots` for
   all 4 libs, declare the DAG, wire `tach check` into dev harness
2. **Add `tests/architecture/` to loops** — start with frozen dataclass
   enforcement and atom round-trip completeness
3. **Retrofit strange-loops** — replace mock-based scaffold tests with factory
   fixtures as real code lands
4. **Extract reusable invariant tests** — the frozen-dataclass checker and the
   import-boundary checker appear in both siftd and painted; could become a
   shared test utility or even a tiny lib
5. **Evaluate tach for siftd** — could replace the hand-rolled `test_imports.py`
   while keeping `test_hard_rules.py` and `test_contracts.py` as tier 3
