"""CLI layer for loops.

This package owns CLI presentation: argparse parsing, dispatch, rendering,
output.

Painted-boundary discipline (current state — refactor paused):

  Within ``cli/``, only ``cli.output`` and ``cli.live`` import painted
  at runtime. (``cli.operation`` has a TYPE_CHECKING-only painted
  import; it does not exercise painted at runtime.)

  This boundary does *not* yet extend to ``loops.commands.*``. Several
  command modules — ``devtools``, ``emit``, ``resolve``, ``pop``, ``sync``,
  ``ticks``, ``init``, ``whoami``, ``stream``, ``store``, ``population`` —
  still import painted directly. The Reporter-injection contract (commands
  never importing painted, accepting a ``Reporter`` when they need to emit
  output) is the *target* shape for future migrations, not the current
  invariant. Only the ``fold`` and ``emit`` views have been pulled onto
  the full Operation IR shape; the rest are entry-point shims.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
