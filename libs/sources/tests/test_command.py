"""Tests for CommandSource."""

import asyncio

import pytest

from sources import CommandSource
from specs import Coerce, Pick, Rename, Skip, Split, Transform


class TestCommandSource:
    """Tests for CommandSource behavior."""

    async def test_echo_single_line(self):
        """Single line output becomes single fact."""
        source = CommandSource(
            command='echo "hello"',
            kind="greeting",
            observer="echo-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].kind == "greeting"
        assert facts[0].observer == "echo-source"
        assert facts[0].payload["line"] == "hello"

    async def test_echo_multiple_lines(self):
        """Multiple lines become multiple facts."""
        source = CommandSource(
            command='printf "line1\\nline2\\nline3"',
            kind="output",
            observer="printf-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 3
        assert [f.payload["line"] for f in facts] == ["line1", "line2", "line3"]

    async def test_observer_identity(self):
        """Observer is stamped on all produced facts."""
        source = CommandSource(
            command='echo "test"',
            kind="test",
            observer="my-observer",
        )

        async for fact in source.stream():
            assert fact.observer == "my-observer"

    async def test_command_failure_emits_error_fact(self):
        """Non-zero exit code emits source.error fact."""
        source = CommandSource(
            command="exit 1",
            kind="output",
            observer="fail-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].kind == "source.error"
        assert facts[0].payload["returncode"] == 1
        assert facts[0].observer == "fail-source"

    async def test_command_with_stderr(self):
        """Stderr captured in error fact."""
        source = CommandSource(
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

    async def test_interval_runs_multiple_times(self):
        """With interval set, command re-runs after delay."""
        source = CommandSource(
            command='echo "tick"',
            kind="tick",
            observer="interval-source",
            interval=0.05,
        )

        facts = []
        count = 0
        async for fact in source.stream():
            facts.append(fact)
            count += 1
            if count >= 3:
                break

        assert len(facts) >= 3
        assert all(f.kind == "tick" for f in facts)

    async def test_no_interval_runs_once(self):
        """Without interval, command runs exactly once."""
        source = CommandSource(
            command='echo "once"',
            kind="once",
            observer="once-source",
            interval=None,
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 1

    async def test_empty_output(self):
        """Command with no output produces no facts."""
        source = CommandSource(
            command="true",  # Exits 0, no output
            kind="silent",
            observer="silent-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 0

    async def test_command_with_arguments(self):
        """Commands with arguments work correctly."""
        source = CommandSource(
            command='echo "a b c" | tr " " "\\n"',
            kind="split",
            observer="tr-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 3
        assert [f.payload["line"] for f in facts] == ["a", "b", "c"]


class TestCommandSourceParse:
    """Tests for CommandSource with parse parameter."""

    async def test_parse_basic_pipeline(self):
        """Parse pipeline transforms line into structured payload."""
        source = CommandSource(
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

        assert len(facts) == 1
        assert facts[0].payload == {"name": "alice", "id": 1234, "score": 95.5}

    async def test_parse_skip_header(self):
        """Skip primitive filters out header lines."""
        source = CommandSource(
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

        assert len(facts) == 2
        assert facts[0].payload == {"name": "alice", "id": 1}
        assert facts[1].payload == {"name": "bob", "id": 2}

    async def test_parse_skip_by_field(self):
        """Skip can filter based on parsed field value."""
        source = CommandSource(
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

        assert len(facts) == 1
        assert facts[0].payload == {"name": "proc2", "cpu": "50"}

    async def test_parse_failed_coercion_skips_line(self):
        """Lines that fail coercion are skipped (None from pipeline)."""
        source = CommandSource(
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

        assert len(facts) == 2
        assert facts[0].payload == {"label": "valid", "value": 42}
        assert facts[1].payload == {"label": "also_valid", "value": 99}

    async def test_parse_transform_then_coerce(self):
        """Transform strips characters before coercion."""
        source = CommandSource(
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

        assert len(facts) == 1
        assert facts[0].payload == {"name": "disk1", "usage": 75}

    async def test_no_parse_uses_line_payload(self):
        """Without parse, payload is {"line": text}."""
        source = CommandSource(
            command='echo "raw text"',
            kind="raw",
            observer="no-parse-source",
        )

        facts = []
        async for fact in source.stream():
            facts.append(fact)

        assert len(facts) == 1
        assert facts[0].payload == {"line": "raw text"}

    async def test_parse_pick_subset(self):
        """Pick selects only specific fields."""
        source = CommandSource(
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

        assert len(facts) == 1
        assert facts[0].payload == {"first": "a", "third": "c", "fifth": "e"}


class TestCommandSourceProtocol:
    """Verify CommandSource satisfies Source protocol."""

    def test_has_observer_property(self):
        """CommandSource has observer property."""
        source = CommandSource(
            command='echo "test"',
            kind="test",
            observer="test-observer",
        )
        assert source.observer == "test-observer"

    def test_has_stream_method(self):
        """CommandSource has async stream method returning async iterator."""
        source = CommandSource(
            command='echo "test"',
            kind="test",
            observer="test-observer",
        )
        assert hasattr(source, "stream")
        # stream() returns an async generator, verify it's callable
        assert callable(source.stream)
