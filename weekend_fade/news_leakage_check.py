"""Can the news model 'remember' the future? Two checks.
1. Direct probes: ask the model what happened to specific stocks after specific weekends.
2. Blinded rerun: company names and tickers scrubbed from every headline, stocks labelled Company A, B, ...
   If the filter still separates good trades from bad ones blind, it is judging the news, not recalling outcomes.
"""
from __future__ import annotations

import json, re, string

import numpy as np
import pandas as pd
import requests

from .backtest import RES
from .news import NAMES
from .sentiment_agent import MODEL, URL, _key, decision, judge_batch

ALIASES = {"GOOGL": ["Google", "Alphabet", "YouTube", "Waymo"], "META": ["Facebook", "Instagram", "WhatsApp", "Zuckerberg"], "MSTR": ["Saylor", "MicroStrategy"],
           "TSLA": ["Musk", "Elon"], "NVDA": ["Huang"], "AAPL": ["iPhone"], "AMZN": ["AWS", "Bezos", "Jassy"], "MSFT": ["Nadella", "Azure"], "COIN": ["Armstrong"]}


def scrub(text: str, sym: str) -> str:
    words = [sym] + [w for w in re.split(r"[\s&]+", NAMES.get(sym, "")) if len(w) > 2] + ALIASES.get(sym, [])
    for w in sorted(set(words), key=len, reverse=True):
        text = re.sub(rf"(?i)\b{re.escape(w)}('s)?\b", "the company", text)
    return text


def probes():
    qs = ["What is your training data cutoff date? Answer with a month and year only.",
          "What happened to IREN Limited stock on Monday 12 October 2026, and did reports that Anthropic was its customer move the price? If you do not know, say UNKNOWN.",
          "How did Nvidia stock perform on Monday 13 July 2026? If you do not know, say UNKNOWN.",
          "Did SanDisk stock rise or fall on Monday 13 July 2026? If you do not know, say UNKNOWN.",
          "What was the biggest news about Micron Technology in October 2026? If you do not know, say UNKNOWN."]
    out = []
    for q in qs:
        r = requests.post(URL, params={"key": _key()}, json={"contents": [{"parts": [{"text": q}]}], "generationConfig": {"temperature": 0}}, timeout=120)
        a = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip() if r.status_code == 200 else f"error {r.status_code}"
        out.append({"q": q, "a": a}); print(f"Q: {q}\nA: {a[:400]}\n", flush=True)
    return out


def blinded():
    R = [json.loads(l) for l in open(RES / "news_checks.jsonl")]
    by_date = {}
    for r in R: by_date.setdefault(r["date"], []).append(r)
    rows = []
    for date, rs in sorted(by_date.items()):
        items, label = [], {}
        for i, r in enumerate([x for x in rs if x["n_headlines"]]):
            lab = f"COMPANY_{string.ascii_uppercase[i % 26]}{'' if i < 26 else i // 26}"; label[lab] = r["stock"]
            heads = [{**h, "title": scrub(h["title"], r["stock"])} for h in r["headlines"]]
            gap = r["gap"]
            items.append({"symbol": lab, "name": "name withheld", "stock_move_bp": gap, "index_move_bp": 0.0, "gap_bp": gap, "headlines": heads})
        ans = judge_batch(items)["answers"] if items else {}
        for r in rs:
            lab = next((k for k, v in label.items() if v == r["stock"]), None)
            a = ans.get(lab) if lab else None
            if r["n_headlines"] and a is None: continue
            act, why = decision(a, r["n_headlines"])
            rows.append({"date": date, "stock": r["stock"], "blind_action": act, "orig_action": r["action"]})
        print(date, len(items), "blinded", flush=True)
    return pd.DataFrame(rows)


def main():
    P = probes()
    B = blinded()
    M = pd.read_csv(RES / "news_filter_trades_v2.csv")[["date", "stock", "net"]].merge(B, on=["date", "stock"])
    res = {"model": MODEL, "probes": P, "agreement_with_named_run": float((M.blind_action == M.orig_action).mean())}
    for col in ("orig_action", "blind_action"):
        k, s = M[M[col] == "trade"].net, M[M[col] == "skip"].net
        res[col] = {"kept_n": int(len(k)), "kept_mean_bp": float(k.mean()), "skipped_n": int(len(s)), "skipped_mean_bp": float(s.mean())}
    (RES / "news_leakage_check.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "probes"}, indent=1))


if __name__ == "__main__":
    main()
