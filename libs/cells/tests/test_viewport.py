"""Tests for cells.viewport: Viewport scroll state."""

from cells import Viewport


class TestViewportBasics:
    def test_default_values(self):
        vp = Viewport()
        assert vp.offset == 0
        assert vp.visible == 0
        assert vp.content == 0

    def test_max_offset_content_fits(self):
        vp = Viewport(offset=0, visible=10, content=5)
        assert vp.max_offset == 0

    def test_max_offset_content_exceeds(self):
        vp = Viewport(offset=0, visible=10, content=25)
        assert vp.max_offset == 15

    def test_max_offset_equal(self):
        vp = Viewport(offset=0, visible=10, content=10)
        assert vp.max_offset == 0

    def test_can_scroll_true(self):
        vp = Viewport(offset=0, visible=10, content=20)
        assert vp.can_scroll is True

    def test_can_scroll_false(self):
        vp = Viewport(offset=0, visible=10, content=5)
        assert vp.can_scroll is False

    def test_is_at_top(self):
        vp = Viewport(offset=0, visible=10, content=20)
        assert vp.is_at_top is True

    def test_is_at_bottom(self):
        vp = Viewport(offset=10, visible=10, content=20)
        assert vp.is_at_bottom is True

    def test_is_at_bottom_exact(self):
        vp = Viewport(offset=5, visible=10, content=15)
        assert vp.is_at_bottom is True


class TestViewportScroll:
    def test_scroll_down(self):
        vp = Viewport(offset=0, visible=10, content=30)
        result = vp.scroll(5)
        assert result.offset == 5

    def test_scroll_up(self):
        vp = Viewport(offset=10, visible=10, content=30)
        result = vp.scroll(-3)
        assert result.offset == 7

    def test_scroll_clamps_to_max(self):
        vp = Viewport(offset=15, visible=10, content=30)
        result = vp.scroll(10)
        assert result.offset == 20  # max_offset

    def test_scroll_clamps_to_zero(self):
        vp = Viewport(offset=5, visible=10, content=30)
        result = vp.scroll(-10)
        assert result.offset == 0

    def test_scroll_no_effect_when_content_fits(self):
        vp = Viewport(offset=0, visible=10, content=5)
        result = vp.scroll(5)
        assert result.offset == 0


class TestViewportScrollTo:
    def test_scroll_to_valid(self):
        vp = Viewport(offset=0, visible=10, content=30)
        result = vp.scroll_to(15)
        assert result.offset == 15

    def test_scroll_to_clamps_high(self):
        vp = Viewport(offset=0, visible=10, content=30)
        result = vp.scroll_to(100)
        assert result.offset == 20

    def test_scroll_to_clamps_negative(self):
        vp = Viewport(offset=10, visible=10, content=30)
        result = vp.scroll_to(-5)
        assert result.offset == 0


class TestViewportPages:
    def test_page_down(self):
        vp = Viewport(offset=0, visible=10, content=30)
        result = vp.page_down()
        assert result.offset == 10

    def test_page_up(self):
        vp = Viewport(offset=15, visible=10, content=30)
        result = vp.page_up()
        assert result.offset == 5

    def test_page_down_clamps(self):
        vp = Viewport(offset=15, visible=10, content=30)
        result = vp.page_down()
        assert result.offset == 20  # max

    def test_page_up_clamps(self):
        vp = Viewport(offset=3, visible=10, content=30)
        result = vp.page_up()
        assert result.offset == 0


class TestViewportHomeEnd:
    def test_home(self):
        vp = Viewport(offset=15, visible=10, content=30)
        result = vp.home()
        assert result.offset == 0

    def test_end(self):
        vp = Viewport(offset=0, visible=10, content=30)
        result = vp.end()
        assert result.offset == 20


class TestViewportScrollIntoView:
    def test_index_already_visible(self):
        vp = Viewport(offset=5, visible=10, content=30)
        # indices 5-14 are visible
        result = vp.scroll_into_view(10)
        assert result.offset == 5  # unchanged

    def test_index_above_viewport(self):
        vp = Viewport(offset=10, visible=10, content=30)
        result = vp.scroll_into_view(5)
        assert result.offset == 5

    def test_index_below_viewport(self):
        vp = Viewport(offset=0, visible=10, content=30)
        # visible: 0-9, want to see 15
        result = vp.scroll_into_view(15)
        assert result.offset == 6  # 15 at bottom row (15 - 10 + 1)

    def test_index_at_bottom_edge(self):
        vp = Viewport(offset=0, visible=10, content=30)
        # visible: 0-9, index 9 is visible
        result = vp.scroll_into_view(9)
        assert result.offset == 0

    def test_index_just_past_bottom(self):
        vp = Viewport(offset=0, visible=10, content=30)
        # visible: 0-9, index 10 is just past
        result = vp.scroll_into_view(10)
        assert result.offset == 1

    def test_index_negative_clamped(self):
        vp = Viewport(offset=5, visible=10, content=30)
        result = vp.scroll_into_view(-3)
        assert result.offset == 0


class TestViewportWithContent:
    def test_with_content_increases(self):
        vp = Viewport(offset=5, visible=10, content=20)
        result = vp.with_content(50)
        assert result.content == 50
        assert result.offset == 5  # still valid

    def test_with_content_clamps_offset(self):
        vp = Viewport(offset=15, visible=10, content=30)
        result = vp.with_content(20)
        assert result.content == 20
        assert result.offset == 10  # clamped to new max


class TestViewportWithVisible:
    def test_with_visible_increases(self):
        vp = Viewport(offset=5, visible=10, content=30)
        result = vp.with_visible(20)
        assert result.visible == 20
        assert result.offset == 5  # still valid

    def test_with_visible_clamps_offset(self):
        vp = Viewport(offset=10, visible=10, content=20)
        result = vp.with_visible(15)
        assert result.visible == 15
        assert result.offset == 5  # max_offset is now 5


class TestViewportEdgeCases:
    def test_zero_visible(self):
        vp = Viewport(offset=0, visible=0, content=10)
        assert vp.max_offset == 10
        assert vp.can_scroll is True

    def test_zero_content(self):
        vp = Viewport(offset=0, visible=10, content=0)
        assert vp.max_offset == 0
        assert vp.can_scroll is False
        assert vp.scroll(5).offset == 0

    def test_immutability(self):
        vp = Viewport(offset=5, visible=10, content=30)
        _ = vp.scroll(5)
        assert vp.offset == 5  # original unchanged
