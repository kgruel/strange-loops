"""siftd — conversation search and analytics, loops-native."""

from .lens import log_view, search_view, siftd_lens, status_view

APP_NAME = "siftd"
PAYLOAD_LENS = siftd_lens
FEEDBACK = {
    "tag": "siftd_loops.feedback:tag_handler",
}


def fetch_status(fold_state: dict) -> dict:
    """Transform vertex_read fold state into the shape status_view expects."""
    exchange_items = fold_state.get("exchange", {}).get("items", {})
    tag_items = fold_state.get("tag", {}).get("items", {})

    # Group conversations by observer/model
    observers: dict[str, int] = {}
    for _conv_id, v in (exchange_items.items() if isinstance(exchange_items, dict) else []):
        obs = v.get("model", "") or v.get("_observer", "unknown")
        observers[obs] = observers.get(obs, 0) + 1

    # Recent conversations (sorted by timestamp)
    recent = []
    items = exchange_items.items() if isinstance(exchange_items, dict) else []
    for conv_id, v in sorted(items, key=lambda kv: kv[1].get("_ts", 0), reverse=True)[:5]:
        recent.append({
            "conversation_id": conv_id,
            "ts": v.get("_ts", ""),
            "model": v.get("model", ""),
            "prompt": v.get("prompt", ""),
        })

    return {
        "conversations": len(exchange_items) if isinstance(exchange_items, dict) else 0,
        "tags": len(tag_items) if isinstance(tag_items, dict) else 0,
        "observers": observers,
        "recent": recent,
    }
