"""fidelity_from_args — derive a Fidelity from a parsed argparse.Namespace.

Pure function. Centralizes the verbose/quiet → depth conversion plus the
``visible`` tag derivation from view-specific flags (``--facts``,
``--refs``, etc).

Mirrors siftd's ``cli/_common.py:fidelity_from_args``: pure, narrow,
testable.

The conventional argparse shape that views build to:
    parser.add_mutually_exclusive_group()
        -q / --quiet      action="store_true"
        -v / --verbose    action="count", default=0
    parser.add_argument(--max-chars, type=int, default=None)
    parser.add_argument(--max-lines, type=int, default=None)

Visible tags are derived from per-flag → tag mappings the view supplies:
    fidelity_from_args(args, visible={"facts": "facts", "refs": "refs"})

If ``args.facts`` is truthy, ``"facts"`` is added to the visible set; same
for ``args.refs`` (and ``args.refs`` is an int > 0). The mapping is
``flag_attr_name -> tag_name``.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

import argparse

from .output import Fidelity


def fidelity_from_args(
    args: argparse.Namespace,
    *,
    visible: dict[str, str] | None = None,
    default_depth: int = 1,
) -> Fidelity:
    """Build a Fidelity from a parsed argparse.Namespace.

    Args:
        args: parsed argparse namespace. May contain any of:
            - ``quiet`` (bool): if True, depth=0
            - ``verbose`` (int): count of -v flags; 1 → depth=2, ≥2 → depth=3
            - ``max_chars`` (int | None): chars budget
            - ``max_lines`` (int | None): lines budget
            All are optional — getattr with defaults.
        visible: optional mapping ``flag_attr -> tag_name``. For each
            entry, if ``getattr(args, flag_attr)`` is truthy (or, for
            int-valued flags like ``refs``, > 0), add ``tag_name`` to
            the visible frozenset.
        default_depth: depth when neither -q nor -v is present
            (1 = SUMMARY).

    Returns:
        A frozen Fidelity instance.
    """
    # Depth from -q / -v (mutually exclusive in well-formed parsers)
    if getattr(args, "quiet", False):
        depth = 0
    else:
        verbose = getattr(args, "verbose", 0) or 0
        if verbose >= 2:
            depth = 3
        elif verbose == 1:
            depth = 2
        else:
            depth = default_depth

    # Density budgets
    chars = getattr(args, "max_chars", None)
    lines = getattr(args, "max_lines", None)
    chars = int(chars) if chars is not None else 0
    lines = int(lines) if lines is not None else 0

    # Visible tags
    tags: set[str] = set()
    if visible:
        for flag_attr, tag_name in visible.items():
            value = getattr(args, flag_attr, None)
            if value is None or value is False:
                continue
            # int-valued flags (refs depth) count as visible when > 0
            if isinstance(value, int) and not isinstance(value, bool):
                if value > 0:
                    tags.add(tag_name)
            elif value:
                tags.add(tag_name)

    return Fidelity(
        depth=depth,
        visible=frozenset(tags),
        chars=chars,
        lines=lines,
    )
