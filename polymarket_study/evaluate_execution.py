from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def first_after(history: list[dict], timestamp: int, window: int):
    points = sorted((int(row["t"]), float(row["p"])) for row in history if "t" in row and "p" in row)
    for ts, price in points:
        if timestamp <= ts <= timestamp + window:
            return price
    return None


def evaluate(observations: Path, raw_dir: Path, threshold: float, max_price: float,
             window: int, fee: float):
    rows = list(csv.DictReader(observations.open()))
    market_rows = defaultdict(dict)
    for row in rows:
        if int(row["seconds"]) == 90:
            market_rows[row["slug"]][row["side"]] = row
    values = []
    for slug, sides in market_rows.items():
        if not all(side in sides for side in ("Up", "Down")):
            continue
        signal = float(sides["Up"]["btc_return_prev_minute"])
        if abs(signal) < threshold:
            continue
        side = "Up" if signal > 0 else "Down"
        start = int(sides["Up"]["start_ts"])
        path = raw_dir / "history" / f"{slug}.json"
        if not path.exists():
            continue
        history = json.loads(path.read_text()).get("history", {})
        execution = first_after(history.get(side, []), start + 90, window)
        if execution is None or execution > max_price or execution >= 1:
            continue
        won = side == sides["Up"]["outcome"]
        pnl = ((1 - execution) / execution - fee) if won else (-1 - fee)
        values.append((pnl, won, execution))
    return {"candidate_markets": len(market_rows), "trades": len(values),
            "win_rate": sum(x[1] for x in values) / len(values) if values else None,
            "pnl_fixed_stake": sum(x[0] for x in values),
            "roi_per_trade": sum(x[0] for x in values) / len(values) if values else None,
            "mean_execution_price": sum(x[2] for x in values) / len(values) if values else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", nargs="+", type=Path, required=True)
    parser.add_argument("--raw", nargs="+", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.0001)
    parser.add_argument("--max-price", type=float, default=0.70)
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--fee", type=float, default=0.01)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {}
    for observations, raw in zip(args.observations, args.raw):
        result[observations.parent.name] = evaluate(observations, raw, args.threshold,
                                                    args.max_price, args.window, args.fee)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
