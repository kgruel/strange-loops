"""Tests for ``loops store migrate`` — the CLI surface over
``migrate.sidecar.run_migration`` (ratified
``design:arrival-break-slice4-migration-sidecar`` §F, §J.1 WP4).

Covers: (a) end-to-end through the CLI on a synthetic legacy jsonl store —
exit 0, target minted, descriptor updated, resolved location pinned, real read path (stats),
arrival domain signature verification; (b) positional-vs-flag agreement / disagreement;
(c) required --vertex flag; (d) signer capability probe (missing self-key);
(e) already-migrated preflight refusal; (f) multi-line refusal rendering for GF-3;
(g) ``--resume`` requires its argument (deliberate, never inferred).
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from custody import arrival_verifier_for, fact_verifier_for
from engine.arrival import ArrivalLog, content_commitment
from lang import parse_vertex_file
from sign import ed25519

from loops.commands.store import _run_migrate, resolve_canonical_path
from loops.main import main


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

        # F7: resolved store location equals minted target path
        assert resolve_canonical_path(vpath) == target_path

        # Legacy source is never mutated
        assert source.read_bytes() == pre_source_bytes

        # F3: Domain separation pin — report and genesis record verify under arrival_verifier_for
        # and are REFUSED by fact_verifier_for
        arr_verifier, _ = arrival_verifier_for(vpath)
        f_verifier, _ = fact_verifier_for(vpath)
        assert arr_verifier is not None
        assert f_verifier is not None

        # Verify migration report signature under arrival domain
        import rfc8785
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        report_sig = report_data["signature"]
        signed_dict = {k: v for k, v in report_data.items() if k != "signature"}
        report_digest = sha256(rfc8785.dumps(signed_dict)).hexdigest()
        assert arr_verifier("alice", report_sig, report_digest) is True
        assert f_verifier("alice", report_sig, report_digest) is False

        # Verify genesis record signature under arrival domain
        log = ArrivalLog(target_path)
        genesis = log.read(0)
        genesis_digest = content_commitment(
            genesis["k"], genesis["at"], genesis["observer"], genesis["origin"], genesis["body"]
        )
        assert arr_verifier("alice", genesis["sig"], genesis_digest) is True
        assert f_verifier("alice", genesis["sig"], genesis_digest) is False

        # F7: Open migrated store through real CLI read path (store stats via main()) asserting fact count
        capsys.readouterr()  # clear buffer
        rc_stats = main([str(vpath), "store", "stats", "--json"])
        assert rc_stats == 0
        stats_out = json.loads(capsys.readouterr().out)
        assert stats_out["total_facts"] == 2

    def test_migrate_positional_and_flag_agreeing_proceeds(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        rc = _run_migrate(
            [str(source), "--vertex", str(vpath), "--rule", "identity"],
            vertex_path=vpath,
        )
        assert rc == 0
        stdout = capsys.readouterr().out
        assert "migrated" in stdout

    def test_migrate_positional_and_flag_disagreeing_refuses(self, tmp_path, capsys):
        vpath_alice = _make_signed_vertex(tmp_path, name="alice")
        vpath_bob = tmp_path / "bob.vertex"
        vpath_bob.write_text('name "bob"\nstore "./legacy.jsonl"\nloops {\n  concept { fold { items "collect" 100 } }\n}\n')
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        rc = _run_migrate(
            [str(source), "--vertex", str(vpath_bob)],
            vertex_path=vpath_alice,
        )
        assert rc == 2
        stderr = capsys.readouterr().err
        assert "conflicts with --vertex" in stderr
        assert "alice" in stderr and "bob" in stderr
        assert list(tmp_path.glob("*.arrival")) == []

    def test_migrate_requires_vertex_flag(self, tmp_path):
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        with pytest.raises(SystemExit) as excinfo:
            _run_migrate([str(source)], vertex_path=None)
        assert excinfo.value.code == 2

    def test_migrate_refuses_when_keys_dir_exists_but_no_self_key(self, tmp_path, capsys):
        vpath = tmp_path / "alice.vertex"
        content = """name "alice"
store "./legacy.jsonl"

observers {
  alice {
    key "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
  }
}

loops {
  concept { fold { items "collect" 100 } }
}
"""
        vpath.write_text(content, encoding="utf-8")
        # Create keys/bob/ directory with bob's key, but no alice key
        ed25519.load_or_generate(tmp_path / "keys" / "bob")
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        rc = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)
        assert rc == 2
        stderr = capsys.readouterr().err
        assert "no signing key for the vertex's self-observer" in stderr
        # Nothing persisted
        assert list(tmp_path.glob("*.arrival")) == []
        assert list(tmp_path.glob("*.migration-report.json")) == []

    def test_migrate_refuses_already_migrated_vertex(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        # First run succeeds
        rc1 = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)
        assert rc1 == 0
        capsys.readouterr()

        # Second run refuses
        rc2 = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)
        assert rc2 == 2
        stderr = capsys.readouterr().err
        assert "already on an arrival lineage" in stderr
        assert "re-migration would orphan it" in stderr
        assert "deliberate re-migration is a slice-6 ceremony" in stderr
        # Only 1 arrival file exists
        assert len(list(tmp_path.glob("*.arrival"))) == 1

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

        assert rc == 2
        stderr = capsys.readouterr().err
        assert stderr.strip()
        # F5: Multi-line refusal rendering preserves structured lines
        assert len(stderr.strip().splitlines()) >= 4
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

    def test_migrate_refuses_unparseable_vertex(self, tmp_path, capsys):
        vpath = tmp_path / "broken.vertex"
        vpath.write_text("invalid { syntax\n", encoding="utf-8")
        source = _write_jsonl(tmp_path / "legacy.jsonl", [_FACT_SIGNED])

        rc = _run_migrate([str(source), "--vertex", str(vpath)], vertex_path=None)
        assert rc == 2
        stderr = capsys.readouterr().err
        assert "the vertex file cannot be parsed" in stderr
        assert list(tmp_path.glob("*.arrival")) == []
