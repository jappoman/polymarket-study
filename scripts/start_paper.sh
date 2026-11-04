#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
mkdir -p data/paper

duration="${PAPER_DURATION:-86400}"
threshold="${PAPER_THRESHOLD:-0.0002}"
max_ask="${PAPER_MAX_ASK:-0.55}"
stamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
output="data/paper/live_${stamp}.jsonl"

echo "Paper-trading avviato. Log: ${repo_dir}/${output}"
echo "Durata: ${duration}s | soglia: ${threshold} | max ask: ${max_ask}"
exec python -m polymarket_study.paper_live \
  --duration "$duration" \
  --output "$output" \
  --threshold "$threshold" \
  --max-ask "$max_ask"
