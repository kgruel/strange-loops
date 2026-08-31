"""Tests for ``loops store migrate`` — the CLI surface over
``migrate.sidecar.run_migration`` (ratified
``design:arrival-break-slice4-migration-sidecar`` §F, §J.1 WP4).

Covers: (a) end-to-end through the CLI on a synthetic legacy jsonl store —
exit 0, target minted, descriptor updated; (b) the GF-3 refusal path — a
mixed-observer batch line refuses before any target bytes exist, no
traceback; (c) ``--resume`` requires its argument (deliberate, never
inferred). Completion/dispatcher lockstep is covered by
``test_store_completion.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lang import parse_vertex_file
from sign import ed25519

from loops.commands.store import _run_migrate


# ---------------------------------------------------------------------------
# State-root isolation — scoped to this module only (apps/loops/tests has no
# existing XDG_STATE_HOME autouse fixture; migrate's head journal reads it
# via ``engine.arrival_head_attestation.heads_dir``, same posture as
# ``libs/migrate/tests/conftest.py``'s autouse fixture).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _make_signed_vertex(tmp_path: Path, name: str = "alice") -> Path:
    """A ``<name>.vertex`` co-located with a flat self-observer keypair.

    The store clause initially points at the legacy source itself — it is
    surgically rewritten onto the minted lineage at publish (§H), so its
    pre-migration value is a placeholder, same posture
    ``libs/migrate/tests/test_sidecar.py::_make_vertex_file`` uses.
    """
    vpath = tmp_path / f"{name}.vertex"
    kp = ed25519.load_or_generate(tmp_path / "keys")
    content = f"""name "{name}"
store "./legacy.jsonl"

observers {{
  {name} {{
    key "{kp.public_b64}"
  }}
}}

loops {{
  concept {{ fold {{ items "collect" 100 }} }}
}}
"""
    vpath.write_text(content, encoding="utf-8")
    return vpath


def _write_jsonl(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


_FACT_SIGNED = {
    "t": "fact", "id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
    "kind": "concept", "ts": 1000.0, "observer": "alice", "origin": "o",
    "payload": '{"text":"one"}', "signature": "sig-alice-1",
}
_FACT_UNSIGNED = {
    "t": "fact", "id": "01ARZ3NDEKTSV4RRFFQ69G5FA1",
    "kind": "concept", "ts": 1001.0, "observer": "alice", "origin": "o",
    "payload": '{"text":"two"}',
}


class TestMigrateEndToEnd:
    def test_migrate_through_cli_mints_lineage_and_updates_descriptor(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        source = _write_jsonl(
            tmp_path / "legacy.jsonl", [_FACT_SIGNED, _FACT_UNSIGNED]
        )
        pre_source_bytes = source.read_bytes()

        rc = _run_migrate(
            [str(source), "--vertex", str(vpath), "--rule", "identity", "--json"],
            vertex_path=None,
        )
        assert rc == 0

        out = json.loads(capsys.readouterr().out)
        target_path = Path(out["target_path"])
        report_path = Path(out["report_path"])
        assert target_path.exists()
        assert report_path.exists()
        assert target_path.name == f"{out['lineage']}.arrival"

        post_ast = parse_vertex_file(vpath)
        assert post_ast.store_backend.name == "file"

        # Legacy source is never mutated
        assert source.read_bytes() == pre_source_bytes

    def test_migrate_refuses_mixed_observer_batch_before_target_exists(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        mixed_batch = {
            "t": "batch",
            "rows": [
                {
                    "t": "fact", "id": "01ARZ3NDEKTSV4RRFFQ69G5FB1",
                    "kind": "concept", "ts": 100.0, "observer": "alice",
                    "origin": "o", "payload": "{}",
                },
                {
                    "t": "fact", "id": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
                    "kind": "concept", "ts": 100.0, "observer": "someone-else",
                    "origin": "o", "payload": "{}",
                },
            ],
        }
        source = _write_jsonl(tmp_path / "legacy.jsonl", [mixed_batch])

        rc = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)

        assert rc != 0
        stderr = capsys.readouterr().err
        assert stderr.strip()
        # No target minted — the refusal fires in the inventory pass, before
        # any target bytes exist (§A.5 / GF-3).
        assert list(tmp_path.glob("*.arrival")) == []
        assert list(tmp_path.glob("*.migration-report.json")) == []

    def test_resume_requires_its_argument(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        with pytest.raises(SystemExit) as excinfo:
            _run_migrate(
                [str(source), "--vertex", str(vpath), "--resume"],
                vertex_path=None,
            )
        assert excinfo.value.code == 2
