"""Lenses — pure ``(data, zoom, width) -> Block`` projections.

``width`` carries the two-state contract painted's ``renderer=`` binding
guarantees: a concrete ``int`` (a real viewport — truncate/pad to fit) or
``None`` (a pipe or file redirect — render at natural width, never clip).
A lens derives "am I piped" from ``width is None``; it is never told
separately, so the two can never disagree.

``zoom_from_fidelity`` is this app's copy of the one compatibility seam
between painted's open ``Fidelity`` and the bounded ``Zoom`` vocabulary the
lenses speak. apps/loops owns the same seam in ``loops.lens_resolver``; the
duplication is deliberate and temporary — apps/tasks does not depend on
apps/loops, and the shared surfacing home that would hold one copy does not
exist yet (design:architecture/surfacing-layer-charter). One seam per app,
not one per call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted import Zoom

__all__ = ["zoom_from_fidelity"]


def zoom_from_fidelity(fidelity) -> Zoom:
    """Adapt the renderer contract's open depth to the bounded lens ``Zoom``.

    ``Fidelity.depth`` is an open int; ``Zoom`` is 0..3. The clamp is
    two-sided so a negative or out-of-range depth cannot raise inside a
    renderer. A ``Zoom`` passed straight through is returned as-is, so a
    lens stays directly callable from a test with a ``Zoom`` literal.
    """
    from painted import Zoom

    if isinstance(fidelity, Zoom):
        return fidelity
    return Zoom(min(max(fidelity.depth, 0), 3))
