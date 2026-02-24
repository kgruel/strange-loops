#!/usr/bin/env bash
set -euo pipefail

# Thin witness for the Bend experiment.
# Emits:
# - link URLs (one per line)
# - boundary markers as comments (ignored by Bend/Python references)

echo "# boundary lobsters.complete"
for i in $(seq 1 20); do
  echo "https://example.com/lobsters/${i}"
done
echo "# boundary danluu.complete"
for i in $(seq 1 20); do
  echo "https://example.com/danluu/${i}"
done
echo "# boundary all.complete"
