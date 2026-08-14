"""StoreReader — read-only inspector for SqliteStore databases."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .tick import Tick

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .witness import WitnessPosition


@dataclass(frozen=True)
class FactPage:
    """One bounded page of a generic fact query (:meth:`StoreReader.query_facts`).

    ``next`` is a 0.8.0 :class:`~engine.witness.WitnessPosition` — the SAME
    cursor type every other temporal seam uses, not a second cursor species.
    It marks the LAST item of this page on the witness (append/rowid) axis;
    hand it back as ``before`` (order ``"newest"``) or ``after`` (order
    ``"oldest"``) to fetch the next page. ``None`` means the walk is complete
    (equivalently: ``truncated`` is False).

    ``truncated`` is True when more matching rows existed beyond ``limit`` in
    the SAME read snapshot the items came from.
    """

    items: list[dict]
    next: "WitnessPosition | None"
    truncated: bool
    #: The order the page was walked in — echoed so a consumer holding only
    #: the page knows which parameter ``next`` feeds.
    order: str


class StoreReader:
    """Read-only connection to a SqliteStore database.

    Opens the database with PRAGMA query_only=ON. Does not create
    the file or parent directories — raises FileNotFoundError if
    the path does not exist.
    """

    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Store not found: {self._path}")

        # ``timeout`` is sqlite's busy wait on a locked database. The 5s
        # default suits interactive commands; latency-critical read paths
        # (shell completion) pass a sub-second value — waiting out an
        # exclusive lock is worse than under-listing there.
        self._conn = sqlite3.connect(str(self._path), timeout=timeout)
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

    def key_prefixes(
        self, kind: str, key_field: str, *, prefix: str = "", limit: int = 200,
    ) -> list[str]:
        """Namespace prefixes (or scoped full keys) for one kind's fold-key field.

        The completion-time sibling of :meth:`fact_key_stats`: that method
        computes an unbounded ``GROUP BY`` over the whole kind partition for a
        display lens; this one is a bounded probe for shell ``<TAB>`` — a
        single ``LIMIT``-capped read of the ``limit`` most-recently INSERTED
        facts of ``kind`` (rowid order, not timestamp order — after a merge
        appends older-``ts`` foreign facts, those count as recent here; a
        namespace live only in lower-rowid facts can be missed), with the
        prefix/full-key split done in Python rather than a second SQL shape.
        TAB must stay instant, so this trades completeness for a fixed, small
        amount of I/O regardless of store size.

        Two modes, chosen by whether ``prefix`` already contains a ``/``:

        - no slash yet — the namespace-prefix drill: distinct first path
          segments (``practice/``, ``design/``...) among the sampled keys.
        - slash present — the scoped drill: full fold-key values starting
          with ``prefix`` (``practice/`` -> ``practice/review-altitude``...).

        Sorted for a stable TAB order. Keys missing the fold-key field (the
        ``None`` bucket ``fact_key_stats`` surfaces as an orphan diagnostic)
        are silently skipped here — nothing to complete from them.
        """
        # ORDER BY rowid, not ts: the single-column kind index is internally
        # (kind, rowid), so this reads exactly ``limit`` index entries
        # backwards with no temp B-tree — ``ORDER BY ts`` would scan and sort
        # the whole kind partition before LIMIT applies (Sol review
        # review/completion-t3 #6; a query-plan regression test holds this).
        # Insertion order ≈ recency, which is all a completion probe needs.
        path = "$." + key_field
        rows = self._conn.execute(
            "SELECT json_extract(payload, ?) AS k FROM facts "
            "WHERE kind = ? ORDER BY rowid DESC LIMIT ?",
            (path, kind, limit),
        ).fetchall()
        keys = [r[0] for r in rows if r[0]]
        if "/" in prefix:
            return sorted({k for k in keys if k.startswith(prefix)})
        namespaces: set[str] = set()
        for k in keys:
            if "/" in k:
                namespaces.add(k.split("/", 1)[0] + "/")
        return sorted(namespaces)

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
        # Reserved _decl.* rows excluded (SPEC §9.4): they are always signed
        # ceremony events, and counting them made an otherwise-empty absorbed
        # store report "facts 0 · signed 1/1" (closing review #8).
        row = self._conn.execute(
            "SELECT COUNT(signature), COUNT(*) FROM facts "
            "WHERE kind NOT GLOB '_decl.*'"
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

    def live_edge(self) -> tuple[int, float | None]:
        """Visible facts past the newest chained tick's window cursor.

        Returns ``(count, oldest_ts)`` — the live edge and the ``ts`` of its
        oldest fact (``None`` when the edge is empty). The boundary is the
        same claim ``SqliteStore.verify_chain`` walks: the newest chained
        tick's ``fact_cursor`` resolved to its rowid (witness/append order,
        never ``ts`` — a backfilled fact with an old event time stays on the
        edge until sealed; see the ORDERING AUTHORITY note in sqlite_store).

        Boundary fallbacks, all conservative (larger edge, never smaller):
        pre-chain schema (no ``window_hash`` column), no chained ticks, or an
        unresolvable cursor fact all report from rowid 0 — every visible fact
        is on the edge, matching ``verify_chain``'s ``covered=0`` for the
        same stores.

        Counts follow the read-surface contract (SPEC §9.4): ``_decl.*``
        excluded. ``verify_chain``'s ``uncovered_facts`` is the forensic
        surface and includes them — the two numbers answer different
        questions and may differ by the control-receipt count.

        SNAPSHOT COHERENCE (sol HIGH r1, 0.10.0): boundary resolution and the
        aggregate are ONE statement, not three. ``StoreReader`` holds no read
        transaction, so a boundary read and a count read taken as separate
        statements straddle any concurrent commit — and sealing is *exactly*
        the concurrent operation that turns a live fact into a covered one.
        The old three-statement form could observe tick N's boundary and
        tick N+1's facts, reporting a count true in no coherent snapshot
        (reproduced: a sealed store answering ``(1, ts)`` instead of
        ``(0, None)``). SQLite runs a single statement against a single
        snapshot, so collapsing them makes the skew inexpressible rather
        than merely unlikely — the boundary CTE and the aggregate now always
        see the same commit, whichever one that is.

        The ``PRAGMA table_info`` schema gate stays a separate statement, and
        that is safe in the only direction it can drift: a migration that adds
        ``window_hash`` between the probe and the aggregate makes this read
        fall back to boundary 0 — the whole store on the edge, the same
        conservative answer every other fallback gives. There is no
        interleaving in which the gate makes the edge look *smaller* than a
        coherent snapshot would.
        """
        cols = {
            r[1] for r in self._conn.execute("PRAGMA table_info(ticks)")
        }
        # All four documented fallbacks live inside the one statement:
        #   pre-chain schema        -> the literal 0 boundary below
        #   no chained tick         -> inner SELECT yields no row -> COALESCE 0
        #   "" cursor sentinel      -> no fact has id '' -> COALESCE 0
        #   unresolvable cursor     -> no id match -> COALESCE 0
        # No parameters are interpolated — `boundary` is one of two literal
        # SQL fragments chosen by the schema probe.
        boundary = (
            """COALESCE((
                SELECT f.rowid FROM facts f
                 WHERE f.id = (
                     SELECT fact_cursor FROM ticks
                      WHERE window_hash IS NOT NULL
                      ORDER BY rowid DESC LIMIT 1
                 )
            ), 0)"""
            if "window_hash" in cols
            else "0"
        )
        count, oldest = self._conn.execute(
            "SELECT COUNT(*), MIN(ts) FROM facts "
            f"WHERE rowid > {boundary} AND kind NOT GLOB '_decl.*'"
        ).fetchone()
        return count, oldest

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
        """Timestamp of the most recent DOMAIN fact, or None if none exist.

        Reserved ``_decl.*`` rows excluded (SPEC §9.4): a declaration edit is
        ontology maintenance, not domain activity — it must not refresh the
        store's apparent last-activity (closing review #8).
        """
        row = self._conn.execute(
            "SELECT MAX(ts) FROM facts WHERE kind NOT GLOB '_decl.*'"
        ).fetchone()
        if row[0] is None:
            return None
        return datetime.fromtimestamp(row[0], tz=timezone.utc)

    def fact_by_id(
        self,
        id_prefix: str,
        *,
        include_internal: bool = False,
        kind: str | None = None,
    ) -> dict | None:
        """Look up a single fact by ID or ID prefix.

        Exact match first, then prefix match. Returns None if no match.
        Raises ValueError if prefix matches multiple facts.

        Reserved ``_decl.*`` rows are excluded by default (SPEC §9.4 — every
        read surface excludes the namespace; a known genesis id is not an
        escape hatch). ``include_internal=True`` is the explicit defeat,
        reserved for surfaces that already carved one out (``--kind _decl.*``).
        """
        internal = "" if include_internal else " AND kind NOT GLOB '_decl.*'"
        # An explicit kind SCOPES the whole lookup — including prefix
        # ambiguity: two facts sharing a prefix across kinds are NOT
        # ambiguous when only one has the requested kind.
        kind_clause = " AND kind = ?" if kind is not None else ""
        kind_params: tuple = (kind,) if kind is not None else ()
        # Exact match
        row = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            f"WHERE id = ?{internal}{kind_clause}",
            (id_prefix, *kind_params),
        ).fetchone()
        if row:
            return self._fact_row_to_dict(row)

        # Prefix match
        rows = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            f"WHERE id >= ? AND id < ?{internal}{kind_clause} "
            "ORDER BY id LIMIT 2",
            (id_prefix, id_prefix + "~", *kind_params),
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
        at_rowid: int | None = None,
    ) -> list[dict]:
        """Facts within a time range, optionally filtered by kind.

        Excludes the reserved ``_decl.*`` namespace by default (SPEC §9.4),
        same ``GLOB`` (not ``LIKE``) rule as :meth:`fact_kind_stats`. Pass
        ``include_internal=True`` for the explicit escape hatch — callers
        that resolve an explicit user-requested internal ``kind`` should set
        this, since the ambient exclusion would otherwise filter out the very
        kind being asked for.

        ``at_rowid`` caps the result to the witness prefix ``rowid <= at_rowid``
        (0.8.0 temporal cursor, A1 facts-only) — rows the store had *received*
        at that position. It composes with the time window: a witnessed read of
        a range returns the facts in ``[since, until]`` that were present at the
        cursor. Resolve a :class:`~engine.witness.WitnessPosition` for the rowid;
        never hand a raw id here (ids are never ordered — A3).
        """
        internal_clause = "" if include_internal else " AND kind NOT GLOB '_decl.*'"
        rowid_clause = " AND rowid <= ?" if at_rowid is not None else ""
        rowid_param: tuple = (at_rowid,) if at_rowid is not None else ()
        if kind is not None:
            from .sql_util import kind_subtree_predicate

            kind_sql, kind_params = kind_subtree_predicate(kind)
            rows = self._conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts "
                f"WHERE ts >= ? AND ts <= ? AND {kind_sql}"
                f"{internal_clause}{rowid_clause} ORDER BY ts",
                (since_ts, until_ts, *kind_params, *rowid_param),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts "
                f"WHERE ts >= ? AND ts <= ?{internal_clause}{rowid_clause} "
                "ORDER BY ts",
                (since_ts, until_ts, *rowid_param),
            ).fetchall()
        return [self._fact_row_to_dict(r) for r in rows]

    def facts_by_kind(
        self,
        kind: str,
        *,
        at_rowid: int | None = None,
        until_ts: float | None = None,
    ) -> list[dict]:
        """All facts for a kind, ordered by insertion (rowid ASC).

        Used for fold replay — facts must be in causal order.

        ``at_rowid`` caps to the witness prefix (``rowid <= at_rowid``): the fold
        reconstructs from the rows the store had received at that position, still
        replayed in ``(ts, id)`` order (0.8.0 fold-at). ``None`` is a head read.

        ``until_ts`` caps to ``ts <= until_ts`` — the event-time projection
        sibling (0.8.0 fold-state-``as_of``, A8): facts are selected by
        timestamp cutoff rather than receipt prefix. Mutually exclusive with
        ``at_rowid`` in practice (the caller picks one selector); both compose
        as independent WHERE clauses if ever passed together.
        """
        rowid_clause = " AND rowid <= ?" if at_rowid is not None else ""
        rowid_param: tuple = (at_rowid,) if at_rowid is not None else ()
        ts_clause = " AND ts <= ?" if until_ts is not None else ""
        ts_param: tuple = (until_ts,) if until_ts is not None else ()
        rows = self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            f"WHERE kind = ?{rowid_clause}{ts_clause} ORDER BY ts, id",
            (kind, *rowid_param, *ts_param),
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

    def query_facts(
        self,
        *,
        limit: int = 100,
        before: "WitnessPosition | None" = None,
        after: "WitnessPosition | None" = None,
        kind: str | None = None,
        observer: str | None = None,
        include_internal: bool = False,
        order: str = "newest",
    ) -> FactPage:
        """Bounded, cursor-bearing generic fact query — one page per call.

        The generic listing seam a CLI ``read --facts --limit N`` needs:
        no time window, no per-kind restriction required, never an unbounded
        scan. Ordering authority is the WITNESS AXIS (``rowid``, append
        order) — the same contract every 0.8.0 temporal seam uses. Fact ids
        are NEVER ordered or compared (A3): the corpus mixes uuid4-era and
        ULID-era ids, and even pure-ULID stores are not within-millisecond
        monotonic. ``order="newest"`` walks ``rowid DESC``; ``"oldest"``
        walks ``rowid ASC``. (Note this is receipt order, not event-time
        ``ts`` order — a merged/backdated fact lists where it was RECEIVED,
        the same honesty the witness prefix gives ``at=`` reads.)

        Cursors are 0.8.0 :class:`~engine.witness.WitnessPosition` values —
        no second cursor type. ``before`` selects ``rowid < before.rowid``,
        ``after`` selects ``rowid > after.rowid`` (both exclusive; they
        compose into a window). Each is A10-verified against THIS store via
        :func:`~engine.witness.verify_position_for_store` before its rowid
        is applied — a foreign position is re-resolved (same lineage) or
        refused (:class:`~engine.witness.WitnessLineageMismatch`), never
        silently applied.

        Filters: ``kind`` matches the kind and its dotted subtree by exact
        binary compare — equality or a ``substr``-based ``'kind.'`` prefix,
        never ``LIKE`` (``_``/``%`` are LIKE wildcards and LIKE is ASCII
        case-insensitive) — same rule as :meth:`facts_between`;
        ``observer`` matches with :func:`engine.observer.observer_matches`
        namespacing semantics (``kyle/loops-claude`` matches bare
        ``loops-claude`` and vice versa), applied IN SQL so ``limit``
        bounds the matching rows, not a pre-filter superset; ``_decl.*``
        is excluded unless ``include_internal=True`` (SPEC §9.4).

        SNAPSHOT: the page SELECT and the ``next``-cursor resolution run
        inside ONE ``BEGIN DEFERRED`` read transaction (opened here, or
        joined if the caller already holds :meth:`snapshot` — same
        connection is NOT same snapshot without it), so ``items``,
        ``truncated``, and ``next`` all describe a single store state. A
        caller paginating across calls who needs full-walk consistency
        against concurrent writers wraps the whole walk in
        :meth:`snapshot`; without it, each page is internally consistent
        and the cursor arithmetic still guarantees no duplicates for
        ``newest`` walks (new rows land at higher rowids than any
        ``before`` cursor) while an ``oldest`` walk tails new appends —
        the honest append-only reading.

        Truncation is probed by over-fetching one row: ``truncated`` is
        True iff a ``limit+1``-th matching row existed in this snapshot,
        and then ``next`` is the :class:`WitnessPosition` of the page's
        last item (resolved with ``group_boundary="allow"`` — a page
        boundary is a read-progress token, not a fold cut, so the A2
        mid-ceremony refusal does not apply). Feed ``next`` back as
        ``before`` for ``"newest"`` or ``after`` for ``"oldest"``.
        """
        from .witness import (
            _resolve_witness_position_on_conn,
            verify_position_for_store,
        )

        if order not in ("newest", "oldest"):
            raise ValueError(
                f"query_facts: order must be 'newest' or 'oldest', got {order!r}"
            )
        if limit < 1:
            raise ValueError(f"query_facts: limit must be >= 1, got {limit}")

        clauses: list[str] = []
        params: list = []
        if before is not None:
            before = verify_position_for_store(before, self._path)
            clauses.append("rowid < ?")
            params.append(before.rowid)
        if after is not None:
            after = verify_position_for_store(after, self._path)
            clauses.append("rowid > ?")
            params.append(after.rowid)
        if kind is not None:
            from .sql_util import kind_subtree_predicate

            kind_sql, kind_params = kind_subtree_predicate(kind)
            clauses.append(kind_sql)
            params.extend(kind_params)
        if observer is not None:
            # observer_matches semantics in SQL: exact, or one side bare
            # matching the other's namespace tail. No LIKE/GLOB wildcards —
            # the tail test is a suffix compare, immune to metacharacters
            # in observer names.
            if "/" in observer:
                clauses.append("(observer = ? OR observer = ?)")
                params.extend([observer, observer.rsplit("/", 1)[1]])
            else:
                clauses.append(
                    "(observer = ? OR substr(observer, -?, ?) = ?)"
                )
                tail = "/" + observer
                params.extend([observer, len(tail), len(tail), tail])
        if not include_internal:
            clauses.append("kind NOT GLOB '_decl.*'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        direction = "DESC" if order == "newest" else "ASC"

        own_txn = not self._conn.in_transaction
        if own_txn:
            self._conn.execute("BEGIN DEFERRED")
        try:
            rows = self._conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts "
                f"{where} ORDER BY rowid {direction} LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            truncated = len(rows) > limit
            rows = rows[:limit]
            next_pos = None
            if truncated:
                next_pos = _resolve_witness_position_on_conn(
                    self._conn, self._path, rows[-1][0], group_boundary="allow",
                )
        finally:
            if own_txn:
                self._conn.rollback()
        return FactPage(
            items=[self._fact_row_to_dict(r) for r in rows],
            next=next_pos,
            truncated=truncated,
            order=order,
        )

    @contextmanager
    def snapshot(self) -> "Iterator[StoreReader]":
        """Pin ONE read snapshot across several reads on this connection.

        ``BEGIN DEFERRED`` takes the snapshot at the first read and holds it
        until the transaction ends, so a certify-then-query pair observes a
        single consistent state. Without it, sharing a connection is not
        sharing a snapshot — each statement autocommits and a concurrent
        writer can land between them (sol P2-a round 2). The reader is
        query_only, so the transaction always ends in rollback; there is
        nothing to commit.
        """
        self._conn.execute("BEGIN DEFERRED")
        try:
            yield self
        finally:
            self._conn.rollback()

    def fts_generation(self) -> str | None:
        """The declaration fingerprint the FTS index was last built for.

        ``None`` when the index or its state table doesn't exist, or when it
        predates fingerprint recording. Read on THIS reader's connection so a
        caller can certify and query without a connection boundary between
        them (sol P2-a).
        """
        try:
            row = self._conn.execute(
                "SELECT value FROM fts_state WHERE key='decl_fingerprint'"
            ).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    def search_facts(
        self,
        query: str,
        *,
        kind: str | None = None,
        kinds: Iterable[str] | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """FTS5 search over fact payloads.

        Requires facts_fts virtual table to exist (built only by the explicit
        vertex_reader.vertex_reindex — reads never create or update the index).
        Returns newest-first, same dict shape as facts_between.

        ``kinds`` restricts the SQL-level result set to a SET of kinds
        BEFORE ``limit`` is applied — distinct from ``kind`` (an exact
        single-kind filter, which takes precedence if both are given). This
        matters when a caller only trusts a SUBSET of what's actually
        indexed (e.g. one indexed kind is stale, another is fresh): without
        a SQL-level restriction, the stale kind's many old matches can crowd
        the newest-``limit`` window and silently push out the fresh kind's
        genuinely-matching rows before the caller ever gets a chance to
        filter them out post-hoc (S2 sol P2 — the exact defect class this
        slice exists to kill). An explicit empty ``kinds`` matches nothing,
        by design (an empty allowlist is not "no restriction").
        """
        # Query-time internal exclusion (SPEC §9.4, defense in depth): internal
        # kinds get no search fields so they never ENTER the index, but a
        # mis-registered declaration must still not LEAVE it via search —
        # unless the caller explicitly targets a _decl.* kind.
        clauses = ["facts_fts MATCH ?", "fts.kind NOT GLOB '_decl.*'"]
        params: list = [query]

        if kind is not None:
            clauses.remove("fts.kind NOT GLOB '_decl.*'")
            clauses.append("fts.kind = ?")
            params.append(kind)
        elif kinds is not None:
            kinds = list(kinds)
            if not kinds:
                return []  # explicit empty allowlist matches nothing
            clauses.remove("fts.kind NOT GLOB '_decl.*'")
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"fts.kind IN ({placeholders})")
            params.extend(kinds)
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


def fact_signatures(
    store_path: Path, ids: Iterable[str], *, timeout: float = 5.0
) -> dict[str, str | None]:
    """Read-only batched lookup of the ``facts.signature`` column by fact id.

    The ONLY source of per-fact signatures for the canonical review projection
    (0.9.0 S4): the fold/Surface path drops signatures entirely, so a review
    that carries authorship must read the column directly.

    Custody constraint: the column is read VERBATIM — a signature travels
    exactly as stored, never recomputed or re-signed. Opens the store read-only
    (URI ``mode=ro``, mirroring ``declaration._open_readonly``) so the lookup
    never mutates it and is safe alongside a concurrent WAL writer, consistent
    with the S2 read-purity posture.

    PRAGMA-probes the ``signature`` column: on a pre-signature store (the column
    is absent) EVERY requested id maps to ``None`` rather than raising
    (``no such column``). An id with no matching row, or a stored NULL signature,
    also maps to ``None``. The returned dict has exactly one entry per DISTINCT
    requested id (insertion order preserved for determinism); passing no ids
    returns ``{}``.

    A module-level function, not a :class:`StoreReader` method, so the app layer
    reaches per-fact signatures through the public ``engine`` surface without
    importing ``StoreReader`` directly (the architecture ratchet).
    """
    wanted = list(dict.fromkeys(ids))  # de-dupe, preserve first-seen order
    out: dict[str, str | None] = dict.fromkeys(wanted, None)
    if not wanted:
        return out
    try:
        conn = sqlite3.connect(
            f"file:{store_path}?mode=ro", uri=True, timeout=timeout
        )
    except sqlite3.Error:
        return out
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        if "signature" not in cols:
            return out
        # Chunk the IN (...) set to stay well under SQLite's bound-variable
        # ceiling (default 999) on a large fold.
        for start in range(0, len(wanted), 500):
            chunk = wanted[start : start + 500]
            placeholders = ",".join("?" * len(chunk))
            for fid, sig in conn.execute(
                f"SELECT id, signature FROM facts WHERE id IN ({placeholders})",
                chunk,
            ):
                out[fid] = sig
    except sqlite3.Error:
        # A malformed/locked store degrades to all-None rather than aborting a
        # read-only review — same posture as declaration._open_readonly.
        return out
    finally:
        conn.close()
    return out
