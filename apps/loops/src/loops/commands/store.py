"""Store command — fetch store data for inspection.

Pure data fetch, no rendering knowledge.
"""
from __future__ import annotations

from pathlib import Path


def resolve_store_path(file_path: Path) -> Path:
    """Resolve a .vertex or .db file to the actual store .db path."""
    if file_path.suffix == ".vertex":
        from dsl import parse_vertex_file

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
      0-1: summary only (counts + stats)
      2:   + latest tick payloads
      3:   + recent fact payloads
    """
    def fetch() -> dict:
        from vertex.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            data = reader.summary()
            data["freshness"] = reader.freshness
            if zoom >= 1:
                # Add a single recent fact payload per kind for SUMMARY gist
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


def make_fidelity_fetcher(path: Path):
    """Create a fetcher for fidelity drill data.

    Returns a callable (since_ts, until_ts, kind?) -> list[dict].
    Each call opens and closes its own StoreReader — the TUI calls this
    on-demand when the user presses 'f', not on every frame.
    """
    def fetch(since_ts: float, until_ts: float, kind: str | None = None) -> list[dict]:
        from vertex.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            return reader.facts_between(since_ts, until_ts, kind=kind)
    return fetch
