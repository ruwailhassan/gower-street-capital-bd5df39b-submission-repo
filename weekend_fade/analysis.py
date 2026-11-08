"""Everything behind the explainer: statistical tests, variant comparison, timing curve and worked example trades.

  python -m weekend_fade.analysis        # writes results/analysis.json (needs data/ from `backtest --fetch`)
"""
from __future__ import annotations

import json, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import hyperliquid as hl
from .backtest import DATA, RES, build_panel, simulate
from .config import BIG, DEFAULT, INDEX, NO_BLUE_OCEAN

ET = ZoneInfo("America/New_York")
RNG = np.random.default_rng(7)
FAIR = "price you see + half-spread"


def clustered_slope(df, y, x, groups):
    d = df[[y, x] + groups].dropna()
    g = np.column_stack([pd.factorize(d[c])[0] for c in groups]) if len(groups) > 1 else pd.factorize(d[groups[0]])[0]
    m = sm.OLS(d[y], sm.add_constant(d[x])).fit(cov_type="cluster", cov_kwds={"groups": g})
    return {"slope": float(m.params[x]), "se": float(m.bse[x]), "t": float(m.tvalues[x]), "p": float(m.pvalues[x]),
            "intercept": float(m.params["const"]), "n": int(len(d)), "r2": float(m.rsquared)}


def weekly_stats(T: pd.DataFrame, col="net_bp") -> dict:
    w = T.groupby("date")[col].mean().sort_index(); n = len(w)
    t = w.mean() / (w.std(ddof=1) / np.sqrt(n))
    nw = sm.OLS(w.values, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": 2})
    flips = np.array([(w.values * RNG.choice([-1, 1], n)).mean() for _ in range(20000)])
    boots = np.array([RNG.choice(w.values, n, replace=True).mean() for _ in range(20000)])
    loo = [(np.delete(w.values, i).mean() / (np.delete(w.values, i).std(ddof=1) / np.sqrt(n - 1))) for i in range(n)]
    top3 = w.sort_values().iloc[:-3]
    return {"weeks": n, "mean_bp": float(w.mean()), "sd_bp": float(w.std(ddof=1)), "t": float(t), "t_newey_west": float(nw.tvalues[0]),
            "sharpe_annual": float(w.mean() / w.std(ddof=1) * np.sqrt(52)), "signflip_p": float((np.abs(flips) >= abs(w.mean())).mean()),
            "boot_ci95_bp": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "leave_one_out_t_min": float(min(loo)), "leave_one_out_t_max": float(max(loo)),
            "drop_best3_mean_bp": float(top3.mean()), "drop_best3_t": float(top3.mean() / (top3.std(ddof=1) / np.sqrt(len(top3)))),
            "weeks_positive": int((w > 0).sum())}


def fama_macbeth(P):
    s = [np.polyfit(g.gap, g.y, 1)[0] for _, g in P.groupby("date") if len(g) > 5]
    s = np.array(s)
    return {"weeks": len(s), "mean_slope": float(s.mean()), "t": float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))), "share_negative": float((s < 0).mean())}


def candles_table():
    d = pd.read_parquet(DATA / "candles_1h.parquet")
    d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True).dt.tz_convert(ET)
    return d


def timing_curve(trades: pd.DataFrame, d: pd.DataFrame) -> dict:
    """Average cumulative signed (stock - index) move after entry, hour by hour, Sun 18:00 -> Mon 09:00."""
    O = d.pivot_table(index="ts", columns="coin", values="o")
    hours = list(range(18, 24)) + list(range(0, 10))
    out = {h: [] for h in hours}
    for _, r in trades.iterrows():
        sun = pd.Timestamp(r.date)
        t0 = (sun + pd.Timedelta(hours=18)).tz_localize(ET)
        if t0 not in O.index: continue
        for h in hours:
            t = (sun + pd.Timedelta(days=0 if h >= 18 else 1, hours=h)).tz_localize(ET)
            if t in O.index and pd.notna(O.at[t, r.stock]) and pd.notna(O.at[t0, r.stock]):
                out[h].append(r.side * (1e4 * np.log(O.at[t, r.stock] / O.at[t0, r.stock]) - 1e4 * np.log(O.at[t, INDEX] / O.at[t0, INDEX])))
    return {"hours": [f"{'Sun' if h >= 18 else 'Mon'} {h:02d}:00" for h in hours],
            "mean_bp": [float(np.mean(out[h])) if out[h] else None for h in hours],
            "se_bp": [float(np.std(out[h], ddof=1) / np.sqrt(len(out[h]))) if len(out[h]) > 2 else None for h in hours],
            "n": [len(out[h]) for h in hours]}


def variants(d: pd.DataFrame) -> list[dict]:
    """Grid of trigger / entry / exit choices, fair fills, 1:1 hedge. Pick on the first half of weekends, test on the second."""
    O = d.pivot_table(index="ts", columns="coin", values="o"); C = d.pivot_table(index="ts", columns="coin", values="c")
    growth = json.loads((DATA / "growth_mode.json").read_text())
    stocks = [c for c in C.columns if c != INDEX and c not in NO_BLUE_OCEAN]
    suns = sorted({t.tz_localize(None).normalize() for t in C.index if t.weekday() == 6})
    T = lambda s, dd, h: (s + pd.Timedelta(days=dd, hours=h)).tz_localize(ET)
    rows = []
    for sun in suns:
        tf, t17 = T(sun, -2, 15), T(sun, 0, 16)
        if tf not in C.index or t17 not in C.index: continue
        for k in stocks:
            if pd.isna(C.at[tf, k]) or pd.isna(C.at[t17, k]) or pd.isna(C.at[tf, INDEX]) or pd.isna(C.at[t17, INDEX]): continue
            gap = 1e4 * (np.log(C.at[t17, k] / C.at[tf, k]) - np.log(C.at[t17, INDEX] / C.at[tf, INDEX]))
            rec = {"date": str(sun.date()), "stock": k, "gap": gap, "big": k in BIG, "fee": 0.9 if growth.get(k) else 9.0}
            for eh, ed in ((18, 0), (19, 0), (20, 0)):
                for xh, xd, lab in ((21, 0, "Sun 21:00"), (0, 1, "Mon 00:00"), (4, 1, "Mon 04:00"), (9, 1, "Mon 09:00")):
                    te, tx = T(sun, ed, eh), T(sun, xd, xh)
                    if te in O.index and tx in O.index and te < tx and pd.notna(O.at[te, k]) and pd.notna(O.at[tx, k]):
                        rec[f"y_{eh}_{lab}"] = 1e4 * (np.log(O.at[tx, k] / O.at[te, k]) - np.log(O.at[tx, INDEX] / O.at[te, INDEX]))
            rows.append(rec)
    V = pd.DataFrame(rows); half = sorted(V.date.unique())[len(V.date.unique()) // 2]
    out = []
    for tb in (25, 50, 100):
        for to in (100, 150, 200, 300):
            for eh in (18, 19, 20):
                for lab in ("Sun 21:00", "Mon 00:00", "Mon 04:00", "Mon 09:00"):
                    col = f"y_{eh}_{lab}"
                    if col not in V or (eh == 20 and lab == "Sun 21:00" and False): continue
                    thr = np.where(V.big, tb, to)
                    X = V[(V.gap.abs() >= thr) & (V.gap.abs() < DEFAULT.review_bp) & V[col].notna()].copy()
                    if len(X) < 20: continue
                    hs = np.where(X.big, DEFAULT.half_spread_bp_big, DEFAULT.half_spread_bp_other)
                    X["net"] = -np.sign(X.gap) * X[col] - 2 * X.fee - 2 * hs - 2 * (DEFAULT.fee_bp_growth + DEFAULT.index_slippage_bp)
                    def wk(Z):
                        w = Z.groupby("date").net.mean()
                        return (w.mean() / w.std(ddof=1) * np.sqrt(52)) if len(w) > 3 and w.std(ddof=1) > 0 else np.nan, w
                    s_all, w_all = wk(X); s_tr, _ = wk(X[X.date < half]); s_te, w_te = wk(X[X.date >= half])
                    out.append({"big_trigger_bp": tb, "other_trigger_bp": to, "entry": f"Sun {eh}:00", "exit": lab, "trades": int(len(X)),
                                "mean_bp": float(X.net.mean()), "win_pct": float(100 * (X.net > 0).mean()),
                                "t": float(w_all.mean() / (w_all.std(ddof=1) / np.sqrt(len(w_all)))), "sharpe_all": float(s_all),
                                "sharpe_train": float(s_tr) if s_tr == s_tr else None, "sharpe_test": float(s_te) if s_te == s_te else None,
                                "test_mean_bp": float(w_te.mean())})
    return out


def examples(T: pd.DataFrame, d: pd.DataFrame) -> list[dict]:
    """Pick real trades (wins and losses, big and small names) and attach their full hourly path and the arithmetic."""
    picks = []
    W = T.sort_values("net_bp")
    picks += [("Big loss, small name", W.iloc[0]), ("Biggest win, small name", W.iloc[-1])]
    B = T[T.big].sort_values("net_bp")
    picks += [("Big-name win", B.iloc[-1]), ("Big-name loss", B.iloc[0])]
    med = T.iloc[(T.net_bp - T.net_bp.median()).abs().argsort()[:1]].iloc[0]; picks.append(("Typical trade (median result)", med))
    last = T[T.date == T.date.max()].sort_values("size_usd").iloc[-1]; picks.append(("Most recent weekend, largest position", last))
    O = d.pivot_table(index="ts", columns="coin", values="o"); C = d.pivot_table(index="ts", columns="coin", values="c")
    growth = json.loads((DATA / "growth_mode.json").read_text())
    out, seen = [], set()
    for label, r in picks:
        key = (r.date, r.stock)
        if key in seen: continue
        seen.add(key)
        sun = pd.Timestamp(r.date)
        span = [t for t in C.index if (sun - pd.Timedelta(days=2, hours=-14)).tz_localize(ET) <= t <= (sun + pd.Timedelta(days=1, hours=6)).tz_localize(ET)]
        tf = (sun - pd.Timedelta(days=2) + pd.Timedelta(hours=15)).tz_localize(ET)
        path = [{"ts": t.strftime("%a %H:%M"), "iso": t.isoformat(), "stock": float(C.at[t, r.stock]) if pd.notna(C.at[t, r.stock]) else None,
                 "index": float(C.at[t, INDEX]) if pd.notna(C.at[t, INDEX]) else None} for t in span]
        T_ = lambda dd, h: (sun + pd.Timedelta(days=dd, hours=h)).tz_localize(ET)
        f = 0.9 if growth.get(r.stock) else 9.0
        hs = DEFAULT.half_spread_bp_big if r.stock in BIG else DEFAULT.half_spread_bp_other
        sm_ = 1e4 * np.log(C.at[T_(0, 16), r.stock] / C.at[tf, r.stock]); im = 1e4 * np.log(C.at[T_(0, 16), INDEX] / C.at[tf, INDEX])
        st = 1e4 * np.log(O.at[T_(1, 4), r.stock] / O.at[T_(0, 18), r.stock]); it = 1e4 * np.log(O.at[T_(1, 4), INDEX] / O.at[T_(0, 18), INDEX])
        out.append({"label": label, "date": r.date, "stock": r.stock, "big": bool(r.stock in BIG), "side": int(r.side),
                    "prices": {"stock_fri_close": float(C.at[tf, r.stock]), "stock_sun_17": float(C.at[T_(0, 16), r.stock]),
                               "stock_entry_18": float(O.at[T_(0, 18), r.stock]), "stock_exit_04": float(O.at[T_(1, 4), r.stock]),
                               "index_fri_close": float(C.at[tf, INDEX]), "index_sun_17": float(C.at[T_(0, 16), INDEX]),
                               "index_entry_18": float(O.at[T_(0, 18), INDEX]), "index_exit_04": float(O.at[T_(1, 4), INDEX])},
                    "stock_move_bp": float(sm_), "index_move_bp": float(im), "gap_bp": float(sm_ - im),
                    "trigger_bp": 50 if r.stock in BIG else 150, "stock_leg_bp": float(r.side * st), "index_leg_bp": float(-r.side * it),
                    "fee_bp_side": f, "half_spread_bp": hs, "net_bp": float(r.net_bp), "size_usd": float(r.size_usd), "pnl_usd": float(r.pnl_usd),
                    "path": path})
    return out


def zoom_5m(trade: dict) -> dict | None:
    """5-minute path around the 20:05 ET Blue Ocean switch (only available for the last ~17 days)."""
    sun = pd.Timestamp(trade["date"])
    a, b = int((sun + pd.Timedelta(hours=17)).tz_localize(ET).timestamp() * 1000), int((sun + pd.Timedelta(hours=23)).tz_localize(ET).timestamp() * 1000)
    s = hl.candles(f"xyz:{trade['stock']}", "5m", a, b); time.sleep(1); i = hl.candles(f"xyz:{INDEX}", "5m", a, b)
    if not s or not i: return None
    si = {x["t"]: float(x["c"]) for x in i}
    pts = [{"ts": pd.Timestamp(x["t"] + 300_000, unit="ms", tz="UTC").tz_convert(ET).strftime("%H:%M"), "stock": float(x["c"]), "index": si.get(x["t"])} for x in s]
    return {"stock": trade["stock"], "date": trade["date"], "points": pts}


def main():
    P = build_panel()
    P["y"] = 1e4 * (np.log(P.x_o / P.s_o) - np.log(P.i_x / P.i_e))
    W, N = P[P.night == "weekend"].copy(), P[P.night == "weeknight"].copy()
    d = candles_table()
    res = {"sample": {"weekends": int(W.date.nunique()), "weeknights": int(N.date.nunique()), "stocks": int(P.stock.nunique()),
                      "first": P.date.min(), "last": P.date.max(), "stock_weekends": int(len(W)), "stock_weeknights": int(len(N))}}
    # 1. how much of the gap comes back
    res["slope_weekend"] = clustered_slope(W, "y", "gap", ["date", "stock"])
    res["slope_weeknight"] = clustered_slope(N, "y", "gap", ["date", "stock"])
    P["wk"] = (P.night == "weekend").astype(int); P["gap_x_wk"] = P.gap * P.wk
    m = sm.OLS(P.y, sm.add_constant(P[["gap", "wk", "gap_x_wk"]])).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(P.date)[0]})
    res["interaction"] = {"extra_slope_weekend": float(m.params.gap_x_wk), "t": float(m.tvalues.gap_x_wk), "p": float(m.pvalues.gap_x_wk)}
    res["fama_macbeth_weekend"] = fama_macbeth(W); res["fama_macbeth_weeknight"] = fama_macbeth(N)
    W["cs_gap"] = W.gap - W.groupby("date").gap.transform("mean"); W["cs_y"] = W.y - W.groupby("date").y.transform("mean")
    res["slope_weekend_cross_sectional"] = clustered_slope(W, "cs_y", "cs_gap", ["date", "stock"])
    for nm, sub in (("big", W[W.big]), ("other", W[~W.big])):
        res[f"slope_weekend_{nm}"] = clustered_slope(sub, "y", "gap", ["date", "stock"])
    # 2. binned picture
    def bins(X):
        X = X.copy(); X["bin"] = pd.qcut(X.gap, 10, labels=False, duplicates="drop")
        g = X.groupby("bin").agg(gap=("gap", "mean"), y=("y", "mean"), sd=("y", "std"), n=("y", "size"))
        return [{"gap": float(r.gap), "y": float(r.y), "se": float(r.sd / np.sqrt(r.n)), "n": int(r.n)} for r in g.itertuples()]
    res["bins_weekend"], res["bins_weeknight"] = bins(W), bins(N)
    res["scatter_weekend"] = W[["gap", "y", "big"]].clip(-1500, 1500).round(1).to_dict("records")
    res["scatter_weeknight"] = N.sample(min(len(N), 1500), random_state=1)[["gap", "y", "big"]].clip(-1500, 1500).round(1).to_dict("records")
    # 3. strategy under three fills, and baselines
    res["strategy"] = {}
    for fill in (FAIR, "25% of the hour's range against you", "worst price in the hour"):
        T = simulate(W, "fade (the strategy)", fill)
        res["strategy"][fill] = {"overall": weekly_stats(T), "trades": int(len(T)), "mean_trade_bp": float(T.net_bp.mean()),
                                 "median_trade_bp": float(T.net_bp.median()), "win_pct": float(100 * (T.net_bp > 0).mean()),
                                 "weekly_bp": T.groupby("date").net_bp.mean().round(2).to_dict(),
                                 "weekly_usd": T.groupby("date").pnl_usd.sum().round(2).to_dict(), "total_usd": float(T.pnl_usd.sum())}
        if fill == FAIR: TF = T
    res["baselines"] = {}
    for rule in ("follow the gap (momentum)", "fade everything, no trigger"):
        T = simulate(W, rule, FAIR); res["baselines"][rule] = {"trades": int(len(T)), **weekly_stats(T)}
    TN = simulate(N, "fade (the strategy)", FAIR); res["placebo_weeknight"] = {"trades": int(len(TN)), **weekly_stats(TN)}
    res["hist_trade_bp"] = np.histogram(TF.net_bp.clip(-1000, 1000), bins=np.arange(-1000, 1050, 50))[0].tolist()
    res["by_stock"] = TF.groupby("stock").agg(trades=("net_bp", "size"), mean_bp=("net_bp", "mean"), usd=("pnl_usd", "sum")).sort_values("usd").round(1).reset_index().to_dict("records")
    res["by_group"] = {g: {"trades": int(len(X)), "mean_bp": float(X.net_bp.mean()), "win_pct": float(100 * (X.net_bp > 0).mean()), **weekly_stats(X)}
                       for g, X in (("big names", TF[TF.big]), ("other stocks", TF[~TF.big]))}
    # 4. timing, variants, examples
    res["timing"] = timing_curve(TF, d)
    res["variants"] = variants(d)
    ex = examples(TF, d)
    res["examples"] = ex
    recent = [e for e in ex if e["date"] >= "2026-10-21"]
    res["zoom"] = zoom_5m(recent[0]) if recent else None
    res["config"] = {k: getattr(DEFAULT, k) for k in DEFAULT.__dataclass_fields__}
    (RES / "analysis.json").write_text(json.dumps(res, default=str))
    print(json.dumps({k: res[k] for k in ("sample", "slope_weekend", "slope_weeknight", "interaction", "fama_macbeth_weekend")}, indent=1))
    print(json.dumps(res["strategy"][FAIR]["overall"], indent=1))
    V = pd.DataFrame(res["variants"]).sort_values("sharpe_train", ascending=False)
    print(V.head(8).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
