# Client Architecture: Apex Composition Layer

`libs/client` is the **apex composition layer** of the Loops substrate. It unites `atoms`, `store`, `lang`, `sign`, `custody`, and `engine` into unified, typed, headless operations.

This document details the architectural rationale, the dependency DAG, dataflow sequences for all core operations, error taxonomy, and testing invariants.

---

## 1. Architectural Motivation

Prior to `libs/client`, presentation surfaces (`apps/loops/src/loops/commands/`) directly composed lower-level substrate libraries by hand. Each CLI command opened SQLite connections, resolved KDL declarations, invoked custody signers, and inspected internal tables independently.

This created several architectural hazards:
1. **Coupling to Presentation**: Substrate logic was entangled with Click/argparse CLI flags and ANSI terminal formatting.
2. **Duplicated Ceremonies**: Admission checks, key resolution, and preflight recovery were re-implemented across command modules.
3. **Leaky Storage Invariants**: Commands made assumptions about SQLite vs JSONL residence rather than treating storage as an authoritative append-only log.

`libs/client` resolves this by establishing a strict **headless API floor**. Downstream presentation layers (`apps/loops`, TUI, external scripts, background agents) consume `client` exclusively and contain zero substrate orchestration logic.

---

## 2. Monorepo Layer Hierarchy

The Loops monorepo enforces a strict directed acyclic graph (DAG) verified by `tests/test_architecture.py` and `./dev check`:

```mermaid
graph TD
    subgraph Presentation ["Layer 6: Presentation (CLI & Apps)"]
        APPS["apps/loops (CLI, TUI, HTTP)"]
    end

    subgraph Composition ["Layer 5: Apex Composition"]
        CLIENT["libs/client (Headless Operations & Models)"]
    end

    subgraph CoreEngine ["Layer 4: Execution & Policy"]
        ENGINE["libs/engine (Admission, Handle, Witness, Ceremonies)"]
    end

    subgraph CustodyLayer ["Layer 3: Key Custody"]
        CUSTODY["libs/custody (Observer Keyring & Signing)"]
    end

    subgraph SyntaxLayer ["Layer 2: Syntax & AST"]
        LANG["libs/lang (KDL Grammar, AST Mutations)"]
    end

    subgraph StorageCrypto ["Layer 1: Storage & Cryptography"]
        STORE["libs/store (Append-Only Log, SQLite Index, Merge)"]
        SIGN["libs/sign (Ed25519 Primitives & Envelopes)"]
    end

    subgraph Primitives ["Layer 0: Pure Primitives"]
        ATOMS["libs/atoms (Fact, Tick, Fold Ops, State)"]
    end

    APPS --> CLIENT
    CLIENT --> ENGINE
    CLIENT --> CUSTODY
    CLIENT --> LANG
    CLIENT --> STORE
    CLIENT --> SIGN
    CLIENT --> ATOMS

    ENGINE --> CUSTODY
    ENGINE --> LANG
    ENGINE --> STORE
    ENGINE --> SIGN
    ENGINE --> ATOMS

    CUSTODY --> SIGN
    CUSTODY --> ATOMS
    LANG --> ATOMS
    STORE --> SIGN
    STORE --> ATOMS
    SIGN --> ATOMS
```

### Layer Responsibilities

| Layer | Library | Primary Concern |
| :--- | :--- | :--- |
| **0. Primitives** | `libs/atoms` | Pure, immutable data structures (`Fact`, `Tick`, `FoldOp`, `Spec`). Zero I/O or crypto. |
| **1. Storage** | `libs/store` | Append-only storage (`.jsonl` canonical logs & SQLite indices), fact hashing, and merge algebra. |
| **1. Crypto** | `libs/sign` | Ed25519 key management, JCS canonical serialization (RFC 8785), and signature envelopes. |
| **2. Language** | `libs/lang` | KDL document parsing, AST definitions (`LoopDef`, `FoldDecl`), validator, and AST mutation splices. |
| **3. Custody** | `libs/custody` | Identity isolation and observer private key custody. |
| **4. Engine** | `libs/engine` | Witness cursors (`WitnessPosition`), admission policy enforcement, declaration resolution, and state folding. |
| **5. Composition** | `libs/client` | **Apex headless operations**: Target resolution, read queries, signed emission, and declaration ceremonies. |
| **6. Presentation** | `apps/loops` | CLI flag parsing, TUI rendering, table formatting, and exit code routing. |

---

## 3. Core Dataflows & Sequences

### Flow A: Target Probing & Resolution (`resolve_target`)

Target probing inspects paths without mutating disk state, spawning WAL files, or constructing unneeded database connections.

```mermaid
sequenceDiagram
    autonumber
    actor Consumer as Caller (CLI / App)
    participant Client as client.target
    participant Probe as engine.probe
    participant Residence as engine.residence

    Consumer->>Client: resolve_target("my_vertex.vertex")
    Client->>Client: Path("my_vertex.vertex").resolve()
    alt Path Does Not Exist
        Client-->>Consumer: raise TargetNotFound
    end
    Client->>Probe: probe_target(path)
    Probe->>Residence: canonical_store_path(), index_path_for()
    Probe-->>Client: TargetInfo(...)
    alt target_type == "unknown"
        Client-->>Consumer: raise TargetUnsupported
    end
    Client-->>Consumer: TargetInfo(target_type, canonical_path, index_path, exists, writable)
```

---

### Flow B: Bounded Read & Witness Pagination (`read_facts`)

Reads operate along the **witness axis** (storage append order / `rowid`) using `WitnessPosition` cursors to prevent duplicate or skipped facts during pagination.

```mermaid
sequenceDiagram
    autonumber
    actor Consumer as Caller
    participant Client as client.read
    participant Preflight as engine.preflight
    participant Reader as engine.store_reader.StoreReader
    participant Store as SQLite / JSONL

    Consumer->>Client: read_facts(target, limit=10, before=cursor, order="newest")
    Client->>Client: resolve_target(target)
    Client->>Preflight: read_preflight(canonical_path, RECOVER_THEN_OPEN)
    Preflight->>Store: Check offset parity & recovery status
    Preflight-->>Client: Store ready
    Client->>Reader: StoreReader(index_path).query_facts(limit=10, before=cursor, order="newest")
    Reader->>Store: SELECT ... WHERE rowid < before.rowid ORDER BY rowid DESC LIMIT 11
    Store-->>Reader: rows (11 fetched for truncation probe)
    Reader-->>Client: FactPage(items, next_position, truncated)
    Client-->>Consumer: FactPageResult(items, next_cursor, truncated, order="newest")
```

---

### Flow C: Validated Fact Emission (`emit_fact`)

Fact emission validates declared observer and kind admission, attaches signatures via Custody, and produces an immutable `EmitReceipt`.

```mermaid
sequenceDiagram
    autonumber
    actor Consumer as Caller
    participant Client as client.emit
    participant Custody as custody.signing
    participant Handle as engine.handle.open_vertex
    participant Admission as engine.admission
    participant Store as engine.store

    Consumer->>Client: emit_fact(target, kind="note", payload={...}, observer="alice")
    Client->>Client: resolve_target(target) (must be .vertex)
    Client->>Custody: fact_signer_for(vertex), tick_signer_for(vertex)
    Custody-->>Client: WriteCredentials(signers)
    Client->>Handle: open_vertex(target, credentials)
    Client->>Handle: handle.receive_as(fact, admit_undeclared=False)
    Handle->>Admission: Verify observer grant & strict kind declaration
    alt Admission Rejected
        Admission-->>Client: raise AdmissionError
        Client-->>Consumer: raise AdmissionFailed
    end
    Handle->>Store: Append to canonical store & update derived index
    Handle->>Custody: Sign committed row
    Store-->>Handle: Commit receipt + Tick attestation
    Handle-->>Client: ReceiveResult(receipt, tick, change)
    Client-->>Consumer: EmitReceipt(id, stored=True, signed=True, observer="alice", state_change=True)
```

---

### Flow D: AST Declaration Mutations (`add_kind`, `edit_kind`, `remove_kind`)

Declarative updates mutate the KDL AST with syntax verification and execute via transactional plan/apply ceremonies.

```mermaid
sequenceDiagram
    autonumber
    actor Consumer as Caller
    participant Client as client.kind
    participant Lang as lang.vertex_mutation
    participant Ceremony as engine.ceremony
    participant File as Filesystem (.vertex & .intent)

    Consumer->>Client: add_kind(target, "task", LoopDef(...), observer="admin")
    Client->>Client: Read current .vertex content
    Client->>Lang: add_vertex_kind(text, "task", definition)
    Lang->>Lang: Splice KDL lexemes & re-parse via safety oracle
    Lang-->>Client: new_vertex_text
    Client->>Ceremony: plan_declaration_update(vertex, new_text)
    Ceremony-->>Client: DeclarationUpdatePreview(applicable=True, changes, mode)
    Client->>Ceremony: apply_declaration_update(preview, observer="admin", credentials)
    Ceremony->>File: Write .intent lock file (O_CREAT | O_EXCL)
    Ceremony->>File: Atomically replace .vertex file
    Ceremony->>File: Remove .intent lock file
    Ceremony-->>Client: ApplyResult(status="applied", file_written=True)
    Client-->>Consumer: KindMutationResult(status="applied", generation_after, changes)
```

---

## 4. Exception Hierarchy & Failure Semantics

All client exceptions derive from `ClientError`, providing clean distinction between resolution, admission, emission, and ceremony failures:

```text
ClientError
 ├── TargetError
 │    ├── TargetNotFound       (Target path does not exist on disk)
 │    ├── TargetUnsupported    (Path exists but is not a Loops artifact)
 │    └── TargetNotWritable    (Target or derived index cannot be written)
 ├── AdmissionFailed           (Strict kind refusal or undeclared observer)
 ├── EmissionFailed            (Failed prior to store commitment)
 │    └── CommittedEmissionError (Fact committed to store, but post-commit task failed)
 └── CeremonyFailed            (AST parse rejection or ceremony apply conflict)
```

### Committed Error Honesty
If a fact successfully commits to the append-only log but a subsequent indexing or notification step fails, the system raises `CommittedEmissionError` carrying `.fact_id`. This informs callers that the event was recorded and prevents blind, duplicate retries.

---

## 5. Verification & Testing Discipline

`libs/client` is verified across three layers of the test pyramid:

```text
▲ [Layer 3: Property Invariants]  test_properties_client.py (Hypothesis)
│                                  • Pagination completeness without duplicates or drops
│                                  • Fact total summary conservation fixpoints
│
▲ [Layer 2: Composition & Int]     test_read.py, test_emit.py, test_kind.py, test_smoke.py
│                                  • Cursor pagination (before/after) & ordering
│                                  • Declared admission vs strict rejection
│                                  • Custody signing & attestation capture
│                                  • AST ceremonies (add/edit/remove) & intent recovery
│
▲ [Layer 1: Unit & Contracts]      test_target.py, test_types.py
                                   • Path probing for .vertex, .jsonl, .db, .sqlite
                                   • Frozen model immutability & .as_dict() serialization
```

### Verification Invariants

1. **Repo Ratchet**: Enforced via `./dev check` (`tests/test_architecture.py`).
2. **Package Tests**: Run via `uv run --package client pytest libs/client/tests`.
3. **Immutability**: All returned result models are frozen dataclasses.
