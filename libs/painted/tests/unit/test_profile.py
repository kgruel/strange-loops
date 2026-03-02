"""Tests for profile bridge: cProfile → flame_lens dicts."""

from painted._profile import ProfileResult, _stats_to_flame_dict, parse_collapsed, profile
from painted.views import flame_lens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _leaf_fn():
    """Pure Python leaf function for profiling."""
    total = 0
    for i in range(500):
        total += i
    return total


def _mid_fn():
    return _leaf_fn() + _leaf_fn()


def _top_fn():
    return _mid_fn() + 1


def _collect_keys(d: dict) -> set[str]:
    """Collect all non-[self] keys from a nested flame dict."""
    keys: set[str] = set()
    for k, v in d.items():
        if k != "[self]":
            keys.add(k)
            if isinstance(v, dict):
                keys.update(_collect_keys(v))
    return keys


def _check_leaves_numeric(d: dict) -> None:
    """Assert all leaf values in a flame dict are numeric."""
    for v in d.values():
        if isinstance(v, dict):
            _check_leaves_numeric(v)
        else:
            assert isinstance(v, (int, float)), f"expected numeric, got {type(v)}: {v}"


# ---------------------------------------------------------------------------
# TestProfile — context manager basics
# ---------------------------------------------------------------------------


class TestProfile:
    """profile() context manager captures cProfile data."""

    def test_result_populated_after_block(self):
        """Result box gets a ProfileResult after the with-block exits."""
        with profile() as result:
            _top_fn()
        assert len(result) == 1
        assert isinstance(result[0], ProfileResult)

    def test_nonzero_total_time(self):
        """Profiled code produces non-zero total_time."""
        with profile() as result:
            _top_fn()
        assert result[0].total_time > 0

    def test_nonzero_call_count(self):
        """Profiled code records function calls."""
        with profile() as result:
            _top_fn()
        assert result[0].call_count > 0

    def test_flame_dict_has_string_keys(self):
        """flame_dict keys are all strings."""
        with profile() as result:
            _top_fn()
        d = result[0].flame_dict
        assert isinstance(d, dict)
        assert len(d) > 0
        for key in d:
            assert isinstance(key, str)

    def test_flame_dict_leaf_values_numeric(self):
        """All leaf values in flame_dict are int or float."""
        with profile() as result:
            _top_fn()
        _check_leaves_numeric(result[0].flame_dict)

    def test_round_trip_flame_lens(self):
        """Profile → flame_dict → flame_lens produces a valid Block."""
        with profile() as result:
            _top_fn()
        block = flame_lens(result[0].flame_dict, 2, 60)
        assert block.width == 60
        assert block.height >= 1

    def test_module_filter(self):
        """Module filter narrows captured functions."""
        with profile(module="painted") as narrow:
            _top_fn()
        with profile() as wide:
            _top_fn()
        # Wide should capture more (or equal) functions than narrow
        assert wide[0].call_count >= narrow[0].call_count


# ---------------------------------------------------------------------------
# TestStatsToFlameDict — conversion logic
# ---------------------------------------------------------------------------


class TestStatsToFlameDict:
    """_stats_to_flame_dict converts raw pstats data to flame dicts."""

    def test_known_call_tree(self):
        """Known caller graph produces expected nested structure."""
        stats = {
            ("test.py", 1, "main"): (1, 1, 0.001, 0.010, {}),
            ("test.py", 5, "render"): (
                1,
                1,
                0.005,
                0.008,
                {("test.py", 1, "main"): (1, 1, 0.005, 0.008)},
            ),
            ("test.py", 10, "flush"): (
                1,
                1,
                0.002,
                0.002,
                {("test.py", 5, "render"): (1, 1, 0.002, 0.002)},
            ),
        }
        result = _stats_to_flame_dict(stats)
        assert "main" in result
        assert isinstance(result["main"], dict)
        assert "render" in result["main"]
        assert isinstance(result["main"]["render"], dict)
        assert "flush" in result["main"]["render"]
        assert result["main"]["render"]["flush"] == 0.002

    def test_self_time_included(self):
        """Branch functions with self-time get a [self] entry."""
        stats = {
            ("test.py", 1, "parent"): (1, 1, 0.003, 0.010, {}),
            ("test.py", 5, "child"): (
                1,
                1,
                0.007,
                0.007,
                {("test.py", 1, "parent"): (1, 1, 0.007, 0.007)},
            ),
        }
        result = _stats_to_flame_dict(stats)
        assert "[self]" in result["parent"]
        assert result["parent"]["[self]"] == 0.003

    def test_module_filter_excludes(self):
        """Module filter excludes functions from other modules."""
        stats = {
            ("myapp/main.py", 1, "main"): (1, 1, 0.001, 0.010, {}),
            ("lib/other.py", 5, "helper"): (
                1,
                1,
                0.005,
                0.005,
                {("myapp/main.py", 1, "main"): (1, 1, 0.005, 0.005)},
            ),
        }
        result = _stats_to_flame_dict(stats, module="myapp")
        assert "main" in result
        # helper should not appear (its file doesn't contain "myapp")
        all_keys = _collect_keys(result)
        assert "helper" not in all_keys

    def test_top_n_limits(self):
        """top_n limits the number of functions in the flame dict."""
        stats = {}
        for i in range(10):
            callers = {}
            if i > 0:
                callers[("test.py", i - 1, f"func_{i - 1}")] = (1, 1, 0.001, 0.001)
            stats[("test.py", i, f"func_{i}")] = (
                1,
                1,
                0.001 * (10 - i),
                0.01 * (10 - i),
                callers,
            )
        result = _stats_to_flame_dict(stats, top_n=3)
        all_keys = _collect_keys(result)
        assert len(all_keys) <= 3

    def test_recursive_no_infinite_loop(self):
        """Recursive functions don't cause infinite loops."""
        stats = {
            ("test.py", 1, "recurse"): (
                10,
                10,
                0.01,
                0.05,
                {("test.py", 1, "recurse"): (9, 9, 0.009, 0.045)},
            ),
        }
        result = _stats_to_flame_dict(stats)
        assert isinstance(result, dict)
        assert "recurse" in result

    def test_empty_stats(self):
        """Empty stats produces empty dict."""
        assert _stats_to_flame_dict({}) == {}

    def test_label_disambiguation(self):
        """Functions with the same name get file-disambiguated labels."""
        stats = {
            ("a.py", 1, "run"): (1, 1, 0.005, 0.010, {}),
            ("b.py", 1, "run"): (
                1,
                1,
                0.005,
                0.005,
                {("a.py", 1, "run"): (1, 1, 0.005, 0.005)},
            ),
        }
        result = _stats_to_flame_dict(stats)
        keys = _collect_keys(result)
        # Both should appear with file prefix disambiguation
        assert any("a.py" in k for k in keys)
        assert any("b.py" in k for k in keys)


# ---------------------------------------------------------------------------
# TestParseCollapsed — Gregg format parser
# ---------------------------------------------------------------------------


class TestParseCollapsed:
    """parse_collapsed handles Brendan Gregg collapsed-stack format."""

    def test_single_stack(self):
        """Single stack line → correct nested dict."""
        result = parse_collapsed("main;render;flush 42")
        assert result == {"main": {"render": {"flush": 42}}}

    def test_multiple_stacks_merged(self):
        """Multiple stacks merge into shared tree."""
        result = parse_collapsed("main;render 10\nmain;flush 5")
        assert result == {"main": {"render": 10, "flush": 5}}

    def test_duplicate_stacks_accumulate(self):
        """Duplicate stacks accumulate counts."""
        result = parse_collapsed("main;render 10\nmain;render 20")
        assert result == {"main": {"render": 30}}

    def test_empty_input(self):
        """Empty input → empty dict."""
        assert parse_collapsed("") == {}

    def test_whitespace_only(self):
        """Whitespace-only input → empty dict."""
        assert parse_collapsed("  \n  \n") == {}

    def test_trailing_whitespace(self):
        """Trailing newlines and spaces are handled."""
        result = parse_collapsed("  main;render 10  \n\n")
        assert result == {"main": {"render": 10}}

    def test_single_frame(self):
        """Stack with one frame (no semicolons) works."""
        result = parse_collapsed("main 100")
        assert result == {"main": 100}

    def test_leaf_promoted_to_branch(self):
        """Frame seen as leaf then as branch gets [self] entry."""
        text = "main;render 10\nmain;render;flush 5"
        result = parse_collapsed(text)
        assert result == {"main": {"render": {"[self]": 10, "flush": 5}}}

    def test_branch_gets_leaf_count(self):
        """Frame seen as branch then as leaf accumulates in [self]."""
        text = "main;render;flush 5\nmain;render 10"
        result = parse_collapsed(text)
        assert result == {"main": {"render": {"flush": 5, "[self]": 10}}}

    def test_invalid_count_skipped(self):
        """Lines with non-integer counts are skipped."""
        result = parse_collapsed("main;render abc\nmain;flush 5")
        assert result == {"main": {"flush": 5}}


# ---------------------------------------------------------------------------
# TestRoundTrip — end-to-end
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """End-to-end: profile → flame_dict → flame_lens → Block."""

    def test_profile_to_block(self):
        """Real profiled code renders through flame_lens."""
        with profile() as result:
            _top_fn()
        block = flame_lens(result[0].flame_dict, 2, 80)
        assert block.height >= 1
        assert block.width == 80

    def test_collapsed_to_block(self):
        """Collapsed stacks parse and render through flame_lens."""
        text = "main;render;paint 50\nmain;render;diff 30\nmain;flush 20"
        d = parse_collapsed(text)
        block = flame_lens(d, 2, 60)
        assert block.height >= 1
        # All top-level keys should be visible
        rows_text = ""
        for y in range(block.height):
            rows_text += "".join(c.char for c in block.row(y))
        assert "main" in rows_text
