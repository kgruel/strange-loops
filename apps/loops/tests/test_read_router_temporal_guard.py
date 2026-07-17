"""Tests for cli.views.read — temporal flags must never silently drop.

Guards friction:as-of-silent-drop-on-fold-path: the read router's
pre-parser consumes --since/--as-of/--id and re-injects them only for the
stream (--facts + temporal) and ticks routes. On the default fold route
they used to vanish — ``sl read project --as-of X`` rendered head state
with exit 0, a silent anachronism against SPEC §9.3's honesty posture.

0.8.0 (temporal-cursor, C1) closes the gap for two of the three: --at
(witness cursor) and --as-of (event-time projection) are now honored
directly on the fold route (A11) — mutually exclusive with each other.
--since and --id still have no fold-route meaning and stay refused,
teaching --facts/--ticks AND the two new cursor flags.
"""

from __future__ import annotations

from unittest import mock

import pytest

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view


def ctx(reporter: BufferReporter | None = None) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter())


class TestFoldRouteRefusesTemporalFlags:
    @pytest.mark.parametrize(
        "argv",
        [
            ["project", "--since", "7d"],
            ["project", "--id", "01ARZ3NDEKTSV4RRFFQ69G5FAV"],
            ["project", "--since", "7d", "--as-of", "30d"],
        ],
    )
    def test_bare_temporal_flag_errors(self, argv):
        reporter = BufferReporter()
        rc = read_view.run(argv, ctx(reporter))
        assert rc == 2
        err = "\n".join(reporter.err_lines)
        assert "cannot honor" in err
        assert "--facts" in err  # points at the supported spelling
        assert "--at" in err and "--as-of" in err  # and the cursor flags

    def test_error_names_the_flag(self):
        reporter = BufferReporter()
        read_view.run(["project", "--since", "7d"], ctx(reporter))
        assert "--since" in "\n".join(reporter.err_lines)

    def test_at_and_as_of_together_refused(self):
        reporter = BufferReporter()
        rc = read_view.run(["project", "--at", "head", "--as-of", "30d"], ctx(reporter))
        assert rc == 2
        err = "\n".join(reporter.err_lines)
        assert "mutually exclusive" in err

    def test_ticks_with_at_refused(self):
        reporter = BufferReporter()
        rc = read_view.run(["project", "--ticks", "--at", "head"], ctx(reporter))
        assert rc == 2
        assert "fold route only" in "\n".join(reporter.err_lines)


class TestTemporalRoutesStillCarryTheCursor:
    def test_facts_since_routes_to_stream_with_flag(self):
        c = ctx()
        with mock.patch("loops.cli.views.stream.run", return_value=0) as m:
            rc = read_view.run(["project", "--facts", "--since", "7d"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--since" in argv and "7d" in argv

    def test_facts_as_of_routes_to_stream_with_flag(self):
        c = ctx()
        with mock.patch("loops.cli.views.stream.run", return_value=0) as m:
            rc = read_view.run(["project", "--facts", "--as-of", "30d"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--as-of" in argv and "30d" in argv

    def test_ticks_as_of_routes_to_ticks_with_flag(self):
        c = ctx()
        with mock.patch("loops.cli.views.ticks.run", return_value=0) as m:
            rc = read_view.run(["project", "--ticks", "--as-of", "30d"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--as-of" in argv and "30d" in argv

    def test_plain_fold_read_unaffected(self):
        c = ctx()
        with mock.patch("loops.cli.views.fold.run", return_value=0) as m:
            rc = read_view.run(["project"], c)
        assert rc == 0
        assert m.called

    def test_facts_without_temporal_flag_still_folds(self):
        c = ctx()
        with mock.patch("loops.cli.views.fold.run", return_value=0) as m:
            rc = read_view.run(["project", "--facts"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--facts" in argv

    def test_bare_as_of_routes_to_fold_with_flag(self):
        # 0.8.0: --as-of alone (no --facts/--ticks) is the fold-route
        # event-time projection — no longer refused.
        c = ctx()
        with mock.patch("loops.cli.views.fold.run", return_value=0) as m:
            rc = read_view.run(["project", "--as-of", "30d"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--as-of" in argv and "30d" in argv

    def test_at_routes_to_fold_with_flag(self):
        c = ctx()
        with mock.patch("loops.cli.views.fold.run", return_value=0) as m:
            rc = read_view.run(["project", "--at", "head"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--at" in argv and "head" in argv
