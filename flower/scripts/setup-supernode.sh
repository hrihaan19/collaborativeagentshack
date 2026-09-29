#!/usr/bin/env bash
# One hospital Mac. Usage: scripts/setup-supernode.sh alder|harbor|riverbend
# Registers a SuperNode on SuperGrid, copies ONLY this hospital's data, starts the node.
set -euo pipefail
H="${1:?hospital id}"; cd "$(dirname "$0")/.."
uv sync
uv run flwr login supergrid
KEY=~/.flwr/domino-$H-key
[ -f "$KEY" ] || ssh-keygen -t ecdsa -b 384 -N "" -f "$KEY"
uv run flwr supernode register "$KEY.pub" supergrid || true
mkdir -p ~/domino-data/$H
[ -d data/$H ] || uv run python scripts/split-data.py
cp -r data/$H/. ~/domino-data/$H/
: "${FLWR_MODEL_API_ENDPOINT:=http://127.0.0.1:11434/v1/responses}"   # local Ollama by default
export FLWR_MODEL_API_ENDPOINT
echo "SuperNode $H -> SuperGrid. Data: ~/domino-data/$H (never leaves this Mac). Model endpoint: $FLWR_MODEL_API_ENDPOINT"
uv run flower-supernode --superlink=fleet-supergrid.flower.ai:443 \
  --auth-supernode-private-key "$KEY" \
  --node-config "hospital='$H' data_dir='$HOME/domino-data/$H'" \
  --allow-runtime-dependency-installation
