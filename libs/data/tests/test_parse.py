"""Tests for parse vocabulary: Skip, Split, Pick, Rename, Transform, Coerce, Explode, Project, Where, run_parse."""

import pytest

from data import Coerce, Explode, Pick, Project, Rename, Skip, Split, Transform, Where, run_parse
from data.parse import resolve_path, run_parse_many, has_explode


class TestSkip:
    """Tests for Skip dataclass."""

    def test_startswith_string(self):
        """Skip line starting with prefix."""
        pipeline = [Skip(startswith="Filesystem"), Split(), Rename({0: "a"})]
        # Header line skipped
        assert run_parse("Filesystem      Size  Used", pipeline) is None
        # Data line passes
        assert run_parse("/dev/sda1       100G  50G", pipeline) == {"a": "/dev/sda1"}

    def test_contains_string(self):
        """Skip line containing substring."""
        pipeline = [Skip(contains="/System"), Split(), Rename({0: "mount"})]
        assert run_parse("/System/Volumes/Data", pipeline) is None
        assert run_parse("/Users/home", pipeline) == {"mount": "/Users/home"}

    def test_equals_string(self):
        """Skip line exactly matching value."""
        pipeline = [Skip(equals=""), Split(), Rename({0: "a"})]
        assert run_parse("", pipeline) is None
        assert run_parse("data", pipeline) == {"a": "data"}

    def test_field_startswith(self):
        """Skip based on dict field value."""
        pipeline = [
            Split(),
            Rename({0: "mount", 1: "size"}),
            Skip(field="mount", startswith="/System"),
        ]
        assert run_parse("/System/Volumes 100G", pipeline) is None
        assert run_parse("/Users 200G", pipeline) == {"mount": "/Users", "size": "200G"}

    def test_field_contains(self):
        """Skip dict where field contains substring."""
        pipeline = [
            Split(),
            Rename({0: "name", 1: "status"}),
            Skip(field="status", contains="idle"),
        ]
        assert run_parse("proc1 idle", pipeline) is None
        assert run_parse("proc2 running", pipeline) == {"name": "proc2", "status": "running"}

    def test_field_equals(self):
        """Skip dict where field equals value."""
        pipeline = [
            Split(),
            Rename({0: "name", 1: "cpu"}),
            Skip(field="cpu", equals="0"),
        ]
        assert run_parse("idle_proc 0", pipeline) is None
        assert run_parse("busy_proc 50", pipeline) == {"name": "busy_proc", "cpu": "50"}

    def test_predicate_on_string(self):
        """Skip using predicate on string input."""
        pipeline = [
            Skip(predicate=lambda x: len(x) < 5),
            Split(),
            Rename({0: "word"}),
        ]
        assert run_parse("hi", pipeline) is None
        assert run_parse("hello", pipeline) == {"word": "hello"}

    def test_predicate_on_dict(self):
        """Skip using predicate on dict input (after Coerce)."""
        pipeline = [
            Split(),
            Rename({0: "name", 1: "cpu"}),
            Coerce({"cpu": int}),
            Skip(predicate=lambda x: x.get("cpu", 0) == 0),
        ]
        assert run_parse("idle 0", pipeline) is None
        assert run_parse("busy 75", pipeline) == {"name": "busy", "cpu": 75}

    def test_field_missing_passes(self):
        """Skip passes when field doesn't exist."""
        pipeline = [
            Split(),
            Rename({0: "a"}),
            Skip(field="missing", equals="x"),
        ]
        # Field doesn't exist, so don't skip
        assert run_parse("value", pipeline) == {"a": "value"}

    def test_no_conditions_passes(self):
        """Skip with no conditions passes everything."""
        pipeline = [Skip(), Split(), Rename({0: "a"})]
        assert run_parse("hello", pipeline) == {"a": "hello"}

    def test_frozen(self):
        """Skip is immutable."""
        s = Skip(startswith="x")
        with pytest.raises(AttributeError):
            s.startswith = "y"


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


class TestResolvePath:
    """Tests for resolve_path utility."""

    def test_simple_key(self):
        assert resolve_path({"status": "ok"}, "status") == "ok"

    def test_nested_path(self):
        data = {"data": {"alerts": [1, 2, 3]}}
        assert resolve_path(data, "data.alerts") == [1, 2, 3]

    def test_deep_nested(self):
        data = {"a": {"b": {"c": 42}}}
        assert resolve_path(data, "a.b.c") == 42

    def test_missing_key(self):
        assert resolve_path({"a": 1}, "b") is None

    def test_missing_nested(self):
        assert resolve_path({"a": {"b": 1}}, "a.c") is None

    def test_non_dict_intermediate(self):
        assert resolve_path({"a": "string"}, "a.b") is None


class TestWhere:
    """Tests for Where parse op."""

    def test_equals_passes(self):
        data = {"status": "success", "data": [1]}
        pipeline = [Where(path="status", op="equals", value="success")]
        assert run_parse(data, pipeline) == data

    def test_equals_filters(self):
        data = {"status": "error", "data": []}
        pipeline = [Where(path="status", op="equals", value="success")]
        assert run_parse(data, pipeline) is None

    def test_not_equals(self):
        data = {"type": "alerting"}
        pipeline = [Where(path="type", op="not_equals", value="recording")]
        assert run_parse(data, pipeline) == data

    def test_not_equals_filters(self):
        data = {"type": "recording"}
        pipeline = [Where(path="type", op="not_equals", value="recording")]
        assert run_parse(data, pipeline) is None

    def test_exists_passes(self):
        data = {"labels": {"severity": "critical"}}
        pipeline = [Where(path="labels", op="exists")]
        assert run_parse(data, pipeline) == data

    def test_exists_filters(self):
        data = {"name": "test"}
        pipeline = [Where(path="labels", op="exists")]
        assert run_parse(data, pipeline) is None

    def test_nested_path(self):
        data = {"labels": {"severity": "critical"}}
        pipeline = [Where(path="labels.severity", op="equals", value="critical")]
        assert run_parse(data, pipeline) == data


class TestExplode:
    """Tests for Explode parse op."""

    def test_basic_explode(self):
        data = {"data": {"alerts": [{"name": "a"}, {"name": "b"}]}}
        pipeline = [Explode(path="data.alerts")]
        results = run_parse_many(data, pipeline)
        assert len(results) == 2
        assert results[0] == {"name": "a"}
        assert results[1] == {"name": "b"}

    def test_explode_with_carry(self):
        data = {"name": "group1", "rules": [{"rule": "r1"}, {"rule": "r2"}]}
        pipeline = [Explode(path="rules", carry={"name": "group_name"})]
        results = run_parse_many(data, pipeline)
        assert len(results) == 2
        assert results[0] == {"rule": "r1", "group_name": "group1"}
        assert results[1] == {"rule": "r2", "group_name": "group1"}

    def test_explode_non_list_passthrough(self):
        data = {"data": "not a list"}
        pipeline = [Explode(path="data")]
        results = run_parse_many(data, pipeline)
        assert len(results) == 1
        assert results[0] == data

    def test_explode_missing_path(self):
        data = {"other": [1, 2]}
        pipeline = [Explode(path="data.alerts")]
        results = run_parse_many(data, pipeline)
        assert len(results) == 1  # passthrough

    def test_explode_scalar_items(self):
        data = {"items": [1, 2, 3]}
        pipeline = [Explode(path="items")]
        results = run_parse_many(data, pipeline)
        assert len(results) == 3
        assert results[0] == {"_value": 1}


class TestProject:
    """Tests for Project parse op."""

    def test_basic_project(self):
        data = {"labels": {"alertname": "HighCPU", "severity": "critical"}, "state": "firing"}
        pipeline = [Project(fields={"name": "labels.alertname", "state": "state", "sev": "labels.severity"})]
        result = run_parse(data, pipeline)
        assert result == {"name": "HighCPU", "state": "firing", "sev": "critical"}

    def test_project_missing_path(self):
        data = {"state": "firing"}
        pipeline = [Project(fields={"name": "labels.alertname", "state": "state"})]
        result = run_parse(data, pipeline)
        assert result == {"name": None, "state": "firing"}

    def test_project_top_level(self):
        data = {"name": "test", "value": 42}
        pipeline = [Project(fields={"n": "name", "v": "value"})]
        result = run_parse(data, pipeline)
        assert result == {"n": "test", "v": 42}


class TestRunParseMany:
    """Tests for run_parse_many stream executor."""

    def test_where_then_explode_then_project(self):
        """Full pipeline: filter → fan-out → reshape."""
        data = {
            "status": "success",
            "data": {
                "alerts": [
                    {"labels": {"alertname": "HighCPU"}, "state": "firing"},
                    {"labels": {"alertname": "DiskFull"}, "state": "pending"},
                ]
            },
        }
        pipeline = [
            Where(path="status", op="equals", value="success"),
            Explode(path="data.alerts"),
            Project(fields={"alertname": "labels.alertname", "state": "state"}),
        ]
        results = run_parse_many(data, pipeline)
        assert len(results) == 2
        assert results[0] == {"alertname": "HighCPU", "state": "firing"}
        assert results[1] == {"alertname": "DiskFull", "state": "pending"}

    def test_where_filters_before_explode(self):
        """Where filters the whole record before explode."""
        data = {"status": "error", "data": {"alerts": [{"name": "a"}]}}
        pipeline = [
            Where(path="status", op="equals", value="success"),
            Explode(path="data.alerts"),
        ]
        results = run_parse_many(data, pipeline)
        assert len(results) == 0

    def test_double_explode(self):
        """Nested explode: groups → rules."""
        data = {
            "data": {
                "groups": [
                    {"name": "g1", "rules": [{"rule": "r1"}, {"rule": "r2"}]},
                    {"name": "g2", "rules": [{"rule": "r3"}]},
                ]
            }
        }
        pipeline = [
            Explode(path="data.groups"),
            Explode(path="rules", carry={"name": "group_name"}),
        ]
        results = run_parse_many(data, pipeline)
        assert len(results) == 3
        assert results[0] == {"rule": "r1", "group_name": "g1"}
        assert results[1] == {"rule": "r2", "group_name": "g1"}
        assert results[2] == {"rule": "r3", "group_name": "g2"}

    def test_where_after_explode(self):
        """Where filters individual records after explode."""
        data = {
            "data": {
                "items": [
                    {"type": "alerting", "name": "a"},
                    {"type": "recording", "name": "b"},
                    {"type": "alerting", "name": "c"},
                ]
            }
        }
        pipeline = [
            Explode(path="data.items"),
            Where(path="type", op="equals", value="alerting"),
        ]
        results = run_parse_many(data, pipeline)
        assert len(results) == 2
        assert results[0]["name"] == "a"
        assert results[1]["name"] == "c"

    def test_has_explode_true(self):
        pipeline = [Where(path="x"), Explode(path="y")]
        assert has_explode(pipeline) is True

    def test_has_explode_false(self):
        pipeline = [Where(path="x"), Project(fields={"a": "b"})]
        assert has_explode(pipeline) is False

    def test_json_array_explode(self):
        """Explode on _json for Radarr-style JSON array responses."""
        data = {"_json": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]}
        pipeline = [Explode(path="_json")]
        results = run_parse_many(data, pipeline)
        assert len(results) == 2
        assert results[0] == {"id": 1, "title": "A"}
        assert results[1] == {"id": 2, "title": "B"}
