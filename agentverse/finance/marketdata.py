"""Real price paths from Binance's free public archive, anonymised for evaluation.

Source: https://github.com/binance/binance-public-data (data.binance.vision).
Licence: CC BY-NC-SA 4.0 under the Binance Vision Dataset Terms. Non-commercial
education/backtesting only; attribute "Binance Vision"; no endorsement implied.
Data is downloaded on the participant's machine at run time and is never
bundled with this kit. Standard library only; no account or API key.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines"
LIVE_API = "https://data-api.binance.vision/api/v3"
ATTRIBUTION = "Price returns derived from Binance Vision public data (CC BY-NC-SA 4.0). Not endorsed by Binance."
# Liquid USDT pairs with continuous spot history since at least 2021.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT")
INTERVALS = ("1h", "4h", "1d")
FIRST_MONTH = (2021, 1)
USER_AGENT = "agentverse-finance-kit/2 (educational backtesting)"


def http_get(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def available_months(today: date | None = None) -> list[tuple[int, int]]:
    """Monthly archives publish after the month ends; skip the last two months to be safe."""
    today = today or date.today()
    end_year, end_month = today.year, today.month - 2
    while end_month < 1:
        end_year, end_month = end_year - 1, end_month + 12
    months, (year, month) = [], FIRST_MONTH
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def archive_url(symbol: str, interval: str, year: int, month: int) -> str:
    if symbol not in SYMBOLS or interval not in INTERVALS:
        raise ValueError(f"Use one of {SYMBOLS} and interval {INTERVALS}")
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{ARCHIVE}/{symbol}/{interval}/{name}"


def parse_klines(zip_bytes: bytes) -> list[tuple[int, str]]:
    """Return (open_time_ms, close) rows. Spot timestamps are microseconds from 2025."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = [n for n in archive.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Expected exactly one CSV in the Binance archive")
        text = archive.read(names[0]).decode("utf-8")
    rows = []
    for record in csv.reader(io.StringIO(text)):
        if not record or not record[0].strip().isdigit():
            continue  # some archives carry a header row
        opened = int(record[0])
        if opened > 10**14:  # microseconds
            opened //= 1000
        close = record[4].strip()
        if not math.isfinite(float(close)) or float(close) <= 0:
            raise ValueError("Archive contains a non-positive close price")
        rows.append((opened, close))
    rows.sort()
    if len(rows) < 10 or any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Archive rows are too few or not strictly increasing")
    return rows


def fetch_month(symbol, interval, year, month, cache: Path | None = None, getter=http_get):
    """Download one monthly archive, verify Binance's published SHA-256, parse it."""
    url = archive_url(symbol, interval, year, month)
    cached = cache / url.rsplit("/", 1)[1] if cache else None
    if cached and cached.exists():
        payload = cached.read_bytes()
    else:
        payload = getter(url)
        expected = getter(url + ".CHECKSUM").decode("utf-8").split()[0].lower()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for {url}; refusing the file")
        if cached:
            cache.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(payload)
    return parse_klines(payload)


def anonymised_window(closes: list[str], rng: random.Random, length: int, invert: bool):
    """Rebase a real window into integer pence of a fictional GBP asset.

    Returns are preserved exactly up to rounding. Optional inversion negates every
    log return (p' = p0^2 / p), so drift alone cannot win and the path is harder
    to look up. Real dates and the symbol are removed.
    """
    if len(closes) < length:
        raise ValueError("Series shorter than requested window")
    start = rng.randrange(len(closes) - length + 1)
    window = [float(value) for value in closes[start : start + length]]
    first = window[0]
    base = rng.randint(5000, 50000)
    prices = []
    for value in window:
        ratio = (first / value) if invert else (value / first)
        prices.append(max(1, round(base * ratio)))
    origin = date(2001, 1, 1) + timedelta(days=rng.randrange(3000))
    return prices, [str(origin + timedelta(days=i)) for i in range(length)]


def real_market_cases(count: int, seed: int, getter=http_get, cache: Path | None = None, today=None):
    """Build `count` anonymised real-data market inputs. Each draws a hidden
    (symbol, interval, month, window, inversion) from the seed. Months are fetched once."""
    if type(count) is not int or not 1 <= count <= 500:
        raise ValueError("Choose 1 to 500 real market paths")
    picker = random.Random(hashlib.sha256(f"real-markets:{seed}".encode()).digest())
    months = available_months(today)
    plans = [
        (picker.choice(SYMBOLS), picker.choice(("1h", "1h", "4h")), picker.choice(months))
        for _ in range(count)
    ]
    loaded, cases = {}, []
    for index, (symbol, interval, (year, month)) in enumerate(plans):
        key = (symbol, interval, year, month)
        if key not in loaded:
            loaded[key] = [close for _, close in fetch_month(*key, cache=cache, getter=getter)]
        rng = random.Random(hashlib.sha256(f"real-path:{seed}:{index}".encode()).digest())
        closes = loaded[key]
        length = rng.randint(48, min(240, len(closes)))
        prices, dates = anonymised_window(closes, rng, length, invert=rng.random() < 0.5)
        cases.append(
            {
                "prices_pence": prices,
                "dates": dates,
                "initial_cash_pence": rng.randint(100000, 1000000),
                "fee_pence": rng.randint(0, 200),
                "slippage_bps": rng.randint(0, 40),
            }
        )
    return cases, sorted(f"{s} {i} {y}-{m:02d}" for s, i, y, m in loaded)


# ---------- live forward test: the future has not happened yet ----------


def live_closed_klines(symbol: str, interval: str, limit: int, getter=http_get, now_ms=None):
    """Closed candles only (close_time < now). Binance REST returns strings for prices."""
    url = f"{LIVE_API}/klines?symbol={symbol}&interval={interval}&limit={limit + 1}"
    rows = json.loads(getter(url, timeout=10).decode("utf-8"))
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    closed = [(int(r[0]), r[4]) for r in rows if int(r[6]) < now_ms]
    return closed[-limit:]


def live_price(symbol: str, getter=http_get) -> str:
    payload = json.loads(getter(f"{LIVE_API}/ticker/price?symbol={symbol}", timeout=10).decode("utf-8"))
    return payload["price"]
