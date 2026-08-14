"""Declaration-update orchestration — plan → apply → recover (libs-handoff S2).

The one place that owns the 8-step declaration-update protocol clients used to
re-assemble by hand (parse, resolve, head-capture, project, diff, open the
right canonical store with signing, CAS absorb, reconcile the ``.vertex``
file). LIBS_CHANGES P0.2 ("one declaration-update orchestration API") and
P0.3 ("recoverable file/store declaration synchronization").

Shape: free functions, like :func:`engine.handle.open_vertex` — a ceremony is
a one-shot operation keyed on a vertex path, not a held session, so it does
NOT live on :class:`~engine.handle.VertexHandle` (which serializes a live
read/receive stream). Signing rides the ratified S3
:class:`~engine.handle.CredentialProvider` shape — the import DAG forbids
engine→custody, so key material is always supplied by the caller,
operation-fresh.

Protocol rules owned here
-------------------------

- **Store-first after genesis.** The store-backed declaration is the
  authority; the ``.vertex`` file is an ingress/presentation cache. Apply
  order is: durable intent → store ceremony (atomic, CAS-guarded by the S1b
  machinery) → atomic file replace → intent removal. Every prefix of that
  sequence is recoverable.
- **Durable intent** (P0.3) lives as a SIBLING of the ``.vertex`` file —
  ``<name>.vertex.intent`` — written atomically (tempfile + fsync + rename)
  BEFORE anything mutates. Sibling, not store-adjacent, because (a) the
  vertex path is the one handle plan, apply, and recover all share; (b) a
  JSONL-canonical store has TWO adjacent artifacts (log + index) and no
  single obvious sibling slot; and (c) the store locator is exactly the kind
  of thing a ceremony may be mid-edit on — the file being reconciled is the
  stable coordinate. It survives process death and is discoverable by
  anything that knows the vertex (``intent_path_for``).
- **Pending intent blocks new ceremonies.** ``plan``/``apply`` refuse (typed)
  while an intent file exists — run :func:`recover_declaration_update`
  first. This is what makes the ``conflict`` classification non-lossy:
  nothing overwrites the evidence.
- **Staleness is the store's CAS, not a re-check race.** ``apply`` passes the
  preview's captured head to ``absorb_edit(expected_head=…)``; a moved head
  refuses inside the store's own transaction
  (:class:`~engine.sqlite_store.StaleDeclarationHead`) with the log
  byte-identical — reused as the ``"stale"`` result, never re-spelled here.
  Genesis mode has no CAS parameter; its stale signal is
  :class:`~engine.sqlite_store.GenesisExists` (a concurrent absorb opened
  the lineage first).
- **Recovery never guesses.** :func:`recover_declaration_update` classifies
  by comparing the store's CURRENT resolved projection fingerprint against
  the fingerprints pinned in the intent: proposed → ``already-applied`` /
  ``safe-to-finish``; the captured pre-ceremony state → ``not-applied``
  (store untouched — the process died before the store commit; the intent is
  void); anything else → ``conflict`` (another writer landed; intent and
  file are left exactly as found). ``not-applied`` is an honest EXTENSION of
  the task's three classes: store-first ordering makes "intent written,
  store never touched" a reachable state, and folding it into either
  ``conflict`` or ``safe-to-finish`` would be a guess.
- **Fingerprints are order-independent.** Documents are sorted by
  ``(kind, subject)`` before hashing: the file projects documents in
  declaration order while the store fold keeps genesis order and APPENDS
  added subjects, so an order-sensitive hash (like ``declaration_generation``'s
  review fingerprint) would misclassify a committed ceremony as ``conflict``
  whenever an author added a kind mid-file.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .handle import CredentialProvider

__all__ = [
    "CeremonyError",
    "IntentCorrupt",
    "DeclarationUpdatePreview",
    "DeclarationUpdateResult",
    "RecoveryOutcome",
    "plan_declaration_update",
    "apply_declaration_update",
    "recover_declaration_update",
    "intent_path_for",
]

INTENT_SUFFIX = ".intent"
_INTENT_VERSION = 1


class CeremonyError(Exception):
    """A ceremony input that cannot be classified — malformed, not stale."""


class IntentCorrupt(CeremonyError):
    """An intent file exists but does not decode to a v1 intent record.

    Recovery refuses rather than guessing: a corrupt intent is evidence of a
    torn write or foreign tampering, and the safe answer is a human look, not
    a silent delete.
    """


def intent_path_for(vertex_path: Path | str) -> Path:
    """The durable-intent sibling for a vertex: ``<name>.vertex.intent``."""
    vertex_path = Path(vertex_path)
    return vertex_path.parent / (vertex_path.name + INTENT_SUFFIX)


def _fingerprint_documents(docs: list[dict[str, Any]]) -> str:
    """Order-independent content hash over a document projection.

    Sorted by ``(kind, subject)`` — see the module docstring for why order
    must not participate. Distinct from ``declaration_generation``'s
    review fingerprint (order-sensitive, same-source comparator): this one
    compares projections across residences and fold orderings.
    """
    ordered = sorted(docs, key=lambda d: (d["kind"], d["subject"]))
    canonical = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    """Tempfile + fsync + rename in ``path``'s directory — the JsonlStore
    durability discipline: the rename publishes only fully-durable bytes."""
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        Path(tmp).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


def _default_file_write(vertex_path: Path, proposed_text: str | None) -> None:
    """The shipped file-cache replacement policy: atomically replace the
    ``.vertex`` with the proposed source text, byte-preserving what the author
    wrote (presentation stays the author's — the library imposes no
    re-rendering). ``None`` (an AST-only plan) is a disclosed no-op: there is
    no canonical text to write, and inventing one is presentation policy an
    app must inject via ``write_file=``."""
    if proposed_text is None:
        return
    _atomic_write(vertex_path, proposed_text)


def _backend_not_writable(canonical_path: Path) -> str | None:
    """Reason the backend WRITE SURFACE is not writable, or ``None``.

    SOL-R2-04: the ceremony's store step writes more than the canonical
    artifact — a JSONL-canonical open also writes the derived sqlite index,
    and any sqlite open needs the containing directory for its WAL/SHM
    siblings. Probing only the log let a writable log inside a read-only
    directory plan as applicable and then fail raw at apply. ``_writable``
    walks to the nearest existing ancestor, so a missing index counts as
    creatable when its directory is writable.
    """
    from .probe import _writable
    from .residence import index_path_for

    if not _writable(canonical_path):
        return f"canonical store not writable: {canonical_path}"
    index = index_path_for(canonical_path)  # idempotent on a .db
    if not _writable(index):
        return f"derived index not writable: {index}"
    if not _writable(canonical_path.parent):
        return (
            f"store directory not writable: {canonical_path.parent} — "
            "sqlite needs it for WAL/SHM siblings"
        )
    return None


def _open_store(canonical_path: Path):
    from atoms import Fact

    from .jsonl_store import open_canonical_store

    return open_canonical_store(
        canonical_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )


# ---------------------------------------------------------------------------
# Preview / result / recovery types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclarationUpdatePreview:
    """Everything ``apply`` needs, captured in one read pass.

    ``mode`` selects the ceremony (``"genesis"`` opens the lineage,
    ``"edit"`` re-emits changed subjects). ``authority`` says which side is
    currently authoritative for resolution — ``"file"`` pre-genesis,
    ``"store"`` after. ``applicable`` + ``reason`` is the backend verdict:
    ``False`` previews still describe honestly (the divergence surface), but
    ``apply`` refuses them typed."""

    vertex_path: Path
    mode: str  # "genesis" | "edit"
    declaration_status: str  # load_declaration_status label at plan time
    generation: dict[str, Any]  # declaration_generation() disclosure
    canonical_mode: str  # "jsonl" | "sqlite"
    canonical_path: Path
    index_path: Path
    changes: tuple  # lang.document.Change rows; () in genesis mode
    documents: tuple  # proposed projection, Document.as_json dicts
    proposed_fingerprint: str
    old_store_fingerprint: str | None  # store projection at plan; None pre-genesis
    expected_head: tuple[float, str] | None  # CAS token; None in genesis mode
    authority: str  # "file" | "store"
    applicable: bool
    reason: str
    proposed_text: str | None
    pending_intent: Path | None


@dataclass(frozen=True)
class DeclarationUpdateResult:
    """``apply``'s typed outcome. ``status`` ∈ ``applied`` / ``noop`` /
    ``stale`` / ``pending-intent`` / ``refused`` / ``needs-recovery``.

    ``needs-recovery`` is the typed recovery state: the store ceremony
    COMMITTED but the file step failed — the intent is left in place
    (``intent_path``) and :func:`recover_declaration_update` finishes."""

    status: str
    reason: str
    receipt: dict[str, Any] | None = None
    intent_path: Path | None = None
    file_written: bool = False


@dataclass(frozen=True)
class RecoveryOutcome:
    """``recover``'s typed classification — never a guess.

    ``classification`` ∈ ``already-applied`` / ``safe-to-finish`` /
    ``not-applied`` / ``conflict``. ``finished`` is True only when a
    ``safe-to-finish`` run actually completed the file replace this call."""

    classification: str
    finished: bool
    reason: str
    intent_path: Path


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def plan_declaration_update(
    vertex_path: Path | str,
    proposed_ast: Any = None,
    *,
    proposed_text: str | None = None,
) -> DeclarationUpdatePreview:
    """Plan a declaration update — read-only over canonical state.

    (Opening a JSONL-canonical store to capture the CAS token may
    materialize/catch up the DERIVED index — rebuildable state, never the
    log or the file.)

    ``proposed_text`` is the preferred proposal channel (KDL source — it also
    powers the default file-cache replacement); ``proposed_ast`` alone plans
    fine but marks the default file step unavailable. Neither → the current
    ``.vertex`` bytes ARE the proposal (the classic absorb flow: the author
    edited the file, the store must catch up).

    The proposal is validated (``lang.validate_vertex``) before anything else:
    absorb mints immutable signed events, so an invalid declaration must
    never enter the lineage — malformed input raises, it is not a recovery
    state.

    Capture ordering (conservative under concurrency, same as the CLI it
    replaces): the CAS token (``declaration_head()``) is read BEFORE the fold
    head used for the diff, so a concurrent edit landing between the two
    makes ``apply`` refuse stale rather than interleave.
    """
    from lang import parse_vertex, validate_vertex
    from lang.document import diff_documents, vertex_to_documents

    from .declaration import (
        declaration_generation,
        resolve_declaration_documents,
    )
    from .probe import probe_target

    vertex_path = Path(vertex_path).resolve()

    # Proposal resolution + validation (raises on malformed input).
    if proposed_ast is None:
        if proposed_text is None:
            proposed_text = vertex_path.read_text(encoding="utf-8")
        proposed_ast = parse_vertex(proposed_text, vertex_path)
    # AST-only plan (proposed_ast given, proposed_text None): the default
    # file step stays unavailable — disclosed via preview.proposed_text.
    validate_vertex(proposed_ast)

    new_docs = vertex_to_documents(proposed_ast)
    documents = tuple(d.as_json() for d in new_docs)
    proposed_fingerprint = _fingerprint_documents(list(documents))

    info = probe_target(vertex_path)
    generation = declaration_generation(vertex_path)
    status = generation["status"]
    pending = intent_path_for(vertex_path)
    pending_intent = pending if pending.exists() else None

    def _preview(
        *,
        mode: str,
        changes: tuple = (),
        expected_head: tuple[float, str] | None = None,
        old_store_fingerprint: str | None = None,
        authority: str,
        applicable: bool,
        reason: str,
    ) -> DeclarationUpdatePreview:
        return DeclarationUpdatePreview(
            vertex_path=vertex_path,
            mode=mode,
            declaration_status=status,
            generation=generation,
            canonical_mode=info.canonical_mode or "sqlite",
            canonical_path=info.canonical_path or vertex_path,
            index_path=info.index_path or vertex_path,
            changes=changes,
            documents=documents,
            proposed_fingerprint=proposed_fingerprint,
            old_store_fingerprint=old_store_fingerprint,
            expected_head=expected_head,
            authority=authority,
            applicable=applicable,
            reason=reason,
            proposed_text=proposed_text,
            pending_intent=pending_intent,
        )

    if info.target_type != "vertex" or info.canonical_path is None:
        return _preview(
            mode="genesis",
            authority="file",
            applicable=False,
            reason=info.reason
            if info.target_type == "vertex"
            else f"not a vertex declaration: {info.reason}",
        )

    if pending_intent is not None:
        return _preview(
            mode="genesis" if generation["lineage"] is None else "edit",
            authority="file" if generation["lineage"] is None else "store",
            applicable=False,
            reason=(
                f"pending declaration-update intent at {pending_intent} — "
                "run recover_declaration_update first"
            ),
        )

    # Applicability spans EVERYTHING the ceremony writes: the vertex file
    # (info.writable — the probed path) and the canonical store's full
    # backend write surface (SOL-R1-04 + SOL-R2-04: log, derived index,
    # and the directory sqlite needs for WAL/SHM siblings — plan must not
    # report a plan as applicable that apply's store step cannot execute).
    surface_reason = _backend_not_writable(info.canonical_path)
    store_writable = info.canonical_writable is not False and surface_reason is None
    writable = info.writable and store_writable
    not_writable_reason = (
        info.reason
        if not info.writable
        else (
            surface_reason
            or f"canonical store not writable: {info.canonical_path}"
        )
    )

    if generation["lineage"] is None:
        # Pre-genesis (or unadopted): the file is authoritative; the ceremony
        # is genesis. An unadopted store with genesis rows will refuse at
        # apply time (AmbiguousGenesis / GenesisExists) — identity is adopted,
        # never inferred, and plan does not pre-judge it.
        return _preview(
            mode="genesis",
            authority="file",
            applicable=writable,
            reason="lineage not open — genesis ceremony"
            if writable
            else not_writable_reason,
        )

    # Edit mode. CAS token FIRST, then the fold head for the diff.
    store = _open_store(info.canonical_path)
    try:
        expected_head = store.declaration_head()
    finally:
        store.close()

    head_docs = resolve_declaration_documents(info.index_path)
    if not isinstance(head_docs, list):
        return _preview(
            mode="edit",
            expected_head=expected_head,
            authority="store",
            applicable=False,
            reason=(
                "store head unavailable — lineage looks unopened or "
                "unhistorized; nothing to diff against"
            ),
        )

    changes = tuple(diff_documents(head_docs, new_docs))
    return _preview(
        mode="edit",
        changes=changes,
        expected_head=expected_head,
        old_store_fingerprint=_fingerprint_documents(head_docs),
        authority="store",
        applicable=writable,
        reason=(
            (
                f"{len(changes)} changed subject(s)"
                if changes
                else "file matches store head — nothing to apply"
            )
            if writable
            else not_writable_reason
        ),
    )


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _write_intent(preview: DeclarationUpdatePreview, observer: str) -> Path:
    intent = {
        "v": _INTENT_VERSION,
        "mode": preview.mode,
        "vertex_path": str(preview.vertex_path),
        "canonical_path": str(preview.canonical_path),
        "created_ts": datetime.now(UTC).timestamp(),
        "observer": observer,
        "old_status": preview.declaration_status,
        "old_decl_head": list(preview.expected_head)
        if preview.expected_head
        else None,
        "old_store_fingerprint": preview.old_store_fingerprint,
        "lineage": preview.generation.get("lineage"),
        "proposed_fingerprint": preview.proposed_fingerprint,
        "proposed_documents": list(preview.documents),
        "proposed_text": preview.proposed_text,
    }
    path = intent_path_for(preview.vertex_path)
    _atomic_write(path, json.dumps(intent, indent=2) + "\n")
    return path


def _remove_intent(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def apply_declaration_update(
    preview: DeclarationUpdatePreview,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
    write_file: Callable[[Path, str | None], None] | None = None,
) -> DeclarationUpdateResult:
    """Apply a planned declaration update — atomic, or a typed state.

    Sequence (store-first, every prefix recoverable):

    1. durable intent (sibling ``.vertex.intent``, tempfile+fsync+rename);
    2. the S1b store ceremony — ``absorb_genesis`` or
       ``absorb_edit(expected_head=preview.expected_head)`` — which holds the
       identity check, CAS, sign-final-payload, and append in ONE
       transaction; a stale preview refuses INSIDE that transaction with the
       canonical log byte-identical;
    3. the file-cache replace (``write_file`` injectable; the shipped default
       atomically writes ``preview.proposed_text``);
    4. intent removal.

    A failure in (2) removes the intent (nothing mutated) and returns
    ``stale``/``refused``. A failure in (3) — including process death,
    which simply never reaches (4) — leaves the intent for
    :func:`recover_declaration_update` and, when the process survives to
    report it, returns the typed ``needs-recovery`` state.

    ``credentials`` supplies the operation-fresh fact signer
    (:class:`~engine.handle.CredentialProvider`, the ratified S3 shape);
    ``None`` or a ``None`` signer refuses at the store's own signing gate —
    declaration events are the attestation root.
    """
    from .sqlite_store import (
        AmbiguousGenesis,
        GenesisExists,
        NoGenesis,
        ReservedKindViolation,
        StaleDeclarationHead,
        UnsignableEdit,
        UnsignableGenesis,
    )

    vertex_path = preview.vertex_path
    pending = intent_path_for(vertex_path)
    if pending.exists():
        return DeclarationUpdateResult(
            status="pending-intent",
            reason=(
                f"pending declaration-update intent at {pending} — run "
                "recover_declaration_update first"
            ),
            intent_path=pending,
        )
    if not preview.applicable:
        return DeclarationUpdateResult(status="refused", reason=preview.reason)
    if preview.mode == "edit" and not preview.changes:
        return DeclarationUpdateResult(
            status="noop", reason="file matches store head — nothing to apply"
        )

    # Canonical-store write-surface gate (SOL-R1-04 + SOL-R2-04): a typed
    # refusal BEFORE any intent lands — and before the edit-mode currency
    # pre-check, whose store open could itself fail raw on an unwritable
    # backend. An unwritable store must leave zero residue.
    surface_reason = _backend_not_writable(preview.canonical_path)
    if surface_reason is not None:
        return DeclarationUpdateResult(
            status="refused",
            reason=f"{surface_reason} — refusing before intent creation",
        )

    fact_signer = None
    if credentials is not None:
        fact_signer = credentials.for_write(vertex_path).fact_signer

    # Cheap currency pre-check (edit mode) before the intent lands — the CAS
    # inside absorb_edit remains the atomic guard; this only avoids intent
    # churn on an already-known-stale preview.
    if preview.mode == "edit":
        import sqlite3

        try:
            store = _open_store(preview.canonical_path)
        except (sqlite3.Error, OSError) as exc:
            return DeclarationUpdateResult(
                status="refused",
                reason=(
                    f"canonical store backend refused the open: {exc} — "
                    "refusing before intent creation"
                ),
            )
        try:
            head_now = store.declaration_head()
        finally:
            store.close()
        if head_now != preview.expected_head:
            return DeclarationUpdateResult(
                status="stale",
                reason=(
                    f"declaration head moved: preview captured "
                    f"{preview.expected_head}, store is at {head_now} — "
                    "re-plan against the current head"
                ),
            )

    intent_path = _write_intent(preview, observer)

    # The writability probe cannot eliminate races (permissions can change
    # between gate and open) — so expected backend failures during the store
    # step are translated into a typed refusal that removes the pre-commit
    # intent (SOL-R2-04: the typed-catch is the floor). Scope: from the open
    # through the absorb; absorb either commits-and-returns or raises with
    # the log untouched, so a caught error here means nothing mutated.
    import sqlite3

    try:
        store = _open_store(preview.canonical_path)
    except (sqlite3.Error, OSError) as exc:
        _remove_intent(intent_path)
        return DeclarationUpdateResult(
            status="refused",
            reason=(
                f"canonical store backend refused the open: {exc} — "
                "intent removed, nothing mutated"
            ),
        )
    try:
        if preview.mode == "genesis":
            try:
                receipt = store.absorb_genesis(
                    list(preview.documents),
                    observer=observer,
                    origin="",
                    fact_signer=fact_signer,
                )
            except GenesisExists as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(
                    status="stale",
                    reason=f"lineage opened since plan: {exc}",
                )
            except (AmbiguousGenesis, UnsignableGenesis) as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(status="refused", reason=str(exc))
            except (sqlite3.Error, OSError) as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(
                    status="refused",
                    reason=(
                        f"store backend failed during genesis: {exc} — "
                        "intent removed, nothing committed"
                    ),
                )
        else:
            try:
                receipt = store.absorb_edit(
                    list(preview.changes),
                    observer=observer,
                    origin="",
                    fact_signer=fact_signer,
                    expected_head=preview.expected_head,
                )
            except StaleDeclarationHead as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(status="stale", reason=str(exc))
            except (
                AmbiguousGenesis,
                NoGenesis,
                ReservedKindViolation,
                UnsignableEdit,
            ) as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(status="refused", reason=str(exc))
            except (sqlite3.Error, OSError) as exc:
                _remove_intent(intent_path)
                return DeclarationUpdateResult(
                    status="refused",
                    reason=(
                        f"store backend failed during edit: {exc} — "
                        "intent removed, nothing committed"
                    ),
                )
    finally:
        store.close()

    # Store committed — the point of no return. File replace, then intent
    # removal; any failure from here is the recover path's job.
    writer = write_file or _default_file_write
    try:
        writer(vertex_path, preview.proposed_text)
    except BaseException as exc:  # noqa: BLE001 — typed recovery, not a crash
        return DeclarationUpdateResult(
            status="needs-recovery",
            reason=(
                f"store ceremony committed but the file step failed ({exc}) — "
                "run recover_declaration_update on the intent"
            ),
            receipt=receipt,
            intent_path=intent_path,
        )
    _remove_intent(intent_path)
    return DeclarationUpdateResult(
        status="applied",
        reason="declaration updated — store committed, file reconciled",
        receipt=receipt,
        file_written=preview.proposed_text is not None or write_file is not None,
    )


# ---------------------------------------------------------------------------
# recover
# ---------------------------------------------------------------------------


def recover_declaration_update(intent: Path | str) -> RecoveryOutcome:
    """Classify and (when safe) finish an interrupted declaration update.

    Idempotent: a ``safe-to-finish`` run completes the file replace and
    removes the intent; a second run over the same path answers
    ``already-applied`` (no pending intent). ``conflict`` leaves the intent
    AND the file exactly as found — nothing is ever clobbered on that path.

    Classification (module docstring has the full rule): the store's current
    resolved projection fingerprint against the intent's pins — proposed →
    applied (file matching decides ``already-applied`` vs
    ``safe-to-finish``); the pre-ceremony state → ``not-applied`` (intent
    void, removed); anything else → ``conflict``.
    """
    intent_path = Path(intent)
    if not intent_path.exists():
        return RecoveryOutcome(
            classification="already-applied",
            finished=False,
            reason="no pending intent at this path — nothing to recover",
            intent_path=intent_path,
        )
    try:
        record = json.loads(intent_path.read_text(encoding="utf-8"))
        if record.get("v") != _INTENT_VERSION:
            raise ValueError(f"unsupported intent version {record.get('v')!r}")
        mode = record["mode"]
        vertex_path = Path(record["vertex_path"])
        canonical_path = Path(record["canonical_path"])
        proposed_fingerprint = record["proposed_fingerprint"]
        old_store_fingerprint = record.get("old_store_fingerprint")
        proposed_text = record.get("proposed_text")
    except (ValueError, KeyError, TypeError) as exc:
        raise IntentCorrupt(
            f"intent at {intent_path} is not a readable v{_INTENT_VERSION} "
            f"record ({exc}) — refusing to classify from corrupt evidence"
        ) from exc

    from .declaration import resolve_declaration_documents
    from .residence import index_path_for

    index_path = index_path_for(canonical_path)
    # Materialize/catch up the index from the canonical log first: a death
    # between the log append and the index commit must still classify as
    # applied (the log is the store). Opening the store runs the S1b
    # tail-in/rebuild rules; a nonexistent store stays nonexistent enough.
    if canonical_path.exists() or index_path.exists():
        store = _open_store(canonical_path)
        store.close()
    current = resolve_declaration_documents(index_path)

    # None = pre-genesis / unusable — no store projection to fingerprint.
    current_fp = _fingerprint_documents(current) if isinstance(current, list) else None

    if current_fp == proposed_fingerprint:
        # Store committed. Does the file already match?
        file_matches = (
            proposed_text is not None
            and vertex_path.exists()
            and vertex_path.read_text(encoding="utf-8") == proposed_text
        )
        if file_matches:
            _remove_intent(intent_path)
            return RecoveryOutcome(
                classification="already-applied",
                finished=False,
                reason="store committed and file already matches the proposal",
                intent_path=intent_path,
            )
        if proposed_text is None:
            # AST-only plan: the store is authoritative and committed, but no
            # canonical text was captured to finish the file with. Disclosed,
            # not guessed; the intent stays until an app finishes the file
            # its own way and removes it (or re-plans from the file).
            return RecoveryOutcome(
                classification="safe-to-finish",
                finished=False,
                reason=(
                    "store committed but the intent carries no proposed text "
                    "— finish the file with app presentation policy, then "
                    "remove the intent"
                ),
                intent_path=intent_path,
            )
        _atomic_write(vertex_path, proposed_text)
        _remove_intent(intent_path)
        return RecoveryOutcome(
            classification="safe-to-finish",
            finished=True,
            reason="store had committed — file replaced atomically, intent cleared",
            intent_path=intent_path,
        )

    store_untouched = (
        current_fp == old_store_fingerprint
        if mode == "edit"
        else current_fp is None
    )
    if store_untouched:
        _remove_intent(intent_path)
        return RecoveryOutcome(
            classification="not-applied",
            finished=False,
            reason=(
                "store still at its pre-ceremony state — the ceremony never "
                "committed; intent discarded, nothing to finish"
            ),
            intent_path=intent_path,
        )

    return RecoveryOutcome(
        classification="conflict",
        finished=False,
        reason=(
            "store matches neither the proposal nor the pre-ceremony state — "
            "another writer landed; intent and file left untouched for review"
        ),
        intent_path=intent_path,
    )
