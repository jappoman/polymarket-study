#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Uso: $0 data/paper/live_YYYY-MM-DDTHH-MM-SSZ.jsonl" >&2
  exit 2
fi

input="$1"
output="${input%.jsonl}_settled.jsonl"
python -m polymarket_study.settle_paper --input "$input" --output "$output"
echo "Output: $output"
