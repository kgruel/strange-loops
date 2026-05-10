"""Corpus: declarative spec + sqlite loader (extracted from bridge.py).

Adds time-window (since/until), fold-dedup toggle, vertex param.
"""
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


KINDS_UPSERT = {"decision", "thread", "task", "plan", "observation", "hypothesis"}
KINDS_COLLECT = {"cite", "handoff"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _vertex_db_path(vertex: str) -> Path:
    """Default sqlite path: <repo>/.loops/data/<vertex>.db"""
    return _repo_root() / ".loops" / "data" / f"{vertex}.db"


@dataclass(frozen=True)
class Corpus:
    vertex: str = "project"
    kinds: tuple[str, ...] = ("decision",)
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    min_chars: int = 50
    fold_dedup: bool = True
    db_path: Optional[Path] = None  # override sqlite path; None = default

    def resolve_db(self) -> Path:
        return self.db_path if self.db_path else _vertex_db_path(self.vertex)


def load(corpus: Corpus) -> list[dict]:
    """Load substantive items from sqlite under the corpus spec.

    Returns rows of {kind, key, topic, message, status, ts, id}. Upsert kinds
    are deduped by (kind, key=topic|name) when fold_dedup=True; collect kinds
    yield one row per fact.
    """
    db = corpus.resolve_db()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    upsert_kinds = tuple(k for k in corpus.kinds if k in KINDS_UPSERT)
    collect_kinds = tuple(k for k in corpus.kinds if k in KINDS_COLLECT)

    rows: list[dict] = []
    ts_clauses, ts_params = [], []
    if corpus.since is not None:
        ts_clauses.append("ts >= ?")
        ts_params.append(corpus.since.timestamp())
    if corpus.until is not None:
        ts_clauses.append("ts <= ?")
        ts_params.append(corpus.until.timestamp())
    ts_filter = (" AND " + " AND ".join(ts_clauses)) if ts_clauses else ""

    if upsert_kinds:
        placeholders = ",".join("?" for _ in upsert_kinds)
        cur = conn.execute(
            f"""SELECT kind, payload, ts, id FROM facts
                WHERE kind IN ({placeholders})
                  AND length(coalesce(json_extract(payload,'$.message'),'')) >= ?
                  {ts_filter}
                ORDER BY ts DESC""",
            (*upsert_kinds, corpus.min_chars, *ts_params),
        )
        seen = set()
        for r in cur:
            payload = json.loads(r["payload"])
            key = payload.get("topic") or payload.get("name")
            if not key:
                continue
            if corpus.fold_dedup:
                ck = (r["kind"], key)
                if ck in seen:
                    continue
                seen.add(ck)
            rows.append({
                "kind": r["kind"],
                "key": key,
                "topic": key,
                "message": payload.get("message", ""),
                "status": payload.get("status", ""),
                "ts": r["ts"],
                "id": r["id"],
            })

    if collect_kinds:
        placeholders = ",".join("?" for _ in collect_kinds)
        cur = conn.execute(
            f"""SELECT kind, payload, ts, id FROM facts
                WHERE kind IN ({placeholders})
                  AND length(coalesce(json_extract(payload,'$.message'),'')) >= ?
                  {ts_filter}
                ORDER BY ts DESC""",
            (*collect_kinds, corpus.min_chars, *ts_params),
        )
        for r in cur:
            payload = json.loads(r["payload"])
            rows.append({
                "kind": r["kind"],
                "key": r["id"][:8],
                "topic": payload.get("ref", "") or r["id"][:8],
                "message": payload.get("message", ""),
                "status": payload.get("status", ""),
                "ts": r["ts"],
                "id": r["id"],
            })

    conn.close()
    return rows


def load_manifest(path: Path) -> list[dict]:
    """Load a previously-saved manifest (json list of rows). For verification
    and for runs that pin against fixture state."""
    return json.load(open(path))
