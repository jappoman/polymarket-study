from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


OBSERVATION_SECONDS = (30, 60, 90, 120, 180, 240)


def epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def parse(value):
    return json.loads(value) if isinstance(value, str) else value


def nearest(history: list[dict], target: float):
    usable = [(float(row["t"]), float(row["p"])) for row in history if "t" in row and "p" in row]
    if not usable:
        return None
    before = [row for row in usable if row[0] <= target]
    if before:
        return max(before, key=lambda row: row[0])
    return min(usable, key=lambda row: abs(row[0] - target))


def outcome(market: dict) -> str | None:
    outcomes = parse(market.get("outcomes", []))
    prices = [float(x) for x in parse(market.get("outcomePrices", []))]
    if not outcomes or not prices:
        return None
    # Resolved markets normally expose [1, 0] or [0, 1]. Ignore unresolved and split outcomes.
    if max(prices) < 0.999 or min(prices) > 0.001:
        return None
    return outcomes[prices.index(max(prices))]


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def calibration_and_backtest(rows: list[dict], output_dir: Path, test_fraction: float,
                             edge: float, haircut: float, stake: float, kelly_fraction: float) -> None:
    """Chronological, expanding-window calibration and execution backtest."""
    ordered = sorted(rows, key=lambda row: (int(row["start_ts"]), int(row["seconds"]), row["side"]))
    split = max(1, int(len(ordered) * (1.0 - test_fraction)))
    train = ordered[:split]
    test = ordered[split:]
    # Coarse buckets reduce noise and make the estimate usable for unseen prices.
    def key(row):
        return (int(row["seconds"]), row["side"], int(float(row["price"]) * 20))

    stats = defaultdict(lambda: [0, 0])
    for row in train:
        k = key(row)
        stats[k][0] += 1
        stats[k][1] += int(row["won"])

    trades = []
    bankroll = 100.0
    for row in test:
        n, wins = stats[key(row)]
        # Laplace smoothing prevents a small bucket from becoming 0% or 100%.
        p_hat = (wins + 1.0) / (n + 2.0)
        observed = float(row["price"])
        execution = min(0.999, observed + haircut)
        edge_value = p_hat - execution
        kelly = max(0.0, edge_value / max(1e-9, 1.0 - execution))
        stake_amount = min(stake, bankroll) if edge_value > edge else 0.0
        if kelly_fraction > 0 and stake_amount:
            stake_amount = min(bankroll, bankroll * kelly * kelly_fraction)
        pnl = 0.0
        if stake_amount > 0:
            pnl = stake_amount * ((1.0 - execution) / execution) if int(row["won"]) else -stake_amount
            bankroll += pnl
        trades.append({
            **row, "train_n": n, "p_hat": p_hat, "execution_price": execution,
            "edge": edge_value, "kelly": kelly, "stake": stake_amount, "pnl": pnl,
            "bankroll": bankroll, "traded": int(stake_amount > 0),
        })
        # Expanding window: a real strategy can only use markets already seen.
        stats[key(row)][0] += 1
        stats[key(row)][1] += int(row["won"])

    trade_rows = [r for r in trades if r["traded"]]
    wins_test = sum(int(r["won"]) for r in trades)
    brier = sum((float(r["p_hat"]) - int(r["won"])) ** 2 for r in trades) / max(1, len(trades))
    summary = {
        "train_rows": len(train), "test_rows": len(test), "trades": len(trade_rows),
        "test_win_rate": wins_test / max(1, len(trades)), "brier_score": brier,
        "starting_bankroll": 100.0, "ending_bankroll": bankroll,
        "total_pnl": bankroll - 100.0, "edge_threshold": edge,
        "spread_haircut": haircut, "fixed_stake": stake,
        "kelly_fraction": kelly_fraction,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "backtest_trades.csv", trades,
              ["slug", "start_ts", "seconds", "side", "price", "outcome", "won",
               "pnl_fixed_stake", "train_n", "p_hat", "execution_price", "edge",
               "kelly", "stake", "pnl", "bankroll", "traded", "resolution_source"])
    (output_dir / "backtest_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def run(input_dir: Path, output_dir: Path, test_fraction: float = 0.3,
        edge: float = 0.03, haircut: float = 0.01, stake: float = 1.0,
        kelly_fraction: float = 0.25) -> None:
    markets = json.loads((input_dir / "markets.json").read_text())
    rows = []
    for market in markets:
        final = outcome(market)
        start = market.get("startDate")
        history_path = input_dir / "history" / f"{market['slug']}.json"
        if not final or not start or not history_path.exists():
            continue
        history = json.loads(history_path.read_text()).get("history", {})
        # Gamma's startDate can be the creation time. For recurring BTC
        # rounds, the slug suffix is the canonical five-minute closing
        # boundary, so the round starts 300 seconds earlier.
        try:
            end_ts = int(market["slug"].rsplit("-", 1)[1])
            start_ts = end_ts - 300
        except (KeyError, ValueError):
            start_ts = epoch(start)
        for seconds in OBSERVATION_SECONDS:
            for side in ("Up", "Down"):
                point = nearest(history.get(side, []), start_ts + seconds)
                if point is None:
                    continue
                price = point[1]
                won = int(side == final)
                # One fixed dollar stake: shares = 1 / price. This is the gross binary payoff.
                pnl = (1.0 / price - 1.0) if won else -1.0
                rows.append({
                    "slug": market["slug"], "start_ts": int(start_ts), "seconds": seconds,
                    "side": side, "price": price, "outcome": final, "won": won, "pnl_fixed_stake": pnl,
                    "resolution_source": market.get("resolutionSource") or market.get("event_resolution_source", ""),
                })
    fields = ["slug", "start_ts", "seconds", "side", "price", "outcome", "won", "pnl_fixed_stake", "resolution_source"]
    write_csv(output_dir / "observations.csv", rows, fields)
    summaries = []
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["seconds"], row["side"], min(99, int(float(row["price"]) * 100)))].append(row)
    for (seconds, side, bucket), values in sorted(grouped.items()):
        n = len(values)
        wins = sum(int(v["won"]) for v in values)
        summaries.append({"seconds": seconds, "side": side, "price_bucket": bucket / 100, "n": n,
                          "win_rate": wins / n, "mean_pnl_fixed_stake": sum(float(v["pnl_fixed_stake"]) for v in values) / n})
    write_csv(output_dir / "summary_by_price.csv", summaries,
              ["seconds", "side", "price_bucket", "n", "win_rate", "mean_pnl_fixed_stake"])
    calibration_and_backtest(rows, output_dir, test_fraction, edge, haircut, stake, kelly_fraction)
    print(f"wrote {len(rows)} observations and {len(summaries)} summary rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/analysis"))
    parser.add_argument("--test-fraction", type=float, default=0.3)
    parser.add_argument("--edge", type=float, default=0.03)
    parser.add_argument("--haircut", type=float, default=0.01)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.25)
    args = parser.parse_args()
    run(args.input, args.output, args.test_fraction, args.edge, args.haircut,
        args.stake, args.kelly_fraction)


if __name__ == "__main__":
    main()
