from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load(path: Path):
    rows = csv.DictReader(path.open())
    markets = defaultdict(dict)
    for row in rows:
        markets[(row["slug"], int(row["seconds"]))][row["side"]] = row
    return markets


def evaluate(markets, seconds, signal, regime, prev_threshold, round_threshold,
             max_price, haircut, fee):
    values = []
    for (slug, point), market in markets.items():
        if point != seconds or not all(s in market for s in ("Up", "Down")):
            continue
        up = market["Up"]
        prev = float(up["btc_return_prev_minute"])
        move = float(up["btc_return_from_start"])
        if abs(prev) < prev_threshold or abs(move) < round_threshold:
            continue
        same = prev * move >= 0
        if regime == "same" and not same:
            continue
        if regime == "opposite" and same:
            continue
        score = {"prev": prev, "round": move, "sum": prev + move,
                 "weighted": 2.0 * prev + move}[signal]
        if score == 0:
            continue
        side = "Up" if score > 0 else "Down"
        price = float(market[side]["price"]) + haircut
        if price > max_price or price >= 1:
            continue
        values.append((1 - price) / price - fee if side == up["outcome"] else -1 - fee)
    return {
        "trades": len(values),
        "wins": sum(v >= 0 for v in values),
        "win_rate": None if not values else sum(v >= 0 for v in values) / len(values),
        "pnl": sum(values),
        "roi": None if not values else sum(values) / len(values),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", nargs="+", type=Path, required=True)
    ap.add_argument("--development-count", type=int, default=4)
    ap.add_argument("--haircut", type=float, default=.04)
    ap.add_argument("--fee", type=float, default=.01)
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    periods = [(p.parent.name, load(p)) for p in args.input]
    candidates = []
    for seconds in (30, 60, 90, 120, 180, 240):
      for signal in ("prev", "round", "sum", "weighted"):
       for regime in ("all", "same", "opposite"):
        for prev_threshold in (0, .00005, .0001, .0002, .0003, .0005):
         for round_threshold in (0, .00005, .0001, .0002):
          for cap in (.50, .55, .60, .65, .70):
            dev = [evaluate(m, seconds, signal, regime, prev_threshold, round_threshold, cap, args.haircut, args.fee)
                   for _, m in periods[:args.development_count]]
            if any(x["trades"] < args.min_trades for x in dev):
                continue
            candidates.append({
                "seconds": seconds, "signal": signal, "regime": regime,
                "prev_threshold": prev_threshold, "round_threshold": round_threshold,
                "max_price": cap, "development": dev,
                "development_pnl": sum(x["pnl"] for x in dev),
                "development_min_pnl": min(x["pnl"] for x in dev),
                "development_roi": sum(x["pnl"] for x in dev) / sum(x["trades"] for x in dev),
            })
    candidates.sort(key=lambda x: (x["development_min_pnl"], x["development_pnl"]), reverse=True)
    chosen = candidates[0] if candidates else None
    evaluation = []
    if chosen:
        evaluation = [{"period": name, **evaluate(m, chosen["seconds"], chosen["signal"], chosen["regime"],
                       chosen["prev_threshold"], chosen["round_threshold"], chosen["max_price"], args.haircut, args.fee)}
                      for name, m in periods[args.development_count:]]
    parameters = vars(args).copy()
    parameters["input"] = [str(p) for p in args.input]
    parameters["output"] = str(args.output)
    result = {"parameters": parameters, "chosen": chosen,
              "evaluation": evaluation,
              "evaluation_total": {"trades": sum(x["trades"] for x in evaluation), "pnl": sum(x["pnl"] for x in evaluation)},
              "top_candidates": candidates[:50]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("chosen", "evaluation", "evaluation_total")}, indent=2))


if __name__ == "__main__":
    main()
