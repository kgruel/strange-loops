#!/usr/bin/env bash
# Witness layer — observes RSS/Atom feeds and emits integer Facts.
#
# Reads apps/reader/loops/feeds.list, fetches each feed with the same
# curl + yq pipeline from feed.loop, translates items to integer facts
# via link hashing. The compute core never touches the network.
#
# Wire format: "kind feed_id value" (space-separated u24 integers)
#   kind=1  item fact (value = link_hash)
#   kind=2  per-feed boundary (value = item_count)
#   kind=3  global boundary (all feeds done)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FEEDS_LIST="${SCRIPT_DIR}/../../../apps/reader/loops/feeds.list"

# Hash a link URL to a 24-bit integer (u24).
# 6 hex digits = 24 bits. For ~50 items per feed, collision probability < 0.01%.
hash_link() {
  printf '%d' "0x$(md5 -qs "$1" | head -c 6)"
}

# Extract link from a JSON feed item.
# Handles RSS (.link is string) and Atom (.link.+href or array of links).
extract_link() {
  jq -r '
    .link |
    if type == "string" then .
    elif type == "object" then (.["+@href"] // .["+href"] // .["@href"] // empty)
    elif type == "array" then
      (.[0] | if type == "string" then .
              elif type == "object" then (.["+@href"] // .["+href"] // .["@href"] // empty)
              else empty end)
    else empty end
  '
}

feed_id=0

# Skip header line, process each feed.
while read -r _kind feed_url; do
  feed_id=$((feed_id + 1))
  item_count=0

  # Fetch feed — same curl + yq pipeline as feed.loop.
  while IFS= read -r item; do
    link=$(echo "$item" | extract_link)
    [ -z "$link" ] && continue

    lh=$(hash_link "$link")
    echo "1 $feed_id $lh"
    item_count=$((item_count + 1))
  done < <(curl -sfL -A 'Mozilla/5.0' "$feed_url" \
    | yq -p xml -o json -I0 '(.rss.channel.item // .feed.entry)[]' 2>/dev/null || true)

  # Per-feed boundary.
  echo "2 $feed_id $item_count"
done < <(tail -n +2 "$FEEDS_LIST")

# Global boundary.
echo "3 0 0"
