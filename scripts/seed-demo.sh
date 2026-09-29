#!/usr/bin/env bash
# Seed the exact fixtures on THIS machine (each hospital seeds its own records; the coordinator seeds nothing).
# Usage: scripts/seed-demo.sh [A|B|C ...]   (default: all three, for single-host dev)
. "$(dirname "$0")/common.sh"
IDS=("$@"); [ ${#IDS[@]} -eq 0 ] && IDS=(A B C)
for HID in "${IDS[@]}"; do
  HID="$(echo "$HID" | tr a-z A-Z)"
  STATE_DIR="$ROOT/state/hospital-$(echo "$HID" | tr 'A-Z' 'a-z')"
  python -c "from domino.hospital.store import HospitalStore; from pathlib import Path; s=HospitalStore('$HID', Path('$STATE_DIR')); s.seed(force=True); print('seeded', '$HID', sorted(s.records()))"
done
