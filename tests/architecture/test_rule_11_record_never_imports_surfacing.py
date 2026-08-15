"""Rule 11: record-layer libs never import surfacing-layer libs."""

from __future__ import annotations

from ._helpers import (
    LIBS,
    REPO_ROOT,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)

#: The instrument family each lib belongs to. Prose counterpart: the
#: "Layers — the instrument families" table in ARCHITECTURE.md, which carries
#: the Weaver-level reasoning and the membership rationale. This dict and that
#: table are the two halves of one declaration — a lib added to one belongs in
#: the other.
_LIB_LAYER: dict[str, str] = {
    "atoms": "record",
    "lang": "record",
    "engine": "record",
    "store": "record",
    "sign": "surfacing",
    "custody": "surfacing",
    "sdk": "surfacing",
}

#: The chartered layer names. ``view`` (painted, external) and ``relevance``
#: (deliberately empty) have no lib members today; they are accepted values so
#: this mapping can say what ARCHITECTURE.md says, and so a misspelled layer
#: cannot quietly exempt a lib from the direction rule below.
_LAYERS = frozenset({"record", "view", "surfacing", "relevance"})


def test_every_lib_declares_a_layer():
    """Every lib under libs/ carries a layer assignment.

    This is what makes a hand-maintained mapping safe: ``_LIB_LAYER`` mirrors
    the filesystem, so the omission has to be loud or the mirror rots (see
    docs/RATCHETS.md). ``LIBS`` is derived from libs/, so a new directory
    fails here before it can slip past Rule 11's direction check by simply
    not being mentioned.
    """
    missing = [name for name in LIBS if name not in _LIB_LAYER]
    assert not missing, (
        "Lib without a layer assignment: "
        + ", ".join(missing)
        + " — assign a layer in _LIB_LAYER (tests/test_architecture.py) AND "
        "add the lib to the Layers table in ARCHITECTURE.md. A lib with no "
        "declared layer is exempt from Rule 11 by accident."
    )

    stale = sorted(set(_LIB_LAYER) - set(LIBS))
    assert not stale, (
        "Stale _LIB_LAYER entry: " + ", ".join(stale) + " no longer exists "
        "under libs/ — drop it here and from ARCHITECTURE.md's Layers table"
    )

    bad = {name: layer for name, layer in _LIB_LAYER.items() if layer not in _LAYERS}
    assert not bad, (
        "Unknown layer name(s): "
        + ", ".join(f"{name}={layer!r}" for name, layer in sorted(bad.items()))
        + f" — must be one of {', '.join(sorted(_LAYERS))}"
    )


def test_record_layer_does_not_import_surfacing():
    """Record-layer libs must not import surfacing-layer libs at runtime.

    The record layer answers Weaver's Level A — what happened, with accuracy
    claims that hold because meaning is out of scope there. The surfacing layer
    is Level C: conduct and authority — host orchestration, coordination,
    attestation. Those claims are relational (conducted-well-or-not), not
    correctness claims. Level A stays semantically and structurally pure of
    Level C, so a record-layer accuracy claim can never depend on an authority
    judgment. The reverse direction is fine and expected: surfacing composes
    over the record (custody -> engine), governed per-lib by Rule 4.

    Rule 4 already forbids each specific edge this rule would catch today.
    Rule 11 is the coarser overlay stated at the layer, so it survives future
    edits to Rule 4's per-lib allowlist: widening ``_LIB_ALLOWED_RUNTIME`` for
    a record lib is a one-line change that reads locally reasonable, and this
    rule is what makes the layer inversion in it fail out loud.

    TYPE_CHECKING-only imports are exempt, matching Rule 4 exactly — the
    collector records runtime imports only, and an annotation-only reference
    creates no runtime dependency to invert.
    """
    surfacing = {name for name, layer in _LIB_LAYER.items() if layer == "surfacing"}

    violations = []
    for lib_name in LIBS:
        if _LIB_LAYER.get(lib_name) != "record":
            continue
        lib_dir = REPO_ROOT / "libs" / lib_name
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            for other_lib in sorted(surfacing):
                for lineno in _imports_module(collector.runtime_modules, other_lib):
                    violations.append(
                        f"  {_rel(py_file)}:{lineno} — record lib {lib_name} "
                        f"imports surfacing lib {other_lib} at runtime"
                    )

    assert not violations, (
        "Layer inversion: the record layer (Weaver Level A — accuracy) must "
        "not depend on the surfacing layer (Level C — conduct/authority). "
        "See ARCHITECTURE.md's Layers table and _LIB_LAYER:\n"
        + "\n".join(violations)
    )
