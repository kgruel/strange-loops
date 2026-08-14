# S4 GATE report — receipt attestation (slice/s4-receipt-attestation)

Gate ran independently at a1de000b (merge-base includes 4b5fa979: confirmed).
The impl report was treated as target, not authority; every oracle below was
re-driven from scratch with a gate-authored driver
(`gate_s4_oracle.py`, fake per-observer signer scheme `S4G:<digest>`,
gate-constructed verifier).

## Verdict table

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Suites | PASS | engine: **1410 passed**; loops: **2521 passed, 1 xfailed** |
| 2 | Oracles 1-4, own driver, both backends | PASS | 23/23 checks green on sqlite AND jsonl: signed=True cross-checked via `verify_facts` (gate verifier, ok+signed=1); per-observer None signer → bob signed=False while alice True under IDENTICAL config, rows independently differ via `fact_signature`; unsigned store → positive `FactAttestation(signed=False)`; tick-fired receive → `TickAttestation(signed=True, chained=True)` cross-checked via `verify_chain` ok+signed=1; unsigned-tick sibling honest (signed=False, chained=True) |
| 3 | Tri-state audit | PASS | None at: storeless vertex, EventStore, FileStore (both `stored=True, attestation=None` — driven), rejected receipt (out-of-potential Grant → `stored=False, attestation=None, tick_attestation=None`, never signed=False). S3 strict rejection raises `UndeclaredKind` before storage — no receipt exists to conflate. None never conflates with the positive signed=False claim. |
| 4 | Mutation check | PASS | Gate-authored mutant: `_fact_attestation` reads `self._store._fact_signer is not None` (config inference). Their tests: **2 failed** (`test_configured_but_none_signer_is_signed_false` both backends). Gate driver: **3 FAIL** lines. Revert → 15 passed. The suite kills config inference. |
| 5 | Consumer regression + CLI honesty | **FAIL (5c)** | 5a/5b PASS; 5c FAIL — see below |
| 6 | append_tick return change | PASS | All call sites: `engine/vertex.py:1169` (uses return — S4 itself), `apps/tasks/src/strange_loops/store.py:114` (ignores), `libs/store/src/store/rebirth.py:451` (ignores). No consumer of the previous None return; additive. `store/slice.py` only references it in comment. |
| 7 | Ceremony-receipt deviation | PASS | Read `sqlite_store.py:absorb_genesis` step 3: refuses `UnsignableGenesis` (rollback) when no signature produced; receipt `signed` from actual outcome. Driven: unsigned store absorb → `UnsignableGenesis` raised; signed absorb → receipt `signed=True`. Deviation from Receipt tri-state is justified — ceremony refuses rather than reports. |
| 8 | "vice versa unreachable" | PASS (argued + mechanism tested) | Via `Vertex.receive` no `signature_override` is passed (`vertex.py` append call takes only `id_override`) — unreachable through receive. Mechanism tested: direct `append(signature_override=...)` into an unsigned store reads back signed via `fact_signature` — attestation is row-honest even if such a path existed. Merge/receive/rebirth write the store directly and mint no Receipt; production replay sets store=None → attestation None (honest tri-state). Reasoned, not driven, for those legs. |

## Overall: FAIL — one item, narrow fix (5c)

### 5a/5b — PASS

- Receipt is a frozen dataclass with new fields **defaulted at the end**
  (`attestation=None`, `tick_attestation=None`) — no positional breakage.
  Consumers swept: `emit.py` (mark site, checks None), `handle.py:1383`
  (`stored`/`fact_id` only), `program.py:123` (`tick` only), tasks/hlab/comms:
  no Receipt-attr consumers. Additive-only confirmed.
- CLI driven end-to-end (gate driver via `cmd_emit`, both backends):
  signed vertex (real Ed25519, declared key) → `tick: … · signed` AND the
  committed tick row's signature column independently non-NULL;
  unsigned vertex → `· unsigned` AND row NULL. 4/4.

### 5c — FAIL: the tri-state-None fallback resurrects the condemned inference

`emit.py:916`: when `receipt.tick_attestation is None`, the mark falls back to
`"signed" if _tick_signer is not None else "unsigned"` — config inference,
verbatim the condemned form. And the None branch is **CLI-reachable**: the
compiler (`compiler.py:960`) falls through to **EventStore** for any store
suffix that is neither `.jsonl` nor sqlite. Repro, driven:

```
vertex("x").store("./x.log")            # → EventStore
+ observers { x { key "<ed25519>" } }   # key declared
sl emit x ping n=1                      # boundary fires
→ stderr: "tick: ping (1 fields) · signed"
```

EventStore has no `append_tick` — the tick was **never persisted and never
signed**, yet the CLI prints `· signed`. This is pre-existing behavior
preserved (severity context: same lie before S4, edge config), but it is the
one site S4 touched, in the CLI-honesty wave, and the gate question was asked
verbatim. Required fix (one line): on `tick_attestation is None` the mark must
be honest about not knowing — `unattested` (or omit the mark), never inferred
from `_tick_signer`.

## Counts and environment

- Branch: detached at a1de000b (`slice/s4-receipt-attestation`); gate report on
  pointer branch `slice/s4-receipt-attestation-gate`.
- engine suite: 1410 passed (6.41s). loops suite: 2521 passed, 1 xfailed (10.69s).
- Post-mutation-revert: `test_receipt_attestation.py` 15 passed; working tree
  clean of the mutant before this report.
