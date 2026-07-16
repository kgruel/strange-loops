"""Store command — fetch store data for inspection.

Pure data fetch, no rendering knowledge.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def _bucket_timestamps(timestamps: list[float], width: int) -> list[float]:
    """Bucket timestamps into equal-width time bins, return counts per bin.

    *timestamps* should be sorted newest-first (as returned by
    ``StoreReader.tick_timestamps``).  Returns *width* floats — one
    count per bin, ordered oldest→newest so the visual reads left-to-right.
    """
    if not timestamps or width <= 0:
        return []
    lo, hi = min(timestamps), max(timestamps)
    if lo == hi:
        # All ticks at same instant — single spike in the middle
        buckets = [0.0] * width
        buckets[width // 2] = float(len(timestamps))
        return buckets
    span = hi - lo
    buckets = [0.0] * width
    for ts in timestamps:
        idx = int((ts - lo) / span * (width - 1))
        idx = max(0, min(idx, width - 1))
        buckets[idx] += 1.0
    return buckets


def _sparkline_str(values: list[float]) -> str:
    """Map bucket counts to sparkline characters."""
    if not values:
        return ""
    mx = max(values)
    if mx == 0:
        return " " * len(values)
    return "".join(
        _SPARK_CHARS[int(v / mx * (len(_SPARK_CHARS) - 1))]
        for v in values
    )


def resolve_store_path(file_path: Path) -> Path:
    """Resolve a .vertex or .db file to the actual store .db path."""
    if file_path.suffix == ".vertex":
        from lang import parse_vertex_file

        ast = parse_vertex_file(file_path)
        if ast.store is None:
            raise ValueError(f"No store configured in {file_path}")
        return (file_path.parent / ast.store).resolve()
    elif file_path.suffix == ".db":
        return file_path.resolve()
    else:
        raise ValueError(f"Expected .vertex or .db file, got {file_path.suffix}")


def _require_materialized_store(target_path: Path) -> Path:
    """Resolve *target_path* to its store ``.db`` and require it exists.

    State 2 of the store-verb existence contract (decision/design/
    store-verb-existence-exit-code-parity): a present ``.vertex`` whose store
    ``.db`` was never written is *not yet materialized* — a distinct condition
    from *written and empty* (write-receipt-vs-temporal-query at the exit-code
    layer). All three store verbs (ticks/stats/verify) surface it as a clean
    RC=1 with a named message rather than ticks' prior silent RC=0-empty.
    """
    db_path = resolve_store_path(target_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"store for '{target_path.stem}' not yet materialized — "
            f"no facts emitted (no database at {db_path})"
        )
    return db_path


def make_fetcher(path: Path, zoom: int, *, kind: str | None = None):
    """Create a zero-arg fetcher for store data.

    zoom controls enrichment depth:
      0:   summary only (counts + stats)
      1:   + sparkline + payload_keys per tick
      2:   + latest tick payloads
      3:   + recent fact payloads

    ``kind``, when given, is the explicit ``--kind`` escape hatch (SPEC
    §9.4): the reserved ``_decl.*`` namespace is excluded from
    ``facts.kinds`` by default, but an explicit ``--kind`` ask narrows the
    listing to that one kind and includes it regardless of namespace —
    an explicit request overrides the ambient default, same rule as every
    other read surface this task touches.
    """
    def fetch() -> dict:
        from engine.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            data = reader.summary(include_internal=kind is not None)
            if kind is not None:
                data["facts"]["kinds"] = {
                    k: v for k, v in data["facts"]["kinds"].items() if k == kind
                }
            data["freshness"] = reader.freshness
            if zoom >= 1:
                # Sparkline + payload keys per tick name
                for name, info in data["ticks"]["names"].items():
                    ts_list = reader.tick_timestamps(name, 50)
                    buckets = _bucket_timestamps(ts_list, 8)
                    info["sparkline"] = _sparkline_str(buckets)
                    # Extract payload key names from latest tick
                    recent = reader.recent_ticks(name, 1)
                    info["payload_keys"] = (
                        list(recent[0].payload.keys()) if recent else []
                    )
                # Keep sample payload per fact kind for SUMMARY gist
                for fkind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(fkind, 1)
                    if recent:
                        info["sample_payload"] = recent[0]["payload"]
            if zoom >= 2:
                for name, info in data["ticks"]["names"].items():
                    recent = reader.recent_ticks(name, 3)
                    if recent:
                        info["latest_payload"] = recent[0].payload
                        info["latest_since"] = recent[0].since.timestamp() if recent[0].since else None
                        info["latest_ts"] = recent[0].ts.timestamp()
            if zoom >= 3:
                for fkind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(fkind, 5)
                    info["recent"] = [f["payload"] for f in recent]
            return data
    return fetch


def _resolve_target(file_arg: str | None, vertex_path: Path | None) -> Path:
    """Resolve the store target: explicit vertex_path > file/name arg > local root.

    State 1 of the store-verb existence contract (decision/design/
    store-verb-existence-exit-code-parity): when a named/explicit target
    resolves to a path that does not exist, raise a clean ``FileNotFoundError``
    here — the single shared chokepoint all three store verbs (ticks/stats/
    verify) pass through — so an absent ``.vertex`` reads as "X does not exist"
    rather than leaking a raw ``[Errno 2]`` from a downstream parse.
    """
    from .resolve import loops_home

    if vertex_path is not None:
        return vertex_path
    if file_arg is not None:
        p = Path(file_arg)
        if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
            target = p
        else:
            # Local-first — same resolution the verbs use
            # (thread:global-local-walk-broken).
            from .resolve import _resolve_vertex_for_dispatch

            resolved = _resolve_vertex_for_dispatch(file_arg)
            if resolved is not None:
                target = resolved
            else:
                from lang.population import resolve_vertex

                target = resolve_vertex(file_arg, loops_home())
        # State 1 covers the .vertex/name target only: an absent .db is a
        # state-2 (materialization) concern handled downstream by
        # _require_materialized_store, and the verbs that forbid a .db target
        # (ticks/reanchor) reject it by suffix with a more useful message — so
        # an existence check here must not pre-empt those.
        if target.suffix != ".db" and not target.exists():
            raise FileNotFoundError(f"{file_arg} does not exist")
        return target
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    raise FileNotFoundError(f"{root} not found. Run 'loops init' first.")


def _run_verify(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Verify the tick hash chain of a store. Exit 0 = intact, 1 = broken.

    Read-only — never migrates schema. Pre-chain stores report all ticks
    as legacy and pass (nothing to verify yet).
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="loops store verify",
        description="Verify tick hash chain and fact-window commitments.",
    )
    if vertex_path is None:
        p.add_argument("file", nargs="?", help="Store .db or .vertex file, or vertex name")
    p.add_argument("--json", action="store_true", help="JSON report")
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Per-tick attestation rows for the chained era "
             "(signature status, window fact count, cursor target)",
    )
    # -h/--help is owned by argparse (add_help=True): parse_args prints the
    # help built from this parser and exits 0 natively. No hand-rolled block.
    args = p.parse_args(argv)

    try:
        target_path = _resolve_target(getattr(args, "file", None), vertex_path).resolve()
        db_path = _require_materialized_store(target_path)
    except (FileNotFoundError, ValueError) as exc:
        # F2 — three-verb --json parity: verify is hand-rolled and raises
        # before its --json branch, so without this an absent target / absent
        # .db / aggregate would emit PLAIN text under --json (a JSONDecodeError
        # for a machine consumer) where store stats emits {"error": ...} via
        # run_cli's _export_json. Match that shape. Non-json errors re-raise to
        # the cli/views boundary for the normal plain rendering (unchanged).
        if args.json:
            import json as _json
            print(_json.dumps({"error": str(exc)}))  # noqa: T201 — machine output path
            return 1
        raise

    # Tick-signature verification composes here (injection, not import):
    # the observer-key registry lives in the .vertex, so a raw .db target
    # verifies the chain but cannot check signatures.
    from custody import fact_verifier_for, tick_verifier_for

    verifier, declared_keys = tick_verifier_for(target_path)
    fact_verifier, _fact_keys = fact_verifier_for(target_path)

    from atoms import Fact
    from engine.sqlite_store import SqliteStore

    store = SqliteStore(path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    try:
        report = store.verify_chain(verifier=verifier, include_ticks=args.verbose)
        fact_report = store.verify_facts(verifier=fact_verifier)
    finally:
        store.close()

    if args.json:
        import json as _json
        print(_json.dumps({**report, "fact_signatures": fact_report}, indent=2))  # noqa: T201 — machine output path
        return 0 if report["ok"] and fact_report["ok"] else 1

    from painted import Block, Style, join_vertical, paint
    from painted.views import Severity, callout

    ok = report["ok"] and fact_report["ok"]
    total_facts = report["covered_facts"] + report["uncovered_facts"]
    if not report["ok"]:
        verdict, verdict_sev = "CHAIN BROKEN", Severity.ERROR
    elif not fact_report["ok"]:
        verdict, verdict_sev = "FACT SIGNATURES BROKEN", Severity.ERROR
    else:
        verdict, verdict_sev = "chain intact", Severity.SUCCESS

    # Composed, never Block.text("\n".join(...)): painted 0.4.0 neutralizes a
    # raw \n to a space at the cell level, so multi-line must be real rows
    # (friction:block-text-multiline-passthrough-broke-on-040).
    blocks: list[Block] = [
        callout(f"{db_path.name} — {verdict}", severity=verdict_sev),
    ]

    def row(text: str) -> None:
        blocks.append(Block.text(f"  {text}", Style(dim=False)))

    # Three orthogonal axes, labeled so they stop reading as competing
    # fractions of one total (disclosure-grammar item b):
    #   chain      — tick hash chain integrity
    #   coverage   — which facts are sealed under a tick window
    #   authorship — per-fact signatures (delta 3); independent of coverage
    chain_bits = [f"{report['ticks']} ticks"]
    if report["chained"]:
        chain_bits.append(f"{report['chained']} chained")
    if report["legacy"]:
        chain_bits.append(f"{report['legacy']} legacy")
    if report["signed"]:
        chain_bits.append(f"{report['signed']} signed")
    chain_line = "chain        " + " · ".join(chain_bits)
    if report["signed"] and report["sig_checked"]:
        plural = "s" if len(declared_keys) != 1 else ""
        chain_line += f" · verified against registry ({len(declared_keys)} key{plural})"
    elif report["signed"]:
        chain_line += " · unchecked (no keys in registry — verify via the .vertex)"
    row(chain_line)

    if report["uncovered_facts"]:
        row(
            f"coverage     {report['covered_facts']}/{total_facts} facts sealed "
            f"under a tick · {report['uncovered_facts']} on live edge"
        )
    else:
        row(f"coverage     {report['covered_facts']}/{total_facts} facts sealed under a tick")

    if fact_report["signed"]:
        checked = "checked against registry" if fact_report["sig_checked"] else (
            "unchecked (no keys in registry)"
        )
        row(f"authorship   {fact_report['signed']}/{total_facts} facts signed · {checked}")
    elif fact_report["facts"]:
        row(f"authorship   0/{total_facts} facts signed (pre-signature era)")

    # The strip-attack tripwires stay WARNING: a benign pre-signing store and a
    # malicious live-edge strip currently look identical here, and under-alarming
    # a real strip is worse than the false-positive. Honest fix (per-observer
    # pre-signing-vs-live-edge detection) is deferred to
    # thread:verify-strip-vs-presigning-detection (disclosure-grammar item c).
    if declared_keys and report["chained"] and not report["signed"]:
        blocks.append(callout(
            "registry declares signing key(s) but no tick is signed",
            severity=Severity.WARNING,
            detail="pre-signing store, or signatures stripped — the registry is the external anchor",
        ))
    if _fact_keys:
        silent = [
            name for name in _fact_keys
            if fact_report["observers"].get(name, {}).get("signed", 0) == 0
            and fact_report["observers"].get(name, {}).get("unsigned", 0) > 0
        ]
        if silent and fact_report["signed"]:
            blocks.append(callout(
                f"keyed observer(s) with no signed facts: {', '.join(silent)}",
                severity=Severity.WARNING,
                detail="pre-signing era, or signatures stripped on the live edge",
            ))

    for b in report["breaks"]:
        blocks.append(callout(
            f"{b['name']} ({b['tick']})", severity=Severity.ERROR, detail=b["reason"]
        ))
    for b in fact_report["breaks"]:
        blocks.append(callout(
            f"fact {b['fact']} ({b['observer']}/{b['kind']})",
            severity=Severity.ERROR, detail=b["reason"],
        ))
    if report["truncated"] or fact_report["truncated"]:
        row(f"… stopped after {len(report['breaks']) + len(fact_report['breaks'])} breaks")
    if args.verbose and report.get("tick_detail"):
        from datetime import datetime, timezone

        row("chained ticks (append order):")
        for t in report["tick_detail"]:
            ts = datetime.fromtimestamp(t["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            if not t["signed"]:
                sig = "unsigned"
            elif t["sig_ok"] is None:
                sig = "signed (unchecked)"
            else:
                sig = "sig ✓" if t["sig_ok"] else "sig ✗"
            cursor = t["cursor_kind"] or "?"
            if t["cursor_preview"]:
                cursor += f': "{t["cursor_preview"]}"'
            row(
                f"  {'✓' if t['ok'] else '✗'} {ts} {t['name']} · {sig} · "
                f"{t['window_facts']} facts · cursor → {cursor}"
            )
    paint(join_vertical(*blocks))
    return 0 if ok else 1


def _run_rebirth(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Rebirth a store: transform-replay into a new store, with receipt.

    The reborn store is a NEW custody context — facts replay in witness
    order through a deterministic transform, old ticks re-enter as facts
    (envelope verbatim), a receipt fact records the source's identity
    (content hash, file hash, chain head), and a genesis tick seals
    everything including the receipt. The source is never modified;
    swapping the reborn store in is a deliberate, separate act.

    Signing composes from the source vertex's key custody: the new
    incarnation is the same identity's next chapter, so the lineage's
    key signs its genesis. A rebirth is immediately verified (re-run
    the transform, diff); ``--check`` re-verifies an existing one.
    """
    import argparse
    import os

    p = argparse.ArgumentParser(
        prog="loops store rebirth",
        description="Replay a store through a transform into a new store, "
                    "with a verifiable receipt and a sealed genesis tick.",
    )
    if vertex_path is None:
        p.add_argument("source", help="Source store .db or .vertex file, or vertex name")
    p.add_argument("target", help="Path for the reborn .db (must not exist; with --check: must exist)")
    p.add_argument(
        "--rule", default="identity", choices=["identity", "ulid-migration"],
        help="Transform: identity (re-seal/cleanup) or ulid-migration "
             "(deterministically migrate uuid4-era ids to event-time ULIDs)",
    )
    p.add_argument(
        "--observer", default=None,
        help="Who performs the rebirth (default: $LOOPS_OBSERVER or 'rebirth')",
    )
    p.add_argument(
        "--check", action="store_true",
        help="Verify an existing rebirth instead of performing one "
             "(re-run the transform, diff the target)",
    )
    p.add_argument("--json", action="store_true", help="JSON receipt/report")
    # -h/--help is owned by argparse (add_help=True): parse_args prints the
    # help built from this parser and exits 0 natively. No hand-rolled block.
    args = p.parse_args(argv)

    src_target = _resolve_target(getattr(args, "source", None), vertex_path).resolve()
    src_db = resolve_store_path(src_target)
    if not src_db.exists():
        raise FileNotFoundError(f"{src_db} does not exist")
    target = Path(args.target)

    from store import identity, rebirth_store, ulid_migration, verify_rebirth

    transform = {"identity": identity, "ulid-migration": ulid_migration}[args.rule]()
    observer = args.observer or os.environ.get("LOOPS_OBSERVER") or "rebirth"

    # Signing/verification compose from the SOURCE vertex's custody — the
    # reborn store is the same lineage's next incarnation (injection, not
    # import; raw .db source → unsigned genesis, honest pre-signature era).
    from custody import tick_signer_for, tick_verifier_for

    signer = tick_signer_for(src_target)
    verifier, _keys = tick_verifier_for(src_target)

    result = None
    if not args.check:
        result = rebirth_store(
            src_db, target,
            transform=transform,
            tick_signer=signer,
            observer=observer,
            source_name=src_db.stem,
        )
    verification = verify_rebirth(src_db, target, transform=transform, verifier=verifier)

    if args.json:
        import dataclasses
        import json as _json

        report = {"verification": dataclasses.asdict(verification)}
        if result is not None:
            report["rebirth"] = dataclasses.asdict(result)
        print(_json.dumps(report, indent=2))  # noqa: T201 — machine output path
        return 0 if verification.ok else 1

    from painted import Block, Style, paint

    mark = "✓" if verification.ok else "✗"
    lines = []
    if result is not None:
        lines.append(f"{mark} {src_db.name} → {target.name}: rebirth (rule={args.rule})")
        lines.append(
            f"  facts: {result.facts_in} in, {result.facts_out} out "
            f"({result.ids_migrated} ids migrated, {result.filtered} filtered)"
        )
        lines.append(f"  ticks: {result.ticks_in} re-entered as facts")
        lines.append(
            f"  receipt: {result.receipt_id} · genesis tick "
            f"{'signed' if result.tick_signed else 'unsigned (no key for source vertex)'}"
        )
    else:
        lines.append(f"{mark} {src_db.name} → {target.name}: rebirth check (rule={args.rule})")
    checks = [
        ("re-run diff clean" if not verification.mismatches
         else f"{len(verification.mismatches)} row mismatches"),
        ("receipt found" if verification.receipt_found else "RECEIPT MISSING"),
        ("counts match" if verification.counts_match else "COUNTS DISAGREE"),
        ("source content match" if verification.source_content_match
         else "SOURCE CHANGED since rebirth"),
        ("chain intact" if verification.chain_ok else "CHAIN BROKEN"),
    ]
    lines.append(f"  verified: {' · '.join(checks)} ({verification.facts_checked} facts checked)")
    for m in verification.mismatches:
        lines.append(f"  ✗ {m}")
    # Compose real rows — Block.text("\n".join(...)) flattens to one line
    # under painted 0.4.0 (friction:block-text-multiline-passthrough-broke-on-040).
    from painted import join_vertical
    paint(join_vertical(*(Block.text(ln, Style(dim=False)) for ln in lines)))
    return 0 if verification.ok else 1


def _run_reanchor(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Re-anchor a store's attestation layer under the current canonical
    encoding (SPEC §8.1: canon migrations re-anchor, never grandfather).

    Requires a .vertex target — the signing keys and observer registry
    live in the custody context, not the raw .db. Re-signs signed facts,
    re-links the chain, then verifies the result against the registry.
    Exit 0 = re-anchored and verified, 1 = post-reanchor verify failed.
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="loops store reanchor",
        description="Recompute chain hashes and signatures under the "
                    "current canonical encoding, then verify.",
    )
    if vertex_path is None:
        p.add_argument("file", nargs="?", help="Vertex .vertex file or vertex name")
    p.add_argument("--json", action="store_true", help="JSON receipt")
    # -h/--help is owned by argparse (add_help=True): parse_args prints the
    # help built from this parser and exits 0 natively. No hand-rolled block.
    args = p.parse_args(argv)

    target_path = _resolve_target(getattr(args, "file", None), vertex_path).resolve()
    if target_path.suffix != ".vertex":
        raise ValueError(
            "reanchor requires a .vertex target — re-signing needs the "
            "keys and registry co-located with the store"
        )
    db_path = resolve_store_path(target_path)
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} does not exist")

    from custody import (
        fact_signer_for, fact_verifier_for, tick_signer_for, tick_verifier_for,
    )

    from atoms import Fact
    from engine.sqlite_store import SqliteStore

    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        tick_signer=tick_signer_for(target_path),
        fact_signer=fact_signer_for(target_path),
    )
    try:
        receipt = store.reanchor()
        verifier, _keys = tick_verifier_for(target_path)
        fact_verifier, _fkeys = fact_verifier_for(target_path)
        report = store.verify_chain(verifier=verifier)
        fact_report = store.verify_facts(verifier=fact_verifier)
    finally:
        store.close()

    ok = report["ok"] and fact_report["ok"]
    if args.json:
        import json as _json
        print(_json.dumps({**receipt, "verified": ok}, indent=2))  # noqa: T201 — machine output path
        return 0 if ok else 1

    from painted import Block, Style, paint

    head = receipt["head"][:16] + "…" if receipt["head"] else "(no chain)"
    paint(Block.text(
        f"{'✓' if ok else '✗'} {db_path.name}: re-anchored — "
        f"{receipt['facts_resigned']} facts re-signed, "
        f"{receipt['ticks_rechained']} ticks re-chained "
        f"({receipt['ticks_resigned']} re-signed) · head {head} · "
        f"verify {'ok' if ok else 'FAILED'}",
        Style(),
    ))
    return 0 if ok else 1


def _read_absorption_state(
    db_path: Path,
) -> tuple[bool, str | None, str | None, bool]:
    """Read (has_genesis, chain_head, fact_cursor, has_marker) for absorb.

    SPEC §9.2 era rule: a genesis pins "everything before me predates
    historization" — a verifiable claim, not an inference from row order.

    - ``has_genesis`` — a ``_decl.genesis`` fact already exists (this store
      has opened its lineage; re-absorb / edit is S4, so absorb refuses).
    - ``chain_head`` — the row-identity hash of the latest *chained* tick
      (what a successor tick's ``prev_hash`` commits to), or None when the
      store has no chained tick. A pre-chain-only store pins on the cursor.
    - ``fact_cursor`` — the id of the newest fact by WITNESS order (rowid),
      matching ``append_tick``'s cursor authority — or None on empty.

    ``has_marker`` — the ``store_meta.own_lineage`` identity marker exists.
    Genesis rows WITHOUT a marker are unclaimable (pre-marker store, or a
    merged foreign genesis) — absorb refuses with adopt guidance rather than
    inferring identity from facts.

    A not-yet-materialized store (no ``.db``, or a schemaless file) returns
    ``(False, None, None, False)``: genesis becomes its first fact.
    """
    import sqlite3

    if not db_path.exists():
        return False, None, None, False

    from engine.sqlite_store import (
        _TICK_ROW_SQL,
        _TICK_ROW_SQL_V1,
        tick_row_hash,
    )
    from lang.document import DECL_GENESIS

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only=ON")
    try:
        try:
            has_genesis = (
                conn.execute(
                    "SELECT 1 FROM facts WHERE kind = ? LIMIT 1", (DECL_GENESIS,)
                ).fetchone()
                is not None
            )
            frow = conn.execute(
                "SELECT id FROM facts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            fact_cursor = frow[0] if frow else None
        except sqlite3.OperationalError:
            # Schemaless / non-store file — nothing absorbed, nothing to pin.
            return False, None, None, False

        chain_head: str | None = None
        try:
            tcols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
            if "window_hash" in tcols:
                row_sql = _TICK_ROW_SQL if "signature" in tcols else _TICK_ROW_SQL_V1
                row = conn.execute(
                    f"SELECT {row_sql} FROM ticks "
                    "WHERE window_hash IS NOT NULL ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if row is not None:
                    # tick_row_hash reads an 11-field row (signature at [10]);
                    # a delta-1 schema yields 10, pad the signature slot NULL.
                    chain_head = tick_row_hash(row if len(row) > 10 else (*row, None))
        except sqlite3.OperationalError:
            pass

        has_marker = False
        try:
            has_marker = (
                conn.execute(
                    "SELECT 1 FROM store_meta WHERE key = 'own_lineage'"
                ).fetchone()
                is not None
            )
        except sqlite3.OperationalError:
            pass  # pre-marker schema

        return has_genesis, chain_head, fact_cursor, has_marker
    finally:
        conn.close()


def _run_absorb(
    argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None
) -> int:
    """Reconcile a store with its ``.vertex`` declaration (SPEC §9.2). Bimodal.

    The verb detects whether the store's lineage is open and switches ceremony:

    - **No genesis → genesis mode** (S1, :func:`_absorb_genesis_mode`): parse the
      ``.vertex`` once, decompose into subject-scoped documents, and append ONE
      signed ``_decl.genesis`` fact carrying the whole document set, the protocol
      version, and the era pins. The genesis fact's own id IS the lineage id.

    - **Genesis present → edit mode** (S4, :func:`_absorb_edit`): diff the
      freshly-parsed file against the fold head (Latest per (kind, subject),
      self-lineage) and re-emit ONLY the changed subjects as whole documents,
      tombstoning removed subjects. Unchanged file writes nothing (idempotence).

    Both ceremonies MUST be signed — declaration events are the store's
    attestation root/history; a missing signing key refuses (exit 2). ``-n`` is
    read-only: genesis mode previews the absorb, edit mode surfaces which
    subjects diverge from the store head (the sole divergence surface — nothing
    auto-absorbs, and the store head stays authoritative until a real absorb).
    ``--json`` emits a machine-readable receipt.
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="loops store absorb",
        description="Reconcile a store with its .vertex declaration (SPEC §9.2). "
                    "No genesis yet → open the lineage (absorb the declaration "
                    "whole as a signed genesis event). Genesis present → edit "
                    "mode: diff the file against the store's fold head and "
                    "re-emit only the changed subjects. -n surfaces divergence "
                    "without writing.",
    )
    if vertex_path is None:
        p.add_argument("file", nargs="?", help="Vertex .vertex file or vertex name")
    p.add_argument(
        "--observer", default=None,
        help="Observer recording the genesis (default: the resolved "
             "self-observer, same resolution emit uses)",
    )
    p.add_argument("--json", action="store_true", help="JSON receipt")
    p.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Show what would be absorbed (genesis) or which subjects diverge "
             "from the store head (edit) without writing",
    )
    # -h/--help is owned by argparse (add_help=True): parse_args prints the
    # help built from this parser and exits 0 natively. No hand-rolled block.
    args = p.parse_args(argv)

    target_path = _resolve_target(getattr(args, "file", None), vertex_path).resolve()
    if target_path.suffix != ".vertex":
        raise ValueError(
            "absorb requires a .vertex target — genesis records the "
            "declaration and signs it with the vertex's co-located key"
        )
    # resolve_store_path raises ValueError('No store configured') for a pure
    # aggregate (combine/discover) vertex — those own no store, so there is
    # nothing to open a lineage over (build-plan aggregation wrinkle, deferred).
    db_path = resolve_store_path(target_path)

    # Parse the declaration ONCE — and VALIDATE it. Absorb mints immutable
    # signed events (genesis/edit rows are never rewritten), so a declaration
    # that ordinary validation rejects (e.g. a loop named into the _decl.*
    # reserved namespace) must never enter the lineage (closing review #6).
    from lang import parse_vertex_file, validate_vertex

    ast = parse_vertex_file(target_path)
    try:
        validate_vertex(ast)
    except Exception as exc:
        from painted import Block, Style, paint
        paint(Block.text(
            f"✗ {target_path.stem}: declaration invalid — {exc}", Style()
        ), file=sys.stderr)
        return 2

    # Observer resolution. Precedence: explicit ``--observer`` on the absorb
    # parser (direct/test calls) > invocation observer from the global peel >
    # resolve_observer's env/declared chain — the same resolution emit uses.
    from loops.commands.identity import resolve_observer

    explicit = args.observer if args.observer is not None else observer
    observer = resolve_observer(explicit)

    # Detect whether the store has already opened its lineage — this selects
    # the ceremony (SPEC §9.2 / §9.5). No genesis → genesis mode (open the
    # lineage, S1). Genesis present → edit mode (S4): diff the file against the
    # fold head and re-emit ONLY the changed subjects. Same verb, two ceremonies.
    has_genesis, _chain_head, _fact_cursor, has_marker = _read_absorption_state(db_path)
    if has_genesis and not has_marker:
        # Genesis rows exist but none is CLAIMED as self — a pre-marker store
        # or a merged foreign genesis. Facts alone cannot prove which; the
        # explicit adopt ceremony must run first (closing re-review #1).
        from painted import Block, Style, paint
        paint(Block.text(
            f"✗ {target_path.stem}: genesis row(s) present but no own_lineage "
            "marker — run `loops store adopt` to claim the store's own "
            "lineage before editing (identity is adopted, never inferred)",
            Style(),
        ), file=sys.stderr)
        return 2
    if has_genesis:
        return _absorb_edit(
            target_path, db_path, ast, observer,
            dry_run=args.dry_run, as_json=args.json,
        )
    return _absorb_genesis_mode(
        target_path, db_path, ast, observer,
        dry_run=args.dry_run, as_json=args.json,
    )


def _absorb_genesis_mode(
    target_path: Path,
    db_path: Path,
    ast: Any,
    observer: str,
    *,
    dry_run: bool,
    as_json: bool,
) -> int:
    """Genesis mode — open the store's lineage (SPEC §9.2 era opening, S1).

    Unchanged from the original ``absorb`` behavior; extracted so the bimodal
    dispatcher can select it when the store has no genesis yet. Its output is
    golden-locked, so the rendering is preserved verbatim.
    """
    from lang.document import DECLARATION_PROTOCOL_VERSION, genesis_payload
    from custody import fact_signer_for

    documents = genesis_payload(ast)["documents"]
    doc_count = len(documents)

    def _render(receipt: dict, *, dry_run: bool) -> None:
        chain_head, fact_cursor = receipt["chain_head"], receipt["fact_cursor"]
        if as_json:
            import json as _json
            print(_json.dumps({**receipt, "dry_run": dry_run}, indent=2))  # noqa: T201 — machine output path
            return
        from painted import Block, Style, join_vertical, paint
        verb = "would absorb" if dry_run else "genesis absorbed"
        lineage_line = (
            "  lineage: (dry-run — no genesis minted)"
            if dry_run else f"  lineage: {receipt['lineage']}"
        )
        head_disp = (chain_head[:16] + "…") if chain_head else "(no chained tick)"
        cursor_disp = fact_cursor if fact_cursor else "(empty store)"
        lines = [
            f"✓ {target_path.stem}: {verb} — protocol v{DECLARATION_PROTOCOL_VERSION}",
            lineage_line,
            f"  documents: {doc_count} subject{'s' if doc_count != 1 else ''}",
            f"  pins: chain_head {head_disp} · fact_cursor {cursor_disp}",
            f"  observer: {observer} · signed",
        ]
        paint(join_vertical(*(Block.text(ln, Style(dim=False)) for ln in lines)))

    def _refuse(msg: str) -> int:
        from painted import Block, Style, paint
        paint(Block.text(f"✗ {target_path.stem}: {msg}", Style()), file=sys.stderr)
        return 2

    if dry_run:
        # Preview only — a read-only projection of what the real (atomic) path
        # would do. Inherently racy (no write lock held); the atomicity
        # guarantees belong to the real path's single transaction.
        has_genesis, chain_head, fact_cursor, _has_marker = _read_absorption_state(db_path)
        if has_genesis:
            # Defensive: a concurrent absorb opened the lineage between the
            # dispatcher's mode check and here — fall back to the edit refusal.
            return _refuse(
                "already absorbed — a genesis event exists. Re-run absorb to "
                "reconcile an edited declaration (edit mode)."
            )
        signer = fact_signer_for(target_path)
        signable = observer and signer is not None and signer(observer, "0" * 64) is not None
        if not signable:
            why = ("no observer resolved to sign as" if not observer
                   else f"no signing key for observer '{observer}'")
            return _refuse(
                f"cannot absorb — {why}. Genesis is the lineage's attestation "
                "root and must be signed; set up signing first "
                "(loops add <vertex> observer --keygen)."
            )
        _render(
            {
                "vertex": target_path.stem, "lineage": None,
                "protocol": DECLARATION_PROTOCOL_VERSION, "documents": doc_count,
                "chain_head": chain_head, "fact_cursor": fact_cursor,
                "observer": observer, "signed": True,
            },
            dry_run=True,
        )
        return 0

    # Real path — the atomic engine primitive holds the identity check, era
    # pins, sign-final-payload, and append in ONE transaction (no TOCTOU).
    if not observer:
        return _refuse(
            "cannot absorb — no observer resolved to sign as. Genesis is the "
            "lineage's attestation root and must be signed; set up signing "
            "first (loops add <vertex> observer --keygen)."
        )

    from atoms import Fact
    from engine.sqlite_store import (
        GenesisExists,
        SqliteStore,
        UnsignableGenesis,
    )

    store = SqliteStore(
        path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    try:
        receipt = store.absorb_genesis(
            documents,
            observer=observer,
            origin="",
            fact_signer=fact_signer_for(target_path),
        )
    except GenesisExists:
        # TOCTOU: a concurrent absorb opened the lineage after the dispatcher's
        # mode check. The atomic primitive caught it — point at edit mode.
        return _refuse(
            "already absorbed — a genesis event exists. Re-run absorb to "
            "reconcile an edited declaration (edit mode)."
        )
    except UnsignableGenesis:
        return _refuse(
            f"cannot absorb — no signing key for observer '{observer}'. Genesis "
            "is the lineage's attestation root and must be signed; set up "
            "signing first (loops add <vertex> observer --keygen)."
        )
    finally:
        store.close()

    receipt["vertex"] = target_path.stem
    _render(receipt, dry_run=False)
    return 0


def _decl_short(kind: str) -> str:
    """A ``_decl.kind-defined`` → ``kind`` short label for edit-mode display."""
    label = kind[len("_decl."):] if kind.startswith("_decl.") else kind
    for suffix in ("-defined", "-retired", "-removed"):
        if label.endswith(suffix):
            return label[: -len(suffix)]
    return label


def _absorb_edit(
    target_path: Path,
    db_path: Path,
    ast: Any,
    observer: str,
    *,
    dry_run: bool,
    as_json: bool,
) -> int:
    """Edit mode — re-emit changed declaration subjects (SPEC §9.2, S4).

    The store's lineage is already open, so this is the edit ceremony: diff the
    freshly-parsed file against the fold head (Latest per (kind, subject),
    self-lineage) and re-emit ONLY the changed subjects as whole documents, plus
    a tombstone per removed subject. Unchanged file → nothing written
    (idempotence). File divergence is SURFACED via ``-n`` (the sole divergence
    surface — no auto-absorb, no silent side-picking); the store head stays
    authoritative for resolution until this runs.
    """
    from lang.document import EditRefused, diff_documents, vertex_to_documents

    from engine.declaration import (
        AmbiguousLineage,
        UnsupportedProtocol,
        resolve_declaration_documents,
    )

    def _refuse(msg: str) -> int:
        from painted import Block, Style, paint
        paint(Block.text(f"✗ {target_path.stem}: {msg}", Style()), file=sys.stderr)
        return 2

    # The edited file's document set.
    new_docs = vertex_to_documents(ast)

    # CAS token FIRST, then the head read: if a concurrent edit lands between
    # the two, the token is older than the head we diffed — absorb_edit then
    # refuses (StaleDeclarationHead) instead of interleaving, and re-running
    # picks up the moved head. Capturing in this order fails conservative.
    from atoms import Fact
    from engine.sqlite_store import SqliteStore

    _cas_store = SqliteStore(
        path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    try:
        expected_head = _cas_store.declaration_head()
    finally:
        _cas_store.close()

    # The fold head from the store. has_genesis was true at dispatch, so this is
    # normally a list; a resolution failure (ambiguous lineage, unsupported
    # protocol) or a non-list refuses cleanly rather than diffing against noise.
    try:
        head = resolve_declaration_documents(db_path)
    except (AmbiguousLineage, UnsupportedProtocol) as exc:
        return _refuse(str(exc))
    if not isinstance(head, list):
        return _refuse(
            "store head unavailable — the lineage looks unopened or unhistorized; "
            "cannot diff (nothing to reconcile against)"
        )

    # Diff. An inexpressible edit (singleton removal / identity rename) refuses.
    try:
        changes = diff_documents(head, new_docs)
    except EditRefused as exc:
        return _refuse(str(exc))

    n_def = sum(1 for c in changes if c.payload is not None)
    n_ret = len(changes) - n_def

    def _emit_json(obj: dict) -> None:
        import json as _json
        print(_json.dumps(obj, indent=2))  # noqa: T201 — machine output path

    # Idempotence: an unchanged file writes nothing.
    if not changes:
        if as_json:
            _emit_json({
                "vertex": target_path.stem, "mode": "edit",
                "diverged": False, "defined": 0, "retired": 0, "changes": [],
            })
        else:
            from painted import Block, Style, paint
            paint(Block.text(
                f"✓ {target_path.stem}: up to date — file matches store head",
                Style(dim=False),
            ))
        return 0

    change_rows = [
        {"kind": c.kind, "subject": c.subject, "change": c.annotation}
        for c in changes
    ]

    def _render_divergence(*, applied: bool) -> None:
        if as_json:
            _emit_json({
                "vertex": target_path.stem, "mode": "edit",
                "diverged": True, "applied": applied,
                "defined": n_def, "retired": n_ret,
                "observer": observer, "signed": applied,
                "changes": change_rows,
            })
            return
        from painted import Block, Style, join_vertical, paint
        if applied:
            head_line = (
                f"✓ {target_path.stem}: reconciled — "
                f"{n_def} re-emitted, {n_ret} retired"
            )
        else:
            head_line = f"✎ {target_path.stem}: file diverges from store head"
        lines = [head_line]
        for c in changes:
            mark = "−" if c.payload is None else ("+" if c.annotation == "added" else "~")
            lines.append(f"  {mark} {_decl_short(c.kind)}:{c.subject} ({c.annotation})")
        if applied:
            lines.append(f"  observer: {observer} · signed")
        else:
            lines.append("  run `loops store absorb` to reconcile")
        paint(join_vertical(*(Block.text(ln, Style(dim=False)) for ln in lines)))

    # -n / --dry-run: the divergence surface. Read-only, exit 0.
    if dry_run:
        _render_divergence(applied=False)
        return 0

    # Real path — atomic, signed re-emit of the changed subjects.
    if not observer:
        return _refuse(
            "cannot absorb — no observer resolved to sign as. A declaration "
            "edit must be signed (it enters the attestation tier); set up "
            "signing first (loops add <vertex> observer --keygen)."
        )

    from custody import fact_signer_for

    from engine.sqlite_store import (
        AmbiguousGenesis,
        NoGenesis,
        StaleDeclarationHead,
        UnsignableEdit,
    )

    store = SqliteStore(
        path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    try:
        store.absorb_edit(
            changes,
            observer=observer,
            origin="",
            fact_signer=fact_signer_for(target_path),
            expected_head=expected_head,
        )
    except StaleDeclarationHead as exc:
        return _refuse(f"{exc}")
    except UnsignableEdit:
        return _refuse(
            f"cannot absorb — no signing key for observer '{observer}'. A "
            "declaration edit must be signed; set up signing first "
            "(loops add <vertex> observer --keygen)."
        )
    except NoGenesis:
        # TOCTOU: the lineage vanished between dispatch and here (not reachable
        # in practice — stores are append-only).
        return _refuse(
            "no genesis — the store's lineage is not open; run absorb to open it"
        )
    except AmbiguousGenesis as exc:
        return _refuse(str(exc))
    finally:
        store.close()

    _render_divergence(applied=True)
    return 0


def _run_adopt(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Explicitly claim a genesis row as the store's own lineage (SPEC §9.2).

    The one legitimate path for an unmarked store (pre-marker era, or one
    holding merged foreign genesis rows) to gain identity. Facts alone cannot
    prove which genesis is self, so identity is ADOPTED under human intent —
    never inferred (a singleton heuristic is the hijack vector this closes).
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="loops store adopt",
        description="Claim a _decl.genesis row as this store's own lineage — "
                    "stamps the store_meta.own_lineage identity marker. "
                    "One-time ceremony for stores absorbed before the marker "
                    "existed (or holding merged foreign genesis rows).",
    )
    if vertex_path is None:
        p.add_argument("file", nargs="?", help="Vertex .vertex file or vertex name")
    p.add_argument(
        "--lineage", default=None,
        help="Genesis id (or unique prefix) to adopt — required when several "
             "genesis rows exist",
    )
    args = p.parse_args(argv)

    target_path = _resolve_target(getattr(args, "file", None), vertex_path).resolve()
    db_path = _require_materialized_store(target_path)

    from atoms import Fact
    from engine.sqlite_store import (
        AmbiguousGenesis,
        GenesisExists,
        NoGenesis,
        SqliteStore,
    )
    from painted import Block, Style, join_vertical, paint

    store = SqliteStore(
        path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    try:
        receipt = store.adopt_lineage(args.lineage)
    except (GenesisExists, NoGenesis, AmbiguousGenesis) as exc:
        paint(Block.text(f"✗ {target_path.stem}: {exc}", Style()), file=sys.stderr)
        return 2
    finally:
        store.close()

    from datetime import datetime, timezone
    when = datetime.fromtimestamp(receipt["ts"], tz=timezone.utc).isoformat()
    lines = [
        f"✓ {target_path.stem}: lineage adopted — {receipt['lineage']}",
        f"  genesis by {receipt['observer']} at {when}",
        f"  ({receipt['genesis_count']} genesis row(s) present; this one is now self)",
    ]
    paint(join_vertical(*(Block.text(ln, Style(dim=False)) for ln in lines)))
    return 0


def _run_store_ticks(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Read a store's tick series — the attestation chain surface.

    Default projection is density (items/facts/delta per window).
    ``--chain`` projects the stored attestation envelope per tick: chain
    linkage, signature presence, and the window cursor. This is a READ of
    the stored flags, not a re-verification — ``store verify`` walks the
    chain in append order and checks integrity; ``store ticks`` lists what
    each tick's envelope says. Requires a ``.vertex`` target: the tick
    series resolves through the vertex name and store. ``--since`` narrows
    the window; the default is the full chain (genesis and the legacy-era
    boundary are exactly what an attestation read wants to see).
    """
    import argparse
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    pre.add_argument("--chain", action="store_true", default=False)
    pre.add_argument("--since", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    target_path = _resolve_target(file_arg, vertex_path).resolve()

    help_args = (
        [HelpArg("file", "Vertex .vertex file or vertex name", positional=True)]
        if vertex_path is None else []
    )
    help_args += [
        HelpArg("--chain", "Project the attestation envelope (chain linkage, "
                "signature, window cursor) and span the full hash chain"),
        HelpArg("--since", "Narrow to ticks within a window (e.g. 7d, 24h); "
                "default is the full chain"),
    ]

    def fetch():
        import dataclasses
        from lang import parse_vertex_file

        from .fetch import fetch_tick_windows

        # Validation is deferred into fetch (mirroring store stats/verify) so
        # `store ticks --help` reaches run_cli's help handler — an eager guard
        # would raise on target resolution before help could render.
        if target_path.suffix != ".vertex":
            raise ValueError(
                "store ticks requires a .vertex target — the tick series "
                "resolves through the vertex name and store"
            )
        # Refuse aggregates: a combine/discover vertex has no own store and no
        # own chain — vertex_ticks returns empty attestation envelopes for it,
        # which would render a genuinely-signed chain as a false "all legacy".
        # The sibling store verbs already refuse storeless aggregates (via
        # resolve_store_path); ticks bypasses that path, so guard here.
        ast = parse_vertex_file(target_path)
        if ast.combine is not None or ast.discover is not None:
            raise ValueError(
                "store ticks reads one store's attestation chain; "
                f"{target_path.name} is an aggregate vertex (no own chain) — "
                "point at the instance store, e.g. .loops/<name>.vertex"
            )

        # State 2: present .vertex / absent .db is "not yet materialized" —
        # RC=1 with a surfaced message, matching stats/verify, not ticks'
        # prior silent RC=0-empty. (decision/design/
        # store-verb-existence-exit-code-parity)
        _require_materialized_store(target_path)

        # --chain spans the full hash chain (all_names) to agree with
        # `store verify`/`store stats`; density stays name-scoped (its
        # delta fields are a same-series concept).
        windows = fetch_tick_windows(
            target_path, since=known.since, all_names=known.chain
        )
        chain = {
            "ticks": len(windows),
            "chained": sum(1 for w in windows if w.chained),
            "signed": sum(1 for w in windows if w.signed),
            "legacy": sum(1 for w in windows if not w.chained),
        }
        window_dicts = [dataclasses.asdict(w) for w in windows]

        # Density default projects each tick as a sealed window of attention:
        # window-scoped fact count + kind mix + MAX tier over touched keys
        # (the TickWindow fields are cumulative fold state; these are the
        # per-window complements). Skipped under --chain — the attestation
        # projection reads the stored envelope only.
        if not known.chain:
            from .fetch import stamp_window_stats

            stamp_window_stats(target_path, window_dicts)

        return {
            "vertex": ast.name,
            "chain_mode": known.chain,
            "chain": chain,
            "since": known.since,
            "windows": window_dicts,
        }

    def renderer(data, fidelity, width):
        from ..lenses.store import tick_chain_view
        from loops.lens_resolver import zoom_from_fidelity
        return tick_chain_view(data, zoom_from_fidelity(fidelity), width)

    return run_cli(
        rest,
        fetch=fetch,
        renderer=renderer,
        default_mode=OutputMode.STATIC,
        prog="loops store ticks",
        description=(
            "Read a store's tick series. The default projects each tick as "
            "a sealed window of attention — window fact count, kind mix, "
            "span, rail tier (-v adds the touched keys); --chain projects "
            "the attestation envelope (chain linkage, signature, window "
            "cursor) per tick."
        ),
        help_args=help_args,
    )


def _run_store_stats(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Store statistics — topline totals and (``--by-kind``) a
    count-descending per-kind tally. Works on a ``.db`` or a ``.vertex``.
    """
    import argparse
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    pre.add_argument("--by-kind", dest="by_kind", action="store_true", default=False)
    pre.add_argument(
        "--kind", default=None,
        help="Narrow to one kind (escape hatch for the reserved _decl.* namespace)",
    )
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    target_path = _resolve_target(file_arg, vertex_path).resolve()

    help_args = (
        [HelpArg("file", "Store .db or .vertex file, or vertex name",
                 positional=True)]
        if vertex_path is None else []
    )

    def fetch():
        from engine.store_reader import StoreReader

        store_path = _require_materialized_store(target_path)
        with StoreReader(store_path) as reader:
            # Explicit --kind is the SPEC §9.4 escape hatch — it overrides
            # the ambient _decl.* exclusion, same rule as `loops store` base.
            summary = reader.summary(include_internal=known.kind is not None)
        if known.kind is not None:
            summary["facts"]["kinds"] = {
                k: v for k, v in summary["facts"]["kinds"].items() if k == known.kind
            }
        kinds = sorted(
            (
                {"kind": k, "count": v["count"]}
                for k, v in summary["facts"]["kinds"].items()
            ),
            key=lambda r: r["count"],
            reverse=True,
        )
        return {
            "vertex": target_path.stem,
            "by_kind": known.by_kind,
            "total_facts": summary["facts"]["total"],
            "total_ticks": summary["ticks"]["total"],
            "kind_count": len(kinds),
            "kinds": kinds,
        }

    def renderer(data, fidelity, width):
        from ..lenses.store import stats_view
        from loops.lens_resolver import zoom_from_fidelity
        return stats_view(data, zoom_from_fidelity(fidelity), width)

    return run_cli(
        rest,
        fetch=fetch,
        renderer=renderer,
        default_mode=OutputMode.STATIC,
        prog="loops store stats",
        description=(
            "Store statistics. --by-kind adds a count-descending per-kind tally."
        ),
        help_args=help_args,
    )


def _run_store(
    argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None
) -> int:
    """Run store command via painted CLI harness.

    ``observer`` is the invocation-level identity (the global ``--observer``
    peel) — threaded only into ``absorb``, which signs a genesis under a
    recording observer; every other subcommand is observer-agnostic.
    """
    import argparse
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    if argv and argv[0] == "verify":
        return _run_verify(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "rebirth":
        return _run_rebirth(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "reanchor":
        return _run_reanchor(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "absorb":
        return _run_absorb(argv[1:], vertex_path=vertex_path, observer=observer)
    if argv and argv[0] == "adopt":
        return _run_adopt(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "ticks":
        return _run_store_ticks(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "stats":
        return _run_store_stats(argv[1:], vertex_path=vertex_path)

    # Base inspect: pre-parse the optional ``file`` target; run_cli owns -h
    # and the -i/-q/-v/--json/--plain axes, listing ``file`` (when accepted)
    # via help_args (decision:design/devtools-help-args-idiom).
    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    pre.add_argument(
        "--kind", default=None,
        help="Narrow to one kind (escape hatch for the reserved _decl.* namespace)",
    )
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    help_args = (
        [HelpArg("file", "Store .db or .vertex file, or vertex name",
                 positional=True)]
        if vertex_path is None else []
    )

    def _resolve_store_target() -> Path:
        return _resolve_target(file_arg, vertex_path)

    def fetch():
        path = _resolve_store_target().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        data = make_fetcher(path, zoom=3, kind=known.kind)()
        # Lead the MINIMAL one-liner with the store name (spine dot-grammar),
        # matching the store ticks/stats surfaces — the vertex name is the
        # store stem, known here at the call site.
        data.setdefault("vertex", path.stem)
        return data

    def renderer(data, fidelity, width):
        from ..lenses.store import store_view
        from loops.lens_resolver import zoom_from_fidelity
        return store_view(data, zoom_from_fidelity(fidelity), width)

    async def fetch_stream():
        import asyncio

        while True:
            try:
                yield fetch()
            except FileNotFoundError:
                pass
            await asyncio.sleep(2.0)

    def handle_interactive(ctx):
        import asyncio as _asyncio
        from ..tui import StoreExplorerApp

        path = _resolve_store_target().resolve()
        app = StoreExplorerApp(path)
        _asyncio.run(app.run())
        return 0

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        renderer=renderer,
        handlers={OutputMode.INTERACTIVE: handle_interactive},
        default_mode=OutputMode.STATIC,
        prog="loops store",
        description=(
            "Inspect store contents. Subcommands: "
            "'loops store verify [target]' checks the tick hash chain; "
            "'loops store rebirth <source> <target>' replays a store "
            "through a transform with a verifiable receipt; "
            "'loops store reanchor <vertex>' recomputes chain hashes; "
            "'loops store absorb <vertex>' opens the declaration lineage "
            "with a signed genesis event."
        ),
        help_args=help_args,
    )


def make_fidelity_fetcher(path: Path):
    """Create a fetcher for fidelity drill data.

    Returns a callable (since_ts, until_ts, kind?) -> list[dict].
    Each call opens and closes its own StoreReader — the TUI calls this
    on-demand when the user presses 'f', not on every frame.
    """
    def fetch(since_ts: float, until_ts: float, kind: str | None = None) -> list[dict]:
        from engine.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            return reader.facts_between(since_ts, until_ts, kind=kind)
    return fetch
