"""Provenance script for the negative batch fixtures — NOT a test.

Deterministic (no minted ids/ts), so regeneration is byte-identical. Each
fixture pins one refusal (or divergence) class from the codec rules of
design:architecture/jsonl-declaration-ceremony-encoding; the Go conformance
oracle must refuse (or diverge) identically.

    uv run --package engine python libs/engine/tests/fixtures/jsonl/generate_negatives.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent


def fact(i: int, kind: str = "_decl.kind-defined", ts: float = 1721359123.5) -> dict:
    return {
        "t": "fact",
        "id": f"01JNEG{i:020d}",
        "kind": kind,
        "ts": ts,
        "observer": "neg",
        "origin": "",
        "payload": "{}",
        "signature": "sig",
    }


def dump(o: dict) -> str:
    return json.dumps(o, ensure_ascii=True, separators=(",", ":"))


def write(name: str, text: str) -> None:
    (HERE / name).write_text(text, encoding="utf-8")


def main() -> None:
    f1, f2 = fact(1), fact(2)
    tick = {
        "t": "tick", "id": "01JNEGTICK", "name": "seal", "ts": 1721359123.5,
        "since": None, "origin": "", "payload": "{}", "prev_hash": None,
        "window_start": None, "fact_cursor": None, "window_hash": None,
    }
    write("batch-empty-rows.jsonl", dump({"t": "batch", "rows": []}) + "\n")
    write("batch-one-row.jsonl", dump({"t": "batch", "rows": [f1]}) + "\n")
    write(
        "batch-nested.jsonl",
        dump({"t": "batch", "rows": [f1, {"t": "batch", "rows": [f2, fact(3)]}]})
        + "\n",
    )
    write("batch-tick-inside.jsonl", dump({"t": "batch", "rows": [f1, tick]}) + "\n")
    write("batch-dup-id.jsonl", dump({"t": "batch", "rows": [f1, f1]}) + "\n")
    write(
        "batch-unknown-key.jsonl",
        dump({"t": "batch", "rows": [f1, f2], "extra": 1}) + "\n",
    )
    # Torn batch tail: a valid plain line, then a batch line cut mid-row with
    # no trailing newline — truncation on open, never an error.
    write(
        "batch-torn-tail.jsonl",
        dump(fact(9, kind="note")) + "\n" + dump({"t": "batch", "rows": [f1, f2]})[:-10],
    )
    # Mixed-ts all-_decl.* batch: codec-VALID (D1 — same-ts is the ceremony's
    # rule); audit_deep reports the divergence.
    late = fact(2)
    late["ts"] = 1721359999.0
    write("batch-mixed-ts-decl.jsonl", dump({"t": "batch", "rows": [fact(1), late]}) + "\n")
    print(f"wrote negatives under {HERE}")


if __name__ == "__main__":
    main()
