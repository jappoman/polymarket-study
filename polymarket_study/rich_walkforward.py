"""Leakage-safe walk-forward test for richer conditional features.

Builds one row per market/observation time from corrected historical CSVs,
fits a small regularized logistic model on earlier periods only, and trades
only when model probability exceeds a conservative ask proxy by an edge
threshold. This is a research diagnostic, not a live strategy.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


FEATURES = (
    "seconds_norm", "btc_return_from_start", "btc_return_prev_minute",
    "btc_range_from_start", "btc_abs_return_from_start", "up_price",
)


def load_markets(paths: list[Path]) -> list[dict]:
    markets = {}
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["slug"], int(row["seconds"]))
                markets.setdefault(key, {}).update(slug=row["slug"])
                if row["side"] == "Up":
                    markets.setdefault(key, {}).update(
                        up_price=float(row["price"]),
                        outcome_up=1.0 if row["outcome"] == "Up" else 0.0,
                        **{name: float(row[name]) for name in FEATURES[1:-1]},
                    )
                else:
                    markets.setdefault(key, {}).update(down_price=float(row["price"]))
                markets[key]["period"] = path.parent.name
                markets[key]["seconds"] = int(row["seconds"])
    return [row for row in markets.values() if all(k in row for k in (
        "up_price", "down_price", "outcome_up", *FEATURES[1:-1]
    ))]


def design(rows: list[dict], feature_names=FEATURES[1:], mean=None, scale=None):
    raw = np.array([[r["seconds"] / 300.0, *[r[k] for k in feature_names]] for r in rows], dtype=float)
    if mean is None:
        mean = raw.mean(axis=0)
        scale = raw.std(axis=0)
        scale[scale < 1e-12] = 1.0
    return np.column_stack([np.ones(len(raw)), (raw - mean) / scale]), mean, scale


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = 1.0):
    beta = np.zeros(x.shape[1])
    n = len(y)
    for _ in range(5000):
        z = np.clip(x @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = (x.T @ (p - y)) / n
        grad[1:] += l2 * beta[1:]
        step = 0.15 / (1.0 + _ / 500)
        new_beta = beta - step * grad
        if np.max(np.abs(new_beta - beta)) < 1e-9:
            beta = new_beta
            break
        beta = new_beta
    return beta


def predict(x, beta):
    return 1.0 / (1.0 + np.exp(-np.clip(x @ beta, -30, 30)))


def evaluate(test, beta, mean, scale, feature_names, edge_threshold, spread_haircut, fee):
    x, _, _ = design(test, feature_names, mean, scale)
    probabilities = predict(x, beta)
    trades = []
    for row, p_up in zip(test, probabilities):
        candidates = [
            ("Up", float(p_up), row["up_price"] + spread_haircut),
            ("Down", float(1 - p_up), row["down_price"] + spread_haircut),
        ]
        side, probability, ask = max(candidates, key=lambda item: item[1] - item[2])
        edge = probability - ask
        if edge < edge_threshold or ask >= 1.0:
            continue
        won = (side == "Up") == bool(row["outcome_up"])
        pnl = (1 - ask) / ask - fee if won else -1.0 - fee
        trades.append({"side": side, "ask": ask, "edge": edge, "won": won, "pnl": pnl})
    return {
        "trades": len(trades),
        "wins": sum(t["won"] for t in trades),
        "pnl": sum(t["pnl"] for t in trades),
        "roi": sum(t["pnl"] for t in trades) / len(trades) if trades else 0.0,
        "mean_edge": sum(t["edge"] for t in trades) / len(trades) if trades else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--train-periods", type=int, default=4)
    parser.add_argument("--edge", type=float, default=0.03)
    parser.add_argument("--spread-haircut", type=float, default=0.04)
    parser.add_argument("--fee", type=float, default=0.01)
    parser.add_argument("--exclude-price", action="store_true",
                        help="fit without the observed Up price feature")
    parser.add_argument("--seconds", type=int, default=None,
                        help="evaluate only at this observation time")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.input_dir.glob("*/observations_btc.csv"))
    period_rows = {path.parent.name: load_markets([path]) for path in paths}
    periods = sorted(period_rows)
    feature_names = tuple(name for name in FEATURES[1:] if not (args.exclude_price and name == "up_price"))
    results = []
    for index in range(args.train_periods, len(periods)):
        train = [row for name in periods[:index] for row in period_rows[name]]
        test = period_rows[periods[index]]
        if args.seconds is not None:
            test = [row for row in test if row["seconds"] == args.seconds]
        x, mean, scale = design(train, feature_names)
        beta = fit_logistic(x, np.array([r["outcome_up"] for r in train]))
        result = evaluate(test, beta, mean, scale, feature_names, args.edge, args.spread_haircut, args.fee)
        results.append({"test_period": periods[index], **result})
    result = {
        "model": "regularized_logistic_market_level",
        "features": ["seconds", *feature_names],
        "periods": periods,
        "train_periods": args.train_periods,
        "edge_threshold": args.edge,
        "spread_haircut": args.spread_haircut,
        "fee": args.fee,
        "evaluation": results,
        "evaluation_total": {
            "trades": sum(r["trades"] for r in results),
            "wins": sum(r["wins"] for r in results),
            "pnl": sum(r["pnl"] for r in results),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["evaluation_total"], indent=2))


if __name__ == "__main__":
    main()
