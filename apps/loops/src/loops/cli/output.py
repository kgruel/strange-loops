"""Reporter Protocol — the single painted-boundary module for cli/.

``cli.output`` is the *only* module in ``cli/`` allowed to ``from painted
import …`` at runtime (with ``cli.live`` as the secondary boundary for
``InPlaceRenderer``). Everyone else uses the ``Reporter`` Protocol or the
re-exports below.

Mirrors siftd's ``output/painted_bridge.py`` discipline: one place owns
the painted contract, the rest of the CLI imports from here. This makes
the eventual painted framework/renderer split painless on the loops side
— we change one file.

Reporter has two implementations:
  - PaintedReporter: production. Delegates to painted.show / print_block.
  - BufferReporter: tests. Captures err/out/blocks into lists for
    assertion. Demonstrates that every CLI invocation is testable
    end-to-end via ``cli.app.main(argv, reporter=BufferReporter())``
    without subprocess spawning or output redirection.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

import shutil
import sys
from typing import Any, Protocol

# The single permitted runtime painted import in cli/.
# Other cli/* modules consume painted symbols by importing from here.
#
# Importing from concrete submodules (rather than the top-level ``painted``
# package) bypasses painted's lazy ``__getattr__`` shim, which Pyright
# cannot follow. The symbols are identical; only the import path changes.
from painted.core.block import Block
from painted.core.cell import Style
from painted.core.fidelity import Fidelity
from painted.core.writer import print_block
from painted.core.zoom import Zoom
from painted.display import show
from painted.palette import current_palette


# Re-exports so other cli/* modules can `from cli.output import Block, Style,
# Fidelity, Zoom` instead of `from painted import …`. Keeps the boundary
# discipline enforceable by grep.
__all__ = [
    "Block",
    "Fidelity",
    "Style",
    "Zoom",
    "Reporter",
    "PaintedReporter",
    "BufferReporter",
    "default_reporter",
    "err",
    "msg",
]


class Reporter(Protocol):
    """Output abstraction for CLI presentation.

    Commands accept a ``Reporter`` to communicate output without depending
    on painted directly. Dispatch uses a Reporter to render Operation
    results. Tests pass a BufferReporter to capture and assert.
    """

    width: int | None
    use_ansi: bool

    def err(self, message: str) -> None:
        """Print an error message (stderr in production)."""
        ...

    def msg(self, message: str) -> None:
        """Print a non-error message (stdout in production)."""
        ...

    def show(self, value: Any) -> None:
        """Show an action result — a string, a Block, or any value
        accepted by painted.show. Used for emit/cite receipts and other
        action-shape outputs."""
        ...

    def print_block(self, block: Block) -> None:
        """Print a Block via painted.print_block. Used by dispatch for
        display-shape Operations."""
        ...


class PaintedReporter:
    """Production Reporter — delegates to painted primitives.

    ``width`` reflects the current terminal width when stdout is a TTY,
    or ``None`` when piped (signaling "no truncation/padding" per
    painted's convention).

    ``use_ansi`` controls colour/escape output for ``print_block``. Views
    set it to False to honour ``--plain``; defaults to True (the painted
    writer itself further suppresses colour for non-TTY stdout).
    """

    def __init__(self, *, use_ansi: bool = True) -> None:
        # Resolve width once at construction. Reporter instances are
        # short-lived (one per main() call) so this is fine.
        self.width: int | None = self._detect_width()
        self.use_ansi: bool = use_ansi

    @staticmethod
    def _detect_width() -> int | None:
        if not sys.stdout.isatty():
            return None
        try:
            return shutil.get_terminal_size().columns
        except OSError:
            return None

    def err(self, message: str) -> None:
        # Use painted's palette for consistent error color across CLI.
        palette = current_palette()
        show(Block.text(message, palette.error), file=sys.stderr)

    def msg(self, message: str) -> None:
        # Match the original loops.main._msg styling — non-error messages
        # render in the success palette (green checkmark vibe) so init/emit
        # confirmation lines remain visually distinct from plain output.
        palette = current_palette()
        show(Block.text(message, palette.success))

    def show(self, value: Any) -> None:
        show(value)

    def print_block(self, block: Block) -> None:
        print_block(block, use_ansi=self.use_ansi)


class BufferReporter:
    """Test Reporter — captures err / msg / show / print_block into lists.

    Each output channel goes to a separate list so tests can assert against
    them independently. Default ``width=80`` matches the conventional
    terminal width used in golden tests; override per-test as needed.
    """

    def __init__(self, *, width: int | None = 80, use_ansi: bool = True) -> None:
        self.width: int | None = width
        self.use_ansi: bool = use_ansi
        self.err_lines: list[str] = []
        self.out_lines: list[str] = []
        self.shown: list[Any] = []
        self.blocks: list[Block] = []

    def err(self, message: str) -> None:
        self.err_lines.append(message)

    def msg(self, message: str) -> None:
        self.out_lines.append(message)

    def show(self, value: Any) -> None:
        self.shown.append(value)

    def print_block(self, block: Block) -> None:
        self.blocks.append(block)

    # --- Convenience for assertions -------------------------------------

    @property
    def err_text(self) -> str:
        """All captured stderr joined with newlines."""
        return "\n".join(self.err_lines)

    @property
    def out_text(self) -> str:
        """All captured stdout joined with newlines."""
        return "\n".join(self.out_lines)


# Module-level convenience for early-migration call sites and pre-dispatch
# errors (where no Reporter instance is yet available). Backed by a default
# PaintedReporter constructed lazily.

_default_reporter: PaintedReporter | None = None


def default_reporter() -> PaintedReporter:
    """Lazily-constructed default PaintedReporter for module-level
    convenience helpers below."""
    global _default_reporter
    if _default_reporter is None:
        _default_reporter = PaintedReporter()
    return _default_reporter


def err(message: str) -> None:
    """Convenience: print an error via the default PaintedReporter.

    Prefer passing an explicit Reporter into command functions. Use this
    only for early-migration call sites (the ``_err`` replacement in main.py)
    and for errors raised before a Reporter has been constructed.
    """
    default_reporter().err(message)


def msg(message: str) -> None:
    """Convenience: print a non-error message via the default PaintedReporter."""
    default_reporter().msg(message)
