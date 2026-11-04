from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def evaluate(path: Path, threshold: float, max_price: float, haircut: float, fee: float):
    rows = list(csv.DictReader(path.open()))
    markets = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        markets[row["slug"]][int(row["seconds"])][row["side"]] = row
    values = []
    for market in markets.values():
        if 90 not in market or not all(side in market[90] for side in ("Up", "Down")):
            continue
        movement = float(market[90]["Up"]["btc_return_prev_minute"])
        if abs(movement) < threshold:
            continue
        side = "Up" if movement > 0 else "Down"
        price = float(market[90][side]["price"]) + haircut
        if price > max_price or price >= 1:
            continue
        won = side == market[90]["Up"]["outcome"]
        gross = (1 - price) / price if won else -1.0
        values.append(gross - fee)
    return {"markets": len(markets), "trades": len(values), "win_rate": None if not values else sum(v >= 0 for v in values) / len(values),
            "pnl_fixed_stake": sum(values), "roi_per_trade": None if not values else sum(values) / len(values)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.0001)
    parser.add_argument("--max-price", type=float, default=0.70)
    parser.add_argument("--haircut", type=float, default=0.01)
    parser.add_argument("--fee", type=float, default=0.01)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {path.parent.name: evaluate(path, args.threshold, args.max_price, args.haircut, args.fee) for path in args.input}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"parameters": vars(args) | {"input": [str(p) for p in args.input]}, "periods": result}, indent=2, default=str) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
