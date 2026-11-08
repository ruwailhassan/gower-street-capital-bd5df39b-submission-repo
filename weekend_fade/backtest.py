"""Reproducible backtest of the weekend fade against simple baselines.

  python -m weekend_fade.backtest --fetch   # download 1h candles from Hyperliquid's public API (no key), ~5 min
  python -m weekend_fade.backtest           # run, write results/BACKTEST.md, results/backtest.json, results/equity.png

Hyperliquid's API serves the most recent ~5,000 hourly candles per market, so the sample is roughly the last 7 months.
Prices are 1h candle opens/closes (last trades), not executable quotes: the three fill models bracket the true cost.
"""
from __future__ import annotations

import argparse, json, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import hyperliquid as hl
from .config import BIG, DEFAULT, DEX, INDEX, NO_BLUE_OCEAN, NOT_US_STOCK
from .signals import log_return_bp, trigger_bp

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
DATA, RES = ROOT / "data", ROOT / "results"


def fetch() -> None:
    DATA.mkdir(exist_ok=True)
    meta = hl.universe(DEX)
    coins = [u["name"].split(":")[1] for u in meta if u["name"].split(":")[1] not in NOT_US_STOCK] + [INDEX]
    rows, now = [], int(time.time() * 1000)
    for i, c in enumerate(coins):
        for x in hl.candles(f"{DEX}:{c}", "1h", 1_700_000_000_000, now):
            rows.append({"coin": c, "t": x["t"], "o": float(x["o"]), "h": float(x["h"]), "l": float(x["l"]), "c": float(x["c"]),
                         "v": float(x["v"]), "n": int(x["n"])})
        time.sleep(2)
        print(f"{i + 1}/{len(coins)} {c}", flush=True)
    d = pd.DataFrame(rows)
    d.to_parquet(DATA / "candles_1h.parquet")
    fees = {u["name"].split(":")[1]: u.get("growthMode") == "enabled" for u in meta}
    (DATA / "growth_mode.json").write_text(json.dumps(fees))
    print(f"saved {len(d):,} candles for {d.coin.nunique()} markets")


def build_panel() -> pd.DataFrame:
    d = pd.read_parquet(DATA / "candles_1h.parquet")
    d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True).dt.tz_convert(ET); d["usd"] = d.v * d.c
    K = d.set_index(["coin", "ts"]).sort_index()
    coins = [c for c in d.coin.unique() if c != INDEX and c not in NO_BLUE_OCEAN]
    def bar(k, t):
        try: return K.loc[(k, t)]
        except KeyError: return None
    at = lambda day, dd, h: (pd.Timestamp(day) + pd.Timedelta(days=dd, hours=h)).tz_localize(ET)
    rows = []
    for day in sorted({t.tz_localize(None).normalize() for t in d.ts}):
        wd = day.weekday()
        if wd == 6: night, sig = "weekend", ((-2, 15), (0, 16))      # Fri 16:00 close -> Sun 17:00 close
        elif wd in (0, 1, 2, 3): night, sig = "weeknight", ((0, 15), (0, 16))   # placebo: 16:00 -> 17:00 same day
        else: continue
        t0, t1, te, tx = at(day, *sig[0]), at(day, *sig[1]), at(day, 0, 18), at(day, 1, 4)
        I = [bar(INDEX, t) for t in (t0, t1, te, tx)]
        if any(b is None for b in I): continue
        for k in coins:
            B = [bar(k, t) for t in (t0, t1, te, tx)]
            if any(b is None for b in B): continue
            rows.append({"date": str(day.date()), "night": night, "stock": k, "big": k in BIG,
                         "gap": log_return_bp(B[0].c, B[1].c) - log_return_bp(I[0].c, I[1].c),
                         "s_o": B[2].o, "s_h": B[2].h, "s_l": B[2].l, "x_o": B[3].o, "x_h": B[3].h, "x_l": B[3].l,
                         "i_e": I[2].o, "i_x": I[3].o, "hour_usd": B[2].usd})
    return pd.DataFrame(rows)


def simulate(P: pd.DataFrame, rule: str, fill: str, cfg=DEFAULT) -> pd.DataFrame:
    growth = json.loads((DATA / "growth_mode.json").read_text())
    trig = P.stock.map(lambda k: trigger_bp(k, cfg))
    if rule == "fade (the strategy)": T = P[(P.gap.abs() >= trig) & (P.gap.abs() < cfg.review_bp)].copy(); T["side"] = -np.sign(T.gap)
    elif rule == "follow the gap (momentum)": T = P[(P.gap.abs() >= trig) & (P.gap.abs() < cfg.review_bp)].copy(); T["side"] = np.sign(T.gap)
    elif rule == "fade everything, no trigger": T = P[P.gap.abs() < cfg.review_bp].copy(); T["side"] = -np.sign(T.gap)
    else: raise ValueError(rule)
    s = T.side
    if fill == "price you see + half-spread":
        e, x = T.s_o, T.x_o; hs = np.where(T.big, cfg.half_spread_bp_big, cfg.half_spread_bp_other)
    elif fill == "25% of the hour's range against you":
        e, x = T.s_o + s * 0.25 * (T.s_h - T.s_l), T.x_o - s * 0.25 * (T.x_h - T.x_l); hs = 0
    else:  # worst price in the hour
        e, x = np.where(s > 0, T.s_h, T.s_l), np.where(s > 0, T.x_l, T.x_h); hs = 0
    fee = T.stock.map(lambda k: cfg.fee_bp_growth if growth.get(k) else cfg.fee_bp_standard)
    stock = s * 1e4 * np.log(np.asarray(x, float) / np.asarray(e, float))
    index = -s * 1e4 * np.log(T.i_x / T.i_e)
    T["net_bp"] = stock + index - 2 * fee - 2 * hs - 2 * (cfg.fee_bp_growth + cfg.index_slippage_bp)
    T["size_usd"] = np.minimum(np.where(T.big, cfg.max_usd_big, cfg.max_usd_other), cfg.max_share_of_hour_volume * T.hour_usd)
    T["pnl_usd"] = T.size_usd * T.net_bp / 1e4
    T["rule"], T["fill"] = rule, fill
    return T


def summarise(T: pd.DataFrame, n_nights: int) -> dict:
    if T.empty: return {"trades": 0}
    per = T.groupby("date").net_bp.mean()
    return {"trades": int(len(T)), "avg_net_pct": round(T.net_bp.mean() / 100, 3), "win_rate_pct": round(100 * (T.net_bp > 0).mean(), 1),
            "t_stat_by_night": round(per.mean() / (per.std(ddof=1) / np.sqrt(len(per))), 2) if len(per) > 2 else None,
            "nights_with_trades": f"{len(per)}/{n_nights}", "nights_positive": int((per > 0).sum()),
            "avg_size_usd": round(T.size_usd.mean()), "total_pnl_usd": round(T.pnl_usd.sum()), "worst_trade_pct": round(T.net_bp.min() / 100, 2)}


def run() -> dict:
    RES.mkdir(exist_ok=True)
    P = build_panel()
    out = {"sample": {"weekends": int(P[P.night == "weekend"].date.nunique()), "weeknights": int(P[P.night == "weeknight"].date.nunique()),
                      "stocks": int(P.stock.nunique()), "first": P.date.min(), "last": P.date.max()}, "results": []}
    for night in ("weekend", "weeknight"):
        Pn = P[P.night == night]; n = Pn.date.nunique()
        half = sorted(Pn.date.unique())[n // 2]
        for rule in ("fade (the strategy)", "follow the gap (momentum)", "fade everything, no trigger"):
            for fill in ("price you see + half-spread", "25% of the hour's range against you", "worst price in the hour"):
                if night == "weeknight" and rule != "fade (the strategy)": continue
                T = simulate(Pn, rule, fill)
                r = {"night": night, "rule": rule, "fill": fill, **summarise(T, n)}
                if rule == "fade (the strategy)":
                    r["first_half_avg_pct"] = round(T[T.date < half].net_bp.mean() / 100, 3)
                    r["second_half_avg_pct"] = round(T[T.date >= half].net_bp.mean() / 100, 3)
                    r["big_names_avg_pct"] = round(T[T.big].net_bp.mean() / 100, 3)
                    r["other_stocks_avg_pct"] = round(T[~T.big].net_bp.mean() / 100, 3)
                out["results"].append(r)
                if night == "weekend" and rule == "fade (the strategy)" and fill.startswith("price you see"):
                    T.to_csv(RES / "weekend_trades.csv", index=False); best = T
    # share of the gap that comes back (regression slope), weekend vs weeknight
    for night in ("weekend", "weeknight"):
        Pn = P[P.night == night]
        y = (np.log(Pn.x_o / Pn.s_o) - np.log(Pn.i_x / Pn.i_e)) * 1e4
        out[f"share_of_gap_that_returns_{night}"] = round(float(-np.polyfit(Pn.gap, y, 1)[0]), 3)
    (RES / "backtest.json").write_text(json.dumps(out, indent=1, default=str))
    _report(out); _chart(best)
    return out


def _report(out: dict) -> None:
    R = pd.DataFrame(out["results"])
    lines = ["# Weekend fade: backtest", "",
             f"Sample: {out['sample']['weekends']} weekends and {out['sample']['weeknights']} weeknights, {out['sample']['stocks']} US stock perps, "
             f"{out['sample']['first']} to {out['sample']['last']} (Hyperliquid 1h candles). In-sample: the rule was designed on this period.", "",
             f"Share of the weekend gap that comes back by Monday 04:00: **{out['share_of_gap_that_returns_weekend']:.0%}**; "
             f"on weeknights (placebo): **{out['share_of_gap_that_returns_weeknight']:.0%}**.", "",
             R.to_markdown(index=False)]
    (RES / "BACKTEST.md").write_text("\n".join(lines))


def _chart(T: pd.DataFrame) -> None:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    w = T.groupby("date").pnl_usd.sum().cumsum()
    fig, ax = plt.subplots(figsize=(9, 3.5)); ax.plot(pd.to_datetime(w.index), w.values, color="#2b6cb0", lw=2)
    ax.axhline(0, color="#999", lw=0.7); ax.set_ylabel("cumulative paper P&L ($)")
    ax.set_title("Weekend fade, volume-capped sizes, 'price you see + half-spread' fills (in-sample)", fontsize=9)
    fig.tight_layout(); fig.savefig(RES / "equity.png", dpi=120)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--fetch", action="store_true"); a = ap.parse_args()
    if a.fetch: fetch()
    out = run()
    print(json.dumps(out["sample"]), "\nshare of gap returning: weekend", out["share_of_gap_that_returns_weekend"], "weeknight", out["share_of_gap_that_returns_weeknight"])
    print(pd.DataFrame(out["results"]).to_string(index=False))
