"""arrival_registry — which adapter opens which artifact.

Slice 2 of the arrival break (``design:arrival-break-slice2-backend-contract``
§B.4). Two halves, deliberately separable:

* :func:`descriptor_for` reads a parsed ``.vertex`` and answers what
  :class:`engine.arrival_contract.StoreDescriptor` — if any — describes its
  store. AST fields plus path arithmetic: no I/O, and no knowledge of which
  backends this process has. It can answer about a ``backend="duckdb"`` vertex
  on a host with no DuckDB adapter installed, which is the point of separating
  naming from opening.

  **"No adapter import" is an IMPORT-TIME claim, scoped deliberately**
  (``finding:s2wp4-gate-f1-descriptor-for-calltime-import``): importing this
  module drags in neither ``sqlite3`` nor the adapter, which is the property
  ``test_importing_the_registry_does_not_drag_the_adapter_in`` pins. CALLING
  :func:`descriptor_for` does reach :mod:`engine.residence`, which imports
  :mod:`engine.arrival` at module level — pre-existing coupling this slice does
  not touch, and slice 5's residence rewiring is where it goes. The adapter
  SURFACE stays out either way; nothing here constructs a ledger.
* :class:`BackendRegistry` maps a backend NAME to an opener. This is the half
  that can fail with :class:`~engine.arrival_contract.UnknownBackend`, because
  this is the half that knows what is registered.

**Nothing calls this in production yet.** Slice 2 builds and proves the
registry; wiring the CLI resolvers, the SDK's canonical surface and the ~30
``open_canonical_store`` importers onto it is slice 5's, where the deletions
it enables land too. Until then this is an ADDITIVE path, ``residence.py`` is
untouched, and today's suffix dispatch keeps working unchanged — which is what
makes that promise mechanical rather than a hope.

The registry is not a singleton and does not register anything at import.
Construct one with :meth:`BackendRegistry.with_builtin_backends`. A
process-wide instance is a decision with no forcing consumer yet; slice 5's
rewiring is where one would earn its keep.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .arrival_contract import (
    ArrivalLedger,
    ArrivalQuery,
    StoreDescriptor,
    UnknownBackend,
)
from .arrival_head_seam import AttestedLedger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from lang.ast import VertexFile

__all__ = ["BackendOpener", "BackendRegistry", "descriptor_for"]


#: What a registered adapter must be: given a descriptor, hand back the
#: custody half and the reads half. The pair is the contract's own §03 split,
#: so an adapter cannot register a single object that does both.
BackendOpener = Callable[[StoreDescriptor], "tuple[ArrivalLedger, ArrivalQuery]"]

#: The backend name the transitional arm synthesizes, and the name the file
#: adapter registers under.
FILE_BACKEND = "file"


def descriptor_for(
    ast: VertexFile, vertex_path: Path | None = None
) -> StoreDescriptor | None:
    """Which adapter opens this vertex's store, or None if no adapter does.

    Four answers, and only the first two describe a ledger:

    **Explicit** — the vertex declared ``backend=``. The declared name wins,
    and there is NO cross-check against the location's suffix. A
    ``backend="file"`` on a ``.duckdb``-named path is legal, because under §02
    the suffix carries no meaning once the backend is declared; adding a "do
    they agree?" check would re-admit inference through the back door on the
    very change that removes it. An unregistered name is not this function's
    to refuse — see :meth:`BackendRegistry.open`.

    **Inferred** — no ``backend=``, and the location is ``.arrival``-canonical.
    Synthesizes ``backend="file"``.

    **Not a ledger** — the location is ``.jsonl``- or sqlite-canonical. Those
    modes have no ledger and never route through a registry; they keep
    resolving through :func:`engine.jsonl_store.open_canonical_store` exactly
    as today. Answering None rather than raising is the honest shape: "no
    adapter describes this" is a fact about the store, not a fault.

    **No store at all** — an aggregate (``combine``) or a loops-only vertex
    declares no location. Same answer, same reason.

    ``lineage`` and ``role`` are left unset. The contract names them
    (backend-contract.html:134-135) but nothing in slices 2-4 reads them, and
    parsing fields nothing consumes is how speculative grammar ossifies. Their
    forcing consumer is slice 5's adopt becoming a descriptor operation.
    """
    from .residence import canonical_mode, canonical_store_path

    if ast.store is None:
        return None

    # Pure path arithmetic — resolves a relative locator against the vertex
    # file's directory, never the process cwd. No mode dispatch, so it
    # survives the break intact.
    location = canonical_store_path(ast.store, vertex_path)

    if ast.store_backend is not None:
        return StoreDescriptor(
            backend=ast.store_backend.name, location=str(location)
        )

    # TRANSITIONAL — DELETE IN SLICE 5.
    # Inferring "file" from an .arrival suffix is exactly what explicit
    # declaration exists to end. It exists here so slices 3-4 are not
    # stranded: every .arrival store in the wild predates the grammar that
    # would let it say so. Slice 5's adopt ceremony writes `backend="file"`
    # into those vertices, and this arm dies with the last undeclared store.
    # Its deletion is a residue sweep, not a behavior change: once every
    # .arrival vertex declares its backend, the explicit arm above already
    # answers every case this one does.
    if canonical_mode(location) == "arrival":
        return StoreDescriptor(backend=FILE_BACKEND, location=str(location))

    return None


def _open_file_backend(
    descriptor: StoreDescriptor,
) -> tuple[ArrivalLedger, ArrivalQuery]:
    """Open the ``.arrival`` log and the projection beside it.

    Imported lazily, inside the opener: ``import engine.arrival_registry``
    must not drag sqlite3 and the whole arrival codec behind it for a caller
    that only wants to NAME a descriptor. That is the same reason the contract
    module is separate from the adapter, held one level up.
    """
    from .arrival import ArrivalLog
    from .arrival_file_backend import FileLedger, FileQuery
    from .residence import index_path_for

    location = Path(descriptor.location)
    return FileLedger(ArrivalLog(location)), FileQuery(index_path_for(location))


#: The opener performs no recovery, and that is what makes the seam above it
#: honest rather than merely early. ``ArrivalLog`` construction does no I/O at
#: all, and ``FileQuery`` now builds its read handle lazily (§0.4), so nothing
#: on this path can catch up, truncate a torn tail, or rebuild an index before
#: the comparison has seen the store as it actually is.


class BackendRegistry:
    """Backend name → opener, and nothing more.

    A lookup table, not a cache: it holds no open handles and opening the
    same descriptor twice yields two independent pairs. Custody lifetime
    belongs to whoever asked for it.
    """

    def __init__(self) -> None:
        self._openers: dict[str, BackendOpener] = {}

    @classmethod
    def with_builtin_backends(cls) -> BackendRegistry:
        """A registry holding the adapters that ship in this package."""
        registry = cls()
        registry.register(FILE_BACKEND, _open_file_backend)
        return registry

    def register(self, name: str, opener: BackendOpener) -> None:
        """Bind a backend name to its opener.

        Re-registering a name refuses. A silent overwrite would let import
        order decide which adapter answers to "file", and the failure would
        surface as a store opening through the wrong codec rather than as an
        error at the point of the mistake.
        """
        if name in self._openers:
            raise ValueError(f"backend {name!r} is already registered")
        self._openers[name] = opener

    def registered(self) -> tuple[str, ...]:
        """The backend names this registry answers to, sorted."""
        return tuple(sorted(self._openers))

    def open(
        self, descriptor: StoreDescriptor
    ) -> tuple[ArrivalLedger, ArrivalQuery]:
        """The custody half and the reads half for this descriptor.

        Refuses an unregistered name with
        :class:`~engine.arrival_contract.UnknownBackend`, naming what IS
        registered. Refusing is the whole point: §02 forbids inferring a
        backend from a suffix, so an unregistered name has no fallback to
        degrade into — and a registry that guessed would reintroduce
        inference at the one seam built to remove it.

        **The custody half comes back wrapped, always, with no way to ask for
        it unwrapped** (slice 3 §D.1). :class:`~engine.arrival_head_seam.AttestedLedger`
        compares the head this store presents against the one this machine last
        accepted, and journals every commit made through it. A configuration
        switch for a safety property is a shape the arrival vocabulary
        ratchet's own denylist rejects: custody is structural rather than
        configured, so there is no flag here and no second opener that skips
        the comparison.

        The comparison happens at construction, which means **this method
        raises what the comparison raises**: a rollback, a fork, a rewrite, a
        replacement or a lost store refuses the open rather than being reported
        afterwards by a caller who might not ask. This is also why the seam
        sits here rather than deeper — the opener above performs no recovery,
        so the comparison sees the store as it is rather than as a catch-up
        just repaired it.
        """
        opener = self._openers.get(descriptor.backend)
        if opener is None:
            known = ", ".join(self.registered()) or "(none)"
            raise UnknownBackend(
                f"no adapter registered for backend {descriptor.backend!r} "
                f"(registered: {known})"
            )
        ledger, query = opener(descriptor)
        attested = AttestedLedger(
            ledger, location=descriptor.location, query=query
        )
        return attested, query
