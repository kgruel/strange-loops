"""arrival_registry — which adapter opens which artifact.

The declaration and registry halves remain deliberately separable:

* :func:`descriptor_for` reads a parsed ``.vertex`` and answers what
  :class:`engine.arrival_contract.StoreDescriptor` — if any — describes its
  store. It can answer about a ``backend="duckdb"`` vertex on a host with no
  DuckDB adapter installed, which is the point of separating naming from
  opening. Only the built-in file location is path-interpreted here; every
  other adapter receives the declared string unchanged.

  **"No adapter import" is an IMPORT-TIME claim, scoped deliberately**
  (``finding:s2wp4-gate-f1-descriptor-for-calltime-import``): importing this
  module drags in neither ``sqlite3`` nor the adapter, which is the property
  ``test_importing_the_registry_does_not_drag_the_adapter_in`` pins. CALLING
  :func:`descriptor_for` reaches :mod:`engine.residence` only for the named
  file adapter, whose relative paths are resolved against the vertex. The
  adapter surface stays out either way; nothing here constructs a ledger.
* :class:`BackendRegistry` maps a backend NAME to an opener. This is the half
  that can fail with :class:`~engine.arrival_contract.UnknownBackend`, because
  this is the half that knows what is registered.

The registry is not a singleton and does not register anything at import.
Construct one with :meth:`BackendRegistry.with_builtin_backends`. A
process-wide instance remains a consumer decision.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .arrival_binding import (
    BindingIdentity,
    BindingProbeError,
    BindingProvider,
    file_binding,
    is_opaque_key_for,
    opaque_binding,
)
from .arrival_contract import (
    ArrivalLedger,
    ArrivalQuery,
    Capabilities,
    Commit,
    ExportedPrefix,
    Head,
    NotAuthority,
    NotSupported,
    Open,
    Profile,
    RecordDraft,
    StoreDescriptor,
    UnknownBackend,
    VerifyScope,
    Watermark,
)
from .arrival_head_seam import AttestedLedger, BindingProbeUnanswered

if TYPE_CHECKING:  # pragma: no cover - typing only
    from lang.ast import VertexFile

    from .arrival_maintenance import MaintenanceOpener, ProjectionMaintenance
    from .arrival_restore import RestoreForwardResult
    from .arrival_search import SearchIndexMaintenance, SearchMaintenanceOpener

__all__ = ["BackendOpener", "BackendRegistry", "descriptor_for"]


#: What a registered adapter must be: given a descriptor, hand back the
#: custody half and the reads half. The pair is the contract's own §03 split,
#: so an adapter cannot register a single object that does both.
BackendOpener = Callable[[StoreDescriptor], "tuple[ArrivalLedger, ArrivalQuery]"]


def _file_binding(descriptor: StoreDescriptor) -> BindingIdentity:
    """The built-in file adapter's binding policy."""

    return file_binding(descriptor.location)


def _validate_binding(
    descriptor: StoreDescriptor, binding: BindingIdentity
) -> None:
    """Reject a provider identity before its opener can create a handle."""

    if not isinstance(binding, BindingIdentity):
        raise TypeError(
            f"binding provider for backend {descriptor.backend!r} returned "
            f"{type(binding).__name__}, not BindingIdentity"
        )
    if binding.backend != descriptor.backend:
        raise ValueError(
            f"binding provider for backend {descriptor.backend!r} returned "
            f"identity for backend {binding.backend!r}"
        )
    if descriptor.backend == FILE_BACKEND:
        if not binding.filesystem_aliases or binding.key.startswith("backend:"):
            raise ValueError(
                "the file backend binding must retain its canonical-path "
                "identity and filesystem alias policy"
            )
        return
    if binding.filesystem_aliases or binding.filesystem_identity is not None:
        raise ValueError(
            f"non-file backend {descriptor.backend!r} supplied filesystem "
            "identity; non-file binding keys are opaque"
        )
    if not is_opaque_key_for(descriptor.backend, binding.key):
        raise ValueError(
            f"non-file backend {descriptor.backend!r} supplied an invalid "
            "binding key; use opaque_binding(backend, normalized_locator)"
        )

#: The explicit name the built-in file adapter registers under.
FILE_BACKEND = "file"


def descriptor_for(
    ast: VertexFile, vertex_path: Path | None = None
) -> StoreDescriptor | None:
    """Which adapter opens this vertex's store, or None if no adapter does.

    Two answers, and only the first describes a ledger:

    **Explicit** — the vertex declared ``backend=``. The declared name wins,
    and there is NO cross-check against the location's suffix. A
    ``backend="file"`` on a ``.duckdb``-named path is legal, because under §02
    the suffix carries no meaning once the backend is declared; adding a "do
    they agree?" check would re-admit inference through the back door on the
    very change that removes it. An unregistered name is not this function's
    to refuse — see :meth:`BackendRegistry.open`.

    **No descriptor** — a bare legacy store, an aggregate (``combine``), or a
    loops-only vertex has no explicit adapter declaration. Suffix inference
    ends here: a ``.arrival`` suffix does not synthesize ``backend="file"``.

    ``lineage`` and ``role`` are declaration claims, not grants. The registry
    checks them against the presented genesis and backend capabilities, then
    keeps enforcing them on the returned custody handle.
    """
    if ast.store is None or ast.store_backend is None:
        return None

    declaration = ast.store_backend
    if declaration.name == FILE_BACKEND:
        # This is the built-in file adapter's interpretation of a location:
        # relative paths are relative to the declaring vertex, never cwd.
        from .residence import canonical_store_path

        location = str(canonical_store_path(ast.store, vertex_path))
    else:
        # No pathlib round-trip for another adapter. A DSN or service URL is
        # opaque, including repeated slashes and query text.
        if ast.store_location is None:
            raise ValueError(
                f"non-file backend {declaration.name!r} has no opaque store "
                "location; construct it by parsing a descriptor declaration"
            )
        location = ast.store_location

    role = None if declaration.role is None else Profile(declaration.role)
    return StoreDescriptor(
        backend=declaration.name,
        location=location,
        lineage=declaration.lineage,
        role=role,
    )


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
    from .arrival_file_backend import FileLedger, FileQuery, file_projection_path

    location = Path(descriptor.location)
    return FileLedger(ArrivalLog(location)), FileQuery(file_projection_path(location))


def _open_file_search_maintenance(descriptor: StoreDescriptor):
    """Build the file adapter's explicit FTS authority lazily."""
    from .arrival_file_backend import FileSearchMaintenance, file_projection_path

    location = Path(descriptor.location)
    return FileSearchMaintenance(location, file_projection_path(location))


def _open_file_maintenance(descriptor: StoreDescriptor) -> ProjectionMaintenance:
    """Build the file adapter's derived-state authority lazily."""
    from .arrival_file_backend import FileProjectionMaintenance, file_projection_path

    location = Path(descriptor.location)
    return FileProjectionMaintenance(location, file_projection_path(location))


def _close_handle(handle: object) -> None:
    """Best-effort release of an adapter half after a refused registry open."""
    close = getattr(handle, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


class _DescriptorLedger:
    """Keep descriptor lineage and role claims true after open.

    Capability checks at open are insufficient on their own: the file adapter
    supports both Authority and Replica, so handing its full custody surface
    through a ``role=replica`` descriptor would let operator intent evaporate
    after one check. This wrapper gates every mutation and every operation
    carrying a lineage before delegating.

    ``role=None`` remains the transitional behavior for existing direct
    ``StoreDescriptor`` callers. It is not an Authority designation; the SDK
    integration cut must make its supported declaration explicit.
    """

    def __init__(self, ledger: ArrivalLedger, descriptor: StoreDescriptor) -> None:
        self._ledger = ledger
        self._lineage = descriptor.lineage
        self._role = descriptor.role

    def _require_role(self, operation: str, *allowed: Profile) -> None:
        if self._role is not None and self._role not in allowed:
            choices = ", ".join(profile.value for profile in allowed)
            raise NotAuthority(
                f"descriptor role {self._role.value!r} does not permit "
                f"{operation}; permitted roles: {choices}"
            )

    def _require_lineage(self, lineage: str, operation: str) -> None:
        if self._lineage is not None and lineage != self._lineage:
            raise NotAuthority(
                f"descriptor names lineage {self._lineage}, but {operation} "
                f"names {lineage}; a descriptor is checked against genesis "
                "and never replaces it"
            )

    def mint(self, options: Mapping[str, Any]) -> Head:
        self._require_role("mint", Profile.AUTHORITY)
        if self._lineage is not None:
            proposed = options.get("lineage")
            if not isinstance(proposed, str):
                raise NotAuthority(
                    f"descriptor pins lineage {self._lineage}; mint must name "
                    "that lineage explicitly"
                )
            self._require_lineage(proposed, "mint")
        # The backend contract requires mint(options) to use the offered
        # lineage. Do not turn a backend breach discovered after durable mint
        # into a precommit-looking descriptor refusal that suppresses the
        # attestation wrapper's bootstrap receipt.
        return self._ledger.mint(options)

    def append(
        self, expected: Head | None, drafts: Sequence[RecordDraft]
    ) -> Commit:
        self._require_role("append", Profile.AUTHORITY)
        if expected is not None:
            self._require_lineage(expected.lineage, "append expectation")
        return self._ledger.append(expected, drafts)

    def replicate(
        self, expected: Head | None, records: Sequence[Mapping[str, Any]]
    ) -> Commit:
        self._require_role("replicate", Profile.AUTHORITY, Profile.REPLICA)
        if expected is not None:
            self._require_lineage(expected.lineage, "replication expectation")
        if self._lineage is not None:
            for index, record in enumerate(records):
                lineage = record.get("lin")
                if not isinstance(lineage, str):
                    raise NotAuthority(
                        f"descriptor pins lineage {self._lineage}; replication "
                        f"record {index} must name a string lineage before "
                        "the target is modified"
                    )
                self._require_lineage(lineage, f"replication record {index}")
        # Every carried record was pinned before delegation. A post-commit
        # mismatch would be a backend conformance failure, and raising here
        # would prevent the attestation wrapper from witnessing durable data.
        return self._ledger.replicate(expected, records)

    def head(self, lineage: str | None = None) -> Head:
        self._require_role("head", Profile.AUTHORITY, Profile.REPLICA)
        requested = self._lineage if lineage is None else lineage
        if requested is not None:
            self._require_lineage(requested, "head request")
        head = self._ledger.head(requested)
        self._require_lineage(head.lineage, "presented genesis")
        return head

    def head_at(self, watermark: Watermark) -> Head:
        self._require_role("head_at", Profile.AUTHORITY, Profile.REPLICA)
        self._require_lineage(watermark.lineage, "watermark")
        head = self._ledger.head_at(watermark)
        self._require_lineage(head.lineage, "watermark result")
        return head

    def read(self, coordinate: int) -> Mapping[str, Any]:
        self._require_role("read", Profile.AUTHORITY, Profile.REPLICA)
        record = self._ledger.read(coordinate)
        lineage = record.get("lin")
        if isinstance(lineage, str):
            self._require_lineage(lineage, "read result")
        return record

    def scan(
        self, *, after: int | None = None, through: Head | None = None
    ) -> Iterator[Mapping[str, Any]]:
        self._require_role("scan", Profile.AUTHORITY, Profile.REPLICA)
        if through is not None:
            self._require_lineage(through.lineage, "scan bound")
        for record in self._ledger.scan(after=after, through=through):
            lineage = record.get("lin")
            if isinstance(lineage, str):
                self._require_lineage(lineage, "scan result")
            yield record

    def verify(self, scope: VerifyScope) -> Head:
        self._require_role(
            "verify", Profile.AUTHORITY, Profile.REPLICA, Profile.ARCHIVE
        )
        through = getattr(scope, "through", None)
        if isinstance(through, Head):
            self._require_lineage(through.lineage, "verification bound")
        head = self._ledger.verify(scope)
        self._require_lineage(head.lineage, "presented genesis")
        return head

    def export(self, *, through: Head, codec: str) -> ExportedPrefix:
        self._require_role("export", Profile.AUTHORITY, Profile.REPLICA)
        self._require_lineage(through.lineage, "export bound")
        exported = self._ledger.export(through=through, codec=codec)
        self._require_lineage(exported.head.lineage, "export result")
        return exported

    def capabilities(self) -> Capabilities:
        return self._ledger.capabilities()

    def close(self) -> None:
        """Release the adapter custody handle, when it owns one."""
        close = getattr(self._ledger, "close", None)
        if callable(close):
            close()


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
        self._bindings: dict[str, BindingProvider] = {}
        self._maintenance_openers: dict[str, MaintenanceOpener] = {}
        self._search_maintenance_openers: dict[str, SearchMaintenanceOpener] = {}

    @classmethod
    def with_builtin_backends(cls) -> BackendRegistry:
        """A registry holding the adapters that ship in this package."""
        registry = cls()
        registry.register(
            FILE_BACKEND,
            _open_file_backend,
            binding_provider=_file_binding,
            maintenance_opener=_open_file_maintenance,
            search_maintenance_opener=_open_file_search_maintenance,
        )
        return registry

    def register(
        self,
        name: str,
        opener: BackendOpener,
        *,
        binding_provider: BindingProvider | None = None,
        maintenance_opener: MaintenanceOpener | None = None,
        search_maintenance_opener: SearchMaintenanceOpener | None = None,
    ) -> None:
        """Bind a backend name to its opener.

        Re-registering a name refuses. A silent overwrite would let import
        order decide which adapter answers to "file", and the failure would
        surface as a store opening through the wrong codec rather than as an
        error at the point of the mistake. ``binding_provider`` and the
        private ``maintenance_opener`` are separate metadata so the opener's
        tuple remains stable. Binding is checked before the opener runs, and
        maintenance remains reachable only through the attested coordinator.
        """
        if name in self._openers:
            raise ValueError(f"backend {name!r} is already registered")
        self._openers[name] = opener
        self._bindings[name] = (
            binding_provider
            if binding_provider is not None
            else lambda descriptor, backend=name: opaque_binding(
                backend, descriptor.location
            )
        )
        if maintenance_opener is not None:
            self._maintenance_openers[name] = maintenance_opener
        if search_maintenance_opener is not None:
            self._search_maintenance_openers[name] = search_maintenance_opener

    def registered(self) -> tuple[str, ...]:
        """The backend names this registry answers to, sorted."""
        return tuple(sorted(self._openers))

    def _maintenance_for(self, descriptor: StoreDescriptor) -> ProjectionMaintenance:
        """Private adapter factory used only after an attested registry open.

        The public maintenance entry point is
        :func:`engine.arrival_maintenance.sync_projection`. Keeping this
        factory private prevents a raw derived-state authority from becoming a
        second registry open path that omits head attestation.
        """
        opener = self._maintenance_openers.get(descriptor.backend)
        if opener is None:
            raise NotSupported(
                f"backend {descriptor.backend!r} does not provide projection maintenance"
            )
        return opener(descriptor)

    def _search_maintenance_for(self, descriptor: StoreDescriptor) -> SearchIndexMaintenance:
        """Private FTS provider reached only by the attested coordinator."""
        opener = self._search_maintenance_openers.get(descriptor.backend)
        if opener is None:
            raise NotSupported(
                f"backend {descriptor.backend!r} does not provide search maintenance"
            )
        return opener(descriptor)

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
        ledger, query, binding = self._open_components(descriptor)
        try:
            attested = AttestedLedger(
                ledger, location=descriptor.location, query=query, binding=binding
            )
        except BaseException:
            _close_handle(query)
            _close_handle(ledger)
            raise
        return attested, query


    def _open_components(
        self, descriptor: StoreDescriptor
    ) -> tuple[ArrivalLedger, ArrivalQuery, BindingIdentity]:
        """Private resources for attested open or the bounded restore procedure.

        Never returned to consumers. Both callers own comparison, witnessing,
        and closure; restoration exposes only its completed receipt.
        """
        opener = self._openers.get(descriptor.backend)
        if opener is None:
            known = ", ".join(self.registered()) or "(none)"
            raise UnknownBackend(
                f"no adapter registered for backend {descriptor.backend!r} "
                f"(registered: {known})"
            )
        provider = self._bindings[descriptor.backend]
        try:
            binding = provider(descriptor)
        except BindingProbeError as exc:
            raise BindingProbeUnanswered(
                f"{descriptor.location} exists and storage would not establish "
                f"its file identity ({exc}); nothing has been accepted or "
                "written — repair the location or retry"
            ) from exc
        _validate_binding(descriptor, binding)
        ledger, query = opener(descriptor)
        try:
            capabilities = ledger.capabilities()
            if (
                descriptor.role is not None
                and descriptor.role not in capabilities.profiles
            ):
                offered = ", ".join(
                    sorted(profile.value for profile in capabilities.profiles)
                ) or "(none)"
                raise NotSupported(
                    f"backend {descriptor.backend!r} cannot open location "
                    f"{descriptor.location!r} as {descriptor.role.value}: "
                    f"capabilities advertise {offered}"
                )

            # Check a presented genesis before AttestedLedger can turn a
            # first-contact head into a bootstrap journal entry. An absent or
            # not-yet-minted ledger has no genesis to compare; its later mint
            # remains pinned by _DescriptorLedger.
            if descriptor.lineage is not None:
                try:
                    presented = ledger.verify(Open())
                except Exception:  # backend-specific absence/corruption
                    presented = None
                if (
                    presented is not None
                    and presented.lineage != descriptor.lineage
                ):
                    raise NotAuthority(
                        f"descriptor names lineage {descriptor.lineage}, but "
                        f"the genesis at {descriptor.location!r} opens "
                        f"{presented.lineage}; the declaration is a check, "
                        "not a replacement for genesis"
                    )

            return _DescriptorLedger(ledger, descriptor), query, binding
        except BaseException:
            _close_handle(query)
            _close_handle(ledger)
            raise

    def restore_forward(
        self,
        source: StoreDescriptor,
        receiver: StoreDescriptor,
        *,
        through: Head | None = None,
    ) -> RestoreForwardResult:
        """Restore an existing exact prefix without granting an open handle."""
        from .arrival_restore import _restore_forward

        return _restore_forward(self, source, receiver, through=through)
