"""siftd feedback handlers — actions that emit facts on the loop."""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def tag_handler(vertex_path: Path, args: argparse.Namespace) -> int:
    """Emit a tag fact — label a conversation for later retrieval."""
    from atoms import Fact
    from engine import SqliteStore
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        print("error: vertex has no store declaration")
        return 1

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    store_path.parent.mkdir(parents=True, exist_ok=True)

    fact = Fact.of(
        "tag",
        args.observer or "user",
        name=args.name,
        conversation_id=args.conversation,
        note=getattr(args, "note", None) or "",
    )

    with SqliteStore(
        path=store_path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    ) as store:
        store.append(fact)

    print(f"tagged {args.conversation[:8]}... as #{args.name}")
    return 0
