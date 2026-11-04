from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_period(path: Path):
    rows = list(csv.DictReader(path.open()))
    markets = defaultdict(dict)
    for row in rows:
        if int(row["seconds"]) == 90:
            markets[row["slug"]][row["side"]] = row
    return markets


def evaluate(markets, condition, threshold, max_price, haircut, fee):
    values = []
    for market in markets.values():
        if not all(side in market for side in ("Up", "Down")):
            continue
        up = market["Up"]
        movement = float(up["btc_return_prev_minute"])
        round_move = float(up["btc_return_from_start"])
        same = movement * round_move >= 0
        if condition == "same" and not same:
            continue
        if condition == "opposite" and same:
            continue
        if abs(movement) < threshold:
            continue
        side = "Up" if movement > 0 else "Down"
        price = float(market[side]["price"]) + haircut
        if price > max_price or price >= 1:
            continue
        won = side == up["outcome"]
        gross = (1 - price) / price if won else -1.0
        values.append(gross - fee)
    return {
        "trades": len(values),
        "wins": sum(v >= 0 for v in values),
        "win_rate": None if not values else sum(v >= 0 for v in values) / len(values),
        "pnl": sum(values),
        "roi_per_trade": None if not values else sum(values) / len(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--development-count", type=int, default=4)
    parser.add_argument("--haircut", type=float, default=0.04)
    parser.add_argument("--fee", type=float, default=0.01)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    periods = [(path.parent.name, load_period(path)) for path in args.input]
    thresholds = [0.0, 0.00005, 0.0001, 0.0002, 0.0003, 0.0005]
    caps = [0.55, 0.60, 0.65, 0.70]
    conditions = ["all", "same", "opposite"]
    candidates = []
    for condition in conditions:
        for threshold in thresholds:
            for cap in caps:
                dev = [evaluate(m, condition, threshold, cap, args.haircut, args.fee)
                       for _, m in periods[:args.development_count]]
                if any(x["trades"] < args.min_trades for x in dev):
                    continue
                candidates.append({
                    "condition": condition,
                    "threshold": threshold,
                    "max_price": cap,
                    "development": dev,
                    "development_pnl": sum(x["pnl"] for x in dev),
                    "development_min_pnl": min(x["pnl"] for x in dev),
                    "development_trades": sum(x["trades"] for x in dev),
                })
    candidates.sort(key=lambda x: (x["development_min_pnl"], x["development_pnl"]), reverse=True)
    chosen = candidates[0] if candidates else None
    evaluation = []
    if chosen:
        evaluation = [
            {"period": name, **evaluate(markets, chosen["condition"], chosen["threshold"], chosen["max_price"], args.haircut, args.fee)}
            for name, markets in periods[args.development_count:]
        ]
    result = {
        "parameters": {"development_count": args.development_count, "haircut": args.haircut, "fee": args.fee, "min_trades": args.min_trades},
        "chosen": chosen,
        "evaluation": evaluation,
        "evaluation_total": {
            "trades": sum(x["trades"] for x in evaluation),
            "pnl": sum(x["pnl"] for x in evaluation),
        },
        "top_candidates": candidates[:20],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("chosen", "evaluation", "evaluation_total")}, indent=2))


if __name__ == "__main__":
    main()
