"""Cut B gate oracle — G1 and G2, re-runnable, independent of the slice's own tests.

Written by the gate, not by the implementer. It asserts the two gate items
from the design fact directly rather than trusting either the implementation
report or the suites the implementation shipped:

* **G1** — re-derivation reproduces every rowid, so an outstanding
  ``WitnessPosition`` re-resolves to the same ``(rowid, seq)``. Probed on a
  store built through the arrival write path AND on a store that received a
  merge, because the merged case is the one whose premise (the index carries
  rows from no source but the log) cut B's merge rewrite establishes.
* **G2** — the git merge driver, proven by performing real ``git merge``
  runs in a throwaway fixture repo built here. Never against a real checkout
  or a live ``.loops/`` store.

Run from the worktree root::

    .venv/bin/python docs/scratch/arrival-sliceB/gate_oracle.py

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "libs" / "engine"))

from atoms import Fact  # noqa: E402
from lang import parse_vertex  # noqa: E402
from lang.document import (  # noqa: E402
    DECL_KIND_DEFINED,
    DECL_KIND_RETIRED,
    Change,
    vertex_to_documents,
)

from engine.arrival import ArrivalLog  # noqa: E402
from engine.arrival_projection import (  # noqa: E402
    canonical_line,
    rederive_projections,
    sort_key,
    write_derived_log,
)
from engine.arrival_store import ArrivalStore  # noqa: E402
from engine.tick import Tick  # noqa: E402
from engine.witness import durable_handle, resolve_witness_position  # noqa: E402
from tests.conftest import Custodian  # noqa: E402

VERTEX = (
    'name "x"\nstore "./s.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n'
    '  b { fold { n "inc" } }\n}\n'
)

_checks = 0


def check(cond: bool, what: str) -> None:
    global _checks
    _checks += 1
    if not cond:
        raise AssertionError(f"FAILED: {what}")
    print(f"  ok  {what}")


def _tick_signer(digest: str) -> str:
    return hashlib.sha256(digest.encode()).hexdigest()


def build_store(dirpath: Path, keys, *, note_prefix: str = "n") -> tuple[ArrivalLog, Path]:
    """An arrival store with facts, two chained ticks and a declaration
    ceremony — every row authored through the arrival write path."""
    log = ArrivalLog.mint(
        dirpath / "s.arrival", observer="kyle", signer=keys.signer, key=keys.public
    )
    store = ArrivalStore(
        path=dirpath / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=keys.signer,
        tick_signer=_tick_signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message=f"{note_prefix}-one"))
        store.append(Fact.of("note", "kyle", message=f"{note_prefix}-two"))
        store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(VERTEX))],
            observer="kyle",
            fact_signer=keys.signer,
        )
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
        )
        # A two-row ceremony rides as ONE batch record — the receipt group
        # whose contiguity has to survive a re-derivation.
        store.absorb_edit(
            [
                Change(kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0},
                       annotation="modified"),
                Change(kind=DECL_KIND_RETIRED, subject="b", payload=None,
                       annotation="removed"),
            ],
            observer="kyle",
            fact_signer=keys.signer,
        )
        store.append(Fact.of("note", "kyle", message=f"{note_prefix}-three"))
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 2}, origin="t")
        )
    finally:
        store.close()
    return log, dirpath / "s.db"


def rowid_snapshot(db: Path) -> dict:
    conn = sqlite3.connect(str(db))
    try:
        return {
            "facts": conn.execute("SELECT rowid, id FROM facts ORDER BY rowid").fetchall(),
            "ticks": conn.execute("SELECT rowid, id FROM ticks ORDER BY rowid").fetchall(),
        }
    finally:
        conn.close()


def position_snapshot(db: Path) -> dict:
    conn = sqlite3.connect(str(db))
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY rowid")]
    finally:
        conn.close()
    out = {}
    for fid in ids:
        p = resolve_witness_position(db, fid, group_boundary="allow")
        out[fid] = (p.rowid, p.seq, p.lineage, durable_handle(p))
    return out


# ---------------------------------------------------------------------------
# G1
# ---------------------------------------------------------------------------


def g1_written_store(tmp: Path) -> None:
    print("\nG1a — a store built through the arrival write path")
    d = tmp / "g1a"
    d.mkdir()
    keys = Custodian(d, "kyle")
    log, db = build_store(d, keys)

    before_rows = rowid_snapshot(db)
    before_pos = position_snapshot(db)
    check(len(before_rows["facts"]) >= 6, f"fixture is not vacuous: {len(before_rows['facts'])} fact rows")
    check(len(before_rows["ticks"]) == 2, "fixture carries two ticks")
    kinds = [r["k"] for r in log.walk()]
    check("batch" in kinds, f"the ceremony really landed as a batch record: {kinds}")

    result = rederive_projections(log.path)
    after_rows = rowid_snapshot(db)
    after_pos = position_snapshot(db)

    check(after_rows == before_rows, "every (rowid, id) pair is identical across re-derivation")
    check(after_pos == before_pos, "every WitnessPosition re-resolves to the same (rowid, seq, lineage, handle)")
    check(result.records > 0 and result.facts == len(before_rows["facts"]),
          f"the re-derivation reports what it replayed: {result.records} records, {result.facts} facts")


def g1_merged_store(tmp: Path) -> None:
    print("\nG1b — a store that RECEIVED A MERGE (the premise cut B establishes)")
    from store import merge_store

    d = tmp / "g1b"
    d.mkdir()
    tgt_dir, src_dir = d / "target", d / "source"
    tgt_dir.mkdir()
    src_dir.mkdir()
    tkeys = Custodian(tgt_dir, "kyle")
    skeys = Custodian(src_dir, "kyle")
    tlog, tdb = build_store(tgt_dir, tkeys, note_prefix="t")
    slog, sdb = build_store(src_dir, skeys, note_prefix="s")

    res = merge_store(tdb, sdb)
    check(res.facts_added > 0, f"the merge actually moved rows: {res}")

    before_rows = rowid_snapshot(tdb)
    before_pos = position_snapshot(tdb)
    rederive_projections(tlog.path)
    check(rowid_snapshot(tdb) == before_rows,
          "a MERGED store's (rowid, id) pairs survive re-derivation")
    check(position_snapshot(tdb) == before_pos,
          "a MERGED store's witness positions survive re-derivation")

    # The premise itself, asserted directly: the index holds exactly the rows
    # the log accounts for, so nothing reached it except by derivation.
    from engine.arrival_projection import rows_of_record

    from_log = {row[0] for rec in ArrivalLog(tlog.path).walk() for _t, row in rows_of_record(rec)}
    conn = sqlite3.connect(str(tdb))
    try:
        in_index = {r[0] for tbl in ("facts", "ticks")
                    for r in conn.execute(f"SELECT id FROM {tbl}")}
    finally:
        conn.close()
    check(from_log == in_index,
          f"the index carries rows from no source but the log ({len(in_index)} ids)")


# ---------------------------------------------------------------------------
# G2
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check_rc: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        HOME=str(repo.parent / "fakehome"),
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_AUTHOR_NAME="gate", GIT_AUTHOR_EMAIL="gate@example.invalid",
        GIT_COMMITTER_NAME="gate", GIT_COMMITTER_EMAIL="gate@example.invalid",
    )
    p = subprocess.run(["git", "-C", str(repo), *args], env=env,
                       capture_output=True, text=True)
    if check_rc and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
    return p


def _fresh_derivation(lines: set[str]) -> bytes:
    """A fresh canonical derivation of a line SET — the same grammar and the
    same order a store's own derivation uses, imported rather than restated."""
    return "".join(ln + "\n" for ln in sorted({canonical_line(x) for x in lines}, key=sort_key)).encode()


def _build_side(dirpath: Path, keys, prefix: str, extra: list[str]) -> Path:
    log, _db = build_store(dirpath, keys, note_prefix=prefix)
    store = ArrivalStore(
        path=dirpath / "s.db", serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict, fact_signer=keys.signer, tick_signer=_tick_signer,
    )
    try:
        for msg in extra:
            store.append(Fact.of("note", "kyle", message=msg))
    finally:
        store.close()
    write_derived_log(log.path)
    return dirpath / "s.jsonl"


def g2_git_merge(tmp: Path) -> None:
    print("\nG2 — a REAL git merge in a throwaway fixture repo")
    d = tmp / "g2"
    d.mkdir()
    (d / "fakehome").mkdir()
    repo = d / "repo"
    repo.mkdir()
    driver = f'"{sys.executable}" -m store.derived_log_merge %O %A %B'

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "gate")
    _git(repo, "config", "user.email", "gate@example.invalid")
    # Registration lives in the FIXTURE repo only — cut B adds no repo-root
    # .gitattributes, which is exactly why the gate must register its own.
    (repo / ".gitattributes").write_text("*.jsonl merge=loops-derived-log\n")
    _git(repo, "config", "merge.loops-derived-log.name", "loops derived log")
    _git(repo, "config", "merge.loops-derived-log.driver", driver)

    base_dir = d / "base"
    base_dir.mkdir()
    bkeys = Custodian(base_dir, "kyle")
    base_jsonl = _build_side(base_dir, bkeys, "b", [])
    shutil.copy2(base_jsonl, repo / "log.jsonl")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    base_lines = set((repo / "log.jsonl").read_text().splitlines())

    def side(name: str, extra: list[str]) -> set[str]:
        sd = d / name
        shutil.copytree(base_dir, sd)
        store = ArrivalStore(
            path=sd / "s.db", serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict, fact_signer=bkeys.signer,
            tick_signer=_tick_signer,
        )
        try:
            for msg in extra:
                store.append(Fact.of("note", "kyle", message=msg))
        finally:
            store.close()
        write_derived_log(sd / "s.arrival")
        return set((sd / "s.jsonl").read_text().splitlines())

    left_lines = side("left", ["left-1", "left-2"])
    right_lines = side("right", ["right-1", "right-2"])
    check(left_lines != right_lines and base_lines < left_lines and base_lines < right_lines,
          "the two sides genuinely diverged above a shared base")

    def commit_branch(branch: str, start: str, lines: set[str], msg: str) -> None:
        _git(repo, "checkout", "-q", start)
        p = _git(repo, "checkout", "-q", "-b", branch, check_rc=False)
        if p.returncode != 0:
            _git(repo, "checkout", "-q", branch)
        (repo / "log.jsonl").write_bytes(_fresh_derivation(lines))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", msg)

    commit_branch("left", "main", left_lines, "left")
    commit_branch("right", "main", right_lines, "right")

    # --- case 1: clean union -------------------------------------------
    _git(repo, "checkout", "-q", "left")
    p = _git(repo, "merge", "--no-edit", "right", check_rc=False)
    check(p.returncode == 0, f"clean union: git merge exits 0 (rc={p.returncode})\n{p.stdout}{p.stderr}")
    merged = (repo / "log.jsonl").read_bytes()
    check(merged == _fresh_derivation(left_lines | right_lines),
          "clean union: the merged file is BYTE-IDENTICAL to a fresh derivation of the union")

    # --- the false-driver control --------------------------------------
    # git's own textual three-way merge can produce the right union by luck,
    # so a content assertion alone would not prove the driver ran.
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _git(repo, "config", "merge.loops-derived-log.driver", "false")
    p = _git(repo, "merge", "--no-edit", "right", check_rc=False)
    check(p.returncode != 0,
          f"FALSE-DRIVER CONTROL: with the driver replaced by `false` the same merge FAILS (rc={p.returncode}) — the driver really ran")
    _git(repo, "merge", "--abort", check_rc=False)
    _git(repo, "config", "merge.loops-derived-log.driver", driver)

    # --- case 2: same id, different bytes ------------------------------
    conflict = set(sorted(right_lines - base_lines))
    victim = sorted(left_lines - base_lines)[0]
    import json as _json

    obj = _json.loads(victim)
    obj["payload"] = _json.dumps({"message": "tampered"})
    tampered = canonical_line(_json.dumps(obj))
    check(tampered != victim, "the tampered line really differs in bytes")

    commit_branch("left2", "main", left_lines, "left2")
    commit_branch("right2", "main", (left_lines - {victim}) | {tampered} | conflict, "right2")
    _git(repo, "checkout", "-q", "left2")
    p = _git(repo, "merge", "--no-edit", "right2", check_rc=False)
    check(p.returncode != 0,
          f"same id / different bytes: git merge exits NON-ZERO (rc={p.returncode})")
    _git(repo, "merge", "--abort", check_rc=False)

    # --- case 3: a line present in base, lost on one side --------------
    # The losing branch must ALSO add a line, or git resolves a one-sided
    # change without ever invoking a driver.
    lost = sorted(base_lines)[0]
    commit_branch("left3", "main", left_lines, "left3")
    commit_branch("right3", "main", (base_lines - {lost}) | conflict, "right3")
    _git(repo, "checkout", "-q", "left3")
    p = _git(repo, "merge", "--no-edit", "right3", check_rc=False)
    check(p.returncode != 0,
          f"loss against base: git merge exits NON-ZERO (rc={p.returncode})")
    _git(repo, "merge", "--abort", check_rc=False)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        g1_written_store(tmp)
        g1_merged_store(tmp)
        g2_git_merge(tmp)
    print(f"\nGATE ORACLE: all {_checks} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
