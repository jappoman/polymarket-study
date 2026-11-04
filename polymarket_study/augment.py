from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def load_candles(directory: Path):
    candles = {}
    for path in directory.glob("*.json"):
        for candle in json.loads(path.read_text()):
            candles[int(candle["ts"])] = candle
    return candles


def candle_at(candles, ts):
    minute = ts - ts % 60
    return candles.get(minute)


def last_closed(candles, ts):
    """Latest 1m candle whose close is strictly before observation ts."""
    open_ts = ((ts - 1) // 60) * 60 - 60
    return candles.get(open_ts)


def augment(input_path: Path, candle_dir: Path, output_path: Path):
    candles = load_candles(candle_dir)
    rows = list(csv.DictReader(input_path.open()))
    # One market's Up row carries the shared BTC feature values; downstream
    # models can use the same features for either side.
    out = []
    for row in rows:
        start = int(row["start_ts"])
        second = int(row["seconds"])
        # A Binance kline keyed by ts covers [ts, ts+60). At observation X
        # only the kline ending before X is known; using the current kline
        # would leak up to 59 seconds of future information.
        c0 = last_closed(candles, start)
        cx = last_closed(candles, start + second)
        prev = candles.get(cx["ts"] - 60) if cx else None
        if not c0 or not cx or not prev:
            continue
        base = c0["open"]
        close = cx["close"]
        prev_close = prev["close"]
        row["btc_return_from_start"] = close / base - 1.0
        row["btc_return_prev_minute"] = close / prev_close - 1.0
        row["btc_range_from_start"] = max(c0["open"], cx["high"]) / min(c0["open"], cx["low"]) - 1.0
        row["btc_abs_return_from_start"] = abs(row["btc_return_from_start"])
        out.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out[0].keys()) if out else list(rows[0].keys())
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote {len(out)} rows")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    augment(args.input, args.candles, args.output)


if __name__ == "__main__":
    main()
