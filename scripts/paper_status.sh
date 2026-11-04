#!/usr/bin/env bash
set -euo pipefail

pgrep -af 'python -m polymarket_study.paper_live' || echo 'Paper-trading non attivo.'
latest="$(find data/paper -maxdepth 1 -type f -name 'live_*.jsonl' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [ -n "${latest:-}" ]; then
  echo "Ultimo log: ${latest}"
  wc -l "$latest"
  tail -n 2 "$latest"
fi
