"""CLI layer for loops.

This package owns CLI presentation: argparse parsing, dispatch, rendering,
output. Commands (``loops.commands.*``) own domain logic and never import
from this package — they accept a ``Reporter`` if they need to emit output.

The single painted-boundary module is ``cli.output``; ``cli.live`` is the
secondary boundary for ``InPlaceRenderer``. No other module in ``cli/``
may ``from painted import …``.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
