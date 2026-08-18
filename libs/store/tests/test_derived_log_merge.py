"""The derived-log git merge driver — gate item 2 of cut B.

decision:design/arrival-sliceB-projections §Q3. The proof shape the design
names is an ACTUAL ``git merge``: a fixture repo, the driver registered
through that repo's own ``.gitattributes`` and config, and assertions on the
real subprocess return codes.

The fixture repo is isolated from the developer's git configuration
(``HOME`` inside ``tmp_path``, global and system config pointed at
``/dev/null``) so a personal hook, template or signing setting cannot decide
whether this gate passes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_projection import derived_lines, write_derived_log
from store.derived_log_merge import (
    DerivedLogMergeConflict,
    merge_derived_log,
)

# Shape-valid founding key + a deterministic stand-in signer. Nothing in this
# suite verifies a signature — mint checks the key's SHAPE only, so the store
# lib's tests need no crypto dependency.
_STUB_KEY = __import__("base64").b64encode(b"k" * 32).decode()


def _sign(observer: str, commitment: str) -> str:
    import hashlib

    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


def _fact(ident: str, message: str) -> dict:
    return {
        "t": "fact",
        "id": ident,
        "kind": "note",
        "ts": 1.0,
        "observer": "kyle",
        "origin": "",
        "payload": json.dumps({"message": message}),
    }


def _mint(path: Path) -> ArrivalLog:
    return ArrivalLog.mint(path, observer="kyle", signer=_sign, key=_STUB_KEY)


def _store_with(path: Path, facts: list[tuple[str, str]]) -> Path:
    """An arrival log carrying ``facts``, with its derived log materialized."""
    log = _mint(path)
    for ident, message in facts:
        log.append("fact", _fact(ident, message), observer="kyle")
    write_derived_log(path)
    return path.with_suffix(".jsonl")


# --- the driver in isolation -------------------------------------------------


def test_a_clean_union_is_the_line_set_of_both_sides(tmp_path):
    ours = _store_with(tmp_path / "a.arrival", [("01A", "a"), ("01SHARED", "s")])
    theirs = _store_with(tmp_path / "b.arrival", [("01SHARED", "s"), ("01B", "b")])
    base = _store_with(tmp_path / "o.arrival", [("01SHARED", "s")])

    # Captured BEFORE the merge: the driver rewrites `ours` in place, so
    # reading it afterwards and comparing to itself would assert nothing.
    our_lines = set(ours.read_text().splitlines())
    their_lines = set(theirs.read_text().splitlines())

    result = merge_derived_log(base, ours, theirs)

    assert set(ours.read_text().splitlines()) == our_lines | their_lines
    assert result.lines == 3 and result.shared == 1


def test_the_output_is_byte_identical_to_a_fresh_derivation(tmp_path):
    """The property that makes the driver safe: nothing it writes could not
    have come out of a re-derivation of the merged store."""
    ours = _store_with(tmp_path / "a.arrival", [("01A", "a"), ("01C", "c")])
    theirs = _store_with(tmp_path / "b.arrival", [("01B", "b"), ("01C", "c")])
    base = _store_with(tmp_path / "o.arrival", [("01C", "c")])

    merge_derived_log(base, ours, theirs)

    # A store that actually holds the union, derived from scratch.
    union = _mint(tmp_path / "u.arrival")
    for ident, message in [("01A", "a"), ("01B", "b"), ("01C", "c")]:
        union.append("fact", _fact(ident, message), observer="kyle")
    fresh = derived_lines(union)

    assert ours.read_text() == "".join(line + "\n" for line in fresh)


def test_output_is_byte_sorted(tmp_path):
    ours = _store_with(tmp_path / "a.arrival", [("01Z", "z"), ("01A", "a")])
    theirs = _store_with(tmp_path / "b.arrival", [("01M", "m")])
    merge_derived_log(tmp_path / "missing.jsonl", ours, theirs)
    raw = ours.read_bytes().splitlines()
    assert raw == sorted(raw) and len(raw) == 3


def test_same_id_different_bytes_refuses(tmp_path):
    """A custody contradiction: at most one of them is what an arrival log
    says. Picking a side would re-mint the silent overwrite this cut
    removes."""
    ours = _store_with(tmp_path / "a.arrival", [("01SAME", "our version")])
    theirs = _store_with(tmp_path / "b.arrival", [("01SAME", "their version")])

    with pytest.raises(DerivedLogMergeConflict, match="01SAME"):
        merge_derived_log(tmp_path / "missing.jsonl", ours, theirs)


def test_a_line_lost_against_base_refuses(tmp_path):
    """A projection of an append-only log cannot lose a line. If one side
    did, that side's log was rewritten — and refusing is the only
    non-destructive answer."""
    base = _store_with(tmp_path / "o.arrival", [("01KEEP", "k"), ("01LOST", "l")])
    ours = _store_with(tmp_path / "a.arrival", [("01KEEP", "k")])  # dropped 01LOST
    theirs = _store_with(
        tmp_path / "b.arrival", [("01KEEP", "k"), ("01LOST", "l"), ("01NEW", "n")]
    )

    with pytest.raises(DerivedLogMergeConflict, match="01LOST"):
        merge_derived_log(base, ours, theirs)


def test_an_absent_base_is_the_ordinary_new_file_merge(tmp_path):
    ours = _store_with(tmp_path / "a.arrival", [("01A", "a")])
    theirs = _store_with(tmp_path / "b.arrival", [("01B", "b")])
    result = merge_derived_log(tmp_path / "nothing-here.jsonl", ours, theirs)
    assert result.lines == 2


def test_a_batch_line_unions_by_every_id_it_carries(tmp_path):
    """A batch line has no single id, so the key is the ROW id and every id
    inside a batch maps to the whole line. A row that is a plain fact on one
    side and rides inside a batch on the other is then a DETECTED divergence
    rather than a silent duplicate."""
    from engine.jsonl_codec import serialize_batch

    plain = _mint(tmp_path / "a.arrival")
    plain.append("fact", _fact("01INBATCH", "x"), observer="kyle")
    write_derived_log(tmp_path / "a.arrival")
    ours = tmp_path / "a.jsonl"

    batched = _mint(tmp_path / "b.arrival")
    rows = [
        ("01INBATCH", "note", 1.0, "kyle", "", json.dumps({"message": "x"}), None),
        ("01OTHER", "note", 1.0, "kyle", "", json.dumps({"message": "y"}), None),
    ]
    batched.append("batch", json.loads(serialize_batch(rows)), observer="kyle")
    write_derived_log(tmp_path / "b.arrival")
    theirs = tmp_path / "b.jsonl"

    with pytest.raises(DerivedLogMergeConflict, match="01INBATCH"):
        merge_derived_log(tmp_path / "missing.jsonl", ours, theirs)


def test_the_driver_never_opens_a_store_or_touches_an_arrival_log(tmp_path):
    """NON-NEGOTIABLE. It reads three files and writes one — so it works
    with no store and no arrival log anywhere near it."""
    ours = tmp_path / "ours.jsonl"
    theirs = tmp_path / "theirs.jsonl"
    ours.write_text(json.dumps(_fact("01A", "a"), separators=(",", ":")) + "\n")
    theirs.write_text(json.dumps(_fact("01B", "b"), separators=(",", ":")) + "\n")

    merge_derived_log(tmp_path / "no-base", ours, theirs)

    assert len(ours.read_text().splitlines()) == 2
    assert not list(tmp_path.glob("*.arrival"))
    assert not list(tmp_path.glob("*.db"))


def test_a_torn_tail_is_dropped_rather_than_parsed(tmp_path):
    ours = _store_with(tmp_path / "a.arrival", [("01A", "a"), ("01C", "c")])
    theirs = _store_with(tmp_path / "b.arrival", [("01B", "b")])
    whole = ours.read_bytes()
    ours.write_bytes(whole[: len(whole) - 10])  # chop mid-line

    result = merge_derived_log(tmp_path / "no-base", ours, theirs)

    assert result.lines == 2  # the surviving whole line plus theirs


# --- an actual git merge (gate item 2) ---------------------------------------


def _git_env(home: Path) -> dict:
    """A git environment isolated from the developer's own configuration.

    A personal hook, commit template or signing setting must not be able to
    decide whether this gate passes.
    """
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
    )
    return env


def _git(repo: Path, *args: str, env: dict, check: bool = True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
    )
    if check:
        assert result.returncode == 0, (
            f"git {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


@pytest.fixture
def fixture_repo(tmp_path):
    """A git repo with the driver registered — IN THE FIXTURE REPO ONLY.

    NON-NEGOTIABLE: cut B adds no repo-root ``.gitattributes`` and changes no
    ``.gitignore`` line. Registration rides wave 2, so the driver is wired
    here, in a throwaway repo, exactly as a user would wire it.
    """
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env(home)

    _git(repo, "init", "-q", "-b", "main", env=env)
    _git(repo, "config", "user.name", "Test", env=env)
    _git(repo, "config", "user.email", "test@example.invalid", env=env)
    _git(repo, "config", "commit.gpgsign", "false", env=env)
    (repo / ".gitattributes").write_text("*.jsonl merge=loops-derived-log\n")
    _git(
        repo,
        "config",
        "merge.loops-derived-log.driver",
        f"{sys.executable} -m store.derived_log_merge %O %A %B",
        env=env,
    )
    _git(repo, "config", "merge.loops-derived-log.name", "loops derived log", env=env)
    return repo, env


def _commit_store(repo, env, name, facts, message):
    """Derive a store's projection INTO the repo and commit it."""
    log_path = repo / f"{name}.arrival"
    if log_path.exists():
        log = ArrivalLog(log_path)
    else:
        log = _mint(log_path)
    for ident, text in facts:
        log.append("fact", _fact(ident, text), observer="kyle")
    write_derived_log(log_path)
    _git(repo, "add", f"{name}.jsonl", ".gitattributes", env=env)
    _git(repo, "commit", "-q", "-m", message, env=env)


def test_git_merge_returns_zero_and_unions_the_two_sides(fixture_repo):
    """Gate item 2: a REAL ``git merge``, asserted on the subprocess."""
    repo, env = fixture_repo
    _commit_store(repo, env, "s", [("01BASE0", "base")], "base")

    _git(repo, "checkout", "-q", "-b", "right", env=env)
    _commit_store(repo, env, "s", [("01RIGHT", "right")], "right")
    right_lines = set((repo / "s.jsonl").read_text().splitlines())

    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "checkout", "-q", "-b", "left", env=env)
    # Fresh log for the left branch, from the same base content.
    (repo / "s.arrival").unlink()
    left = _mint(repo / "s.arrival")
    for ident, text in [("01BASE0", "base"), ("01LEFT0", "left")]:
        left.append("fact", _fact(ident, text), observer="kyle")
    write_derived_log(repo / "s.arrival")
    _git(repo, "add", "s.jsonl", env=env)
    _git(repo, "commit", "-q", "-m", "left", env=env)
    left_lines = set((repo / "s.jsonl").read_text().splitlines())

    merge = _git(repo, "merge", "right", "-m", "merge", env=env, check=False)

    assert merge.returncode == 0, f"{merge.stdout}\n{merge.stderr}"
    # PROVE THE DRIVER RAN. git's own textual 3-way merge can produce the
    # right union by luck when the hunks do not overlap, so a passing
    # assertion about content is not evidence that the driver was invoked.
    # Re-run the same merge with the driver replaced by /bin/false: if git
    # were resolving this textually, that would still succeed.
    _git(repo, "reset", "-q", "--hard", "HEAD@{1}", env=env, check=False)
    _git(repo, "config", "merge.loops-derived-log.driver", "false", env=env)
    sabotaged = _git(repo, "merge", "right", "-m", "merge", env=env, check=False)
    assert sabotaged.returncode != 0, (
        "git resolved the merge without invoking the driver — this gate is "
        "not testing what it claims to test"
    )
    _git(repo, "merge", "--abort", env=env, check=False)
    _git(
        repo,
        "config",
        "merge.loops-derived-log.driver",
        f"{sys.executable} -m store.derived_log_merge %O %A %B",
        env=env,
    )
    merge = _git(repo, "merge", "right", "-m", "merge", env=env, check=False)
    assert merge.returncode == 0, f"{merge.stdout}\n{merge.stderr}"

    merged = (repo / "s.jsonl").read_text().splitlines()
    assert set(merged) == left_lines | right_lines
    assert len(merged) == 3
    # And the bytes are what a fresh derivation of that set would produce.
    raw = (repo / "s.jsonl").read_bytes().splitlines()
    assert raw == sorted(raw)


def test_git_merge_exits_nonzero_when_one_id_carries_two_payloads(fixture_repo):
    repo, env = fixture_repo
    _commit_store(repo, env, "s", [("01BASE0", "base")], "base")

    _git(repo, "checkout", "-q", "-b", "right", env=env)
    (repo / "s.arrival").unlink()
    right = _mint(repo / "s.arrival")
    for ident, text in [("01BASE0", "base"), ("01CLASH", "their version")]:
        right.append("fact", _fact(ident, text), observer="kyle")
    write_derived_log(repo / "s.arrival")
    _git(repo, "add", "s.jsonl", env=env)
    _git(repo, "commit", "-q", "-m", "right", env=env)

    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "checkout", "-q", "-b", "left", env=env)
    (repo / "s.arrival").unlink()
    left = _mint(repo / "s.arrival")
    for ident, text in [("01BASE0", "base"), ("01CLASH", "our version")]:
        left.append("fact", _fact(ident, text), observer="kyle")
    write_derived_log(repo / "s.arrival")
    _git(repo, "add", "s.jsonl", env=env)
    _git(repo, "commit", "-q", "-m", "left", env=env)

    merge = _git(repo, "merge", "right", "-m", "merge", env=env, check=False)

    assert merge.returncode != 0
    assert "01CLASH" in merge.stdout + merge.stderr, (
        f"the driver's refusal did not name the id:\n"
        f"{merge.stdout}\n{merge.stderr}"
    )


def test_git_merge_exits_nonzero_when_a_base_line_was_dropped(fixture_repo):
    """Both sides must change the file, or git resolves the merge without
    ever invoking a driver — so the losing side ALSO adds a line."""
    repo, env = fixture_repo
    _commit_store(repo, env, "s", [("01KEEP0", "k"), ("01LOST0", "l")], "base")

    _git(repo, "checkout", "-q", "-b", "right", env=env)
    _commit_store(repo, env, "s", [("01RIGHT", "r")], "right adds")

    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "checkout", "-q", "-b", "left", env=env)
    # A rewritten log: 01LOST0 is gone, and a new line takes its place, so
    # both sides genuinely diverge from base.
    (repo / "s.arrival").unlink()
    left = _mint(repo / "s.arrival")
    for ident, text in [("01KEEP0", "k"), ("01LEFT0", "left")]:
        left.append("fact", _fact(ident, text), observer="kyle")
    write_derived_log(repo / "s.arrival")
    _git(repo, "add", "s.jsonl", env=env)
    _git(repo, "commit", "-q", "-m", "left drops a line", env=env)

    merge = _git(repo, "merge", "right", "-m", "merge", env=env, check=False)

    assert merge.returncode != 0
    assert "01LOST0" in merge.stdout + merge.stderr, (
        f"the driver did not run, or did not name the lost id:\n"
        f"{merge.stdout}\n{merge.stderr}"
    )


def test_the_module_entry_point_reports_usage_rather_than_tracing(fixture_repo):
    """git's contract is three arguments and a return code, so a
    mis-invocation must be a return code too."""
    result = subprocess.run(
        [sys.executable, "-m", "store.derived_log_merge"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_no_repo_root_gitattributes_or_gitignore_change_ships():
    """NON-NEGOTIABLE: registration rides wave 2."""
    root = Path(__file__).resolve().parents[3]
    attributes = root / ".gitattributes"
    if attributes.exists():
        assert "loops-derived-log" not in attributes.read_text()
    gitignore = root / ".gitignore"
    assert "*.jsonl" in gitignore.read_text(), (
        "cut B must not un-ignore *.jsonl — that is wave 2's"
    )


def test_the_driver_refuses_arrival_records_rather_than_unioning_them(tmp_path):
    """There is no textual merge driver for ``.arrival``, and pointing THIS
    one at arrival logs must fail loudly rather than half-work.

    Two arrival logs cannot be merged textually: every record after the
    divergence carries a ``prev`` chained to a different predecessor, so a
    textual union produces a file that refuses to walk. Combining lineages
    is a custody ceremony called ``merge_store``.

    The lines here are arrival RECORDS — the structural genesis at ordinal 0
    included — not codec fact/tick lines. They carry ``k``/``lin``/``ord``
    and no ``t`` discriminator, so the line grammar refuses them, and the
    refusal is what stops a union from being written.
    """
    ours = _store_with(tmp_path / "a.arrival", [("01A", "a")])
    theirs = _store_with(tmp_path / "b.arrival", [("01B", "b")])
    # Point the driver at the ARRIVAL LOGS themselves, not their projections.
    ours_arrival = tmp_path / "a.arrival"
    theirs_arrival = tmp_path / "b.arrival"
    before = ours_arrival.read_bytes()
    # Not vacuous: these really are arrival records, genesis first.
    first = json.loads(before.splitlines()[0])
    assert first["k"] == "genesis" and first["ord"] == 0 and "t" not in first

    with pytest.raises(Exception) as exc:
        merge_derived_log(tmp_path / "no-base", ours_arrival, theirs_arrival)
    assert not isinstance(exc.value, DerivedLogMergeConflict), (
        "an arrival log is not a derived log with a conflict in it — it is "
        "the wrong grammar entirely, and the refusal must say so"
    )

    # NOTHING was written: the target log is byte-identical.
    assert ours_arrival.read_bytes() == before

    # And through the git-facing entry point it is a non-zero exit, not a
    # traceback and not a silent union.
    result = subprocess.run(
        [
            sys.executable, "-m", "store.derived_log_merge",
            str(tmp_path / "no-base"), str(ours_arrival), str(theirs_arrival),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "derived-log merge" in result.stderr
    assert ours_arrival.read_bytes() == before


def test_no_arrival_merge_driver_module_exists():
    """The structural half of the same rule: there is no second driver, so
    nobody can wire one up by reaching for an obvious name."""
    import store.derived_log_merge as driver

    assert not (Path(driver.__file__).parent / "arrival_merge.py").exists()
