"""Shared plumbing for the loops-go conformance generators.

These generators produce the ground truth of the cross-implementation
differential oracle: every vector and fixture under `loops-go/testdata/` is the
output of *this* repo's `atoms`/`engine`/`store` running for real. They are
loops code — they import the reference implementation directly — so they live
in the loops workspace and write into a loops-go checkout named at the command
line. See `docs/dev/loops-go-protocol-queue.md`.

Two things every generator needs and neither should re-derive:

* **Provenance** — the loops commit the artifact was generated from, so a
  drifted fixture is diagnosable rather than merely wrong.
* **Destination** — the loops-go checkout. Named explicitly (`--loops-go`) or
  via `$LOOPS_GO_REPO`; never inferred from `$HOME`. The predecessor scripts
  lived in the loops-go tree and reached back with
  `sys.path.insert(0, Path.home() / "Code" / "loops" / ...)`, which bypassed the
  workspace, any release artifact, and any version pin.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

LOOPS_ROOT = Path(__file__).resolve().parent.parent

# Subdirectories of loops-go/testdata/ that generators write into.
_TESTDATA_SUBDIRS = ("stores", "vectors")


def loops_commit() -> str:
    """The loops commit these artifacts were generated from."""
    return subprocess.check_output(
        ["git", "-C", str(LOOPS_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def add_destination_arg(parser: argparse.ArgumentParser) -> None:
    """Add the `--loops-go` destination flag to a generator's parser."""
    parser.add_argument(
        "--loops-go",
        type=Path,
        default=os.environ.get("LOOPS_GO_REPO"),
        metavar="DIR",
        help="path to the loops-go checkout to write testdata into "
        "(default: $LOOPS_GO_REPO)",
    )


def testdata_dir(loops_go: Path | None, subdir: str) -> Path:
    """Resolve `<loops-go>/testdata/<subdir>`, refusing an unnamed destination.

    Refuses rather than guessing: a generator that silently writes into a
    default checkout is how the artifacts and the implementation drift apart
    without anyone choosing it.
    """
    if subdir not in _TESTDATA_SUBDIRS:
        raise ValueError(f"unknown testdata subdir {subdir!r}")
    if loops_go is None:
        raise SystemExit(
            "no loops-go checkout named. Pass --loops-go DIR or set "
            "$LOOPS_GO_REPO. (Generation moved into this repo; the artifacts "
            "still live in loops-go, where the Go conformance suite reads them.)"
        )
    root = Path(loops_go).expanduser().resolve()
    if not (root / "SPEC.md").is_file():
        raise SystemExit(f"{root} does not look like a loops-go checkout (no SPEC.md)")
    out = root / "testdata" / subdir
    out.mkdir(parents=True, exist_ok=True)
    return out


def unlink_store(path: Path) -> None:
    """Remove a SQLite store and its WAL sidecars, so a run starts clean."""
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        p.unlink(missing_ok=True)


def fixture_ulid(prefix: str, slot: str) -> str:
    """A deterministic, VALID ULID whose lexicographic rank is `slot`.

    loops-go SPEC §2.2 defines `facts.id` as a 26-character Crockford-base32
    ULID. Crockford excludes `I`, `L`, `O` and `U`, so a readable prefix has to
    be chosen against that alphabet — which is what the first tie fixture got
    wrong (`TIE…` is 26 characters and is not a ULID; sol MEDIUM, 2026-07-27).
    The Python writer accepts anything through `id_override` and the Go reader
    treats ids as opaque strings, so nothing in the corpus caught it: a
    conforming consumer that validates the stated store format would reject the
    fixture before reaching the oracle.

    Two constraints, both enforced here rather than left to the caller:

    * every character in the Crockford alphabet — checked against `is_ulid`
      imported from the reference implementation, not a re-derived alphabet;
    * the first character must keep the 48-bit millisecond timestamp in range.
      `T…` overflows ("Timestamp value is too large"), so prefixes start `0`.

    The `slot` character carries the whole ordering signal; the rest is padding
    to the ULID width. Callers pick slots so that lexicographic id order
    constructs the order the fixture is about.
    """
    from store.rebirth import is_ulid
    from ulid import ULID

    fid = f"{prefix}{slot}".ljust(26, "0")
    if len(fid) != 26 or not is_ulid(fid):
        raise ValueError(
            f"{fid!r} is not a valid ULID (SPEC §2.2: 26 chars, Crockford "
            f"base32 — no I, L, O, U). Fix the prefix, not this check."
        )
    # `is_ulid` is a shape check; parsing catches the separate failure mode
    # where every character is legal but the leading ones overflow the field.
    ULID.from_str(fid)
    return fid
