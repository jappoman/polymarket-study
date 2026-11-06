"""Public, no-login paper recorder for live BTC 5m markets.

It never creates orders. It records Polymarket's live CLOB prices and the
resolution-aligned Chainlink TWAP-60 stream relayed by Polymarket RTDS.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets


GAMMA = "https://gamma-api.polymarket.com/events"
WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RTDS = "wss://ws-live-data.polymarket.com"
OBSERVATIONS = (30, 60, 90, 120, 180, 240, 300)
MAX_CHAINLINK_LAG = 5.0
CHAINLINK_WARMUP_SPAN = 70.0
CHAINLINK_WARMUP_TIMEOUT = 180.0
RTDS_REFRESH_SECONDS = 3.0
SCHEMA_VERSION = 4
MIN_ASK_SIZE = 1.0
MAX_SILENCE_SECONDS = 180.0


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
                start = int(slug.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            # The numeric suffix is the market start timestamp.
            if now - 300 < start <= now + 600 and market.get("clobTokenIds"):
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


def update_chainlink(prices: dict, message: dict) -> None:
    """Keep Polymarket's public Chainlink TWAP-60 stream, without look-ahead."""
    if message.get("topic") != "crypto_prices_twap_sixty":
        return
    payload = message.get("payload") or {}
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        records = [payload]
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("symbol") not in (None, "btc/usd"):
            continue
        timestamp = record.get("timestamp") or message.get("timestamp")
        value = record.get("value")
        if value is None and record.get("full_accuracy_value") is not None:
            value = float(record["full_accuracy_value"]) / 1e18
        if timestamp is None or value is None:
            continue
        points = prices.setdefault("twap60", [])
        points.append((int(float(timestamp)) / 1000.0, float(value)))
        cutoff = points[-1][0] - 1800
        prices["twap60"] = [point for point in points if point[0] >= cutoff]


def nearest_chainlink(points: list[tuple[float, float]], target: float):
    before = [point for point in points if point[0] <= target]
    return max(before, key=lambda point: point[0]) if before else None


def chainlink_features(prices: dict, start: int, seconds: int) -> dict | None:
    points = prices.get("twap60", [])
    opening = nearest_chainlink(points, start)
    current = nearest_chainlink(points, start + seconds)
    previous = nearest_chainlink(points, start + seconds - 60)
    if not opening or not current or not previous:
        return None
    if any(target - point[0] > MAX_CHAINLINK_LAG for target, point in (
        (start, opening), (start + seconds, current),
        (start + seconds - 60, previous),
    )):
        return None
    window = [value for timestamp, value in points
              if start <= timestamp <= start + seconds]
    if not window:
        return None
    return {
        "btc_source": "polymarket_rtds_chainlink_twap_60",
        "chainlink_twap_start": opening[1],
        "chainlink_twap_at_observation": current[1],
        "chainlink_twap_return_from_start": current[1] / opening[1] - 1.0,
        "chainlink_twap_return_prev_minute": current[1] / previous[1] - 1.0,
        "chainlink_twap_range_from_start": max(window) / opening[1] - min(window) / opening[1],
        "chainlink_twap_abs_return_from_start": abs(current[1] / opening[1] - 1.0),
        "chainlink_observed_at": current[0],
        "chainlink_lag_seconds": start + seconds - current[0],
    }


async def collect_chainlink(prices: dict, stop: asyncio.Event) -> None:
    subscription = {
        "action": "subscribe",
        "subscriptions": [{
            "topic": "crypto_prices_twap_sixty",
            "type": "update",
            "filters": json.dumps({"symbol": "btc/usd"}),
        }],
    }
    while not stop.is_set():
        try:
            async with websockets.connect(RTDS, close_timeout=5, max_queue=None) as socket:
                await socket.send(json.dumps(subscription))
                # The legacy public RTDS endpoint currently sends a history
                # snapshot on subscribe but may not emit subsequent TWAP
                # updates on the same socket. Reconnect periodically so the
                # snapshot remains a live, timestamped poll rather than a
                # silently frozen 59-second window.
                refresh_deadline = time.monotonic() + RTDS_REFRESH_SECONDS
                while not stop.is_set() and time.monotonic() < refresh_deadline:
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=5)
                        if isinstance(raw, bytes):
                            raw = raw.decode()
                        if raw in ("PONG", "pong", "PING", "ping", ""):
                            continue
                        message = json.loads(raw)
                        if isinstance(message, dict):
                            update_chainlink(prices, message)
                    except asyncio.TimeoutError:
                        continue
        except Exception as exc:
            if not stop.is_set():
                print(f"[paper] Chainlink RTDS non disponibile: {exc!r}; ritento", flush=True)
                await asyncio.sleep(2)


def update_book(books: dict, message: dict | list, history: dict | None = None) -> None:
    if isinstance(message, list):
        for item in message:
            update_book(books, item, history)
        return
    if not isinstance(message, dict):
        return
    event = message.get("event_type")
    if event == "book":
        asks = message.get("asks", [])
        bids = message.get("bids", [])
        best_ask = min(((float(x["price"]), float(x.get("size", 0))) for x in asks), default=(None, None))
        best_bid = max(((float(x["price"]), float(x.get("size", 0))) for x in bids), default=(None, None))
        books[message["asset_id"]] = {
            "best_ask": best_ask[0], "best_ask_size": best_ask[1],
            "best_bid": best_bid[0], "best_bid_size": best_bid[1],
            "book_ts": message.get("timestamp"),
        }
        if history is not None:
            history.setdefault(message["asset_id"], []).append(
                copy.copy(books[message["asset_id"]]))
    elif event == "price_change":
        for change in message.get("price_changes", message.get("changes", [])):
            asset = change.get("asset_id")
            if not asset:
                continue
            book = books.setdefault(asset, {})
            if change.get("best_ask") is not None:
                book["best_ask"] = float(change["best_ask"])
                if change.get("best_ask_size") is not None:
                    book["best_ask_size"] = float(change["best_ask_size"])
                elif change.get("side") == "SELL":
                    book["best_ask_size"] = float(change.get("size", 0))
            if change.get("best_bid") is not None:
                book["best_bid"] = float(change["best_bid"])
                if change.get("best_bid_size") is not None:
                    book["best_bid_size"] = float(change["best_bid_size"])
                elif change.get("side") == "BUY":
                    book["best_bid_size"] = float(change.get("size", 0))
            book["book_ts"] = message.get("timestamp")
            if history is not None:
                history.setdefault(asset, []).append(copy.copy(book))


def book_at_or_before(history: dict, asset: str, target: float) -> dict:
    candidates = []
    for book in history.get(asset, []):
        raw_ts = book.get("book_ts")
        try:
            timestamp = float(raw_ts) / 1000.0 if float(raw_ts) > 10_000_000_000 else float(raw_ts)
        except (TypeError, ValueError):
            continue
        if timestamp <= target:
            candidates.append((timestamp, book))
    return max(candidates, key=lambda item: item[0])[1] if candidates else {}


def append(path: Path, row: dict) -> None:
    row.setdefault("schema_version", SCHEMA_VERSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


async def record(duration: int, output: Path, threshold: float, max_ask: float) -> None:
    deadline = time.time() + duration
    written = 0
    last_write = time.time()
    last_status = 0.0
    last_health = 0.0
    chainlink: dict = {}
    seen: set[tuple[str, int]] = set()
    chainlink_stop = asyncio.Event()
    chainlink_task = asyncio.create_task(collect_chainlink(chainlink, chainlink_stop))
    print("[paper] warm-up Chainlink in corso; non salvo osservazioni finché il feed non ha storico sufficiente", flush=True)
    warmup_deadline = min(deadline, time.time() + CHAINLINK_WARMUP_TIMEOUT)
    warmup_started = time.time()
    chainlink_ready = False
    while time.time() < warmup_deadline:
        points = chainlink.get("twap60", [])
        span = points[-1][0] - points[0][0] if len(points) >= 2 else 0.0
        if span >= CHAINLINK_WARMUP_SPAN:
            print(f"[paper] Chainlink pronto | storico: {span:.0f}s", flush=True)
            chainlink_ready = True
            break
        await asyncio.sleep(1)
    if not chainlink_ready:
        waited = time.time() - warmup_started
        print(f"[paper] ATTENZIONE: Chainlink non pronto dopo {waited:.0f}s; continuo a ritentare senza salvare dati stantii", flush=True)
    while time.time() < deadline:
        if time.time() - last_write > MAX_SILENCE_SECONDS:
            raise RuntimeError(
                f"nessun dato scritto da {time.time() - last_write:.0f}s; "
                "riavvio richiesto dal supervisore"
            )
        points = chainlink.get("twap60", [])
        span = points[-1][0] - points[0][0] if len(points) >= 2 else 0.0
        if time.time() - last_health >= 60:
            append(output, {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "event": "health", "chainlink_ready": span >= CHAINLINK_WARMUP_SPAN,
                "chainlink_points": len(points), "chainlink_span_seconds": span,
                "observations_saved": written,
            })
            last_write = time.time()
            print(f"[paper] health | Chainlink: {span:.0f}s di storico | righe salvate: {written}", flush=True)
            last_health = time.time()
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
            start = int(market["slug"].rsplit("-", 1)[1])
            end = start + 300
            outcomes, tokens = parse_tokens(market)
            for outcome, token in zip(outcomes, tokens):
                token_map[token] = (market["slug"], outcome, start, end)
            for seconds in OBSERVATIONS:
                target = start + seconds
                if target >= now - 2:
                    pending[(market["slug"], seconds)] = target
        books: dict[str, dict] = {}
        book_history: dict[str, list[dict]] = {}
        assets = list(token_map)
        try:
            async with websockets.connect(WS, ping_interval=None, close_timeout=5, max_queue=None) as socket:
                await socket.send(json.dumps({"assets_ids": assets, "type": "market", "custom_feature_enabled": True}))
                end_cycle = min(deadline, time.time() + 75)
                last_ping = 0.0
                receive_task = asyncio.create_task(socket.recv())
                while time.time() < end_cycle:
                    done, _ = await asyncio.wait(
                        {receive_task}, timeout=1.0,
                    )
                    if receive_task in done:
                        try:
                            raw = receive_task.result()
                            if raw not in ("PONG", "pong"):
                                message = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                                if isinstance(message, (dict, list)):
                                    update_book(books, message, book_history)
                        finally:
                            receive_task = asyncio.create_task(socket.recv())
                    if time.time() - last_ping >= 10:
                        await socket.send("PING")
                        last_ping = time.time()
                    current = time.time()
                    for key, target in pending.items():
                        # Keep a target pending briefly: RTDS can deliver a
                        # snapshot several seconds after its newest timestamp.
                        # The feature function still enforces point <= target
                        # and the five-second source-lag guard, so this wait
                        # does not introduce look-ahead.
                        if key in seen or current < target:
                            continue
                        slug, seconds = key
                        features = chainlink_features(chainlink, target - seconds, seconds)
                        if not features:
                            if current <= target + 15:
                                continue
                            seen.add(key)
                            continue
                        prev = features["chainlink_twap_return_prev_minute"]
                        move = features["chainlink_twap_return_from_start"]
                        if seconds == 300:
                            append(output, {
                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                                "observation_type": "close_snapshot", "slug": slug,
                                "start_ts": target - seconds, "seconds": seconds,
                                "strategy": "close_snapshot", "side": None, "eligible": False,
                                "signal_threshold": threshold, "max_ask": max_ask,
                                "ask": None, "bid": None, **features,
                            })
                            last_write = time.time()
                            written += 1
                            seen.add(key)
                            continue
                        same = prev * move >= 0
                        for strategy, eligible, side in (
                            ("prev_follow", abs(prev) >= threshold, "Up" if prev > 0 else "Down"),
                            ("round_follow", abs(move) >= threshold, "Up" if move > 0 else "Down"),
                            ("same_prev", abs(prev) >= threshold and same, "Up" if prev > 0 else "Down"),
                            ("opposite_prev", abs(prev) >= threshold and not same, "Up" if prev > 0 else "Down"),
                        ):
                            token = next((t for t, v in token_map.items() if v[0] == slug and v[1] == side), None)
                            book = book_at_or_before(book_history, token, target) if token else {}
                            up_token = next((t for t, v in token_map.items()
                                             if v[0] == slug and v[1] == "Up"), None)
                            down_token = next((t for t, v in token_map.items()
                                               if v[0] == slug and v[1] == "Down"), None)
                            up_book = book_at_or_before(book_history, up_token, target) if up_token else {}
                            down_book = book_at_or_before(book_history, down_token, target) if down_token else {}
                            ask = book.get("best_ask")
                            ask_size = book.get("best_ask_size")
                            append(output, {
                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                                "observation_type": "signal",
                                "slug": slug, "start_ts": target - seconds, "seconds": seconds,
                                "strategy": strategy, "side": side,
                                "eligible": eligible and ask is not None and ask <= max_ask and
                                ask_size is not None and ask_size >= MIN_ASK_SIZE,
                                "signal_threshold": threshold, "max_ask": max_ask, "ask": ask,
                                "ask_size": ask_size, "bid": book.get("best_bid"),
                                "bid_size": book.get("best_bid_size"), "book_ts": book.get("book_ts"),
                                "up_ask": up_book.get("best_ask"),
                                "up_ask_size": up_book.get("best_ask_size"),
                                "up_bid": up_book.get("best_bid"),
                                "up_bid_size": up_book.get("best_bid_size"),
                                "up_book_ts": up_book.get("book_ts"),
                                "down_ask": down_book.get("best_ask"),
                                "down_ask_size": down_book.get("best_ask_size"),
                                "down_bid": down_book.get("best_bid"),
                                "down_bid_size": down_book.get("best_bid_size"),
                                "down_book_ts": down_book.get("book_ts"), **features,
                            })
                            last_write = time.time()
                            written += 1
                        seen.add(key)
                    if time.time() - last_status >= 30:
                        print(f"[paper] in esecuzione | mercati: {len(markets)} | righe salvate: {written}", flush=True)
                        last_status = time.time()
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await receive_task
                with contextlib.suppress(asyncio.TimeoutError, Exception):
                    await asyncio.wait_for(socket.close(), timeout=3)
        except Exception as exc:
            append(output, {"recorded_at": datetime.now(timezone.utc).isoformat(),
                            "event": "connection_error", "error": repr(exc)})
            last_write = time.time()
            print(f"[paper] errore connessione: {exc!r}", flush=True)
    chainlink_stop.set()
    await chainlink_task


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
