"""Tests for parse vocabulary: Split, Pick, Rename, Transform, Coerce, run_parse."""

import pytest

from specs import Coerce, Pick, Rename, Split, Transform, run_parse


class TestSplit:
    """Tests for Split dataclass."""

    def test_whitespace_default(self):
        """Split() with no delimiter splits on whitespace and collapses runs."""
        pipeline = [Split(), Pick(0, 1, 2), Rename({0: "a", 1: "b", 2: "c"})]
        result = run_parse("hello   world  test", pipeline)
        assert result == {"a": "hello", "b": "world", "c": "test"}

    def test_explicit_delimiter(self):
        """Split with explicit delimiter."""
        pipeline = [Split(delim=":"), Pick(0, 1), Rename({0: "a", 1: "b"})]
        result = run_parse("key:value", pipeline)
        assert result == {"a": "key", "b": "value"}

    def test_max_splits(self):
        """Split with max limits number of splits."""
        pipeline = [Split(delim="=", max=1), Pick(0, 1), Rename({0: "key", 1: "val"})]
        result = run_parse("name=a=b=c", pipeline)
        assert result == {"key": "name", "val": "a=b=c"}

    def test_empty_string(self):
        """Split on empty string produces empty list."""
        pipeline = [Split(), Pick(0), Rename({0: "a"})]
        result = run_parse("", pipeline)
        assert result is None  # Pick(0) fails on empty list

    def test_frozen(self):
        """Split is immutable."""
        s = Split(delim=":")
        with pytest.raises(AttributeError):
            s.delim = ","


class TestPick:
    """Tests for Pick dataclass."""

    def test_select_indices(self):
        """Pick selects specific indices."""
        pipeline = [Split(), Pick(0, 2), Rename({0: "first", 1: "third"})]
        result = run_parse("a b c d", pipeline)
        assert result == {"first": "a", "third": "c"}

    def test_negative_index(self):
        """Pick supports negative indices."""
        pipeline = [Split(), Pick(0, -1), Rename({0: "first", 1: "last"})]
        result = run_parse("a b c d", pipeline)
        assert result == {"first": "a", "last": "d"}

    def test_index_out_of_range(self):
        """Pick returns None for out-of-range index."""
        pipeline = [Split(), Pick(0, 99), Rename({0: "a", 1: "b"})]
        result = run_parse("hello world", pipeline)
        assert result is None

    def test_single_index(self):
        """Pick with single index."""
        pipeline = [Split(), Pick(1), Rename({0: "second"})]
        result = run_parse("a b c", pipeline)
        assert result == {"second": "b"}

    def test_frozen(self):
        """Pick is immutable."""
        p = Pick(0, 1, 2)
        with pytest.raises(AttributeError):
            p.indices = (3, 4)


class TestRename:
    """Tests for Rename dataclass."""

    def test_basic_rename(self):
        """Rename maps indices to names."""
        pipeline = [Split(), Rename({0: "user", 1: "pid"})]
        result = run_parse("alice 1234", pipeline)
        assert result == {"user": "alice", "pid": "1234"}

    def test_partial_rename(self):
        """Rename can select subset of fields."""
        pipeline = [Split(), Rename({0: "first", 2: "third"})]
        result = run_parse("a b c d", pipeline)
        assert result == {"first": "a", "third": "c"}

    def test_index_out_of_range(self):
        """Rename returns None for out-of-range index."""
        pipeline = [Split(), Rename({0: "a", 99: "b"})]
        result = run_parse("hello", pipeline)
        assert result is None

    def test_empty_mapping(self):
        """Rename with empty mapping produces empty dict."""
        pipeline = [Split(), Rename({})]
        result = run_parse("hello world", pipeline)
        assert result == {}

    def test_frozen(self):
        """Rename is immutable."""
        r = Rename({0: "a"})
        with pytest.raises(AttributeError):
            r.mapping = {1: "b"}

    def test_mapping_immutable(self):
        """Rename mapping cannot be modified."""
        r = Rename({0: "a", 1: "b"})
        with pytest.raises(TypeError):
            r.mapping[0] = "changed"


class TestTransform:
    """Tests for Transform dataclass."""

    def test_strip(self):
        """Transform strips characters."""
        pipeline = [
            Split(),
            Pick(0, 1),
            Rename({0: "name", 1: "pct"}),
            Transform("pct", strip="%"),
        ]
        result = run_parse("disk1 27%", pipeline)
        assert result == {"name": "disk1", "pct": "27"}

    def test_lstrip(self):
        """Transform lstrips characters."""
        pipeline = [
            Split(),
            Rename({0: "val"}),
            Transform("val", lstrip="$"),
        ]
        result = run_parse("$100", pipeline)
        assert result == {"val": "100"}

    def test_rstrip(self):
        """Transform rstrips characters."""
        pipeline = [
            Split(),
            Rename({0: "size"}),
            Transform("size", rstrip="Gi"),
        ]
        result = run_parse("123Gi", pipeline)
        assert result == {"size": "123"}

    def test_replace(self):
        """Transform replaces substring."""
        pipeline = [
            Split(),
            Rename({0: "path"}),
            Transform("path", replace=("//", "/")),
        ]
        result = run_parse("a//b//c", pipeline)
        assert result == {"path": "a/b/c"}

    def test_combined_transforms(self):
        """Multiple transform options applied in order."""
        pipeline = [
            Split(),
            Rename({0: "val"}),
            Transform("val", strip=" ", replace=(",", "")),
        ]
        result = run_parse(" 1,234 ", pipeline)
        assert result == {"val": "1234"}

    def test_missing_field(self):
        """Transform returns None if field missing."""
        pipeline = [
            Split(),
            Rename({0: "a"}),
            Transform("missing", strip="%"),
        ]
        result = run_parse("hello", pipeline)
        assert result is None

    def test_frozen(self):
        """Transform is immutable."""
        t = Transform("x", strip="%")
        with pytest.raises(AttributeError):
            t.field = "y"


class TestCoerce:
    """Tests for Coerce dataclass."""

    def test_coerce_int(self):
        """Coerce to int."""
        pipeline = [
            Split(),
            Pick(0, 1),
            Rename({0: "name", 1: "count"}),
            Coerce({"count": int}),
        ]
        result = run_parse("items 42", pipeline)
        assert result == {"name": "items", "count": 42}
        assert isinstance(result["count"], int)

    def test_coerce_float(self):
        """Coerce to float."""
        pipeline = [
            Split(),
            Rename({0: "price"}),
            Coerce({"price": float}),
        ]
        result = run_parse("3.14", pipeline)
        assert result == {"price": 3.14}
        assert isinstance(result["price"], float)

    def test_coerce_bool_true(self):
        """Coerce to bool (true values)."""
        for val in ["true", "True", "1", "yes"]:
            pipeline = [Split(), Rename({0: "flag"}), Coerce({"flag": bool})]
            result = run_parse(val, pipeline)
            assert result == {"flag": True}

    def test_coerce_bool_false(self):
        """Coerce to bool (false values)."""
        for val in ["false", "False", "0", "no"]:
            pipeline = [Split(), Rename({0: "flag"}), Coerce({"flag": bool})]
            result = run_parse(val, pipeline)
            assert result == {"flag": False}

    def test_coerce_bool_invalid(self):
        """Coerce to bool with invalid value returns None."""
        pipeline = [Split(), Rename({0: "flag"}), Coerce({"flag": bool})]
        result = run_parse("maybe", pipeline)
        assert result is None

    def test_coerce_str(self):
        """Coerce to str (passthrough)."""
        pipeline = [Split(), Rename({0: "val"}), Coerce({"val": str})]
        result = run_parse("hello", pipeline)
        assert result == {"val": "hello"}

    def test_coerce_multiple_fields(self):
        """Coerce multiple fields."""
        pipeline = [
            Split(),
            Rename({0: "name", 1: "count", 2: "price"}),
            Coerce({"count": int, "price": float}),
        ]
        result = run_parse("item 5 9.99", pipeline)
        assert result == {"name": "item", "count": 5, "price": 9.99}

    def test_coerce_failure_returns_none(self):
        """Coerce returns None on conversion failure."""
        pipeline = [Split(), Rename({0: "count"}), Coerce({"count": int})]
        result = run_parse("not_a_number", pipeline)
        assert result is None

    def test_missing_field_returns_none(self):
        """Coerce returns None if field missing."""
        pipeline = [Split(), Rename({0: "a"}), Coerce({"missing": int})]
        result = run_parse("hello", pipeline)
        assert result is None

    def test_frozen(self):
        """Coerce is immutable."""
        c = Coerce({"x": int})
        with pytest.raises(AttributeError):
            c.types = {"y": float}

    def test_types_immutable(self):
        """Coerce types mapping cannot be modified."""
        c = Coerce({"x": int, "y": float})
        with pytest.raises(TypeError):
            c.types["x"] = str


class TestRunParse:
    """Tests for run_parse() function."""

    def test_empty_pipeline(self):
        """Empty pipeline returns None."""
        result = run_parse("hello", [])
        assert result is None

    def test_pipeline_must_produce_dict(self):
        """Pipeline that doesn't end with dict returns None."""
        pipeline = [Split()]  # Only Split, produces list not dict
        result = run_parse("hello world", pipeline)
        assert result is None

    def test_full_pipeline(self):
        """Full pipeline: Split → Pick → Rename → Transform → Coerce."""
        pipeline = [
            Split(),
            Pick(0, 1, 4),
            Rename({0: "fs", 1: "size", 2: "pct"}),
            Transform("pct", strip="%"),
            Coerce({"pct": int}),
        ]
        result = run_parse("/dev/disk1s1 466Gi 123Gi 340Gi 27% 1234567 99% / /System", pipeline)
        assert result == {"fs": "/dev/disk1s1", "size": "466Gi", "pct": 27}

    def test_none_propagation(self):
        """None from any step stops pipeline."""
        pipeline = [
            Split(),
            Pick(0, 99),  # Will fail - index out of range
            Rename({0: "a", 1: "b"}),
        ]
        result = run_parse("hello", pipeline)
        assert result is None


class TestRealWorldParsing:
    """Tests with real command output."""

    def test_df_output(self):
        """Parse df output line."""
        line = "/dev/disk3s1s1  466Gi  8.8Gi  211Gi     5%   96Ki  2213694528    0%   /"

        pipeline = [
            Split(),
            Pick(0, 1, 2, 3, 4, 8),
            Rename({0: "fs", 1: "size", 2: "used", 3: "avail", 4: "pct", 5: "mount"}),
            Transform("pct", strip="%"),
            Coerce({"pct": int}),
        ]

        result = run_parse(line, pipeline)
        assert result == {
            "fs": "/dev/disk3s1s1",
            "size": "466Gi",
            "used": "8.8Gi",
            "avail": "211Gi",
            "pct": 5,
            "mount": "/",
        }

    def test_ps_output(self):
        """Parse ps output line."""
        line = "  501 12345 92.3  1.2 /usr/bin/python script.py"

        pipeline = [
            Split(),
            Pick(0, 1, 2, 3),
            Rename({0: "uid", 1: "pid", 2: "cpu", 3: "mem"}),
            Coerce({"uid": int, "pid": int, "cpu": float, "mem": float}),
        ]

        result = run_parse(line, pipeline)
        assert result == {"uid": 501, "pid": 12345, "cpu": 92.3, "mem": 1.2}

    def test_env_output(self):
        """Parse env KEY=value output."""
        line = "PATH=/usr/local/bin:/usr/bin:/bin"

        pipeline = [
            Split(delim="=", max=1),
            Rename({0: "key", 1: "value"}),
        ]

        result = run_parse(line, pipeline)
        assert result == {"key": "PATH", "value": "/usr/local/bin:/usr/bin:/bin"}

    def test_skip_header_line(self):
        """Header lines can be detected by failed coercion."""
        header = "Filesystem      Size  Used Avail Use% Mounted"
        data = "/dev/sda1       100G   50G   50G  50% /"

        pipeline = [
            Split(),
            Pick(0, 4, 5),
            Rename({0: "fs", 1: "pct", 2: "mount"}),
            Transform("pct", strip="%"),
            Coerce({"pct": int}),
        ]

        # Header fails coercion (Use% → int fails)
        header_result = run_parse(header, pipeline)
        assert header_result is None

        # Data line succeeds
        data_result = run_parse(data, pipeline)
        assert data_result == {"fs": "/dev/sda1", "pct": 50, "mount": "/"}

    def test_multiple_transforms(self):
        """Chain multiple Transform ops."""
        line = "disk1  $1,234.56"

        pipeline = [
            Split(),
            Rename({0: "name", 1: "price"}),
            Transform("price", lstrip="$"),
            Transform("price", replace=(",", "")),
            Coerce({"price": float}),
        ]

        result = run_parse(line, pipeline)
        assert result == {"name": "disk1", "price": 1234.56}


class TestEdgeCases:
    """Edge case tests."""

    def test_single_field(self):
        """Parse single field."""
        pipeline = [Split(), Rename({0: "only"})]
        result = run_parse("value", pipeline)
        assert result == {"only": "value"}

    def test_unicode(self):
        """Parse unicode characters."""
        pipeline = [Split(), Rename({0: "emoji", 1: "text"})]
        result = run_parse("🎉 celebration", pipeline)
        assert result == {"emoji": "🎉", "text": "celebration"}

    def test_tabs_as_whitespace(self):
        """Tabs treated as whitespace in default split."""
        pipeline = [Split(), Rename({0: "a", 1: "b"})]
        result = run_parse("hello\tworld", pipeline)
        assert result == {"a": "hello", "b": "world"}

    def test_newline_in_value(self):
        """Newlines are not special to split."""
        pipeline = [Split(delim=":"), Rename({0: "a", 1: "b"})]
        result = run_parse("key:value\nwith\nnewlines", pipeline)
        assert result == {"a": "key", "b": "value\nwith\nnewlines"}

    def test_empty_fields_with_delimiter(self):
        """Empty fields preserved with explicit delimiter."""
        pipeline = [Split(delim=":"), Rename({0: "a", 1: "b", 2: "c"})]
        result = run_parse("a::c", pipeline)
        assert result == {"a": "a", "b": "", "c": "c"}
