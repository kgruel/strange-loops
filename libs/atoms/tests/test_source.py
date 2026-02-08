"""Tests for Source."""

import asyncio

import pytest

from atoms import Source, CommandSource
from atoms import Coerce, Pick, Rename, Skip, Split, Transform


class TestSource:
    """Tests for Source behavior."""

    async def test_echo_single_line(self):
        """Single line output becomes single fact plus completion."""
        source = Source(
            command='echo "hello"',
            kind="greeting",
            observer="echo-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        # One data fact + one completion fact
        data_facts = [f for f in facts if f.kind == "greeting"]
        complete_facts = [f for f in facts if f.kind == "greeting.complete"]
        assert len(data_facts) == 1
        assert len(complete_facts) == 1
        assert data_facts[0].observer == "echo-source"
        assert data_facts[0].payload["line"] == "hello"

    async def test_echo_multiple_lines(self):
        """Multiple lines become multiple facts."""
        source = Source(
            command='printf "line1\\nline2\\nline3"',
            kind="output",
            observer="printf-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "output"]
        assert len(data_facts) == 3
        assert [f.payload["line"] for f in data_facts] == ["line1", "line2", "line3"]

    async def test_observer_identity(self):
        """Observer is stamped on all produced facts."""
        source = Source(
            command='echo "test"',
            kind="test",
            observer="my-observer",
        )

        async for fact in source.stream():
            assert fact.observer == "my-observer"

    async def test_command_failure_emits_error_fact(self):
        """Non-zero exit code emits source.error fact."""
        source = Source(
            command="exit 1",
            kind="output",
            observer="fail-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 2
        assert facts[0].kind == "source.error"
        assert facts[0].payload["returncode"] == 1
        assert facts[0].observer == "fail-source"
        # Source always closes its own boundary
        assert facts[1].kind == "output.complete"
        assert facts[1].payload["status"] == "error"

    async def test_command_with_stderr(self):
        """Stderr captured in error fact."""
        source = Source(
            command='echo "error message" >&2 && exit 1',
            kind="output",
            observer="stderr-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        error_facts = [f for f in facts if f.kind == "source.error"]
        assert len(error_facts) == 1
        assert "error message" in error_facts[0].payload["stderr"]

    async def test_every_runs_multiple_times(self):
        """With every set, command re-runs after delay."""
        source = Source(
            command='echo "tick"',
            kind="tick",
            observer="every-source",
            every=0.05,
        )

        facts = []
        count = 0
        async for fact in source.stream():
            facts.append(fact)
            count += 1
            if count >= 4:  # Get at least 2 data facts + 2 complete facts
                break

        # Filter for data facts only
        data_facts = [f for f in facts if f.kind == "tick"]
        complete_facts = [f for f in facts if f.kind == "tick.complete"]
        assert len(data_facts) >= 2
        assert len(complete_facts) >= 2

    async def test_no_every_runs_once(self):
        """Without every, command runs exactly once."""
        source = Source(
            command='echo "once"',
            kind="once",
            observer="once-source",
            every=None,
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        # One data fact + one completion fact
        data_facts = [f for f in facts if f.kind == "once"]
        assert len(data_facts) == 1

    async def test_empty_output(self):
        """Command with no output produces only completion fact."""
        source = Source(
            command="true",  # Exits 0, no output
            kind="silent",
            observer="silent-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        # No data facts, just completion
        data_facts = [f for f in facts if f.kind == "silent"]
        assert len(data_facts) == 0
        assert len(facts) == 1
        assert facts[0].kind == "silent.complete"

    async def test_command_with_arguments(self):
        """Commands with arguments work correctly."""
        source = Source(
            command='echo "a b c" | tr " " "\\n"',
            kind="split",
            observer="tr-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "split"]
        assert len(data_facts) == 3
        assert [f.payload["line"] for f in data_facts] == ["a", "b", "c"]


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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
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
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "line"]
        assert len(data_facts) == 3
        assert [f.payload["line"] for f in data_facts] == ["a", "b", "c"]

    async def test_format_json_parses_output(self):
        """format=json parses stdout as JSON, emits single fact."""
        source = Source(
            command='echo \'{"name": "alice", "score": 42}\'',
            kind="data",
            observer="json-source",
            format="json",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"name": "alice", "score": 42}

    async def test_format_json_with_array(self):
        """format=json wraps top-level arrays/scalars into a dict payload."""
        source = Source(
            command='echo \'[1, 2, 3]\'',
            kind="data",
            observer="json-array-source",
            format="json",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"_json": [1, 2, 3]}

        complete_facts = [f for f in facts if f.kind == "data.complete"]
        assert len(complete_facts) == 1

    async def test_format_json_with_scalar(self):
        """format=json wraps top-level scalars into a dict payload."""
        source = Source(
            command="echo 42",
            kind="data",
            observer="json-scalar-source",
            format="json",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"_json": 42}

    async def test_format_ndjson_with_arrays(self):
        """format=ndjson wraps non-object records into a dict payload."""
        source = Source(
            command='printf \'[1, 2]\\n[3, 4]\\n\'',
            kind="data",
            observer="ndjson-array-source",
            format="ndjson",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "data"]
        assert len(data_facts) == 2
        assert [f.payload for f in data_facts] == [{"_json": [1, 2]}, {"_json": [3, 4]}]

    async def test_format_json_invalid_emits_error(self):
        """format=json with invalid JSON emits error fact plus completion."""
        source = Source(
            command='echo "not valid json"',
            kind="data",
            observer="bad-json-source",
            format="json",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        # Error fact + completion fact (command itself succeeded)
        error_facts = [f for f in facts if f.kind == "source.error"]
        assert len(error_facts) == 1
        assert "JSON decode error" in error_facts[0].payload["error"]

    async def test_format_json_with_parse(self):
        """format=json applies parse to the parsed dict.

        Note: Parse ops that work with dicts (Coerce, Transform, Skip with field)
        can be used. Pick/Rename expect lists, so they don't apply to JSON dicts.
        """
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
        async for fact in source.stream():
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
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "blob"]
        assert len(data_facts) == 1
        assert data_facts[0].payload == {"text": "line1\nline2\nline3"}

    async def test_format_blob_preserves_whitespace(self):
        """format=blob preserves all whitespace."""
        source = Source(
            command='printf "  indented\\n\\nempty line above"',
            kind="blob",
            observer="whitespace-source",
            format="blob",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "blob"]
        assert len(data_facts) == 1
        assert data_facts[0].payload["text"] == "  indented\n\nempty line above"

    async def test_format_blob_empty_output(self):
        """format=blob with no output produces only completion fact."""
        source = Source(
            command="true",
            kind="blob",
            observer="empty-blob-source",
            format="blob",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        # No data facts, just completion
        data_facts = [f for f in facts if f.kind == "blob"]
        assert len(data_facts) == 0
        assert len(facts) == 1
        assert facts[0].kind == "blob.complete"


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

    def test_has_stream_method(self):
        """Source has async stream method returning async iterator."""
        source = Source(
            command='echo "test"',
            kind="test",
            observer="test-observer",
        )
        assert hasattr(source, "stream")
        assert callable(source.stream)


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
        async for fact in source.stream():
            facts.append(fact)

        data_facts = [f for f in facts if f.kind == "greeting"]
        assert len(data_facts) == 1
        assert data_facts[0].payload["line"] == "hello"
