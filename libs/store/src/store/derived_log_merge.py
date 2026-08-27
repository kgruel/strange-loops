"""A semantic git merge driver for the derived ``.jsonl`` projection.

Cut B of the arrival substrate (decision:design/arrival-sliceB-projections
§Q3). The derived log is a byte-sorted projection of an arrival log, so two
branches that both appended to their stores produce two files whose contents
overlap and whose lines interleave — a textual three-way merge produces
garbage, and git's built-in ``merge=union`` produces duplicate and
interleaved lines in arbitrary order while detecting neither same-id
divergence nor loss.

This driver unions by **row id** over whole canonical lines and REFUSES the
two cases a projection of an append-only log cannot honestly resolve.

``libs/store`` is the maintenance-operations lib by charter, and a git driver
is tooling over store artifacts rather than a runtime write path. **The sort
rule and the line grammar live once in engine** — this module imports
:func:`engine.arrival_projection.canonical_line` and
:func:`~engine.arrival_projection.sort_key` rather than re-spelling them, so
driver output and a fresh derivation cannot drift.

**NON-NEGOTIABLE: the driver never opens a store and never touches an
arrival log.** It reads three files and writes one.

There is deliberately **no merge driver for ``.arrival``**. Two arrival logs
cannot be merged textually — every record after the divergence point carries
a ``prev`` chained to a different predecessor, so a textual union produces a
file that refuses to walk. Combining two arrival lineages is a custody
ceremony and its name is :func:`store.merge_store`.

Registration rides wave 2: this cut adds no repo-root ``.gitattributes`` and
changes no ``.gitignore`` line.

Usage (git's contract — ``%A`` is rewritten in place)::

    python -m store.derived_log_merge %O %A %B
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DerivedLogMergeConflict",
    "DerivedLogMergeResult",
    "merge_derived_log",
]


class DerivedLogMergeConflict(Exception):
    """The two sides make claims a projection of an append-only log cannot
    both satisfy. Names the offending row id."""


@dataclass(frozen=True)
class DerivedLogMergeResult:
    """What the union contained. Counts, never a verdict about the stores."""

    lines: int
    from_ours: int
    from_theirs: int
    shared: int


def _read(path: Path) -> list[str]:
    """A derived log's lines, or ``[]`` when the file is absent or empty.

    An absent ``%O`` is the ordinary new-file merge (neither side had the
    file at the merge base); an unterminated final line is a torn tail and
    was never a record, so it is dropped rather than parsed.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    if not raw:
        return []
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    else:
        lines.pop()  # torn tail: never terminated, so never a record
    return lines


def _index(lines: list[str], side: str) -> dict[str, str]:
    """Map every row id in ``lines`` to the canonical line carrying it.

    **The union key is the ROW ID, and identity is the whole canonical
    line.** A batch line carries several ids and every one of them maps to
    that same whole line — which is why the key cannot be a naive ``(t, id)``
    pair read off the object: a batch has no single id, and the same row can
    be a plain fact line on one side and ride inside a batch on the other.
    Mapping id → whole line makes that a detectable divergence rather than a
    silent duplicate.

    Lines are CANONICALIZED before comparison, through engine's one spelling
    of the grammar, so key order or whitespace noise cannot mint a false
    conflict.
    """
    from engine.arrival_projection import canonical_line
    from engine.jsonl_codec import deserialize_records

    index: dict[str, str] = {}
    for line in lines:
        canonical = canonical_line(line)
        for _t, row in deserialize_records(canonical):
            row_id = row[0]
            previous = index.get(row_id)
            if previous is not None and previous != canonical:
                raise DerivedLogMergeConflict(
                    f"{side} carries row id {row_id} twice, with different "
                    "bytes — no index can consume such a log, so there is "
                    "nothing here to merge"
                )
            index[row_id] = canonical
    return index


def merge_derived_log(
    base: Path, ours: Path, theirs: Path, out: Path | None = None
) -> DerivedLogMergeResult:
    """Union two derived logs, or refuse. Writes ``out`` (default ``ours``).

    Per row id:

    ==================================  ==========================
    id on one side only                 include
    id on both sides, identical bytes   include once
    id on both sides, DIFFERENT bytes   **REFUSE**
    id in ``base``, absent from a side  **REFUSE**
    ==================================  ==========================

    *Same id, different bytes* is a custody contradiction: at most one of
    them is what an arrival log says. Today's ``INSERT OR IGNORE`` resolves
    the same collision silently in the target's favour, and that is the
    behaviour this cut removes — a driver that picked a side would re-mint
    it.

    *Loss against base* cannot happen to a projection of an append-only log.
    If one branch's file lost a line the other kept, that branch's log was
    rewritten. Refusing is the only non-destructive answer, and it is the
    property that makes this a SEMANTIC driver rather than ``merge=union``.

    Output is byte-sorted and byte-identical to a fresh derivation of the
    merged set.
    """
    from engine.arrival_projection import sort_key

    base_index = _index(_read(Path(base)), "the merge base")
    our_index = _index(_read(Path(ours)), "our side")
    their_index = _index(_read(Path(theirs)), "their side")

    for row_id in sorted(base_index):
        for side, index in (("ours", our_index), ("theirs", their_index)):
            if row_id not in index:
                raise DerivedLogMergeConflict(
                    f"row id {row_id} is in the merge base but absent from "
                    f"{side} — a projection of an append-only log cannot "
                    "lose a line, so that side's log was rewritten; refusing "
                    "rather than choosing which history is real"
                )

    shared = 0
    merged = dict(our_index)
    for row_id, line in their_index.items():
        existing = merged.get(row_id)
        if existing is None:
            merged[row_id] = line
            continue
        shared += 1
        if existing != line:
            raise DerivedLogMergeConflict(
                f"row id {row_id} carries different bytes on the two sides — "
                "at most one of them is what an arrival log says, and "
                "choosing between them would re-mint the silent-overwrite "
                "this driver exists to remove"
            )

    lines = sorted(set(merged.values()), key=sort_key)
    target = Path(ours if out is None else out)
    target.write_text(
        "".join(line + "\n" for line in lines), encoding="utf-8"
    )
    return DerivedLogMergeResult(
        lines=len(lines),
        from_ours=len(our_index),
        from_theirs=len(their_index),
        shared=shared,
    )


def main(argv: list[str]) -> int:
    """git's driver contract: ``%O %A %B``, rewrite ``%A``, rc 0 or nonzero.

    ``%O``/``%A``/``%B`` are temp files with no ``.jsonl`` suffix — the
    driver is SELECTED by the logical pathname through ``.gitattributes``,
    so nothing here may sniff a suffix.
    """
    if len(argv) != 3:
        print(
            "usage: python -m store.derived_log_merge %O %A %B",
            file=sys.stderr,
        )
        return 2
    base, ours, theirs = (Path(a) for a in argv)
    try:
        merge_derived_log(base, ours, theirs)
    except DerivedLogMergeConflict as conflict:
        print(f"derived-log merge refused: {conflict}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — a driver reports, never traces
        print(f"derived-log merge failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
