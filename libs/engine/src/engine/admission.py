"""Declared admission policy, resolved at the engine boundary.

A ``.vertex`` declaration can carry admission policy in two places:

* ``observers { name { grant { potential ... } } }`` — per-observer
  emission constraints (``ObserverDecl.grant.potential``);
* ``strict true`` — vertex-wide refusal of undeclared kinds.

Historically both were parsed and historized but only enforced by
whichever *caller* remembered to build a :class:`~engine.peer.Grant`
by hand — declared policy was silently bypassable by omission. This
module is the enforcement seam: :func:`grant_for_observer` resolves the
declared policy for an observer, and ``VertexProgram.receive_as`` /
``VertexHandle.receive_as`` apply it automatically. Bypassing declared
policy is still possible, but only through an *explicit* entry point
(the raw ``receive``, documented as the bypass) — never by omission.

Strict enforcement lives in :meth:`engine.vertex.Vertex.receive_receipt`
(the engine floor; see decision:design/strict-enforcement-at-engine-receive);
this module supplies its typed rejection, :class:`UndeclaredKind`.
"""

from __future__ import annotations

TYPE_CHECKING = False
if TYPE_CHECKING:
    from lang.ast import VertexFile
    from .peer import Grant


class AdmissionError(Exception):
    """Base for declared-admission-policy refusals at the engine boundary."""


class UnknownObserver(AdmissionError):
    """The vertex declares observers, and this observer is not one of them.

    Raised by :func:`grant_for_observer` only when an ``observers`` block
    exists — a vertex with no observers block has no declared policy, and
    every observer resolves to unrestricted (``None``).
    """

    def __init__(self, observer: str, vertex: str) -> None:
        super().__init__(
            f"observer {observer!r} is not declared in vertex {vertex!r} — "
            f"declared admission policy admits only declared observers. "
            f"Declare the observer, or use the raw receive entry point to "
            f"bypass declared policy explicitly."
        )
        self.observer = observer
        self.vertex = vertex


class UndeclaredKind(AdmissionError):
    """A strict vertex refused a fact whose kind is not declared.

    Raised by ``Vertex.receive_receipt`` *before* storage when the resolved
    declaration says ``strict`` — nothing is appended. Bypass is the
    explicit ``admit_undeclared=True`` parameter, never an omission.
    """

    def __init__(self, kind: str, vertex: str) -> None:
        super().__init__(
            f"vertex {vertex!r} declares strict — kind {kind!r} is not "
            f"declared, fact refused before storage. Declare the kind in "
            f"the vertex file, or pass admit_undeclared=True to bypass "
            f"strict admission explicitly."
        )
        self.kind = kind
        self.vertex = vertex


class AggregateAdmissionUnsupported(AdmissionError):
    """Admission policy cannot be resolved against an aggregate vertex.

    Combine/discover aggregates are read-path compositions over member
    stores; writes target a member directly, and each member's own
    declaration is the admission authority. Resolving a grant against the
    aggregate would invent a policy no member declared.
    """

    def __init__(self, vertex: str) -> None:
        super().__init__(
            f"vertex {vertex!r} is a combine/discover aggregate — admission "
            f"policy resolves against a member declaration, not the "
            f"aggregate. Write to the member vertex directly."
        )
        self.vertex = vertex


def grant_for_observer(ast: "VertexFile", observer: str) -> "Grant | None":
    """Resolve the declared admission policy for ``observer`` to a Grant.

    The five contract cases (LIBS_CHANGES P1, observer admission):

    * **aggregate vertex** (``combine``/``discover`` set) — raises
      :class:`AggregateAdmissionUnsupported`; members own admission.
    * **no observers block** — returns ``None``: the declaration carries
      no observer policy, admission is unrestricted.
    * **unknown observer** (observers declared, this one absent) — raises
      :class:`UnknownObserver`: a declared-policy vertex admits only
      declared observers.
    * **declared observer without a grant** — returns ``None``: declared,
      unconstrained (same admission as no-policy, reached deliberately).
    * **declared observer with a potential set** — returns a
      :class:`~engine.peer.Grant` carrying that ``potential`` frozenset.

    Returns:
        ``Grant | None`` suitable for ``Vertex.receive(fact, grant)``.
    """
    if ast.combine is not None or ast.discover is not None:
        raise AggregateAdmissionUnsupported(ast.name)

    if not ast.observers:
        return None

    for decl in ast.observers:
        if decl.name == observer:
            if decl.grant is None:
                return None
            from .peer import Grant

            return Grant(potential=frozenset(decl.grant.potential))

    raise UnknownObserver(observer, ast.name)


__all__ = [
    "AdmissionError",
    "UnknownObserver",
    "UndeclaredKind",
    "AggregateAdmissionUnsupported",
    "grant_for_observer",
]
