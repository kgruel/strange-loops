"""The probe classification matrix under the arrival mode.

The half-migrated store — a ``.db`` with BOTH an ``.arrival`` and a
``.jsonl`` sibling — is the one configuration cut A could use to silently
mint two custody holders (design §4.2). Law 1 makes arrival the only
available answer, so it is pinned here from all three entry points: the
``.db``, the ``.jsonl``, and the ``.arrival``.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from engine.arrival import ArrivalLog
from engine.probe import probe_target

_KEY = base64.b64encode(b"k" * 32).decode()


def _sign(observer: str, commitment: str) -> str:
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


def _mint(tmp_path: Path) -> Path:
    return ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY
    ).path


# --- the .arrival arm --------------------------------------------------------


def test_an_arrival_locator_probes_as_arrival_log_even_when_absent(tmp_path):
    info = probe_target(tmp_path / "s.arrival")
    assert info.target_type == "arrival_log"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == tmp_path / "s.arrival"
    assert info.index_path == tmp_path / "s.db"
    assert info.exists is False
    assert info.index_current is None


def test_a_minted_arrival_log_probes_with_content_corroboration(tmp_path):
    path = _mint(tmp_path)
    info = probe_target(path)
    assert info.target_type == "arrival_log"
    assert info.exists is True
    assert "does not decode" not in info.reason
    # no index yet: current and absent must not collapse
    assert info.index_current is False


def test_content_that_is_not_arrival_records_is_noted_not_verdicted(tmp_path):
    path = tmp_path / "s.arrival"
    path.write_text('{"nope": 1}\n')
    info = probe_target(path)
    assert info.target_type == "arrival_log"  # the suffix classifies
    assert "does not decode as arrival records" in info.reason


def test_probing_never_creates_anything(tmp_path):
    path = _mint(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    probe_target(path)
    probe_target(tmp_path / "s.db")
    probe_target(tmp_path / "s.jsonl")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# --- the half-migrated store, from all three entry points --------------------


def _half_migrated(tmp_path: Path) -> None:
    _mint(tmp_path)
    (tmp_path / "s.jsonl").write_text("")
    (tmp_path / "s.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)


def test_a_db_with_an_arrival_sibling_is_a_derived_index_over_arrival(tmp_path):
    _mint(tmp_path)
    (tmp_path / "s.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
    info = probe_target(tmp_path / "s.db")
    assert info.target_type == "derived_index"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == tmp_path / "s.arrival"
    assert info.writable is False


def test_half_migrated_db_arrival_wins_and_the_legacy_log_is_named(tmp_path):
    _half_migrated(tmp_path)
    info = probe_target(tmp_path / "s.db")
    assert info.target_type == "derived_index"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == tmp_path / "s.arrival"
    assert "projection" in info.reason


def test_half_migrated_jsonl_classifies_as_a_projection_not_a_store(tmp_path):
    _half_migrated(tmp_path)
    info = probe_target(tmp_path / "s.jsonl")
    assert info.target_type == "derived_log"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == tmp_path / "s.arrival"
    assert info.writable is False


def test_half_migrated_arrival_probes_as_the_store(tmp_path):
    _half_migrated(tmp_path)
    info = probe_target(tmp_path / "s.arrival")
    assert info.target_type == "arrival_log"
    assert info.canonical_mode == "arrival"


def test_exactly_one_custody_holder_across_the_whole_matrix(tmp_path):
    """The claim behind the matrix: however the half-migrated store is
    probed, every answer names the SAME canonical artifact."""
    _half_migrated(tmp_path)
    canonicals = {
        probe_target(tmp_path / name).canonical_path
        for name in ("s.arrival", "s.jsonl", "s.db")
    }
    assert canonicals == {tmp_path / "s.arrival"}


# --- the legacy arms are undisturbed -----------------------------------------


def test_a_jsonl_with_no_arrival_sibling_stays_a_jsonl_log(tmp_path):
    (tmp_path / "s.jsonl").write_text("")
    info = probe_target(tmp_path / "s.jsonl")
    assert info.target_type == "jsonl_log"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == tmp_path / "s.jsonl"


def test_a_db_with_a_jsonl_sibling_stays_a_jsonl_derived_index(tmp_path):
    (tmp_path / "s.jsonl").write_text("")
    (tmp_path / "s.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
    info = probe_target(tmp_path / "s.db")
    assert info.target_type == "derived_index"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == tmp_path / "s.jsonl"


def test_a_bare_db_stays_sqlite_canonical(tmp_path):
    (tmp_path / "s.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
    info = probe_target(tmp_path / "s.db")
    assert info.target_type == "sqlite_store"
    assert info.canonical_mode == "sqlite"


# --- vertex targets ----------------------------------------------------------


def test_a_vertex_declaring_an_arrival_store_reports_the_arrival_mode(tmp_path):
    vertex = tmp_path / "t.vertex"
    vertex.write_text(
        'name "t"\nstore "s.arrival"\n\nloops {\n'
        '  note { fold { items "collect" 10 } }\n}\n'
    )
    _mint(tmp_path)
    info = probe_target(vertex)
    assert info.target_type == "vertex"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == tmp_path / "s.arrival"
    assert info.index_path == tmp_path / "s.db"
    assert info.index_current is False  # log minted, index not built
