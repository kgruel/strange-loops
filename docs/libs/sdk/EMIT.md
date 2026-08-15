# Fact Emission in Loops

In the Loops paradigm, a **Fact** is an intentional observation produced by an **Observer** at a specific point in time. Emitting a fact appends it to an immutable, append-only store, evaluates it against declared admission policies, attaches cryptographic signatures via key custody, and folds it into living state.

The `libs/sdk` library provides headless, transport-agnostic emission APIs for CLI commands, agents, TUI interfaces, and automated services.

---

## 1. Core Emission API

```python
from sdk import emit_fact, EmitReceipt

receipt = emit_fact(
    "path/to/project.vertex",
    kind_or_fact="task",
    payload={"title": "Design SDK emission API", "priority": 1},
    observer="alice",
)

# Or emitting a pre-constructed Fact atom directly:
from atoms import Fact

fact = Fact.of("task", "alice", title="Design SDK emission API", priority=1)
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

## 2. Result Models: `EmitReceipt` & `EmitPreviewResult`

### `EmitReceipt`
Every emission returns an immutable `EmitReceipt` dataclass:

```python
@dataclass(frozen=True)
class EmitReceipt:
    schema: str = "loops.sdk/emit-receipt/v1"
    id: str = ""                # Canonical ULID assigned to the persisted fact
    stored: bool = True         # True when successfully committed to the log (False on dry-run)
    signed: bool | None = None  # True if signed with an Ed25519 custody key
    observer: str = ""          # Producing observer identity
    tick_mark: str | None = None# Name of tick mark if sealed (e.g. "default")
    tick_id: str | None = None  # Tick ID if a tick was closed during write
    state_change: bool = False  # True only if this fact was committed and mutated folded state
    affected_sections: list[str] = field(default_factory=list) # Fold sections updated or predicted
    delta_count: int = 0        # Number of structural row changes committed in the fold
    predicted_state_change: bool = False # Predicted fold mutation on dry-run simulation

    def as_dict(self) -> dict[str, Any]: ...
```

### `EmitPreviewResult`
Preflight dry-run simulations return an `EmitPreviewResult`:

```python
@dataclass(frozen=True)
class EmitPreviewResult:
    schema: str = "loops.sdk/emit-preview/v1"
    target: str = ""
    kind: str = ""
    observer: str = ""
    origin: str = ""
    ts: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    kind_declared: bool = False
    fold_key_field: str | None = None
    fold_key_present: bool = True
    fold_key_value: Any | None = None
    admitted: bool = True
    strict: bool = False
    would_store: bool = True
    would_fold: bool = True

    def as_dict(self) -> dict[str, Any]: ...
```

---

## 3. Preflight & Dry-Run Simulation

Simulate whether a fact would be admitted, whether required fold keys are present, and whether state would mutate without writing to disk:

```python
from sdk import preview_emission, emit_fact

# Dedicated preflight inspection
preview = preview_emission(
    "project.vertex",
    kind_or_fact="task",
    payload={"title": "Test task"},
    observer="alice",
)
assert preview.admitted is True
assert preview.would_fold is True

# Or via emit_fact(..., dry_run=True)
uncommitted_receipt = emit_fact(
    "project.vertex",
    kind_or_fact="task",
    payload={"title": "Test task"},
    observer="alice",
    dry_run=True,
)
assert uncommitted_receipt.stored is False
assert uncommitted_receipt.state_change is False
assert uncommitted_receipt.predicted_state_change is True
```

---

## 4. Batch Fact Emission

Emit multiple facts sequentially under a single vertex handle session:

```python
from sdk import emit_batch
from atoms import Fact

items = [
    Fact.of("task", "alice", title="Task 1"),
    ("note", {"title": "Note 2"}),
    {"kind": "task", "payload": {"title": "Task 3"}, "observer": "bob"},
]

receipts = emit_batch("project.vertex", items, observer="alice")
assert len(receipts) == 3
assert all(r.stored for r in receipts)
```

---

## 5. Declared Admission Policy

Loops vertices can declare admission rules governing what facts are permitted:

### Strict Mode (`strict true`)
When a vertex declares `strict true`, any fact whose `kind` is not declared in the vertex's `loops { ... }` block is rejected before storage:

```python
from sdk import emit_fact, AdmissionFailed

try:
    emit_fact("strict_app.vertex", "custom_kind", {"data": 123}, observer="alice")
except AdmissionFailed as err:
    print(f"Emission rejected by strict policy: {err}")
    print(f"Rejected kind: {err.kind}, vertex: {err.vertex}")

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

## 6. Cryptographic Attestation & Key Custody

When signing keys exist in the vertex's `keys/` directory, `emit_fact` automatically signs the committed row using Ed25519:

```python
from custody import ensure_signing_key
from sdk import emit_fact

# Ensure custody keypair exists for 'alice'
ensure_signing_key("project.vertex", "alice")

# Fact is automatically signed
receipt = emit_fact("project.vertex", "note", {"body": "Signed"}, observer="alice")
assert receipt.signed is True
```

---

## 7. Error Taxonomy & Exception Handling

```text
SdkError
 ├── TargetError
 │    ├── TargetNotFound       # .vertex file does not exist on disk
 │    ├── TargetUnsupported    # Target is not a recognized .vertex file
 │    └── TargetNotWritable    # Target or derived index cannot be written
 ├── AdmissionFailed           # Refused by strict mode or observer grants (carries .observer, .kind, .vertex)
 ├── EmissionFailed
 │    ├── InvalidEmissionRequest # Invalid emission parameters or missing observer
 │    └── CommittedEmissionError # Stored to disk, but post-commit task failed (carries .fact_id)
 └── SdkValueError
      └── InvalidEmissionRequest # Inherits both SdkValueError and EmissionFailed (and ValueError)
```

### Committed Error Honesty
If a fact is successfully appended to the canonical store but a post-commit operation (such as index update or notification hook) raises an error, `CommittedEmissionError` is raised with `.fact_id` populated:

```python
from sdk import CommittedEmissionError, emit_fact

try:
    receipt = emit_fact("project.vertex", "task", {"title": "Test"}, observer="alice")
except CommittedEmissionError as exc:
    print(f"Fact committed with ID {exc.fact_id}, but post-commit hook failed: {exc}")
    # Do NOT retry with a new ID; the fact is already durably recorded!
```
