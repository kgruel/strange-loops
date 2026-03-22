"""Tests for Source and SequentialSource."""

import asyncio

import pytest

from atoms import Source, CommandSource, SequentialSource, SourceError
from atoms import Coerce, Pick, Rename, Skip, Split, Transform


class TestSource:
    """Tests for Source behavior."""

    async def test_echo_single_line(self):
        """Single line output becomes single fact."""
        source = Source(
            command='echo "hello"',
            kind="greeting",
            observer="echo-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].kind == "greeting"
        assert facts[0].observer == "echo-source"
        assert facts[0].payload["line"] == "hello"

    async def test_echo_multiple_lines(self):
        """Multiple lines become multiple facts."""
        source = Source(
            command='printf "line1\\nline2\\nline3"',
            kind="output",
            observer="printf-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 3
        assert [f.payload["line"] for f in facts] == ["line1", "line2", "line3"]

    async def test_observer_identity(self):
        """Observer is stamped on all produced facts."""
        source = Source(
            command='echo "test"',
            kind="test",
            observer="my-observer",
        )

        async for fact in source.collect():
            assert fact.observer == "my-observer"

    async def test_command_failure_raises_source_error(self):
        """Non-zero exit code raises SourceError."""
        source = Source(
            command="exit 1",
            kind="output",
            observer="fail-source",
        )

        with pytest.raises(SourceError) as exc_info:
            async for _fact in source.collect():
                pass

        assert exc_info.value.returncode == 1

    async def test_command_with_stderr(self):
        """Stderr is captured in SourceError."""
        source = Source(
            command='echo "error message" >&2 && exit 1',
            kind="output",
            observer="stderr-source",
        )

        with pytest.raises(SourceError) as exc_info:
            async for _fact in source.collect():
                pass

        assert "error message" in exc_info.value.stderr

    async def test_empty_output(self):
        """Command with no output produces no facts."""
        source = Source(
            command="true",  # Exits 0, no output
            kind="silent",
            observer="silent-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 0

    async def test_command_with_arguments(self):
        """Commands with arguments work correctly."""
        source = Source(
            command='echo "a b c" | tr " " "\\n"',
            kind="split",
            observer="tr-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 3
        assert [f.payload["line"] for f in facts] == ["a", "b", "c"]

    async def test_no_lifecycle_facts_emitted(self):
        """Source yields only domain facts — no .complete or source.error."""
        source = Source(
            command='echo "hello"',
            kind="greeting",
            observer="obs",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert all(f.kind == "greeting" for f in facts)
        assert not any(f.kind.endswith(".complete") for f in facts)
        assert not any(f.kind == "source.error" for f in facts)


class TestSourceParse:
    """Tests for Source with parse parameter."""

    async def test_parse_basic_pipeline(self):
        """Parse pipeline transforms line into structured payload."""
        source = Source(
            command='echo "alice 1234 95.5"',
            kind="user",
            observer="parse-source",
            parse=[
                Split(),
                Rename({0: "name", 1: "id", 2: "score"}),
                Coerce({"id": int, "score": float}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "user"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"name": "alice", "id": 1234, "score": 95.5}

    async def test_parse_skip_header(self):
        """Skip primitive filters out header lines."""
        source = Source(
            command='printf "NAME ID\\nalice 1\\nbob 2"',
            kind="user",
            observer="skip-source",
            parse=[
                Skip(startswith="NAME"),
                Split(),
                Rename({0: "name", 1: "id"}),
                Coerce({"id": int}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "user"]
        assert len(data_facts) == 2
        assert data_facts[0].payload == {"name": "alice", "id": 1}
        assert data_facts[1].payload == {"name": "bob", "id": 2}

    async def test_parse_skip_by_field(self):
        """Skip can filter based on parsed field value."""
        source = Source(
            command='printf "proc1 0\\nproc2 50\\nproc3 0"',
            kind="process",
            observer="field-skip-source",
            parse=[
                Split(),
                Rename({0: "name", 1: "cpu"}),
                Skip(field="cpu", equals="0"),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "process"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"name": "proc2", "cpu": "50"}

    async def test_parse_failed_coercion_skips_line(self):
        """Lines that fail coercion are skipped (None from pipeline)."""
        source = Source(
            command='printf "valid 42\\ninvalid NaN\\nalso_valid 99"',
            kind="data",
            observer="coerce-source",
            parse=[
                Split(),
                Rename({0: "label", 1: "value"}),
                Coerce({"value": int}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 2
        assert data_facts[0].payload == {"label": "valid", "value": 42}
        assert data_facts[1].payload == {"label": "also_valid", "value": 99}

    async def test_parse_transform_then_coerce(self):
        """Transform strips characters before coercion."""
        source = Source(
            command='echo "disk1 75%"',
            kind="disk",
            observer="transform-source",
            parse=[
                Split(),
                Rename({0: "name", 1: "usage"}),
                Transform("usage", strip="%"),
                Coerce({"usage": int}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "disk"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"name": "disk1", "usage": 75}

    async def test_no_parse_uses_line_payload(self):
        """Without parse, payload is {"line": text}."""
        source = Source(
            command='echo "raw text"',
            kind="raw",
            observer="no-parse-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "raw"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"line": "raw text"}

    async def test_parse_pick_subset(self):
        """Pick selects only specific fields."""
        source = Source(
            command='echo "a b c d e"',
            kind="picked",
            observer="pick-source",
            parse=[
                Split(),
                Pick(0, 2, 4),
                Rename({0: "first", 1: "third", 2: "fifth"}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "picked"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"first": "a", "third": "c", "fifth": "e"}


class TestSourceFormat:
    """Tests for Source format parameter."""

    async def test_format_lines_default(self):
        """format=lines is the default, each line becomes a fact."""
        source = Source(
            command='printf "a\\nb\\nc"',
            kind="line",
            observer="lines-source",
            format="lines",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 3
        assert [f.payload["line"] for f in facts] == ["a", "b", "c"]

    async def test_format_json_parses_output(self):
        """format=json parses stdout as JSON, emits single fact."""
        source = Source(
            command='echo \'{"name": "alice", "score": 42}\'',
            kind="data",
            observer="json-source",
            format="json",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload == {"name": "alice", "score": 42}

    async def test_format_json_with_array(self):
        """format=json wraps top-level arrays/scalars into a dict payload."""
        source = Source(
            command='echo \'[1, 2, 3]\'',
            kind="data",
            observer="json-array-source",
            format="json",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload == {"_json": [1, 2, 3]}

    async def test_format_json_with_scalar(self):
        """format=json wraps top-level scalars into a dict payload."""
        source = Source(
            command="echo 42",
            kind="data",
            observer="json-scalar-source",
            format="json",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload == {"_json": 42}

    async def test_format_ndjson_with_arrays(self):
        """format=ndjson wraps non-object records into a dict payload."""
        source = Source(
            command='printf \'[1, 2]\\n[3, 4]\\n\'',
            kind="data",
            observer="ndjson-array-source",
            format="ndjson",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 2
        assert [f.payload for f in facts] == [{"_json": [1, 2]}, {"_json": [3, 4]}]

    async def test_format_json_invalid_no_error_fact(self):
        """format=json with invalid JSON logs to stderr, no domain facts."""
        source = Source(
            command='echo "not valid json"',
            kind="data",
            observer="bad-json-source",
            format="json",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        # No data facts and no lifecycle facts — invalid JSON is logged to stderr
        assert len(facts) == 0

    async def test_format_json_with_parse(self):
        """format=json applies parse to the parsed dict."""
        source = Source(
            command='echo \'{"name": "alice", "score": "42"}\'',
            kind="data",
            observer="json-parse-source",
            format="json",
            parse=[
                Coerce({"score": int}),
            ],
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"name": "alice", "score": 42}

    async def test_format_blob_single_fact(self):
        """format=blob emits entire stdout as single fact."""
        source = Source(
            command='printf "line1\\nline2\\nline3"',
            kind="blob",
            observer="blob-source",
            format="blob",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload == {"text": "line1\nline2\nline3"}

    async def test_format_blob_preserves_whitespace(self):
        """format=blob preserves all whitespace."""
        source = Source(
            command='printf "  indented\\n\\nempty line above"',
            kind="blob",
            observer="whitespace-source",
            format="blob",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload["text"] == "  indented\n\nempty line above"

    async def test_format_blob_empty_output(self):
        """format=blob with no output produces no facts."""
        source = Source(
            command="true",
            kind="blob",
            observer="empty-blob-source",
            format="blob",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 0


class TestSourceOrigin:
    """Tests for Source origin field."""

    async def test_origin_default_empty(self):
        """Source origin defaults to empty string."""
        source = Source(command='echo "hi"', kind="test", observer="obs")
        assert source.origin == ""

    async def test_origin_stamped_on_lines(self):
        """Source-level origin is stamped on facts in lines format."""
        source = Source(
            command='echo "hello"',
            kind="greeting",
            observer="obs",
            origin="my-source",
        )
        facts = []
        async for fact in source.collect():
            facts.append(fact)
        assert len(facts) == 1
        assert facts[0].origin == "my-source"

    async def test_origin_stamped_on_ndjson(self):
        """Source-level origin is used as default in ndjson format."""
        source = Source(
            command='echo \'{"msg": "hi"}\'',
            kind="data",
            observer="obs",
            format="ndjson",
            origin="my-source",
        )
        facts = []
        async for fact in source.collect():
            facts.append(fact)
        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].origin == "my-source"

    async def test_ndjson_origin_override(self):
        """_origin in ndjson payload overrides Source-level origin."""
        source = Source(
            command='echo \'{"msg": "hi", "_origin": "override"}\'',
            kind="data",
            observer="obs",
            format="ndjson",
            origin="default-origin",
        )
        facts = []
        async for fact in source.collect():
            facts.append(fact)
        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].origin == "override"


class TestSourceProtocol:
    """Verify Source satisfies SourceProtocol."""

    def test_has_observer_property(self):
        """Source has observer property."""
        source = Source(
            command='echo "test"',
            kind="test",
            observer="test-observer",
        )
        assert source.observer == "test-observer"

    def test_has_collect_method(self):
        """Source has async collect method returning async iterator."""
        source = Source(
            command='echo "test"',
            kind="test",
            observer="test-observer",
        )
        assert hasattr(source, "collect")
        assert callable(source.collect)


class TestSourceError:
    """Tests for SourceError exception."""

    def test_basic_construction(self):
        err = SourceError("echo hi", 1, "something went wrong")
        assert err.command == "echo hi"
        assert err.returncode == 1
        assert err.stderr == "something went wrong"

    def test_defaults(self):
        err = SourceError("cmd")
        assert err.returncode == 1
        assert err.stderr == ""

    def test_from_exception(self):
        """SourceError wraps general exceptions."""
        try:
            raise SourceError("cmd", stderr="boom")
        except SourceError as e:
            assert "boom" in str(e)


class TestCommandSourceAlias:
    """Verify CommandSource is a deprecated alias for Source."""

    def test_command_source_is_source(self):
        """CommandSource is an alias for Source."""
        assert CommandSource is Source

    async def test_command_source_works(self):
        """CommandSource works identically to Source."""
        source = CommandSource(
            command='echo "hello"',
            kind="greeting",
            observer="alias-source",
        )

        facts = []
        async for fact in source.collect():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].kind == "greeting"
        assert facts[0].payload["line"] == "hello"


class TestSequentialSource:
    """Tests for SequentialSource — sequential execution with exit-on-failure."""

    async def test_all_succeed(self):
        """When all sources succeed, all facts are yielded in order."""
        seq = SequentialSource(sources=(
            Source(command='echo "step1"', kind="step1", observer="ci"),
            Source(command='echo "step2"', kind="step2", observer="ci"),
        ), _observer="ci")

        facts = []
        async for fact in seq.collect():
            facts.append(fact)

        # Only domain facts — no lifecycle artifacts
        step1_data = [f for f in facts if f.kind == "step1"]
        step2_data = [f for f in facts if f.kind == "step2"]
        assert len(step1_data) == 1
        assert len(step2_data) == 1

    async def test_first_fails_skips_second(self):
        """When first source exits non-zero, second is skipped via SourceError."""
        seq = SequentialSource(sources=(
            Source(command="exit 1", kind="lint", observer="ci"),
            Source(command='echo "should not run"', kind="test", observer="ci"),
        ), _observer="ci")

        with pytest.raises(SourceError):
            async for _fact in seq.collect():
                pass

    async def test_second_fails_third_skipped(self):
        """Failure in the middle stops remaining sources."""
        seq = SequentialSource(sources=(
            Source(command='echo "ok"', kind="step1", observer="ci"),
            Source(command="exit 42", kind="step2", observer="ci"),
            Source(command='echo "should not run"', kind="step3", observer="ci"),
        ), _observer="ci")

        facts = []
        with pytest.raises(SourceError) as exc_info:
            async for fact in seq.collect():
                facts.append(fact)

        # step1 ran and produced a fact
        step1_data = [f for f in facts if f.kind == "step1"]
        assert len(step1_data) == 1

        # step3 never ran
        step3_data = [f for f in facts if f.kind == "step3"]
        assert len(step3_data) == 0

        # Error carries the failing command info
        assert exc_info.value.returncode == 42

    async def test_observer_property(self):
        """SequentialSource exposes observer."""
        seq = SequentialSource(sources=(), _observer="ci")
        assert seq.observer == "ci"

class TestSourceParseHelpers:
    """Direct tests for _parse_data / _parse_data_many without subprocess."""

    def test_parse_data_non_str_non_dict(self):
        # L91: defensive normalization for non-str, non-dict input
        source = Source(command="unused", kind="test", observer="t")
        result = source._parse_data(42)
        assert result == {"_json": 42}

    def test_parse_data_many_non_str_non_dict(self):
        # L103-104: wraps non-str/dict into {"_json": ...}
        source = Source(command="unused", kind="test", observer="t")
        result = source._parse_data_many([1, 2, 3])
        assert result == [{"_json": [1, 2, 3]}]

    def test_parse_data_many_no_pipeline(self):
        # L106-108: no parse pipeline, dict input → [data]
        source = Source(command="unused", kind="test", observer="t")
        result = source._parse_data_many({"a": 1})
        assert result == [{"a": 1}]

    def test_parse_data_many_no_pipeline_str(self):
        # L109: no parse pipeline, str input → []
        source = Source(command="unused", kind="test", observer="t")
        result = source._parse_data_many("hello")
        assert result == []

    def test_parse_data_many_with_pipeline(self):
        # L111-113: with parse pipeline, delegates to run_parse_many
        from atoms import Explode
        source = Source(
            command="unused", kind="test", observer="t",
            parse=(Explode(path="items"),),
        )
        result = source._parse_data_many({"items": [{"n": "a"}, {"n": "b"}]})
        assert len(result) == 2


class TestSourceSubprocessEdges:
    """Tests for subprocess edge cases."""

    async def test_json_format_with_explode(self):
        """JSON format with explode pipeline fans out records."""
        from atoms import Explode
        source = Source(
            command='echo \'{"items": [{"name": "a"}, {"name": "b"}]}\'',
            kind="test", observer="t", format="json",
            parse=(Explode(path="items"),),
        )
        facts = [f async for f in source.collect()]
        names = [f.payload["name"] for f in facts]
        assert "a" in names
        assert "b" in names

    async def test_ndjson_format_skips_empty_lines(self):
        """NDJSON skips blank lines and parses each JSON line."""
        source = Source(
            command='printf \'{"x":1}\\n\\n{"x":2}\\n\'',
            kind="test", observer="t", format="ndjson",
        )
        facts = [f async for f in source.collect()]
        assert len(facts) == 2

    async def test_env_vars_passed(self):
        """Environment variables are forwarded to subprocess."""
        source = Source(
            command='echo $MY_TEST_VAR',
            kind="test", observer="t",
            env={"MY_TEST_VAR": "hello_from_env"},
        )
        facts = [f async for f in source.collect()]
        assert any("hello_from_env" in f.payload.get("line", "") for f in facts)

    async def test_ndjson_json_error_continues(self):
        """NDJSON skips malformed lines and continues."""
        source = Source(
            command='printf \'{"x":1}\\nnot json\\n{"x":2}\\n\'',
            kind="test", observer="t", format="ndjson",
        )
        facts = [f async for f in source.collect()]
        assert len(facts) == 2  # malformed line skipped

    async def test_generic_exception_wrapped(self):
        """Non-SourceError exceptions are wrapped in SourceError."""
        source = Source(
            command="this_command_really_does_not_exist_xyz_99",
            kind="test", observer="t",
        )
        with pytest.raises(SourceError):
            async for _ in source.collect():
                pass


    def test_empty_sources_kind_is_empty_string(self):
        seq = SequentialSource(sources=(), _observer="ci")
        assert seq.kind == ""

    def test_empty_sources_command_is_empty_string(self):
        seq = SequentialSource(sources=(), _observer="ci")
        assert seq.command == ""

    async def test_declaration_order_preserved(self):
        """Facts arrive in declaration order: all of source1, then source2."""
        seq = SequentialSource(sources=(
            Source(command='printf "a\\nb"', kind="first", observer="ci"),
            Source(command='printf "c\\nd"', kind="second", observer="ci"),
        ), _observer="ci")

        facts = []
        async for fact in seq.collect():
            facts.append(fact)

        kinds = [f.kind for f in facts]
        # All "first" facts before any "second" facts
        first_idx = [i for i, k in enumerate(kinds) if k == "first"]
        second_idx = [i for i, k in enumerate(kinds) if k == "second"]
        assert max(first_idx) < min(second_idx)
