"""`loops ls <vertex>` — unified declarations view, narrowed by flag or positional.

Phase 3 of plan:vertex-living-document, extended to converge with read's
grammar (fix/ls-flag-grammar, 2026-05-17). Aggregates the four declarative
surfaces (kinds / observers / combine / sources) into one consolidated
view. Narrowing is available in two equivalent shapes:

  Flag form (canonical, composes, matches read):
    loops ls <vertex> --kind                 the KINDS listing
    loops ls <vertex> --kind decision        DESCEND into the decision kind —
                                             its entries one level down (the
                                             kind stat view, not the facts)
    loops ls <vertex> --kind --observer      KINDS + OBSERVERS sections
    loops ls <vertex> --observer kyle        narrow OBSERVERS to one entry
    loops ls <vertex> --row [TEMPLATE]       narrow SOURCES (template sources)

  Positional form (back-compat alias for the bare single-section flag):
    loops ls <vertex> kind                   equivalent to --kind
    loops ls <vertex> observer               equivalent to --observer
    loops ls <vertex> row [TEMPLATE]         equivalent to --row

Mixing the two forms is an error — the helpful message points at the flag
form as canonical. The principle is the same one that governs `read`:
filters narrow a unified view and should be flags; positionals identify a
target the verb operates on. The positional form predates this rule and
stays for muscle memory and shell-friendly terseness.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


_FILTER_SUBCOMMANDS = frozenset({"kind", "observer", "combine", "row"})
# Order preserved for both --help rendering and stable filter-list output.
_SECTION_FLAGS = ("kind", "observer", "combine", "row")


def _print_ls_help(target: str | None = None) -> None:
    if target is None:
        p = argparse.ArgumentParser(
            prog="loops ls",
            description=(
                "Stat over the containment tree (vertex ⊃ kind ⊃ key ⊃ fact).\n"
                "`ls` lists entries one level down from where you point it,\n"
                "with stat columns (Σfacts / last-update / type).\n\n"
                "  loops ls                 vertices visible from here\n"
                "  loops ls --all  / -a     expand the config layer (vs count-line)\n"
                "  loops ls -1              terse, names only (scripting)\n"
                "  loops ls <vertex>        descend — list the vertex's kinds\n"
                "  loops ls <vertex> --kind NAME   descend — the kind's entries\n"
                "                                  (namespaces / keys; read for facts)\n"
                "  loops ls <vertex> --kind NAME --key PREFIX/   drill a namespace\n\n"
                "Declaration narrowing (flag form, composable):\n"
                "  --kind                show the KINDS listing\n"
                "  --observer [NAME]     show OBSERVERS section (or one entry)\n"
                "  --combine [PATH]      show COMBINE section (or one entry)\n"
                "  --row [TEMPLATE]      show SOURCES section (or one template)\n\n"
                "Positional alias (back-compat): loops ls <vertex> kind|observer|combine|row"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p.add_argument("vertex", nargs="?", help="Vertex name (omit for root listing)")
    else:
        p = argparse.ArgumentParser(
            prog=f"loops ls {target}",
            description=(
                f"Stat over vertex '{target}' (kinds, then a kind's entries).\n\n"
                "  --kind                show the KINDS listing (count / share / trend)\n"
                "  --kind NAME           descend into one kind — its entries one level\n"
                "                        down (namespaces / keys); use read for facts\n"
                "  --kind NAME --key P/  drill a namespace within the kind\n\n"
                "Declaration narrowing (flag form, composable):\n"
                "  --observer [NAME]     show OBSERVERS section (or one named entry)\n"
                "  --combine [PATH]      show COMBINE section (or one named entry)\n"
                "  --row [TEMPLATE]      show SOURCES section (or one template)\n\n"
                "Positional alias (back-compat):\n"
                f"  loops ls {target} kind|observer|combine|row"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    p.print_help(sys.stdout)


def _peel_section_flags(
    rest: list[str],
) -> tuple[list[str], dict[str, str], list[str]]:
    """Extract --kind/--observer/--combine/--row from rest.

    Each flag uses ``nargs='?'``: bare form selects the section, with a value
    narrows to one named entry. argparse correctly treats a following ``--*``
    token as the next flag (verified empirically — see PLAN.md §A).

    Returns ``(filters, narrows, leftover_argv)``:
      filters — section keys present (e.g. ['kind', 'observer'])
      narrows — section → name when given a value (e.g. {'kind': 'decision'})
      leftover_argv — args not consumed (passed through to run_cli)
    """
    p = argparse.ArgumentParser(add_help=False)
    for verb in _SECTION_FLAGS:
        p.add_argument(f"--{verb}", nargs="?", const=True, default=None)
    known, leftover = p.parse_known_args(rest)

    filters: list[str] = []
    narrows: dict[str, str] = {}
    for verb in _SECTION_FLAGS:
        val = getattr(known, verb)
        if val is None:
            continue
        filters.append(verb)
        if val is not True:
            narrows[verb] = val
    return filters, narrows, leftover


def detect_kind_descent(argv: list[str]) -> tuple[str, str, list[str]] | None:
    """Recognise ``ls <vertex> --kind VALUE`` — the descent into one kind.

    decision:design/ls-as-stat-over-containment: a named ``--kind VALUE`` is a
    descent one containment level down, to the kind's *entries* (the kind stat
    view), NOT a dump of its facts (that is ``read``). Returns
    ``(vertex, kind_value, rest_argv)`` when argv is exactly that descent —
    bare ``--kind`` (no value), other section flags, the positional form, or
    ``-h`` all return ``None`` and stay on the listing path.
    """
    if not argv or argv[0].startswith("-"):
        return None
    vertex, rest = argv[0], argv[1:]
    if rest and rest[0] in ("-h", "--help"):
        return None
    if rest and rest[0] in _FILTER_SUBCOMMANDS:  # positional form — not a descent
        return None
    flag_filters, flag_narrows, leftover = _peel_section_flags(rest)
    if flag_filters == ["kind"] and "kind" in flag_narrows:
        return vertex, flag_narrows["kind"], leftover
    return None


def _run_ls(argv: list[str]) -> int:
    """Dispatch ``loops ls`` — root listing or per-vertex unified view.

    Forms (see module docstring for the full grammar):
      loops ls                          — list all discovered vertices (root)
      loops ls <vertex>                 — unified declarations for one vertex
      loops ls <vertex> --kind [NAME]   — flag form (canonical, composable)
      loops ls <vertex> kind            — positional alias (back-compat)
    """
    if argv and argv[0] in ("-h", "--help"):
        _print_ls_help()
        return 0

    if not argv or argv[0].startswith("-"):
        # No target — fall through to the existing root-listing handler.
        from loops.commands.population import _run_ls_root

        return _run_ls_root(argv)

    target = argv[0]
    rest = argv[1:]

    # Intercept --help at vertex level before sub-verb consumption.
    if rest and rest[0] in ("-h", "--help"):
        _print_ls_help(target)
        return 0

    # Positional sub-verb (legacy form): a bare token that names a section.
    positional_filter: str | None = None
    if rest and rest[0] in _FILTER_SUBCOMMANDS:
        positional_filter = rest[0]
        rest = rest[1:]

    flag_filters, flag_narrows, rest = _peel_section_flags(rest)

    if positional_filter and (flag_filters or flag_narrows):
        _err(
            "ls: don't mix the positional form with --kind/--observer/--combine/--row.\n"
            "  flag form is canonical:    sl ls <vertex> --kind [NAME]\n"
            "  positional is back-compat: sl ls <vertex> kind"
        )
        return 2

    if positional_filter is not None:
        filters: list[str] | None = [positional_filter]
        narrows: dict[str, str] = {}
    else:
        filters = flag_filters or None  # None = all sections visible
        narrows = flag_narrows

    # Render through painted's run_cli for zoom/width handling.
    from painted import run_cli

    from loops.lenses.declarations import declarations_view

    def fetch():
        return fetch_declarations(
            target, filters=filters, narrows=narrows, extra_argv=rest,
        )

    def render(ctx, data):
        return declarations_view(
            data, ctx.zoom, ctx.width, piped=not getattr(ctx, "is_tty", True)
        )

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog=f"loops ls {target}",
        description="List vertex declarations",
    )


def fetch_declarations(
    target: str,
    *,
    filter_: str | None = None,
    filters: list[str] | None = None,
    narrows: dict[str, str] | None = None,
    extra_argv: list[str] | None = None,  # noqa: ARG001 — reserved for future read-style flags
) -> dict[str, Any]:
    """Aggregate kinds + observers + combine + sources for the vertex.

    Narrowing inputs accept two equivalent shapes:
      * legacy single-section: ``filter_="kind"`` (kept for callers that
        predate the flag-grammar convergence)
      * multi-section + name: ``filters=["kind", "observer"]``,
        ``narrows={"kind": "decision"}``

    The returned dict exposes both ``filter`` (legacy, single) and
    ``filters``/``narrows`` (new) so lens code can transition incrementally.
    """
    from engine.declaration import load_declaration
    from lang.population import (
        resolve_vertex,
    )
    from loops.commands.resolve import _resolve_vertex_for_dispatch, loops_home

    # Normalise narrowing inputs — legacy filter_ wins when it's the only one set.
    if filters is None and filter_ is not None:
        filters = [filter_]
    narrows = narrows or {}
    # Back-fill legacy `filter` from `filters` when only the new shape is given.
    legacy_filter = filter_ if filter_ is not None else (
        filters[0] if filters and len(filters) == 1 else None
    )

    # Allow `loops ls reading/feeds` to qualify a template.
    if "/" in target and not target.startswith(("./", "/")):
        vertex_ref, qualifier = target.split("/", 1)
    else:
        vertex_ref, qualifier = target, None

    # Local-first — same resolution the verbs use (thread:global-local-walk-broken).
    vertex_path = _resolve_vertex_for_dispatch(vertex_ref)
    if vertex_path is None:
        missing = resolve_vertex(vertex_ref, loops_home())
        return {
            "error": f"vertex not found: {missing}",
            "vertex_name": vertex_ref,
            "filter": legacy_filter,
            "filters": filters,
            "narrows": narrows,
        }

    try:
        vf = load_declaration(vertex_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"failed to parse {vertex_path.name}: {exc}",
            "vertex_name": vertex_ref,
            "filter": legacy_filter,
            "filters": filters,
            "narrows": narrows,
        }

    kinds = _summarize_kinds(vf)
    observers = _summarize_observers(vf)
    combine = _summarize_combine(vf)
    sources = _summarize_sources(vf, vertex_path, qualifier)

    # Stat-over-containment (decision:design/ls-as-stat-over-containment): join
    # live per-kind stats (count / %, mtime) onto the declared kinds and stamp
    # the vertex-level header stat. Declared-but-empty kinds keep count 0; live
    # kinds with no declaration (e.g. tick.<name>, _sync.*) are appended so the
    # body is a faithful listing of what's actually inside.
    stat = _vertex_stat(vf, vertex_path)
    merged_kinds = _merge_kind_stats(kinds, stat["kind_stats"], stat["facts"])

    return {
        "vertex_name": vf.name,
        "vertex_path": str(vertex_path),
        "vertex_kind": stat["vertex_kind"],
        "facts": stat["facts"],
        # Header kind-count matches the body (declared ∪ live), so "N kinds"
        # never contradicts the number of rows listed below it.
        "kind_count": len(merged_kinds) or None,
        "mtime": stat["mtime"],
        "signed": stat.get("signed"),
        "kinds": merged_kinds,
        "observers": observers,
        "combine": combine,
        "sources": sources,
        "filter": legacy_filter,
        "filters": filters,
        "narrows": narrows,
    }


def _rollup_entries(
    raw: dict, key_prefix: str | None, field_label: str,
    key_tiers: dict | None = None,
) -> list[dict[str, Any]]:
    """Roll fold-key stats up to the *next containment level* below the prefix.

    Given per-key ``{key: {count, earliest, latest}}`` and an optional
    ``key_prefix`` already descended into, group the keys one level deeper:
    a key with a further ``/`` segment collapses into a namespace entry
    (``design/`` → drill again with ``--key design/``); a key with no further
    segment is a leaf. The ``None`` key (facts missing the fold field) collects
    under ``(no <field>)`` — the orphan diagnostic. Count-descending.

    ``key_tiers`` (raw-key → rail tier) rides through so each rollup row carries
    a tier: a leaf inherits its key's tier, a namespace MAX-propagates over the
    keys it collapses (decision:design/salience-max-propagation). Absent when a
    caller doesn't tier (the JSON contract stays tier-optional).
    """
    from loops.surface import tier_max

    kt = key_tiers or {}
    out: dict[str, dict[str, Any]] = {}
    for key, st in raw.items():
        if key is None:
            if key_prefix:  # the orphan bucket is not under any prefix
                continue
            head, is_leaf = f"(no {field_label})", True
        else:
            rest = key
            if key_prefix:
                if not key.lower().startswith(key_prefix.lower()):
                    continue
                rest = key[len(key_prefix):]
            if "/" in rest:
                head = (key_prefix or "") + rest.split("/", 1)[0] + "/"
                is_leaf = False
            else:
                head = (key_prefix or "") + rest
                is_leaf = True
        e = out.setdefault(
            head, {"count": 0, "latest": None, "leaf": is_leaf, "_tiers": []}
        )
        e["count"] += st["count"]
        if e["latest"] is None or st["latest"] > e["latest"]:
            e["latest"] = st["latest"]
        if not is_leaf:
            e["leaf"] = False
        if key in kt:
            e["_tiers"].append(kt[key])
    entries: list[dict[str, Any]] = []
    for k, v in out.items():
        tiers = v.pop("_tiers")
        entry = {"key": k, **v}
        if key_tiers is not None:
            entry["tier"] = tier_max(tiers)
        entries.append(entry)
    entries.sort(key=lambda r: r["count"], reverse=True)
    return entries


def fetch_kind_stat(
    target: str, kind: str, *, key_prefix: str | None = None,
) -> dict[str, Any]:
    """Stat one kind — its header summary + the entries one containment level
    down (decision:design/ls-as-stat-over-containment; reverses
    ls-stat-decisions-a-d B — ``--kind`` descends to entries, NOT to ``read``).

    For a ``by``-fold kind the entries are its fold keys, rolled up to the next
    namespace level (and re-rolled by ``key_prefix`` when drilling). For a
    collect-fold (no fold key) the entries degrade to a by-observer breakdown.
    """
    from engine.declaration import load_declaration
    from lang.population import resolve_vertex

    from loops.commands.fetch import _get_key_field
    from loops.commands.resolve import _resolve_vertex_for_dispatch, loops_home

    vertex_path = _resolve_vertex_for_dispatch(target)
    if vertex_path is None:
        return {
            "error": f"vertex not found: {resolve_vertex(target, loops_home())}",
            "vertex_name": target, "kind": kind,
        }
    try:
        vf = load_declaration(vertex_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"failed to parse {vertex_path.name}: {exc}",
            "vertex_name": target, "kind": kind,
        }

    fold_op = ""
    for k in _summarize_kinds(vf):
        if k["name"] == kind:
            fold_op = k["fold_op"]
            break
    key_field = _get_key_field(vertex_path, kind)

    # A collect-fold has no fold key, so --key has nothing to scope — reject it
    # rather than silently ignore it while the header claims "under <prefix>".
    if key_prefix and key_field is None:
        return {
            "error": (
                f"kind '{kind}' is a collect-fold (no fold key) — "
                "--key doesn't apply; it lists by observer"
            ),
            "vertex_name": vf.name, "kind": kind,
        }

    store = vf.store
    if store is None:
        return {
            "error": f"{vf.name} is an aggregation vertex — no own store to stat",
            "vertex_name": vf.name, "kind": kind,
        }
    if not store.is_absolute():
        store = (vertex_path.parent / store).resolve()

    base = {
        "vertex_name": vf.name, "kind": kind, "fold_op": fold_op,
        "key_field": key_field, "key_prefix": key_prefix,
        "by": "key" if key_field else "observer",
    }
    if not store.exists():
        return {**base, "count": 0, "vertex_total": 0, "share": 0.0,
                "earliest": None, "latest": None, "distinct_keys": 0, "entries": []}

    from engine.store_reader import StoreReader

    with StoreReader(store) as reader:
        # The default `fact_total` excludes the reserved _decl.* namespace
        # (SPEC §9.4) so the share denominator stays honest as S4 re-absorbs
        # grow the internal row count — otherwise every declaration edit would
        # silently shrink every kind's rendered share.
        vertex_total = reader.fact_total
        if key_field:
            raw = reader.fact_key_stats(kind, key_field)
        else:
            raw = reader.fact_observer_stats(kind)

    # When drilling (--key prefix), the header summarizes the *subtree*, not the
    # whole kind — count / span / distinct all scope to the prefix.
    if key_field and key_prefix:
        scoped = {
            k: v for k, v in raw.items()
            if k and k.lower().startswith(key_prefix.lower())
        }
    else:
        scoped = raw
    count = sum(v["count"] for v in scoped.values())
    earliest = min((v["earliest"] for v in scoped.values()), default=None)
    latest = max((v["latest"] for v in scoped.values()), default=None)
    distinct = len([k for k in scoped if k is not None])

    # Rail tiers (decision:design/tier-one-home-inheritance): score each entry
    # by fact count and bucket by quantile — the same machinery `_assign_tiers`
    # runs over Surface salience, reused not forked. Scope is the kind's key
    # population (a degradation from vertex-scope, honest for a --kind cut — the
    # same caveat surface._assign_tiers names for a filtered fetch).
    from loops.surface import tiers_for_scores

    if key_field:
        scored = list(raw.keys())
        key_tiers = dict(zip(scored, tiers_for_scores([raw[k]["count"] for k in scored])))
        entries = _rollup_entries(raw, key_prefix, key_field, key_tiers)
    else:
        obs = sorted(raw.items(), key=lambda kv: kv[1]["count"], reverse=True)
        tiers = tiers_for_scores([v["count"] for _, v in obs])
        entries = [
            {"key": (k or "(none)"), "count": v["count"],
             "latest": v["latest"], "leaf": True, "tier": t}
            for (k, v), t in zip(obs, tiers)
        ]

    # Coerce timestamps to epoch floats — the same JSON contract as the listing
    # path (_store_stats) and `read --json`, so `latest` is a number, not a
    # datetime string, across every ls subcommand.
    def _epoch(dt: Any) -> float | None:
        return dt.timestamp() if dt is not None else None

    for e in entries:
        e["latest"] = _epoch(e["latest"])

    return {
        **base,
        "count": count, "vertex_total": vertex_total,
        "share": (count / vertex_total * 100) if vertex_total else 0.0,
        "earliest": _epoch(earliest), "latest": _epoch(latest),
        "distinct_keys": distinct, "entries": entries,
    }


def _run_kind_stat(vertex: str, kind: str, rest: list[str]) -> int:
    """Render ``ls <vertex> --kind <kind>`` — the kind stat view (descent to
    entries, not facts). ``--key <prefix>`` drills one namespace deeper."""
    import argparse

    kp = argparse.ArgumentParser(add_help=False)
    kp.add_argument("--key", default=None)
    known, leftover = kp.parse_known_args(rest)

    from painted import run_cli

    from loops.lenses.declarations import kind_stat_view

    def fetch():
        return fetch_kind_stat(vertex, kind, key_prefix=known.key)

    def render(ctx, data):
        return kind_stat_view(
            data, ctx.zoom, ctx.width, piped=not getattr(ctx, "is_tty", True)
        )

    return run_cli(
        leftover, fetch=fetch, render=render,
        prog=f"loops ls {vertex} --kind {kind}",
        description=f"Stat view of kind '{kind}' in {vertex}",
    )


def _vertex_stat(vf, vertex_path: Path) -> dict[str, Any]:
    """Vertex-level stat header + per-kind live stats (or empties if no store)."""
    from loops.commands.vertices import _classify_kind, _store_stats

    vertex_kind = _classify_kind(vf)
    store = vf.store
    stats: dict[str, Any] | None = None
    if store is not None:
        if not store.is_absolute():
            store = (vertex_path.parent / store).resolve()
        stats = _store_stats(store)
    if stats is None:
        return {
            "vertex_kind": vertex_kind,
            "facts": None,
            "kind_count": None,
            "mtime": None,
            "signed": None,
            "kind_stats": [],
        }
    return {"vertex_kind": vertex_kind, **stats}


def _merge_kind_stats(
    declared: list[dict[str, Any]],
    kind_stats: list[dict[str, Any]],
    total: int | None,
) -> list[dict[str, Any]]:
    """Join declared kinds (fold-op) with live stats (count/%/mtime).

    Output is count-descending, declared-but-empty kinds last (count 0), and
    any live kind absent from the declaration appended so `sl ls <vertex>`
    lists what's actually stored, not just what's declared.
    """
    by_name = {k["kind"]: k for k in kind_stats}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in declared:
        name = d["name"]
        seen.add(name)
        live = by_name.get(name)
        count = live["count"] if live else 0
        share = (count / total * 100) if total else 0.0
        out.append({
            **d,
            "count": count,
            "share": share,
            "latest": live["latest"] if live else None,
            "trend": live.get("trend", []) if live else [],
        })
    for k in kind_stats:
        if k["kind"] in seen:
            continue
        count = k["count"]
        share = (count / total * 100) if total else 0.0
        out.append({
            "name": k["kind"],
            "fold_op": "",  # undeclared (system kind, e.g. tick.* / _sync.*)
            "target": "",
            "preview_fields": (),
            "count": count,
            "share": share,
            "latest": k["latest"],
            "trend": k.get("trend", []),
        })
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


def _summarize_kinds(vf) -> list[dict[str, Any]]:
    """[(kind_name, fold_op_repr, target_field)] for each loop kind."""
    from lang.ast import (
        FoldAvg,
        FoldBy,
        FoldCollect,
        FoldCount,
        FoldLatest,
        FoldMax,
        FoldMin,
        FoldSum,
        FoldWindow,
    )

    out: list[dict[str, Any]] = []
    for kind_name, loop_def in (vf.loops or {}).items():
        if not loop_def.folds:
            out.append({"name": kind_name, "fold_op": "(no fold)", "target": "", "preview_fields": ()})
            continue
        # Render the first fold (typical case is one fold per kind).
        fd = loop_def.folds[0]
        op = fd.op
        if isinstance(op, FoldBy):
            op_repr = f'by "{op.key_field}"'
        elif isinstance(op, FoldCollect):
            op_repr = f"collect {op.max_items}"
        elif isinstance(op, FoldCount):
            op_repr = "count"
        elif isinstance(op, FoldLatest):
            op_repr = "latest"
        elif isinstance(op, FoldMax):
            op_repr = f'max "{op.field}"'
        elif isinstance(op, FoldMin):
            op_repr = f'min "{op.field}"'
        elif isinstance(op, FoldSum):
            op_repr = f'sum "{op.field}"'
        elif isinstance(op, FoldAvg):
            op_repr = f'avg "{op.field}"'
        elif isinstance(op, FoldWindow):
            op_repr = f'window {op.size} "{op.field}"'
        else:
            op_repr = type(op).__name__
        out.append({"name": kind_name, "fold_op": op_repr, "target": fd.target, "preview_fields": loop_def.preview_fields})
    return out


def _summarize_observers(vf) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in vf.observers or ():
        entry: dict[str, Any] = {"name": o.name}
        if o.identity:
            entry["identity"] = o.identity
        if o.grant:
            entry["grants"] = sorted(o.grant.potential)
        out.append(entry)
    return out


def _summarize_combine(vf) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for e in vf.combine or ():
        entry: dict[str, str] = {"path": e.name}
        if e.alias:
            entry["alias"] = e.alias
        out.append(entry)
    return out


def _summarize_sources(
    vf, vertex_path: Path, qualifier: str | None
) -> list[dict[str, Any]]:
    """For each file-backed template source, return its header + rows."""
    from lang.ast import FromFile, TemplateSource
    from lang.population import list_file_read, template_name

    out: list[dict[str, Any]] = []
    for src in vf.sources or ():
        if not isinstance(src, TemplateSource):
            continue
        if not isinstance(src.from_, FromFile):
            continue
        tname = template_name(src)
        if qualifier is not None and tname != qualifier:
            continue
        list_path = src.from_.path
        if not list_path.is_absolute():
            list_path = (vertex_path.parent / list_path).resolve()
        if list_path.exists():
            header, rows = list_file_read(list_path)
        else:
            header, rows = [], []
        out.append({
            "template": tname,
            "list_path": str(list_path),
            "header": header,
            "rows": [
                {h: r.values.get(h, "") for h in header}
                for r in rows
            ],
        })
    return out


def _err(msg: str) -> None:
    from painted import Block, paint
    from painted.palette import current_palette

    paint(Block.text(f"Error: {msg}", current_palette().error), file=sys.stderr)
