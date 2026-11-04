from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .api import get_json, save_json


GAMMA = "https://gamma-api.polymarket.com/events"
CLOB = "https://clob.polymarket.com/prices-history"
SERIES_ID = 10684  # BTC Up or Down 5m recurring series


def day_ranges(start: date, end: date):
    current = start
    while current < end:
        following = current + timedelta(days=1)
        yield current.isoformat() + "T00:00:00Z", following.isoformat() + "T00:00:00Z"
        current = following


def parse_json_field(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def discover(start: date, end: date) -> list[dict]:
    found: dict[str, dict] = {}
    for lower, upper in day_ranges(start, end):
        offset = 0
        while True:
            rows = get_json(GAMMA, {
                "series_id": SERIES_ID,
                "closed": "true",
                "limit": 500,
                "offset": offset,
                "start_date_min": lower,
                "start_date_max": upper,
            })
            if not rows:
                break
            for event in rows:
                if not event.get("slug", "").startswith("btc-updown-5m-"):
                    continue
                for market in event.get("markets", []):
                    record = dict(market)
                    record["event_slug"] = event.get("slug")
                    record["event_title"] = event.get("title")
                    record["event_description"] = event.get("description")
                    record["event_resolution_source"] = event.get("resolutionSource")
                    found[record["slug"]] = record
            # Gamma currently returns at most 100 rows for this filtered
            # series even when a larger limit is requested.
            if len(rows) == 0:
                break
            offset += len(rows)
            if offset > 1000:
                raise RuntimeError("Gamma pagination exceeded its safe per-day limit")
    return sorted(found.values(), key=lambda row: row.get("startDate", ""))


def fetch_history(token_id: str, start_ts: int, end_ts: int) -> list[dict]:
    # With an explicit window the CLOB returns the market's trade points in
    # that round instead of a heavily downsampled long-range series.
    result = get_json(CLOB, {
        "market": token_id,
        "startTs": max(0, start_ts - 120),
        "endTs": end_ts + 120,
    })
    return result.get("history", [])


def collect_one(market: dict, out: Path, sleep_seconds: float) -> str:
    slug = market["slug"]
    path = out / "history" / f"{slug}.json"
    if path.exists():
        return "skipped"
    tokens = parse_json_field(market.get("clobTokenIds", []))
    outcomes = parse_json_field(market.get("outcomes", []))
    # BTC 5m slugs use the round's closing boundary as the suffix, e.g.
    # ...-1786751700 is the 23:55 UTC close of the 23:50--23:55 round.
    end_ts = int(slug.rsplit("-", 1)[1])
    start_ts = end_ts - 300
    history = {}
    for outcome, token in zip(outcomes, tokens):
        history[outcome] = fetch_history(str(token), start_ts, end_ts)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    save_json(path, {"slug": slug, "market_id": market.get("id"), "history": history})
    return "downloaded"


def collect(start: date, end: date, out: Path, sleep_seconds: float, workers: int) -> None:
    markets = discover(start, end)
    save_json(out / "markets.json", markets)
    print(f"discovered {len(markets)} markets")
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(collect_one, market, out, sleep_seconds) for market in markets]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                # A single public-API disconnect must not discard completed
                # rounds; the next resumable run will retry this market.
                print(f"warning: {type(exc).__name__}: {exc}", flush=True)
            completed += 1
            if completed % 25 == 0 or completed == len(markets):
                print(f"processed {completed}/{len(markets)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, help="UTC date, inclusive")
    parser.add_argument("--end-date", required=True, help="UTC date, exclusive")
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    collect(date.fromisoformat(args.start_date), date.fromisoformat(args.end_date), args.out, args.sleep, args.workers)


if __name__ == "__main__":
    main()
