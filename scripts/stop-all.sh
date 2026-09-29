#!/usr/bin/env bash
. "$(dirname "$0")/common.sh"
for f in state/*.pid; do [ -f "$f" ] && { kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; }; done
pkill -f "[f]lower-superlink" 2>/dev/null || true
pkill -f "[f]lower-supernode" 2>/dev/null || true
pkill -f "domino.coordinator.api" 2>/dev/null || true
pkill -f "domino.hospital.console" 2>/dev/null || true
echo "stopped"
