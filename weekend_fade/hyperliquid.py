"""Read-only Hyperliquid public market data. There is deliberately no signing, wallet or order code anywhere in this package."""
from __future__ import annotations

import time

import requests

URL = "https://api.hyperliquid.xyz/info"


def _post(body: dict, tries: int = 6):
    for a in range(tries):
        r = requests.post(URL, json=body, timeout=30)
        if r.status_code == 200:
            return r.json()
        time.sleep(2 * (a + 1))
    r.raise_for_status()


def universe(dex: str) -> list[dict]:
    return _post({"type": "meta", "dex": dex})["universe"]


def candles(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    return _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms}})


def book(coin: str) -> dict:
    """{'bids': [(px, sz), ...], 'asks': [...], 'mid': float, 'time_ms': int}"""
    b = _post({"type": "l2Book", "coin": coin})
    bids = [(float(x["px"]), float(x["sz"])) for x in b["levels"][0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in b["levels"][1]]
    mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else float("nan")
    return {"bids": bids, "asks": asks, "mid": mid, "time_ms": b.get("time")}
