"""Tests for cli.views.read — temporal flags must never silently drop.

Guards friction:as-of-silent-drop-on-fold-path: the read router's
pre-parser consumes --since/--as-of/--id and re-injects them only for the
stream (--facts + temporal) and ticks routes. On the default fold route
they used to vanish — ``sl read project --as-of X`` rendered head state
with exit 0, a silent anachronism against SPEC §9.3's honesty posture.

Until fold-state-as-of ships (0.8.0 temporal-cursor work), the router
refuses: exit 2 + a reporter error naming the supported spellings.
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
            ["project", "--as-of", "30d"],
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

    def test_error_names_the_flag(self):
        reporter = BufferReporter()
        read_view.run(["project", "--as-of", "30d"], ctx(reporter))
        assert "--as-of" in "\n".join(reporter.err_lines)


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
