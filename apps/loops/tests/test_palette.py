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


# --- rail_style: tier → Style map (parallel to _grammar.TIER_GLYPHS) ---

def test_rail_style_tiers():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert p.rail_style("high") == p.header
    assert p.rail_style("mid") == p.content
    assert p.rail_style("tail") == p.metadata
    assert p.rail_style("stale") == p.old

def test_rail_style_unknown_recedes_to_chrome():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert p.rail_style("") == p.chrome
    assert p.rail_style("nonsense") == p.chrome


# --- observer_style: stable hash-pool identity hue ---

def test_observer_style_stable():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert p.observer_style("alice") == p.observer_style("alice")
    assert isinstance(p.observer_style("alice"), Style)

def test_observer_style_empty_recedes():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert p.observer_style("") == p.metadata

def test_observer_style_empty_pool():
    from loops.palette import LoopsPalette
    p = LoopsPalette(kind_pool=())
    assert isinstance(p.observer_style("alice"), Style)


# --- horizon_meter_style: proximity ramp, thresholds owned by the palette ---

def test_horizon_meter_ramp():
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert p.horizon_meter_style(0.3) == p.accent    # < .6 calm
    assert p.horizon_meter_style(0.6) == p.warn      # .6–.85 approaching
    assert p.horizon_meter_style(0.84) == p.warn
    assert p.horizon_meter_style(0.85) == p.critical  # ≥ .85 about to seal
    assert p.horizon_meter_style(1.0) == p.critical


# --- _grammar.recency_style: freshness gradient over a recency tag ---

def test_recency_style_grades_by_age():
    import time

    from loops.lenses._grammar import recency_style
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    now = time.time()
    assert recency_style(now, p) == p.fresh
    assert recency_style(now - 172800, p) == p.old

def test_recency_style_unparseable_recedes():
    from loops.lenses._grammar import recency_style
    from loops.palette import LoopsPalette
    p = LoopsPalette()
    assert recency_style("not-a-timestamp", p) == p.metadata
