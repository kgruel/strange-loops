# Fact Emission in Loops

In the Loops paradigm, a **Fact** is an intentional observation produced by an **Observer** at a specific point in time. Emitting a fact appends it to an immutable, append-only store, evaluates it against declared admission policies, attaches cryptographic signatures via key custody, and folds it into living state.

The `libs/client` library provides headless, transport-agnostic emission APIs for CLI commands, agents, TUI interfaces, and automated services.

---

## 1. Core Emission API

```python
from client import emit_fact, EmitReceipt

receipt = emit_fact(
    "path/to/project.vertex",
    kind_or_fact="task",
    payload={"title": "Design client emission API", "priority": 1},
    observer="alice",
)

# Or emitting a pre-constructed Fact atom directly:
from atoms import Fact

fact = Fact.of("task", "alice", title="Design client emission API", priority=1)
receipt = emit_fact("path/to/project.vertex", fact)
```

### Signature

```python
def emit_fact(
    target: Path | str,
    kind_or_fact: str | Fact,
    payload: dict[str, Any] | None = None,
    *,
    observer: str | None = None,
    origin: str = "",
    ts: float | None = None,
    id_override: str | None = None,
    credentials: CredentialProvider | None = None,
    admit_undeclared: bool = False,
) -> EmitReceipt:
```

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`target`** | `Path \| str` | *required* | Path to the target `.vertex` declaration file. |
| **`kind_or_fact`** | `str \| Fact` | *required* | Domain routing key string, or a pre-instantiated `Fact` atom. |
| **`payload`** | `dict[str, Any] \| None` | `None` | Observation data dict (optional when passing a `Fact` atom). |
| **`observer`** | `str \| None` | `None` | Authorship identity attributing the fact (required when passing kind string). |
| **`origin`** | `str` | `""` | Optional origin or upstream provenance string (e.g. `"agent-session-42"`). |
| **`ts`** | `float \| None` | `None` | Unix timestamp in seconds. Defaults to `datetime.now(UTC).timestamp()`. |
| **`id_override`** | `str \| None` | `None` | Optional deterministic ULID/UUID (for replay, migrations, and test vectors). |
| **`credentials`** | `CredentialProvider \| None` | `None` | Key provider. Defaults to `CustodyCredentialProvider` (loading keys from `keys/`). |
| **`admit_undeclared`** | `bool` | `False` | When `True`, overrides strict-mode kind admission refusal. |

---

## 2. Result Model: `EmitReceipt`

Every emission returns an immutable `EmitReceipt` dataclass:

```python
@dataclass(frozen=True)
class EmitReceipt:
    schema: str = "loops.cli/emit-receipt/v1"
    id: str = ""                # Canonical ULID assigned to the persisted fact
    stored: bool = True         # True when successfully committed to the log
    signed: bool | None = None  # True if signed with an Ed25519 custody key
    observer: str = ""          # Producing observer identity
    tick_mark: str | None = None# Name of tick mark if sealed (e.g. "default")
    tick_id: str | None = None  # Tick ID if a tick was closed during write
    state_change: bool = False  # True if this fact mutated the folded state

    def as_dict(self) -> dict[str, Any]: ...
```

---

## 3. Declared Admission Policy

Loops vertices can declare admission rules governing what facts are permitted:

### Strict Mode (`strict true`)
When a vertex declares `strict true`, any fact whose `kind` is not declared in the vertex's `loops { ... }` block is rejected before storage:

```python
from client import emit_fact, AdmissionFailed

try:
    emit_fact("strict_app.vertex", "custom_kind", {"data": 123}, observer="alice")
except AdmissionFailed as err:
    print(f"Emission rejected by strict policy: {err}")

# Explicit bypass when intentional:
receipt = emit_fact(
    "strict_app.vertex",
    "custom_kind",
    {"data": 123},
    observer="alice",
    admit_undeclared=True,
)
```

### Observer Grants (`observers { ... }`)
When a vertex declares an `observers { ... }` block, only declared observers with matching capability grants may emit facts. Undeclared observers raise `AdmissionFailed`.

---

## 4. Cryptographic Attestation & Key Custody

When signing keys exist in the vertex's `keys/` directory, `emit_fact` automatically signs the committed row using Ed25519:

```python
from custody import ensure_signing_key
from client import emit_fact

# Ensure custody keypair exists for 'alice'
ensure_signing_key("project.vertex", "alice")

# Fact is automatically signed
receipt = emit_fact("project.vertex", "note", {"body": "Signed"}, observer="alice")
assert receipt.signed is True
```

---

## 5. Error Taxonomy & Exception Handling

```text
ClientError
 ├── TargetError
 │    ├── TargetNotFound       # .vertex file does not exist on disk
 │    └── TargetUnsupported    # Target is not a recognized .vertex file
 ├── AdmissionFailed           # Refused by strict mode or observer grants
 └── EmissionFailed
      └── CommittedEmissionError # Stored to disk, but post-commit task failed
```

### Committed Error Honesty
If a fact is successfully appended to the canonical store but a post-commit operation (such as index update or notification hook) raises an error, `CommittedEmissionError` is raised with `.fact_id` populated:

```python
from client import CommittedEmissionError, emit_fact

try:
    receipt = emit_fact("project.vertex", "task", {"title": "Test"}, observer="alice")
except CommittedEmissionError as exc:
    print(f"Fact committed with ID {exc.fact_id}, but post-commit hook failed: {exc}")
    # Do NOT retry with a new ID; the fact is already durably recorded!
```

---

## 6. Emission Extension Roadmap

The following capabilities are planned for upcoming iterative slices:

1. **Deterministic IDs & `Fact` Object Overloads**: Accept pre-instantiated `atoms.Fact` objects and `id_override` parameter.
2. **Preflight Dry-Run (`preview_emission` / `dry_run=True`)**: Simulate admission, fold-key presence, and state diffs without disk mutations.
3. **Atomic Batch Emission (`emit_batch`)**: Commit multiple facts under a single transaction.
4. **Rich State Delta Receipts**: Surface affected fold sections and entity keys in `EmitReceipt`.
