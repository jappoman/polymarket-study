from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

from .api import get_json, save_json


BASE = "https://api.binance.com/api/v3/klines"


def days(start: date, end: date):
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def fetch_day(day: date):
    start_ms = int(day.strftime("%s")) * 1000
    end_ms = start_ms + 86_400_000
    result = []
    cursor = start_ms
    while cursor < end_ms:
        batch = get_json(BASE, {"symbol": "BTCUSDT", "interval": "1m", "startTime": cursor,
                                "endTime": end_ms, "limit": 1000})
        if not batch:
            break
        result.extend(batch)
        cursor = int(batch[-1][0]) + 60_000
        if len(batch) < 1000:
            break
        time.sleep(0.05)
    return [{"ts": int(row[0] // 1000), "open": float(row[1]), "high": float(row[2]),
             "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])} for row in result]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--out", type=Path, default=Path("data/binance"))
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    for day in days(start, end):
        path = args.out / f"{day.isoformat()}.json"
        if path.exists():
            continue
        save_json(path, fetch_day(day))
        print(day.isoformat(), flush=True)


if __name__ == "__main__":
    main()
