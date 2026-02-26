"""Viewport: scroll state for vertically-scrollable views."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Viewport:
    """Scroll state for a vertically-scrollable view.

    Tracks offset (first visible row), visible height, and content height.
    All operations return new Viewport instances (immutable).

    Use with vslice() for rendering:
        visible_block = vslice(content_block, viewport.offset, viewport.visible)
    """

    offset: int = 0
    visible: int = 0
    content: int = 0

    @property
    def max_offset(self) -> int:
        """Maximum valid offset (0 if content fits in viewport)."""
        return max(0, self.content - self.visible)

    @property
    def can_scroll(self) -> bool:
        """True if content exceeds viewport height."""
        return self.content > self.visible

    @property
    def is_at_top(self) -> bool:
        """True if scrolled to the top."""
        return self.offset == 0

    @property
    def is_at_bottom(self) -> bool:
        """True if scrolled to the bottom."""
        return self.offset >= self.max_offset

    def _clamp(self, offset: int) -> int:
        """Clamp offset to valid range [0, max_offset]."""
        return max(0, min(offset, self.max_offset))

    def scroll(self, delta: int) -> Viewport:
        """Scroll by delta rows. Positive = down, negative = up."""
        return replace(self, offset=self._clamp(self.offset + delta))

    def scroll_to(self, position: int) -> Viewport:
        """Scroll to absolute position."""
        return replace(self, offset=self._clamp(position))

    def page_up(self) -> Viewport:
        """Scroll up by one page (visible height)."""
        return self.scroll(-self.visible)

    def page_down(self) -> Viewport:
        """Scroll down by one page (visible height)."""
        return self.scroll(self.visible)

    def home(self) -> Viewport:
        """Scroll to top."""
        return replace(self, offset=0)

    def end(self) -> Viewport:
        """Scroll to bottom."""
        return replace(self, offset=self.max_offset)

    def scroll_into_view(self, index: int) -> Viewport:
        """Adjust offset to ensure index is visible.

        If index is above the viewport, scrolls up to show it at top.
        If index is below the viewport, scrolls down to show it at bottom.
        If index is already visible, returns unchanged.
        """
        if index < self.offset:
            return replace(self, offset=max(0, index))
        elif index >= self.offset + self.visible:
            return replace(self, offset=self._clamp(index - self.visible + 1))
        return self

    def with_content(self, content: int) -> Viewport:
        """Return viewport with updated content height, clamping offset if needed."""
        new = replace(self, content=content)
        return replace(new, offset=new._clamp(new.offset))

    def with_visible(self, visible: int) -> Viewport:
        """Return viewport with updated visible height, clamping offset if needed."""
        new = replace(self, visible=visible)
        return replace(new, offset=new._clamp(new.offset))
