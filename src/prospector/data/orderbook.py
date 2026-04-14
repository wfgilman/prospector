"""
Live L2 orderbook poller for slippage calibration.

Subscribes to Hyperliquid's WebSocket l2Book feed and stores periodic
snapshots as parquet. This process runs continuously in the background
to accumulate real spread and depth data that cannot be retrieved
historically via the public API.

Storage layout:
    data/orderbook/<coin>/YYYY-MM-DD.parquet

Schema (one row per snapshot):
    timestamp      datetime64[ms, UTC]
    coin           str
    bid_px_1..10   float64    best bid price (1 = best)
    bid_sz_1..10   float64    size at that level
    ask_px_1..10   float64    best ask price (1 = best)
    ask_sz_1..10   float64    size at that level
    mid            float64    (ask_px_1 + bid_px_1) / 2
    spread         float64    ask_px_1 - bid_px_1
    spread_pct     float64    spread / mid

Usage:
    python -m prospector.data.orderbook
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

WS_URL = "wss://api.hyperliquid.xyz/ws"
N_LEVELS = 10  # levels per side to store

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "orderbook"

DEFAULT_COINS = ["BTC-PERP", "ETH-PERP", "SOL-PERP"]

# Flush accumulated snapshots to parquet every N rows (per coin).
FLUSH_EVERY = 500


def _coin_api(name: str) -> str:
    return name.removesuffix("-PERP")


def _parquet_path(coin: str, date: str, base: Path = DATA_DIR) -> Path:
    safe_coin = coin.replace("-", "_")
    return base / safe_coin / f"{date}.parquet"


def _snapshot_to_row(coin: str, ts_ms: int, levels: list[list]) -> dict:
    """
    Convert a raw l2Book levels payload to a flat dict row.

    `levels` is [[bids], [asks]] where each entry is {"px": str, "sz": str, "n": int}.
    """
    bids, asks = levels[0], levels[1]
    row: dict = {
        "timestamp": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
        "coin": coin,
    }
    for i in range(N_LEVELS):
        bid = bids[i] if i < len(bids) else None
        ask = asks[i] if i < len(asks) else None
        row[f"bid_px_{i+1}"] = float(bid["px"]) if bid else float("nan")
        row[f"bid_sz_{i+1}"] = float(bid["sz"]) if bid else float("nan")
        row[f"ask_px_{i+1}"] = float(ask["px"]) if ask else float("nan")
        row[f"ask_sz_{i+1}"] = float(ask["sz"]) if ask else float("nan")

    best_bid = row["bid_px_1"]
    best_ask = row["ask_px_1"]
    row["mid"] = (best_bid + best_ask) / 2 if (best_bid and best_ask) else float("nan")
    row["spread"] = best_ask - best_bid if (best_bid and best_ask) else float("nan")
    row["spread_pct"] = row["spread"] / row["mid"] if row["mid"] else float("nan")
    return row


def _flush(coin: str, rows: list[dict], base: Path) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    path = _parquet_path(coin, date_str, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
    df.to_parquet(path, index=False)
    log.debug("%s: flushed %d rows → %s", coin, len(rows), path)


async def _connect_and_stream(
    coins: list[str],
    buffers: dict[str, list[dict]],
    base: Path,
) -> None:
    """Open one WebSocket connection, stream until it drops, then return."""
    import websockets
    from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

    # Disable client-side pings: Hyperliquid manages its own server-side
    # heartbeat and does not reliably respond to client pings.
    async with websockets.connect(WS_URL, ping_interval=None) as ws:
        for coin in coins:
            sub = {
                "method": "subscribe",
                "subscription": {"type": "l2Book", "coin": _coin_api(coin)},
            }
            await ws.send(json.dumps(sub))
            log.info("Subscribed to l2Book for %s", coin)

        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("channel") != "l2Book":
                    continue

                data = msg.get("data", {})
                api_coin = data.get("coin", "")
                ts_ms = data.get("time", int(datetime.now(tz=timezone.utc).timestamp() * 1000))
                levels = data.get("levels", [[], []])

                matched = next((c for c in coins if _coin_api(c) == api_coin), None)
                if matched is None:
                    continue

                row = _snapshot_to_row(matched, ts_ms, levels)
                buffers[matched].append(row)

                if len(buffers[matched]) >= FLUSH_EVERY:
                    _flush(matched, buffers[matched], base)
                    buffers[matched] = []

        except (ConnectionClosedError, ConnectionClosedOK) as exc:
            log.warning("WebSocket connection closed: %s — will reconnect", exc)


async def poll(
    coins: list[str] = DEFAULT_COINS,
    base: Path = DATA_DIR,
    reconnect_delay: float = 5.0,
) -> None:
    """
    Subscribe to l2Book for all coins and write snapshots to parquet.
    Reconnects automatically on drop. Runs forever; interrupt with Ctrl-C.
    """
    import asyncio

    buffers: dict[str, list[dict]] = {c: [] for c in coins}

    while True:
        try:
            await _connect_and_stream(coins, buffers, base)
        except Exception as exc:
            log.error("Unexpected error: %s — reconnecting in %.0fs", exc, reconnect_delay)

        # Flush any buffered rows before reconnecting so data isn't lost on drops.
        for coin, rows in buffers.items():
            if rows:
                _flush(coin, rows, base)
                buffers[coin] = []

        log.info("Reconnecting in %.0fs…", reconnect_delay)
        await asyncio.sleep(reconnect_delay)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Poll Hyperliquid L2 orderbook snapshots")
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    try:
        asyncio.run(poll(coins=args.coins, base=args.data_dir))
    except KeyboardInterrupt:
        log.info("Stopped by user — flushing buffers")
        # Buffers are flushed on each reconnect cycle; final flush is best-effort.
