from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def normal_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def pearson_binary(xs: list[float], ys: list[int]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return numerator / (dx * dy) if dx and dy else None


def run(path: Path, output: Path) -> None:
    rows = list(csv.DictReader(path.open()))
    markets = {}
    for row in rows:
        markets[row["slug"]] = row
    ordered = sorted(markets.values(), key=lambda r: int(r["start_ts"]))
    outcomes = [int(r["outcome"] == "Up") for r in ordered]
    n = len(outcomes)
    up = sum(outcomes)
    rate = up / n if n else None
    z = (rate - 0.5) / math.sqrt(0.25 / n) if n else None
    transitions = {"up_up": 0, "up_down": 0, "down_up": 0, "down_down": 0}
    for a, b in zip(outcomes, outcomes[1:]):
        transitions[('up_' if a else 'down_') + ('up' if b else 'down')] += 1
    transition_rate = {
        "P(next_up|up)": transitions["up_up"] / max(1, transitions["up_up"] + transitions["up_down"]),
        "P(next_up|down)": transitions["down_up"] / max(1, transitions["down_up"] + transitions["down_down"]),
    }
    by_second = defaultdict(list)
    for row in rows:
        if row["side"] == "Up":
            by_second[int(row["seconds"])].append((float(row["price"]), int(row["outcome"] == "Up")))
    price_stats = {}
    for second, values in sorted(by_second.items()):
        prices, labels = zip(*values)
        brier = sum((p - y) ** 2 for p, y in values) / len(values)
        price_stats[str(second)] = {"n": len(values), "correlation": pearson_binary(list(prices), list(labels)),
                                    "brier_raw_price": brier, "mean_price": sum(prices) / len(prices),
                                    "outcome_rate": sum(labels) / len(labels)}
    by_hour = defaultdict(list)
    for row in ordered:
        hour = (int(row["start_ts"]) // 3600) % 24
        by_hour[hour].append(int(row["outcome"] == "Up"))
    result = {
        "markets": n, "up_count": up, "up_rate": rate,
        "binomial_z_vs_50_50": z, "binomial_two_sided_p_approx": normal_two_sided(z) if z is not None else None,
        "transitions": transitions, "transition_rates": transition_rate,
        "price_vs_outcome_by_observation_seconds": price_stats,
        "outcome_rate_by_utc_hour": {str(h): {"n": len(v), "up_rate": sum(v) / len(v)} for h, v in sorted(by_hour.items())},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
