#!/usr/bin/env bash
# Witness layer — observes disk usage and emits Facts.
#
# This is the I/O boundary: it touches the world (df -h), translates
# raw output into structured integer facts, and writes them to stdout.
#
# Wire format: "kind mount_id pct" (space-separated u24 integers)
#   kind=1  disk data fact
#   kind=2  boundary signal (disk.complete)
#
# The compute core reads these and folds. It never touches the world.

set -euo pipefail

# Mount path → integer ID.
# The witness layer owns this — it's knowledge about the observed world.
mount_id() {
  case "$1" in
    /)                        echo 1 ;;
    /System/Volumes/VM)       echo 2 ;;
    /System/Volumes/Preboot)  echo 3 ;;
    /System/Volumes/Data)     echo 4 ;;
    /nix)                     echo 5 ;;
    *)                        echo "" ;;
  esac
}

count=0

# Process substitution avoids subshell — count survives the loop.
while read -r _ _ _ _ pct _ _ _ mount; do
  id=$(mount_id "$mount")
  [ -z "$id" ] && continue

  # Strip the % suffix from capacity.
  pct="${pct%\%}"

  echo "1 $id $pct"
  count=$((count + 1))
done < <(df -h | tail -n +2)

# Boundary signal.
echo "2 0 0"
