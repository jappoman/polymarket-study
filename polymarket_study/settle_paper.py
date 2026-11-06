from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


GAMMA = "https://gamma-api.polymarket.com/markets"
EVENTS = "https://gamma-api.polymarket.com/events"


def outcome(slug: str):
    response = requests.get(GAMMA, params={"slug": slug}, timeout=20)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        response = requests.get(EVENTS, params={"slug": slug}, timeout=20)
        response.raise_for_status()
        events = response.json()
        rows = [market for event in events for market in event.get("markets", [])]
    if not rows:
        return None
    market = rows[0]
    outcomes = market.get("outcomes", [])
    prices = market.get("outcomePrices", [])
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(prices, str):
        prices = json.loads(prices)
    prices = [float(x) for x in prices]
    if not prices or max(prices) < .999:
        return None
    return {
        "outcome": outcomes[prices.index(max(prices))],
        "final_outcome_prices": prices,
        "resolution_source": market.get("resolutionSource") or "",
        "closed": market.get("closed"),
        "end_date": market.get("endDate"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fee", type=float, default=.01)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.open() if line.strip()]
    cache = {}
    close_snapshots = {
        row.get("slug"): row for row in rows
        if row.get("schema_version") in (3, 4)
        and row.get("observation_type") == "close_snapshot"
        and row.get("btc_source") == "polymarket_rtds_chainlink_twap_60"
        and row.get("chainlink_lag_seconds") is not None
        and float(row["chainlink_lag_seconds"]) <= 5
    }
    settled = []
    for row in rows:
        slug = row.get("slug")
        if slug and slug not in cache:
            cache[slug] = outcome(slug)
        result = cache.get(slug)
        final = result["outcome"] if result else None
        row["outcome"] = final
        if result:
            row.update({key: value for key, value in result.items() if key != "outcome"})
        elif slug in close_snapshots:
            close = close_snapshots[slug]
            start_value = float(close["chainlink_twap_start"])
            final_value = float(close["chainlink_twap_at_observation"])
            row["outcome"] = "Up" if final_value >= start_value else "Down"
            row["resolution_source"] = "chainlink_close_snapshot_derived"
            row["resolution_rule"] = "close_twap >= opening_twap"
            row["resolution_derived"] = True
            final = row["outcome"]
        ask = row.get("ask")
        if row.get("eligible") and final and ask is not None:
            won = row["side"] == final
            row["won"] = won
            row["pnl_fixed_stake"] = ((1 - float(ask)) / float(ask) - args.fee
                                       if won else -1 - args.fee)
        settled.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for row in settled:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    trades = [r for r in settled if "pnl_fixed_stake" in r]
    print(json.dumps({"rows": len(settled), "settled_trades": len(trades),
                      "pnl": sum(r["pnl_fixed_stake"] for r in trades),
                      "wins": sum(r["won"] for r in trades)}, indent=2))


if __name__ == "__main__":
    main()
