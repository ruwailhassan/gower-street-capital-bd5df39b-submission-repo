"""News/sentiment agent: does weekend news explain a stock perp's weekend move relative to the market?

The model only answers a narrow question about evidence. It never sizes, places or approves trades: the deterministic
engine reads its structured answer and applies a fixed rule (see `decision`).
"""
from __future__ import annotations

import json, os, time
from pathlib import Path

import requests

MODEL = "gemini-3.5-flash-lite"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
SKIP_CONFIDENCE = 0.6
NEWS_TYPES = ["earnings or guidance", "merger or acquisition", "regulation or legal", "product or contract", "analyst action",
              "executive or insider", "company-specific crypto exposure", "macro or sector only", "no relevant news", "other"]

SCHEMA = {"type": "object", "properties": {
    "explained_by_news": {"type": "boolean"},
    "direction_consistent": {"type": "boolean"},
    "confidence": {"type": "number"},
    "news_type": {"type": "string", "enum": NEWS_TYPES},
    "key_headline_ids": {"type": "array", "items": {"type": "integer"}},
    "reasoning": {"type": "string"}},
    "required": ["explained_by_news", "direction_consistent", "confidence", "news_type", "key_headline_ids", "reasoning"]}


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY")
    if not k:
        env = Path(__file__).resolve().parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="): k = line.split("=", 1)[1].strip()
    if not k: raise RuntimeError("GEMINI_API_KEY not set")
    return k


def prompt(symbol: str, name: str, stock_move_bp: float, index_move_bp: float, gap_bp: float, heads: list[dict]) -> str:
    lines = "\n".join(f"[{i}] {h['time_et']} ET | {h['source']} | {h['title']}" for i, h in enumerate(heads)) or "(no headlines found)"
    return f"""You are checking whether weekend news explains a stock's price move on a 24/7 perpetual futures venue.
Between Friday 16:00 ET (US market close) and Sunday 17:00 ET the stock market was closed.
Stock: {symbol} ({name}). Its perp moved {stock_move_bp:+.0f} basis points; the Nasdaq-100 perp moved {index_move_bp:+.0f} bp.
So {symbol} moved {gap_bp:+.0f} bp MORE than the market ({'up' if gap_bp > 0 else 'down'} relative to the market).

Headlines published in that window:
{lines}

Question: is there company-specific news in these headlines that plausibly explains a relative move of this size and direction?
Rules:
- Market-wide or macro news (rates, tariffs on everything, index moves) does NOT explain a RELATIVE move; the market move is already removed.
- Sector news counts only if it hits this company much more than the Nasdaq-100 as a whole.
- Old stories republished, opinion pieces, "stocks to watch" lists and price-recap articles are not news.
- direction_consistent: true only if the news would push this stock {'up' if gap_bp > 0 else 'down'} relative to the market.
- confidence: 0 to 1, how sure you are that news explains the move. With no relevant headlines, explained_by_news=false.
Return JSON only."""


def judge(symbol: str, name: str, stock_move_bp: float, index_move_bp: float, gap_bp: float, heads: list[dict]) -> dict:
    """Ask the model; returns its structured answer plus the exact prompt (for the log)."""
    p = prompt(symbol, name, stock_move_bp, index_move_bp, gap_bp, heads)
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    last = None
    for a in range(5):
        r = requests.post(URL, params={"key": _key()}, json=body, timeout=60)
        if r.status_code == 200:
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            ans = json.loads(txt)
            ans["confidence"] = max(0.0, min(1.0, float(ans["confidence"])))
            return {"model": MODEL, "answer": ans, "prompt": p}
        last = f"{r.status_code} {r.text[:200]}"
        time.sleep(4 * (a + 1))
    raise RuntimeError(f"model call failed: {last}")


def decision(ans: dict | None, n_headlines: int) -> tuple[str, str]:
    """Fixed, deterministic rule on top of the model's answer. Returns (action, reason)."""
    if n_headlines == 0:
        return "trade", "no weekend headlines: move treated as noise"
    if ans is None:
        return "skip", "news check unavailable: fail safe"
    if ans["explained_by_news"] and ans["direction_consistent"] and ans["confidence"] >= SKIP_CONFIDENCE:
        return "skip", f"news explains the move ({ans['news_type']}, confidence {ans['confidence']:.2f})"
    return "trade", f"news does not explain the move ({ans['news_type']}, confidence {ans['confidence']:.2f})"


BATCH_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
    "symbol": {"type": "string"}, **SCHEMA["properties"]}, "required": ["symbol"] + SCHEMA["required"]}}}, "required": ["results"]}


def judge_batch(items: list[dict]) -> dict:
    """One call for one weekend. items: [{symbol, name, stock_move_bp, index_move_bp, gap_bp, headlines}].
    Each stock gets its own verdict under exactly the same rules as `judge`. Returns {symbol: answer}, plus the prompt."""
    blocks = []
    for it in items:
        heads = "\n".join(f"  [{i}] {h['time_et']} ET | {h['source']} | {h['title']}" for i, h in enumerate(it["headlines"])) or "  (no headlines found)"
        d = "up" if it["gap_bp"] > 0 else "down"
        blocks.append(f"### {it['symbol']} ({it['name']}): perp {it['stock_move_bp']:+.0f} bp, Nasdaq-100 perp {it['index_move_bp']:+.0f} bp, "
                      f"so {it['gap_bp']:+.0f} bp relative to the market ({d}).\n{heads}")
    p = f"""You are checking whether weekend news explains each stock's price move on a 24/7 perpetual futures venue.
Between Friday 16:00 ET (US market close) and Sunday 17:00 ET the stock market was closed. For each stock below you get its move,
the Nasdaq-100 perp's move, the move RELATIVE to the market, and the headlines published in that window (ids are per stock).

{chr(10).join(blocks)}

For EACH stock answer separately: is there company-specific news in ITS headlines that plausibly explains a relative move of that size and direction?
Rules:
- Market-wide or macro news does NOT explain a RELATIVE move; the market move is already removed.
- Sector news counts only if it hits this company much more than the Nasdaq-100 as a whole.
- Old stories republished, opinion pieces, "stocks to watch" lists and price-recap articles are not news.
- direction_consistent: true only if the news would push that stock in the direction of its relative move.
- confidence: 0 to 1, how sure you are that news explains the move. With no relevant headlines, explained_by_news=false.
Return one result per stock, using the stock's symbol. JSON only."""
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": BATCH_SCHEMA}}
    last = None
    for a in range(6):
        try:
            r = requests.post(URL, params={"key": _key()}, json=body, timeout=120)
            if r.status_code == 200:
                res = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])["results"]
                out = {}
                for x in res:
                    x["confidence"] = max(0.0, min(1.0, float(x["confidence"]))); out[x.pop("symbol").upper()] = x
                return {"model": MODEL, "answers": out, "prompt": p}
            last = f"{r.status_code} {r.text[:200]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(5 * (a + 1))
    raise RuntimeError(f"model call failed: {last}")
