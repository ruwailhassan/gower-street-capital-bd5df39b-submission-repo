"""Historical test of the news filter: run the news check on every past trade and compare traded vs skipped.
Results cached in results/news_cache.jsonl (safe to resume)."""
from __future__ import annotations

import json, time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .backtest import DATA, RES
from .config import INDEX
from .news import NAMES, headlines, weekend_window
from .rule_research import panel, simulate
from .sentiment_agent import decision, judge

ET = ZoneInfo("America/New_York")
CACHE = RES / "news_cache.jsonl"


def moves():
    d = pd.read_parquet(DATA / "candles_1h.parquet"); d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True).dt.tz_convert(ET)
    return d.pivot_table(index="ts", columns="coin", values="c")


HEADS = RES / "news_headlines.jsonl"
CHECKS = RES / "news_checks.jsonl"


def run_checks(trades: pd.DataFrame):
    """1) fetch every trade's weekend headlines in parallel (cached); 2) one model call per weekend (cached)."""
    from concurrent.futures import ThreadPoolExecutor
    from .sentiment_agent import MODEL, judge_batch
    C = moves()
    heads = {}
    if HEADS.exists():
        for l in HEADS.read_text().splitlines(): r = json.loads(l); heads[(r["date"], r["stock"])] = r
    if CACHE.exists():                       # reuse headlines fetched by the first (per-trade) run
        for l in CACHE.read_text().splitlines():
            r = json.loads(l); heads.setdefault((r["date"], r["stock"]), {"date": r["date"], "stock": r["stock"], "headlines": r["headlines"]})
    def info(t):
        sun = pd.Timestamp(t.date)
        fri, s17 = (sun - pd.Timedelta(days=2, hours=-15)).tz_localize(ET), (sun + pd.Timedelta(hours=16)).tz_localize(ET)
        return 1e4 * np.log(C.at[s17, t.stock] / C.at[fri, t.stock]), 1e4 * np.log(C.at[s17, INDEX] / C.at[fri, INDEX])
    todo = [t for t in trades.itertuples() if (t.date, t.stock) not in heads]
    def fetch(t):
        sun = pd.Timestamp(t.date); start, end = weekend_window(datetime(sun.year, sun.month, sun.day, tzinfo=ET))
        return t, headlines(t.stock, start, end)
    with ThreadPoolExecutor(6) as ex:
        for t, h in ex.map(fetch, todo):
            rec = {"date": t.date, "stock": t.stock, "headlines": h}; heads[(t.date, t.stock)] = rec
            with open(HEADS, "a") as f: f.write(json.dumps(rec) + "\n")
    print(f"headlines ready for {len(heads)} trades ({len(todo)} fetched now)", flush=True)
    checks = {}
    if CHECKS.exists():
        for l in CHECKS.read_text().splitlines(): r = json.loads(l); checks[(r["date"], r["stock"])] = r
    for date, g in trades.groupby("date"):
        g = [t for t in g.itertuples() if (t.date, t.stock) not in checks]
        if not g: continue
        items, rows = [], []
        for t in g:
            sm, im = info(t); h = heads[(t.date, t.stock)]["headlines"]
            rows.append((t, sm, im, h))
            if h: items.append({"symbol": t.stock, "name": NAMES.get(t.stock, t.stock), "stock_move_bp": sm, "index_move_bp": im, "gap_bp": sm - im, "headlines": h})
        answers = judge_batch(items)["answers"] if items else {}
        for t, sm, im, h in rows:
            ans = answers.get(t.stock) if h else None
            if h and ans is None: print("no verdict for", t.stock, date); continue     # leave out, never count as a skip
            act, why = decision(ans, len(h))
            rec = {"date": t.date, "stock": t.stock, "gap": sm - im, "n_headlines": len(h), "headlines": h, "answer": ans, "action": act, "why": why, "model": MODEL}
            checks[(t.date, t.stock)] = rec
            with open(CHECKS, "a") as f: f.write(json.dumps(rec) + "\n")
        print(f"{date}: {len(g)} trades, {len(items)} with headlines, skips: {sum(checks[(t.date, t.stock)]['action'] == 'skip' for t, *_ in rows if (t.date, t.stock) in checks)}", flush=True)
    return pd.DataFrame(checks.values())


def weekly(T):
    w = T.groupby("date").net.mean()
    return {"trades": int(len(T)), "mean_bp": float(T.net.mean()), "win": float(100 * (T.net > 0).mean()), "weeks": int(len(w)),
            "t": float(w.mean() / (w.std(ddof=1) / np.sqrt(len(w)))) if len(w) > 2 else None,
            "sharpe": float(w.mean() / w.std(ddof=1) * np.sqrt(52)) if len(w) > 2 else None, "worst_bp": float(T.net.min())}


def main():
    P = panel()
    rules = {"v1 (Sun 18:00, 1:1, exit 04:00)": (18, ("time", 28), "1:1"), "v2 (Sun 19:00, beta, take 50% else 04:00)": (19, ("target", .5, 28), "beta")}
    trades = {k: simulate(P, e, x, h, "equal", None) for k, (e, x, h) in rules.items()}
    N = run_checks(trades["v1 (Sun 18:00, 1:1, exit 04:00)"][["date", "stock"]].drop_duplicates())
    out = {}
    for k, T in trades.items():
        M = T.merge(N[["date", "stock", "action", "n_headlines", "answer"]], on=["date", "stock"], how="left")
        M["action"] = M.action.fillna("trade")
        out[k] = {"all trades (no filter)": weekly(M), "kept by news filter": weekly(M[M.action == "trade"]),
                  "skipped (news explains move)": weekly(M[M.action == "skip"]) if (M.action == "skip").sum() > 2 else {"trades": int((M.action == "skip").sum()), "mean_bp": float(M[M.action == "skip"].net.mean()) if (M.action == "skip").any() else None},
                  "no headlines at all": weekly(M[M.n_headlines == 0]) if (M.n_headlines == 0).sum() > 2 else None}
        M.to_csv(RES / f"news_filter_trades_{k.split()[0]}.csv", index=False)
    (RES / "news_backtest.json").write_text(json.dumps(out, default=str, indent=1))
    for k, v in out.items():
        print("\n" + k)
        for g, s in v.items(): print(f"  {g:32s} {json.dumps({a: (round(b, 2) if isinstance(b, float) else b) for a, b in (s or {}).items()})}")


if __name__ == "__main__":
    main()
