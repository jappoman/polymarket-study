from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


def load_candles(paths: list[Path]):
    candles = {}
    for path in paths:
        for row in json.loads(path.read_text()):
            candles[int(row["ts"])] = row
    return candles


def build_snapshots(book_path: Path, target_seconds: tuple[int, ...]):
    cols = ["market_slug", "captured_at", "seconds_to_close", "outcome",
            "is_winning_outcome", "best_ask", "best_bid"]
    df = pd.read_parquet(book_path, columns=cols)
    result = {}
    for seconds in target_seconds:
        target = 300 - seconds
        near = df[(df["seconds_to_close"] - target).abs() <= 1.25].copy()
        near["distance"] = (near["seconds_to_close"] - target).abs()
        # Select the closest timestamp per market, retaining both outcomes.
        times = (near.groupby(["market_slug", "captured_at"], as_index=False)
                      .agg(distance=("distance", "min"), n=("outcome", "nunique")))
        times = times[times.n >= 2].sort_values(["market_slug", "distance", "captured_at"])
        chosen = times.drop_duplicates("market_slug")
        merged = near.merge(chosen[["market_slug", "captured_at"]],
                            on=["market_slug", "captured_at"], how="inner")
        result[seconds] = {slug: group.set_index("outcome").to_dict("index")
                           for slug, group in merged.groupby("market_slug")}
    return result


def evaluate(snapshots, candles, seconds, signal, regime, threshold, cap, fee):
    values = []
    for slug, sides in snapshots.get(seconds, {}).items():
        if not all(side in sides for side in ("Up", "Down")):
            continue
        # The slug suffix is the closing boundary, not the opening boundary.
        start = int(slug.rsplit("-", 1)[1]) - 300
        c0 = candles.get(start - 60)
        # Match augment.py: use only a candle whose close is strictly before
        # the observation timestamp, avoiding a boundary-time look-ahead.
        close_open = ((start + seconds - 1) // 60) * 60 - 60
        cx = candles.get(close_open)
        prev_candle = candles.get(close_open - 60)
        if not c0 or not cx or not prev_candle:
            continue
        prev = cx["close"] / prev_candle["close"] - 1.0
        move = cx["close"] / c0["open"] - 1.0
        same = prev * move >= 0
        if regime == "same" and not same or regime == "opposite" and same:
            continue
        if abs(prev) < threshold:
            continue
        score = {"prev": prev, "round": move, "sum": prev + move}[signal]
        side = "Up" if score > 0 else "Down"
        ask = float(sides[side]["best_ask"])
        if not (0 < ask <= cap):
            continue
        won = bool(sides[side]["is_winning_outcome"])
        values.append((1 - ask) / ask - fee if won else -1 - fee)
    return {"trades": len(values), "wins": sum(v >= 0 for v in values),
            "win_rate": None if not values else sum(v >= 0 for v in values) / len(values),
            "pnl": sum(values), "roi": None if not values else sum(values) / len(values)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=Path, required=True)
    ap.add_argument("--binance", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fee", type=float, default=.01)
    args = ap.parse_args()
    seconds = (30, 60, 90, 120, 180, 240)
    candles = load_candles(sorted(args.binance.glob("*.json")))
    snapshots = build_snapshots(args.book, seconds)
    rows = []
    for x in seconds:
        for signal in ("prev", "round", "sum"):
            for regime in ("all", "same", "opposite"):
                for threshold in (0, .00005, .0001, .0002, .0003, .0005):
                    for cap in (.55, .60, .65, .70, .75, .80, .90):
                        result = evaluate(snapshots, candles, x, signal, regime, threshold, cap, args.fee)
                        if result["trades"] >= 20:
                            rows.append({"seconds": x, "signal": signal, "regime": regime,
                                         "threshold": threshold, "max_ask": cap, **result})
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    result = {"book": str(args.book), "markets": len(snapshots[90]),
              "fee": args.fee, "top_by_pnl": rows[:50], "top_by_roi": sorted(rows, key=lambda r: r["roi"], reverse=True)[:50]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"markets": result["markets"], "top_by_pnl": rows[:10]}, indent=2))


if __name__ == "__main__":
    main()
