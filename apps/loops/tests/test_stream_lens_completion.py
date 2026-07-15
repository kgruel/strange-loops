"""Closing the completion-T3 residue note: "--lens on the stream path."

Dissolution finding, not a product change (loops decision
completion/stream-lens-residue-dissolved): ``stream`` is not a registered
top-level command (``registry.VERBS``/``COMMANDS`` has no "stream" entry — see
``apps/loops/CLAUDE.md`` Level 2), so painted's completion walk never reaches
it. Completion is keyed on the FIRST argv token only (``complete_app`` in
``painted/cli/complete.py``): for ``loops read ...`` it always forwards to the
one static parser ``add_read_args`` builds, regardless of what the ``read``
router decides to do with the parsed flags at runtime. Since
``--facts --since``/``--as-of``/``--id`` is exactly the combination that
routes ``read``'s runtime into ``commands/stream.py``'s own local parser
(``cli/views/read.py`` lines 38-48), and ``add_read_args`` already declares
``--lens`` with ``complete_lens`` attached (``cli/read_args.py`` lines 91-96),
TAB on a stream-routed line was never actually blind — it uses read's
completer unconditionally. This test is the live proof: it drives painted's
real ``complete_app`` producer over the loops app's built command roster,
on the exact argv shape that routes to stream at runtime.
"""

import hashlib
from pathlib import Path

import pytest

from atoms import Fact
from engine.sqlite_store import SqliteStore
from lang import parse_vertex_file
from lang.document import genesis_payload


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold_and_absorb(tmp_path: Path) -> Path:
    """Same scaffold shape as ``test_completion_review_remediation.py``."""
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    docs = genesis_payload(parse_vertex_file(vpath))["documents"]
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return vpath


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Isolate cwd/home lens tiers to empty dirs — same shape as
    ``test_lens_completion.py``'s ``isolated`` fixture, so only built-in
    lenses (confluence/graph/horizon/fold) appear in the candidate set.
    """
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return tmp_path


class TestStreamRoutedLensCompletion:
    def test_lens_completes_on_the_facts_since_line_that_routes_to_stream(self, isolated):
        """``loops read project --facts --since 1d --lens <TAB>`` — this exact
        flag combination is what ``cli/views/read.py`` routes into
        ``stream_view.run`` at runtime (``--facts`` + ``--since``). Completion
        still offers every resolvable lens because it never simulates the
        route — it always walks ``add_read_args``'s static parser.
        """
        from painted.cli import complete_app

        from loops.cli.app import _build_commands

        cmds = _build_commands()
        cands = complete_app(
            cmds,
            ["read", "project", "--facts", "--since", "1d", "--lens"],
            "",
            prog="loops",
        )
        values = {c.value for c in cands}
        for name in ("confluence", "graph", "horizon", "fold"):
            assert name in values, f"{name} missing from stream-routed --lens completion"

    def test_lens_completes_on_the_id_line_that_also_routes_to_stream(self, isolated):
        """``--facts --id`` is the other stream-routing combination
        (``cli/views/read.py`` line 38) — same completer, same coverage."""
        from painted.cli import complete_app

        from loops.cli.app import _build_commands

        cmds = _build_commands()
        cands = complete_app(
            cmds,
            ["read", "project", "--facts", "--id", "abc123", "--lens"],
            "",
            prog="loops",
        )
        values = {c.value for c in cands}
        assert "confluence" in values

    def test_stream_runtime_accepts_the_advertised_lens_flag(self, tmp_path):
        """Completion-mirrors-runtime parity: run the REAL stream delegate
        (``commands/stream.py:_run_stream``, the code the ``read`` router
        forwards into) with ``--lens`` on the line. If runtime ever dropped
        or renamed its own ``--lens`` while completion kept advertising it,
        this fails with argparse's "unrecognized arguments" exit — the
        completion-mirrors-runtime violation this task guards against."""
        from loops.commands.stream import _run_stream

        vpath = _scaffold_and_absorb(tmp_path)
        rc = _run_stream(["--since", "1d", "--lens", "confluence"], vertex_path=vpath)
        assert rc == 0
