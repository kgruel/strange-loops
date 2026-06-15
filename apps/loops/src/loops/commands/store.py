"""Store command — fetch store data for inspection.

Pure data fetch, no rendering knowledge.
"""
from __future__ import annotations

from pathlib import Path

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


def make_fetcher(path: Path, zoom: int):
    """Create a zero-arg fetcher for store data.

    zoom controls enrichment depth:
      0:   summary only (counts + stats)
      1:   + sparkline + payload_keys per tick
      2:   + latest tick payloads
      3:   + recent fact payloads
    """
    def fetch() -> dict:
        from engine.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            data = reader.summary()
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
                for kind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(kind, 1)
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
                for kind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(kind, 5)
                    info["recent"] = [f["payload"] for f in recent]
            return data
    return fetch


def _resolve_target(file_arg: str | None, vertex_path: Path | None) -> Path:
    """Resolve the store target: explicit vertex_path > file/name arg > local root."""
    from .resolve import loops_home

    if vertex_path is not None:
        return vertex_path
    if file_arg is not None:
        p = Path(file_arg)
        if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
            return p
        # Local-first — same resolution the verbs use
        # (thread:global-local-walk-broken).
        from .resolve import _resolve_vertex_for_dispatch

        resolved = _resolve_vertex_for_dispatch(file_arg)
        if resolved is not None:
            return resolved
        from lang.population import resolve_vertex

        return resolve_vertex(file_arg, loops_home())
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

    target_path = _resolve_target(getattr(args, "file", None), vertex_path).resolve()
    db_path = resolve_store_path(target_path)
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} does not exist")

    # Tick-signature verification composes here (injection, not import):
    # the observer-key registry lives in the .vertex, so a raw .db target
    # verifies the chain but cannot check signatures.
    from loops.commands.signing import fact_verifier_for, tick_verifier_for

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

    from painted import Block, Style, show

    ok = report["ok"] and fact_report["ok"]
    if not report["ok"]:
        verdict = "CHAIN BROKEN"
    elif not fact_report["ok"]:
        verdict = "FACT SIGNATURES BROKEN"
    else:
        verdict = "chain intact"
    lines = [
        f"{'✓' if ok else '✗'} {db_path.name}: {verdict}",
        f"  ticks: {report['ticks']} ({report['chained']} chained, "
        f"{report['legacy']} legacy, {report['signed']} signed)",
        f"  facts: {report['covered_facts']} covered, {report['uncovered_facts']} uncovered (live edge)",
    ]
    if report["signed"] and report["sig_checked"]:
        lines.append(
            f"  signatures: {report['signed']} checked against registry "
            f"({len(declared_keys)} key{'s' if len(declared_keys) != 1 else ''})"
        )
    elif report["signed"]:
        lines.append(
            f"  signatures: {report['signed']} present, unchecked "
            "(no keys in registry — verify via the .vertex, not the raw .db)"
        )
    if declared_keys and report["chained"] and not report["signed"]:
        # The strip-attack tripwire: a total signature strip renders as
        # honest unsigned history INSIDE the store; the registry outside it
        # is the anchor (see verify_chain's documented scope boundary).
        lines.append(
            "  ⚠ registry declares signing key(s) but no tick is signed — "
            "pre-signing store, or signatures stripped"
        )
    # Fact authorship signatures (delta 3) — a separate claim from the
    # chain: per-observer authorship over content, transport-stable.
    if fact_report["signed"]:
        checked = "checked against registry" if fact_report["sig_checked"] else (
            "present, unchecked (no keys in registry)"
        )
        lines.append(
            f"  fact signatures: {fact_report['signed']} signed, "
            f"{fact_report['unsigned']} unsigned · {checked}"
        )
    elif fact_report["facts"]:
        lines.append(
            f"  fact signatures: none ({fact_report['facts']} pre-signature facts)"
        )
    if _fact_keys:
        # Per-observer era tripwire (analog of the tick strip tripwire):
        # a keyed observer with zero signed facts is either pre-signing
        # history or a live-edge strip.
        silent = [
            name for name in _fact_keys
            if fact_report["observers"].get(name, {}).get("signed", 0) == 0
            and fact_report["observers"].get(name, {}).get("unsigned", 0) > 0
        ]
        if silent and fact_report["signed"]:
            lines.append(
                f"  ⚠ keyed observer(s) with no signed facts: {', '.join(silent)} "
                "— pre-signing era, or signatures stripped on the live edge"
            )
    for b in report["breaks"]:
        lines.append(f"  ✗ {b['name']} ({b['tick']}): {b['reason']}")
    for b in fact_report["breaks"]:
        lines.append(f"  ✗ fact {b['fact']} ({b['observer']}/{b['kind']}): {b['reason']}")
    if report["truncated"] or fact_report["truncated"]:
        lines.append(
            f"  … stopped after {len(report['breaks']) + len(fact_report['breaks'])} breaks"
        )
    if args.verbose and report.get("tick_detail"):
        from datetime import datetime, timezone

        lines.append("  chained ticks (append order):")
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
            lines.append(
                f"    {'✓' if t['ok'] else '✗'} {ts} {t['name']} · {sig} · "
                f"{t['window_facts']} facts · cursor → {cursor}"
            )
    show(Block.text("\n".join(lines), Style(dim=False)))
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
    from loops.commands.signing import tick_signer_for, tick_verifier_for

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

    from painted import Block, Style, show

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
    show(Block.text("\n".join(lines), Style(dim=False)))
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

    from loops.commands.signing import (
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

    from painted import Block, Style, show

    head = receipt["head"][:16] + "…" if receipt["head"] else "(no chain)"
    show(Block.text(
        f"{'✓' if ok else '✗'} {db_path.name}: re-anchored — "
        f"{receipt['facts_resigned']} facts re-signed, "
        f"{receipt['ticks_rechained']} ticks re-chained "
        f"({receipt['ticks_resigned']} re-signed) · head {head} · "
        f"verify {'ok' if ok else 'FAILED'}",
        Style(),
    ))
    return 0 if ok else 1


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    import argparse
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    if argv and argv[0] == "verify":
        return _run_verify(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "rebirth":
        return _run_rebirth(argv[1:], vertex_path=vertex_path)
    if argv and argv[0] == "reanchor":
        return _run_reanchor(argv[1:], vertex_path=vertex_path)

    # Base inspect: pre-parse the optional ``file`` target; run_cli owns -h
    # and the -i/-q/-v/--json/--plain axes, listing ``file`` (when accepted)
    # via help_args (decision:design/devtools-help-args-idiom).
    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
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
        return make_fetcher(path, zoom=3)()

    def render(ctx, data):
        from ..lenses.store import store_view

        return store_view(data, ctx.zoom, ctx.width)

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
        render=render,
        handlers={OutputMode.INTERACTIVE: handle_interactive},
        default_mode=OutputMode.STATIC,
        prog="loops store",
        description=(
            "Inspect store contents. Subcommands: "
            "'loops store verify [target]' checks the tick hash chain; "
            "'loops store rebirth <source> <target>' replays a store "
            "through a transform with a verifiable receipt; "
            "'loops store reanchor <vertex>' recomputes chain hashes."
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
