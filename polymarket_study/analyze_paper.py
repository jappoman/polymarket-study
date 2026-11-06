"""Analyze settled, canonical live paper observations.

This is intentionally separate from the historical Binance/proxy analyzer.
It only accepts schema_version=3 rows produced by paper_live.py after the
slug-start timestamp correction.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def wilson_lower(wins: int, n: int, z: float = 1.959963984540054) -> float:
    if not n:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.input.open(encoding="utf-8") if line.strip()]
    trades = [
        row for row in rows
        if row.get("schema_version") in (3, 4)
        and row.get("observation_type") == "signal"
        and row.get("outcome") in ("Up", "Down")
        and row.get("eligible") is True
        and row.get("ask") is not None
        and float(row["ask"]) > 0
    ]

    groups = defaultdict(list)
    for row in trades:
        groups[(row["strategy"], int(row["seconds"]))].append(row)

    summaries = []
    for (strategy, seconds), values in sorted(groups.items()):
        wins = sum(row.get("won") is True or row.get("side") == row.get("outcome") for row in values)
        n = len(values)
        pnl = 0.0
        for row in values:
            won = row.get("won")
            if won is None:
                won = row["side"] == row["outcome"]
            ask = float(row["ask"])
            pnl += (1 - ask) / ask - 0.01 if won else -1.01
        summaries.append({
            "strategy": strategy,
            "seconds": seconds,
            "trades": n,
            "wins": wins,
            "win_rate": wins / n if n else 0.0,
            "win_rate_95_lower": wilson_lower(wins, n),
            "pnl_fixed_stake": pnl,
            "roi": pnl / n if n else 0.0,
            "mean_ask": sum(float(row["ask"]) for row in values) / n if n else None,
            "markets": len({row["slug"] for row in values}),
        })

    result = {
        "input_rows": len(rows),
        "canonical_rows": sum(row.get("schema_version") in (3, 4) for row in rows),
        "resolved_eligible_trades": len(trades),
        "summaries": summaries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "input_rows": result["input_rows"],
        "resolved_eligible_trades": result["resolved_eligible_trades"],
        "groups": len(summaries),
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
