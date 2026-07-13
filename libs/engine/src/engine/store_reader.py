"""StoreReader — read-only inspector for SqliteStore databases."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .tick import Tick


class StoreReader:
    """Read-only connection to a SqliteStore database.

    Opens the database with PRAGMA query_only=ON. Does not create
    the file or parent directories — raises FileNotFoundError if
    the path does not exist.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Store not found: {self._path}")

        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA query_only=ON")

    @property
    def fact_total(self) -> int:
        """Visible total facts — the reserved ``_decl.*`` namespace excluded.

        A ``@property`` (not a method) so ``reader.fact_total`` reads as a count,
        not a bound method: a method here silently mis-renders (a truthy bound
        method that format-prints as a repr) at any un-called call site. Excludes
        ``_decl.*`` by default (SPEC §9.4 — every read surface excludes it),
        using the same ``GLOB`` (not ``LIKE``) predicate as :meth:`fact_kind_stats`
        so the visible total stays consistent with the visible per-kind breakdown.
        Before S4 the delta was a single ``genesis`` row and an honest total could
        ignore it; the edit ceremony (S4) grows the ``_decl.*`` row count on every
        re-absorb, so an unfiltered total would drift from the kinds it sums to.
        For the raw all-rows count use :meth:`fact_total_all`.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE kind NOT GLOB '_decl.*'"
        ).fetchone()
        return row[0]

    def fact_total_all(self) -> int:
        """Raw total facts, INCLUDING the reserved ``_decl.*`` namespace.

        The explicit escape hatch defeating the default exclusion of
        :attr:`fact_total` — the ``--kind`` defeat the other read surfaces use,
        named so the intent is legible at the call site.
        """
        row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        return row[0]

    @property
    def tick_total(self) -> int:
        """Total number of ticks in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()
        return row[0]

    def fact_kind_stats(self, *, include_internal: bool = False) -> dict[str, dict]:
        """Per-kind fact counts and time ranges.

        Excludes the reserved ``_decl.*`` declaration-event namespace by
        default (SPEC §9.4 — every read surface excludes it; ``GLOB`` not
        ``LIKE``, since ``_`` is a LIKE single-char wildcard, not a GLOB one).
        Pass ``include_internal=True`` for the explicit escape hatch.
        """
        where = "" if include_internal else "WHERE kind NOT GLOB '_decl.*'"
        rows = self._conn.execute(
            f"SELECT kind, COUNT(*), MIN(ts), MAX(ts) FROM facts {where} GROUP BY kind"
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def fact_key_stats(self, kind: str, key_field: str) -> dict:
        """Per-fold-key stats within one kind — the containment level below kind.

        ``GROUP BY json_extract(payload, '$.<key_field>')`` over the kind
        partition (rides ``idx_facts_kind``). Returns ``{key_value: {count,
        earliest, latest}}``, count-descending then latest-descending — the
        same shape as :meth:`fact_kind_stats`, one containment level down
        (vertex ⊃ kind ⊃ key). The ``None`` bucket collects facts of this kind
        that are missing the key field (the silently-orphaned case CLAUDE.md
        warns about) — it doubles as an orphan diagnostic, rendered ``(no
        <field>)`` by the lens.
        """
        path = "$." + key_field
        rows = self._conn.execute(
            "SELECT json_extract(payload, ?) AS k, COUNT(*), MIN(ts), MAX(ts) "
            "FROM facts WHERE kind = ? "
            "GROUP BY k ORDER BY COUNT(*) DESC, MAX(ts) DESC",
            (path, kind),
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def fact_observer_stats(self, kind: str) -> dict:
        """Per-observer fact counts and freshness within one kind, count-desc.

        The collect-fold descent: kinds with no fold key (``session``, ``log``,
        ``cite``) have no payload key to group on, so the natural "one level
        down" is by emitter. ``GROUP BY observer`` over the kind partition.
        """
        rows = self._conn.execute(
            "SELECT observer, COUNT(*), MIN(ts), MAX(ts) FROM facts "
            "WHERE kind = ? GROUP BY observer ORDER BY COUNT(*) DESC, MAX(ts) DESC",
            (kind,),
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def fact_density_by_kind(
        self, *, since: float, until: float, buckets: int = 8
    ) -> dict[str, list[int]]:
        """Per-kind activity histogram over ``[since, until]`` in ``buckets`` bins.

        Feeds the trend sparkline — each kind maps to a list of ``buckets``
        counts, oldest→newest, on a *shared* time axis so sparklines across
        kinds are directly comparable (a kind dormant in the window reads as an
        empty/flat trend, which is the honest signal). One ``idx_facts_ts``
        range scan; bucketing is in-memory.
        """
        span = (until - since) or 1.0
        rows = self._conn.execute(
            "SELECT kind, ts FROM facts WHERE ts >= ? AND ts <= ?",
            (since, until),
        ).fetchall()
        out: dict[str, list[int]] = {}
        for kind, ts in rows:
            arr = out.setdefault(kind, [0] * buckets)
            b = int((ts - since) / span * buckets)
            arr[min(buckets - 1, b)] += 1
        return out

    def signed_counts(self) -> tuple[int, int] | None:
        """``(signed, total)`` fact counts, or ``None`` on pre-signature stores.

        Guards on a ``PRAGMA table_info`` probe — the ``signature`` column is
        absent entirely on pre-delta-3 schemas, where a bare query would raise
        ``no such column``. ``COUNT(signature)`` counts non-NULL signatures.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)")}
        if "signature" not in cols:
            return None
        row = self._conn.execute(
            "SELECT COUNT(signature), COUNT(*) FROM facts"
        ).fetchone()
        return (row[0], row[1])

    def tick_name_stats(self) -> dict[str, dict]:
        """Per-name tick counts and time ranges."""
        rows = self._conn.execute(
            "SELECT name, COUNT(*), MIN(ts), MAX(ts) FROM ticks GROUP BY name"
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def summary(self, *, include_internal: bool = False) -> dict:
        """Aggregate store contents into a summary dict.

        ``include_internal`` threads to both :meth:`fact_total` and
        :meth:`fact_kind_stats` — the ``_decl.*`` reserved namespace is excluded
        from ``facts.total`` and ``facts.kinds`` together by default (SPEC §9.4),
        so the total always sums to the visible kinds.
        """
        return {
            "facts": {
                "total": self.fact_total_all() if include_internal else self.fact_total,
                "kinds": self.fact_kind_stats(include_internal=include_internal),
            },
            "ticks": {
                "total": self.tick_total,
                "names": self.tick_name_stats(),
            },
        }

    def tick_timestamps(self, name: str, limit: int | None = None) -> list[float]:
        """Raw timestamps for a tick name, newest first. No payload parsing."""
        query = "SELECT ts FROM ticks WHERE name = ? ORDER BY ts DESC"
        params: list = [name]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [r[0] for r in self._conn.execute(query, params).fetchall()]

    def recent_ticks(self, name: str, n: int) -> list[Tick]:
        """Last N ticks for a given name, newest first."""
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks "
            "WHERE name = ? ORDER BY ts DESC LIMIT ?",
            (name, n),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    def ticks_between(
        self,
        since_ts: float,
        until_ts: float,
        name: str | None = None,
        *,
        with_envelope: bool = False,
    ) -> list[Tick] | list[tuple[Tick, dict]]:
        """Ticks within a time range, optionally filtered by name.

        With ``with_envelope=True``, returns ``(Tick, envelope)`` pairs.
        The envelope is the witness-era attestation metadata added at
        append time — deliberately NOT on ``Tick`` itself (a Tick is the
        produced snapshot; chain link and signature are properties of the
        stored, witnessed row). Shape::

            {"chained": bool, "signed": bool, "fact_cursor": str,
             "cursor_kind": str, "cursor_preview": str}

        Pre-chain rows (and pre-chain schemas) report ``chained=False``
        with empty cursor fields. Both shapes come from a single query so
        tick↔envelope pairing never relies on a join.
        """
        env_cols = ""
        have_chain = have_sig = False
        if with_envelope:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(ticks)")}
            have_chain = "window_hash" in cols
            have_sig = "signature" in cols
            if have_chain:
                env_cols = ", window_hash, fact_cursor"
                if have_sig:
                    env_cols += ", signature"
        name_clause = " AND name = ?" if name is not None else ""
        params: tuple = (since_ts, until_ts) + ((name,) if name is not None else ())
        rows = self._conn.execute(
            f"SELECT name, ts, since, origin, payload{env_cols} FROM ticks "
            f"WHERE ts >= ? AND ts <= ?{name_clause} ORDER BY ts",
            params,
        ).fetchall()
        ticks = [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]
        if not with_envelope:
            return ticks

        from .sqlite_store import cursor_fact_summary

        envelopes: list[dict] = []
        for r in rows:
            chained = have_chain and r[5] is not None
            cursor = (r[6] or "") if chained else ""
            env = {
                "chained": chained,
                "signed": bool(have_sig and chained and r[7] is not None),
                "fact_cursor": cursor,
            }
            env.update(
                cursor_fact_summary(self._conn, cursor) if cursor
                else {"cursor_kind": "", "cursor_preview": ""}
            )
            envelopes.append(env)
        return list(zip(ticks, envelopes, strict=True))

    @property
    def freshness(self) -> datetime | None:
        """Timestamp of the most recent fact, or None if store is empty."""
        row = self._conn.execute("SELECT MAX(ts) FROM facts").fetchone()
        if row[0] is None:
            return None
        return datetime.fromtimestamp(row[0], tz=timezone.utc)

    def fact_by_id(self, id_prefix: str) -> dict | None:
        """Look up a single fact by ID or ID prefix.

        Exact match first, then prefix match. Returns None if no match.
        Raises ValueError if prefix matches multiple facts.
        """
        # Exact match
        row = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts WHERE id = ?",
            (id_prefix,),
        ).fetchone()
        if row:
            return self._fact_row_to_dict(row)

        # Prefix match
        rows = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            "WHERE id >= ? AND id < ? ORDER BY id LIMIT 2",
            (id_prefix, id_prefix + "~"),
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                f"Ambiguous ID prefix '{id_prefix}' — matches {rows[0][0]} and {rows[1][0]}"
            )
        return self._fact_row_to_dict(rows[0])

    @staticmethod
    def _fact_row_to_dict(r: tuple) -> dict:
        """Convert a (id, kind, ts, observer, origin, payload) row to dict."""
        return {
            "id": r[0],
            "kind": r[1],
            "ts": datetime.fromtimestamp(r[2], tz=timezone.utc),
            "observer": r[3],
            "origin": r[4],
            "payload": json.loads(r[5]),
        }

    def facts_between(
        self,
        since_ts: float,
        until_ts: float,
        kind: str | None = None,
        *,
        include_internal: bool = False,
    ) -> list[dict]:
        """Facts within a time range, optionally filtered by kind.

        Excludes the reserved ``_decl.*`` namespace by default (SPEC §9.4),
        same ``GLOB`` (not ``LIKE``) rule as :meth:`fact_kind_stats`. Pass
        ``include_internal=True`` for the explicit escape hatch — callers
        that resolve an explicit user-requested internal ``kind`` should set
        this, since the ambient exclusion would otherwise filter out the very
        kind being asked for.
        """
        internal_clause = "" if include_internal else " AND kind NOT GLOB '_decl.*'"
        if kind is not None:
            rows = self._conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts "
                "WHERE ts >= ? AND ts <= ? AND (kind = ? OR kind LIKE ?)"
                f"{internal_clause} ORDER BY ts",
                (since_ts, until_ts, kind, kind + ".%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts "
                f"WHERE ts >= ? AND ts <= ?{internal_clause} ORDER BY ts",
                (since_ts, until_ts),
            ).fetchall()
        return [self._fact_row_to_dict(r) for r in rows]

    def facts_by_kind(self, kind: str) -> list[dict]:
        """All facts for a kind, ordered by insertion (rowid ASC).

        Used for fold replay — facts must be in causal order.
        """
        rows = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            "WHERE kind = ? ORDER BY ts, id",
            (kind,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "kind": r[1],
                "ts": r[2],
                "observer": r[3],
                "origin": r[4],
                "payload": json.loads(r[5]),
            }
            for r in rows
        ]

    def resolve_entity_id(self, kind: str, key: str, value: str) -> str | None:
        """Return the ULID of the most recent fact of kind where payload[key] == value.

        This is the entity reference primitive: given an entity address
        (kind + fold key field + fold key value), resolve it to the ULID
        of the most recent fact contributing to that entity's fold state.

        Returns None if no matching fact exists.
        """
        path = "$." + key
        row = self._conn.execute(
            "SELECT id FROM facts "
            "WHERE kind = ? AND json_extract(payload, ?) = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1",
            (kind, path, value),
        ).fetchone()
        return row[0] if row else None

    def recent_facts(self, kind: str, n: int) -> list[dict]:
        """Last N facts for a given kind, newest first. Returns raw dicts."""
        rows = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            "WHERE kind = ? ORDER BY ts DESC LIMIT ?",
            (kind, n),
        ).fetchall()
        return [self._fact_row_to_dict(r) for r in rows]

    def search_facts(
        self,
        query: str,
        *,
        kind: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """FTS5 search over fact payloads.

        Requires facts_fts virtual table to exist (see vertex_reader._ensure_fts).
        Returns newest-first, same dict shape as facts_between.
        """
        clauses = ["facts_fts MATCH ?"]
        params: list = [query]

        if kind is not None:
            clauses.append("fts.kind = ?")
            params.append(kind)
        if since is not None:
            clauses.append("f.ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("f.ts <= ?")
            params.append(until)

        where = " AND ".join(clauses)
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT f.id, f.kind, f.ts, f.observer, f.origin, f.payload "
            f"FROM facts_fts fts "
            f"JOIN facts f ON f.rowid = fts.fact_rowid "
            f"WHERE {where} "
            f"ORDER BY f.ts DESC LIMIT ?",
            params,
        ).fetchall()

        return [self._fact_row_to_dict(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StoreReader:
        return self

    def __exit__(self, *args) -> None:
        self.close()
