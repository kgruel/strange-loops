"""Store-backed population facts helpers.

This module lives in the app layer (apps/loops) so it can depend on engine
StoreReader and treat the vertex store as the audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine.store_reader import StoreReader
from lang.population import PopulationRow, list_file_write

POP_ADD_KIND = "pop.add"
POP_RM_KIND = "pop.rm"
POP_FACT_KINDS = (POP_ADD_KIND, POP_RM_KIND)


def pop_read_facts(store_path: Path) -> list[dict]:
    """Read pop facts from a store and return them in chronological order."""
    store_path = Path(store_path)
    if not store_path.exists():
        return []

    now = datetime.now(timezone.utc).timestamp()
    with StoreReader(store_path) as reader:
        adds = reader.facts_between(0.0, now, kind=POP_ADD_KIND)
        rms = reader.facts_between(0.0, now, kind=POP_RM_KIND)

    facts = adds + rms
    facts.sort(key=lambda f: f["ts"])
    return facts


def pop_store_has_facts(
    store_path: Path, *, template: str | None = None, include_unscoped: bool = True
) -> bool:
    """True if the store contains any pop facts (optionally scoped by template)."""
    store_path = Path(store_path)
    if not store_path.exists():
        return False

    with StoreReader(store_path) as reader:
        recent = reader.recent_facts(POP_ADD_KIND, 200) + reader.recent_facts(
            POP_RM_KIND, 200
        )

    if template is None:
        return bool(recent)

    for fact in recent:
        payload = fact.get("payload") or {}
        t = payload.get("template", None)
        if t == template:
            return True
        if include_unscoped and (t is None or t == ""):
            return True
    return False


def pop_fold_rows(
    facts: list[dict],
    header: list[str],
    *,
    template: str | None = None,
    include_unscoped: bool = True,
) -> list[PopulationRow]:
    """Fold pop.add/pop.rm facts into current rows using list header as schema."""
    if not header:
        return []

    state: dict[str, PopulationRow] = {}
    key_field = header[0]

    for fact in facts:
        payload = fact.get("payload") or {}

        if template is not None:
            t = payload.get("template", None)
            if t == template:
                pass
            elif include_unscoped and (t is None or t == ""):
                pass
            else:
                continue

        key = payload.get("key", "")
        if not key:
            continue

        if fact.get("kind") == POP_ADD_KIND:
            values: dict[str, str] = {key_field: str(key)}
            for field in header[1:]:
                values[field] = str(payload.get(field, ""))
            state[str(key)] = PopulationRow(key=str(key), values=values)
        elif fact.get("kind") == POP_RM_KIND:
            state.pop(str(key), None)

    return [state[k] for k in sorted(state.keys())]


def pop_materialize_list(
    *,
    store_path: Path,
    list_path: Path,
    header: list[str],
    template: str | None = None,
    include_unscoped: bool = True,
) -> list[PopulationRow]:
    """Materialize a .list file from folded pop facts. Returns the rows written."""
    facts = pop_read_facts(store_path)
    rows = pop_fold_rows(
        facts, header, template=template, include_unscoped=include_unscoped
    )
    list_file_write(list_path, header, rows)
    return rows

