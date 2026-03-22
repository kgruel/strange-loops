"""Tests for palette — kind_style and freshness_style methods."""

from painted import Style


def test_kind_style_explicit():
    from loops.palette import LoopsPalette
    p = LoopsPalette(kind_styles={"metric": Style(bold=True)})
    assert p.kind_style("metric").bold is True

def test_kind_style_fallback():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    s = p.kind_style("unknown_kind")
    assert isinstance(s, Style)

def test_kind_style_empty_pool():
    from loops.palette import LoopsPalette
    p = LoopsPalette(kind_pool=())
    s = p.kind_style("anything")
    assert isinstance(s, Style)  # returns default Style()

def test_freshness_fresh():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    s = p.freshness_style(10)  # < 300s = fresh
    assert s == p.fresh

def test_freshness_recent():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    s = p.freshness_style(1800)  # < 3600s = recent
    assert s == p.recent

def test_freshness_stale():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    s = p.freshness_style(43200)  # < 86400s = stale
    assert s == p.stale

def test_freshness_old():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    s = p.freshness_style(172800)  # > 86400s = old
    assert s == p.old
