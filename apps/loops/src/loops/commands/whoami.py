"""Show resolved observer identity."""
from __future__ import annotations


def _whoami_from_identity_store() -> str:
    """Try to read observer name from the local identity vertex store.

    Uses dispatch resolution (local .loops/ first) so it finds the
    workspace identity, not the config-level template.
    """
    try:
        from .fetch import fetch_fold
        from .resolve import _resolve_vertex_for_dispatch

        identity_path = _resolve_vertex_for_dispatch("identity")
        if identity_path is None:
            return ""
        fold_state = fetch_fold(identity_path, kind="self")
        for section in fold_state.sections:
            if section.kind == "self":
                for item in section.items:
                    if item.payload.get("name") == "name":
                        msg = item.payload.get("message", "")
                        # "meta-claude. Some description..." → "meta-claude"
                        return msg.split(".")[0].strip() if msg else ""
        return ""
    except Exception:
        return ""


def _run_whoami(argv: list[str]) -> int:
    """Show resolved observer identity.

    Resolution chain:
    1. LOOPS_OBSERVER env var / .vertex single-observer (via resolve_observer)
    2. Identity store self/name fact (for multi-observer .vertex files)
    """
    from painted import show, Block, Style
    from .identity import resolve_observer

    observer = resolve_observer()
    if not observer:
        # Fall back to identity store — handles multi-observer .vertex
        observer = _whoami_from_identity_store()
    if not observer:
        show(Block.text("No observer identity resolved.", Style(dim=True)))
        return 1
    show(Block.text(observer, Style()))
    return 0
