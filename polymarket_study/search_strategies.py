from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_observations(path: Path):
    rows = list(csv.DictReader(path.open()))
    by = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        by[row["slug"]][int(row["seconds"])][row["side"]] = row
    return [value for _, value in sorted(by.items(), key=lambda item: int(item[1][30]["Up"]["start_ts"]))]


def trade(market, kind: str, second: int, parameter):
    up = market[second]["Up"]
    outcome = up["outcome"]
    price = float(up["price"])
    if kind == "follow":
        side = "Up" if price >= 0.5 else "Down"
    elif kind == "contrarian":
        side = "Down" if price >= 0.5 else "Up"
    elif kind in ("momentum", "reversion"):
        change = price - float(market[30]["Up"]["price"])
        if abs(change) < parameter:
            return None
        side = "Up" if change > 0 else "Down"
        if kind == "reversion":
            side = "Down" if side == "Up" else "Up"
    elif kind == "price_band":
        low, high = parameter
        if not low <= price <= high:
            return None
        side = "Up" if price >= 0.5 else "Down"
    else:
        raise ValueError(kind)
    execution = float(market[second][side]["price"]) + 0.01
    if execution >= 1:
        return None
    won = side == outcome
    pnl = (1 - execution) / execution if won else -1.0
    return pnl, int(won)


def score(markets, strategy):
    kind, second, parameter = strategy
    values = [trade(market, kind, second, parameter) for market in markets]
    values = [value for value in values if value is not None]
    return {
        "n": len(values),
        "win_rate": sum(value[1] for value in values) / len(values) if values else 0.0,
        "pnl": sum(value[0] for value in values),
        "roi_per_trade": sum(value[0] for value in values) / len(values) if values else 0.0,
    }


def strategies():
    result = []
    for second in (30, 60, 90, 120, 180, 240):
        result += [(kind, second, None) for kind in ("follow", "contrarian")]
        result += [(kind, second, threshold) for kind in ("momentum", "reversion") for threshold in (0.01, 0.03, 0.05, 0.1, 0.15, 0.2)]
        result += [("price_band", second, (low, high)) for low in (0.1, 0.2, 0.3, 0.4, 0.45, 0.5)
                   for high in (0.55, 0.6, 0.7, 0.8, 0.9) if low <= high]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datasets = [load_observations(path) for path in args.period]
    rows = []
    for index, strategy in enumerate(strategies()):
        row = {"strategy": json.dumps(strategy)}
        for period, markets in zip(args.period, datasets):
            # All inputs are usually named observations.csv; use the parent
            # directory so period results cannot overwrite each other.
            label = period.parent.name
            row[label + "_score"] = json.dumps(score(markets, strategy))
        rows.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} strategies")


if __name__ == "__main__":
    main()
