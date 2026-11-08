"""Deterministic news fetch: weekend headlines for one stock from Google News search (public RSS, no key)."""
from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")
NAMES = {
    "AAOI": "Applied Optoelectronics", "AAPL": "Apple", "AMAT": "Applied Materials", "AMD": "AMD", "AMZN": "Amazon", "ARM": "Arm Holdings",
    "ASML": "ASML", "AVGO": "Broadcom", "BABA": "Alibaba", "BE": "Bloom Energy", "BMNR": "BitMine", "COIN": "Coinbase", "COST": "Costco",
    "CRCL": "Circle Internet", "CRWD": "CrowdStrike", "CRWV": "CoreWeave", "CVX": "Chevron", "DELL": "Dell", "GME": "GameStop",
    "GOOGL": "Alphabet Google", "HIMS": "Hims & Hers", "HOOD": "Robinhood", "IBM": "IBM", "INTC": "Intel", "IREN": "IREN", "LITE": "Lumentum",
    "LLY": "Eli Lilly", "LYTE": "Lyte", "META": "Meta Platforms", "MRNA": "Moderna", "MRVL": "Marvell", "MSFT": "Microsoft", "MSTR": "Strategy MicroStrategy",
    "MU": "Micron", "NBIS": "Nebius", "NFLX": "Netflix", "NOK": "Nokia", "NOW": "ServiceNow", "NVDA": "Nvidia", "ORCL": "Oracle", "PLTR": "Palantir",
    "QCOM": "Qualcomm", "QNT": "QNT", "RIVN": "Rivian", "RKLB": "Rocket Lab", "SNDK": "SanDisk", "STRC": "Strategy preferred STRC", "TSLA": "Tesla",
    "TSM": "TSMC", "UMC": "United Microelectronics", "USAR": "USA Rare Earth", "WDC": "Western Digital",
}


def weekend_window(sunday: datetime) -> tuple[datetime, datetime]:
    """Friday 16:00 ET to Sunday 17:00 ET for the weekend ending on `sunday` (a date in that Sunday)."""
    s = sunday.astimezone(NY).replace(hour=0, minute=0, second=0, microsecond=0) if sunday.tzinfo else sunday.replace(tzinfo=NY)
    return s - timedelta(days=2) + timedelta(hours=16), s + timedelta(hours=17)


def headlines(symbol: str, start: datetime, end: datetime, max_items: int = 25) -> list[dict]:
    name = NAMES.get(symbol, symbol)
    q = f'("{name}" OR {symbol}) stock after:{(start - timedelta(days=1)).date()} before:{(end + timedelta(days=1)).date()}'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    for a in range(4):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "weekend-fade-research/0.1"})
            if r.status_code == 200: break
        except requests.RequestException:
            pass
        time.sleep(2 * (a + 1))
    else:
        raise RuntimeError(f"news fetch failed for {symbol}")
    out, seen = [], set()
    for it in ET.fromstring(r.text).findall(".//item"):
        title = (it.findtext("title") or "").strip(); pub = it.findtext("pubDate")
        if not title or not pub: continue
        t = parsedate_to_datetime(pub).astimezone(NY)
        if not (start <= t <= end): continue
        key = title.lower()[:80]
        if key in seen: continue
        seen.add(key)
        out.append({"time_et": t.strftime("%a %H:%M"), "title": title, "source": (it.findtext("source") or "").strip()})
    out.sort(key=lambda h: h["time_et"])
    return out[:max_items]
