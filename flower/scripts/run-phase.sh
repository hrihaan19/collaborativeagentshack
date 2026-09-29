#!/usr/bin/env bash
# Coordinator side (Mac 4). Usage: scripts/run-phase.sh search|approve|chain|schedule [supergrid|local-agent]
set -euo pipefail
PHASE="${1:?phase}"; SL="${2:-supergrid}"; cd "$(dirname "$0")/.."
DONORS="$(python3 -c 'import json;print(json.dumps(json.load(open("data/public-donors.json")),separators=(",",":")))')"
ALT='{"pair":"ALT","donor_blood":"O","donor_hla":["A2","A68","B7","B8","DR11","DR13"]}'
uv run flwr run . "$SL" --run-config "phase=\"$PHASE\" donors='$DONORS' altruist='$ALT'" --stream 2>&1 | tee -a "../docs/evidence/run-$PHASE-$(date +%H%M%S).log"
uv run flwr ls "$SL" >> ../docs/evidence/flwr-ls.txt 2>&1 || true
