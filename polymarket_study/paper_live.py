"""Public, no-login paper recorder for live BTC 5m markets.

It never creates orders. It records the live best ask at fixed observation
points and the independent BTC signal so the strategies can be settled later.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets


GAMMA = "https://gamma-api.polymarket.com/events"
WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
OBSERVATIONS = (30, 60, 90, 120, 180, 240)


def get_active_markets() -> list[dict]:
    response = requests.get(GAMMA, params={
        "series_id": 10684, "active": "true", "closed": "false", "limit": 100,
    }, timeout=20)
    response.raise_for_status()
    now = int(time.time())
    markets = []
    for event in response.json():
        for market in event.get("markets", []):
            slug = market.get("slug", "")
            if not slug.startswith("btc-updown-5m-"):
                continue
            try:
                end = int(slug.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            if now - 5 < end <= now + 600 and market.get("clobTokenIds"):
                markets.append(market)
    return sorted({m["slug"]: m for m in markets}.values(), key=lambda m: m["slug"])


def parse_tokens(market: dict) -> tuple[list[str], list[str]]:
    outcomes = market.get("outcomes", [])
    tokens = market.get("clobTokenIds", [])
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(tokens, str):
        tokens = json.loads(tokens)
    return [str(x) for x in outcomes], [str(x) for x in tokens]


def btc_features(start: int, seconds: int) -> dict | None:
    end_ms = (start + seconds + 60) * 1000
    response = requests.get("https://api.binance.com/api/v3/klines", params={
        "symbol": "BTCUSDT", "interval": "1m", "startTime": (start - 180) * 1000,
        "endTime": end_ms, "limit": 10,
    }, timeout=10)
    response.raise_for_status()
    candles = {int(row[0] // 1000): {"open": float(row[1]), "close": float(row[4])}
               for row in response.json()}
    close_open = ((start + seconds - 1) // 60) * 60 - 60
    c0, cx, previous = candles.get(start - 60), candles.get(close_open), candles.get(close_open - 60)
    if not c0 or not cx or not previous:
        return None
    return {
        "btc_return_from_start": cx["close"] / c0["open"] - 1.0,
        "btc_return_prev_minute": cx["close"] / previous["close"] - 1.0,
    }


def update_book(books: dict, message: dict) -> None:
    event = message.get("event_type")
    if event == "book":
        asks = message.get("asks", [])
        bids = message.get("bids", [])
        books[message["asset_id"]] = {
            "best_ask": min((float(x["price"]) for x in asks), default=None),
            "best_bid": max((float(x["price"]) for x in bids), default=None),
            "book_ts": message.get("timestamp"),
        }
    elif event == "price_change":
        for change in message.get("price_changes", message.get("changes", [])):
            asset = change.get("asset_id")
            if not asset:
                continue
            book = books.setdefault(asset, {})
            if change.get("best_ask") is not None:
                book["best_ask"] = float(change["best_ask"])
            if change.get("best_bid") is not None:
                book["best_bid"] = float(change["best_bid"])
            book["book_ts"] = message.get("timestamp")


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


async def record(duration: int, output: Path, threshold: float, max_ask: float) -> None:
    deadline = time.time() + duration
    written = 0
    last_status = 0.0
    while time.time() < deadline:
        markets = await asyncio.to_thread(get_active_markets)
        if not markets:
            if time.time() - last_status >= 30:
                print("[paper] nessun mercato BTC 5m attivo trovato; continuo a controllare", flush=True)
                last_status = time.time()
            await asyncio.sleep(5)
            continue
        print(f"[paper] mercati attivi: {len(markets)} | osservazioni salvate: {written}", flush=True)
        token_map = {}
        pending = {}
        now = int(time.time())
        for market in markets:
            end = int(market["slug"].rsplit("-", 1)[1])
            start = end - 300
            outcomes, tokens = parse_tokens(market)
            for outcome, token in zip(outcomes, tokens):
                token_map[token] = (market["slug"], outcome, start, end)
            for seconds in OBSERVATIONS:
                target = start + seconds
                if target >= now - 2:
                    pending[(market["slug"], seconds)] = target
        books: dict[str, dict] = {}
        seen: set[tuple[str, int]] = set()
        assets = list(token_map)
        try:
            async with websockets.connect(WS, ping_interval=None, close_timeout=5) as socket:
                await socket.send(json.dumps({"assets_ids": assets, "type": "market", "custom_feature_enabled": True}))
                end_cycle = min(deadline, time.time() + 75)
                while time.time() < end_cycle:
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=1.0)
                        if raw not in ("PONG", "pong"):
                            message = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                            if isinstance(message, dict):
                                update_book(books, message)
                    except asyncio.TimeoutError:
                        pass
                    if int(time.time()) % 10 == 0:
                        await socket.send("PING")
                    current = time.time()
                    for key, target in pending.items():
                        if key in seen or current < target or current > target + 3:
                            continue
                        slug, seconds = key
                        features = await asyncio.to_thread(btc_features, target - seconds, seconds)
                        if not features:
                            seen.add(key)
                            continue
                        prev = features["btc_return_prev_minute"]
                        move = features["btc_return_from_start"]
                        same = prev * move >= 0
                        for strategy, eligible, side in (
                            ("prev_follow", abs(prev) >= threshold, "Up" if prev > 0 else "Down"),
                            ("round_follow", abs(move) >= threshold, "Up" if move > 0 else "Down"),
                            ("same_prev", abs(prev) >= threshold and same, "Up" if prev > 0 else "Down"),
                            ("opposite_prev", abs(prev) >= threshold and not same, "Up" if prev > 0 else "Down"),
                        ):
                            token = next((t for t, v in token_map.items() if v[0] == slug and v[1] == side), None)
                            book = books.get(token, {}) if token else {}
                            ask = book.get("best_ask")
                            append(output, {
                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                                "slug": slug, "start_ts": target - seconds, "seconds": seconds,
                                "strategy": strategy, "side": side, "eligible": eligible and ask is not None and ask <= max_ask,
                                "signal_threshold": threshold, "max_ask": max_ask, "ask": ask,
                                "bid": book.get("best_bid"), "book_ts": book.get("book_ts"), **features,
                            })
                            written += 1
                        seen.add(key)
                    if time.time() - last_status >= 30:
                        print(f"[paper] in esecuzione | mercati: {len(markets)} | righe salvate: {written}", flush=True)
                        last_status = time.time()
                await socket.close()
        except Exception as exc:
            append(output, {"recorded_at": datetime.now(timezone.utc).isoformat(),
                            "event": "connection_error", "error": repr(exc)})
            print(f"[paper] errore connessione: {exc!r}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=3600)
    parser.add_argument("--output", type=Path, default=Path("data/paper/live.jsonl"))
    parser.add_argument("--threshold", type=float, default=.0002)
    parser.add_argument("--max-ask", type=float, default=.55)
    args = parser.parse_args()
    asyncio.run(record(args.duration, args.output, args.threshold, args.max_ask))


if __name__ == "__main__":
    main()
