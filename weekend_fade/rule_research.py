"""Search for better deterministic entry / exit / hedge / sizing / filter rules. Choose on the first half of weekends (train),
report the second half (test). Writes results/rule_research.json and prints the leaders.

Strictness: a target or stop is observed on an hourly price and executed one hour later (no look-ahead).
Betas use only weekday data from before each weekend.
"""
from __future__ import annotations

import itertools, json
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .backtest import DATA, RES
from .config import BIG, DEFAULT, INDEX, NO_BLUE_OCEAN

ET = ZoneInfo("America/New_York")
HOURS = [17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]          # Sun 17:00 .. Mon 05:00 as hours after Sunday 00:00


def panel():
    d = pd.read_parquet(DATA / "candles_1h.parquet")
    d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True).dt.tz_convert(ET); d["usd"] = d.v * d.c
    O = d.pivot_table(index="ts", columns="coin", values="o"); C = d.pivot_table(index="ts", columns="coin", values="c")
    Hh = d.pivot_table(index="ts", columns="coin", values="h"); Ll = d.pivot_table(index="ts", columns="coin", values="l")
    U = d.pivot_table(index="ts", columns="coin", values="usd")
    growth = json.loads((DATA / "growth_mode.json").read_text())
    stocks = [c for c in C.columns if c != INDEX and c not in NO_BLUE_OCEAN]
    # trailing weekday betas: daily 16:00 closes
    daily = C[(C.index.hour == 15) & (C.index.weekday < 5)]
    dret = np.log(daily).diff()
    suns = sorted({t.tz_localize(None).normalize() for t in C.index if t.weekday() == 6})
    at = lambda s, h: (s + pd.Timedelta(hours=h)).tz_localize(ET)
    wk_vol = {}  # weekend volume Fri16 -> Sun17 per stock, for the abnormal-volume filter
    rows = []
    for sun in suns:
        fri = (sun - pd.Timedelta(days=2) + pd.Timedelta(hours=15)).tz_localize(ET)
        need = [fri] + [at(sun, h) for h in HOURS]
        if any(t not in O.index for t in need) or pd.isna(C.at[fri, INDEX]): continue
        win = U.loc[fri:at(sun, 16)]
        past = dret[dret.index < fri].tail(60)
        for k in stocks:
            if pd.isna(C.at[fri, k]) or pd.isna(C.at[at(sun, 16), k]): continue
            path_s = [O.at[at(sun, h), k] for h in HOURS[1:]]; path_i = [O.at[at(sun, h), INDEX] for h in HOURS[1:]]
            if any(pd.isna(x) for x in path_s + path_i): continue
            gap = 1e4 * (np.log(C.at[at(sun, 16), k] / C.at[fri, k]) - np.log(C.at[at(sun, 16), INDEX] / C.at[fri, INDEX]))
            pr = past[[k, INDEX]].dropna()
            beta = float(np.cov(pr[k], pr[INDEX])[0, 1] / pr[INDEX].var()) if len(pr) >= 20 else 1.0
            v = float(win[k].sum()); prev = wk_vol.get(k, [])
            vol_ratio = v / np.mean(prev[-8:]) if len(prev) >= 3 else np.nan
            wk_vol.setdefault(k, []).append(v)
            rng = [float(Hh.at[at(sun, h), k] - Ll.at[at(sun, h), k]) if pd.notna(Hh.at[at(sun, h), k]) else 0.0 for h in HOURS[1:]]
            rows.append({"date": str(sun.date()), "stock": k, "big": k in BIG, "gap": gap, "beta": float(np.clip(beta, 0.3, 3.0)), "rng": rng,
                         "vol_ratio": vol_ratio, "fee": 0.9 if growth.get(k) else 9.0, "s": path_s, "i": path_i,
                         "hour_usd": float(U.at[at(sun, 16), k]) if pd.notna(U.at[at(sun, 16), k]) else 0.0})   # 16:00-17:00 candle: last full hour before the 17:00 scan
    return pd.DataFrame(rows)


def simulate(P, entry_h, exit_rule, hedge, sizing, vol_cap, cfg=DEFAULT, fill="fair"):
    """exit_rule: ('time', H) | ('target', frac, H) | ('stop', bp, H) | ('target_stop', frac, bp, H). H = time stop (hours after Sun 00:00)."""
    trig = np.where(P.big, cfg.trigger_bp_big, cfg.trigger_bp_other)
    X = P[(P.gap.abs() >= trig) & (P.gap.abs() < cfg.review_bp)]
    if vol_cap: X = X[~(X.vol_ratio > vol_cap)]
    out = []
    ei = HOURS[1:].index(entry_h)
    for r in X.itertuples():
        side = -np.sign(r.gap); h = r.beta if hedge == "beta" else 1.0
        s0, i0 = r.s[ei], r.i[ei]
        pnl = lambda j: side * (1e4 * np.log(r.s[j] / s0) - h * 1e4 * np.log(r.i[j] / i0))
        H = exit_rule[-1]; last = HOURS[1:].index(H)
        exit_j = last
        if exit_rule[0] != "time":
            for j in range(ei + 1, last):
                p = pnl(j)
                hit_t = exit_rule[0] in ("target", "target_stop") and p >= exit_rule[1] * abs(r.gap)
                hit_s = exit_rule[0] in ("stop", "target_stop") and p <= -exit_rule[-2]
                if hit_t or hit_s:
                    exit_j = min(j + 1, last); break       # observed at hour j, executed one hour later
        hs = cfg.half_spread_bp_big if r.big else cfg.half_spread_bp_other
        if fill == "fair":
            slip = 2 * hs
        else:   # pay a share of that hour's high-low range at entry and at exit (0.25 = 'a bit worse', 0.5 = 'worst price')
            q = 0.25 if fill == "range25" else 0.5
            slip = q * 1e4 * (r.rng[ei] / r.s[ei] + r.rng[exit_j] / r.s[exit_j])
        net = pnl(exit_j) - 2 * r.fee - slip - 2 * h * (cfg.fee_bp_growth + cfg.index_slippage_bp)
        w = min(abs(r.gap) / (cfg.trigger_bp_big if r.big else cfg.trigger_bp_other), 3.0) if sizing == "scaled" else 1.0
        out.append({"date": r.date, "stock": r.stock, "gap": r.gap, "net": net, "w": w, "hold_h": HOURS[1:][exit_j] - entry_h})
    return pd.DataFrame(out)


def score(T):
    if len(T) < 15: return None
    wk = T.groupby("date").apply(lambda g: np.average(g.net, weights=g.w))
    if len(wk) < 4 or wk.std(ddof=1) == 0: return None
    return {"trades": int(len(T)), "mean_trade_bp": float(T.net.mean()), "win": float(100 * (T.net > 0).mean()),
            "sharpe": float(wk.mean() / wk.std(ddof=1) * np.sqrt(52)), "t": float(wk.mean() / (wk.std(ddof=1) / np.sqrt(len(wk)))),
            "weekly_bp": float(wk.mean()), "avg_hold_h": float(T.hold_h.mean())}


def main():
    P = panel(); dates = sorted(P.date.unique()); half = dates[len(dates) // 2]
    exits = [("time", 21), ("time", 24), ("time", 28),
             ("target", .5, 28), ("target", .75, 28), ("stop", 100, 28), ("stop", 200, 28), ("target_stop", .5, 200, 28), ("target", .5, 24)]
    grid = list(itertools.product([18, 19], exits, ["1:1", "beta"], ["equal", "scaled"], [None, 3.0, 2.0]))
    res = []
    for entry, ex, hedge, sizing, vcap in grid:
        if ex[-1] <= entry: continue
        T = simulate(P, entry, ex, hedge, sizing, vcap)
        a, tr, te = score(T), score(T[T.date < half]), score(T[T.date >= half])
        if not (a and tr and te): continue
        name = {"time": lambda e: f"time {e[1] % 24:02d}:00", "target": lambda e: f"take profit at {int(e[1]*100)}% of gap, else {e[2] % 24:02d}:00",
                "stop": lambda e: f"stop at -{e[1]}bp, else {e[2] % 24:02d}:00", "target_stop": lambda e: f"take {int(e[1]*100)}% / stop -{e[2]}bp, else {e[3] % 24:02d}:00"}[ex[0]](ex)
        res.append({"entry": f"Sun {entry}:00", "exit": name, "hedge": hedge, "sizing": sizing, "skip_if_weekend_volume_above": vcap,
                    **{f"all_{k}": v for k, v in a.items()}, **{f"train_{k}": v for k, v in tr.items() if k in ("sharpe", "mean_trade_bp", "t")},
                    **{f"test_{k}": v for k, v in te.items() if k in ("sharpe", "mean_trade_bp", "t", "trades")}})
    R = pd.DataFrame(res).sort_values("train_sharpe", ascending=False)
    base = R[(R.entry == "Sun 18:00") & (R.exit == "time 04:00") & (R.hedge == "1:1") & (R.sizing == "equal") & R.skip_if_weekend_volume_above.isna()]
    out = {"n_rules": len(R), "train_end": half, "baseline": base.iloc[0].to_dict(), "rules": R.to_dict("records")}
    (RES / "rule_research.json").write_text(json.dumps(out, default=str))
    pd.set_option("display.width", 260); pd.options.display.float_format = "{:,.2f}".format
    cols = ["entry", "exit", "hedge", "sizing", "skip_if_weekend_volume_above", "all_trades", "all_mean_trade_bp", "all_win", "train_sharpe", "test_sharpe", "test_mean_trade_bp", "all_t", "all_avg_hold_h"]
    print(f"{len(R)} rule sets, train = weekends before {half}\nBASELINE (current rule):"); print(base[cols].to_string(index=False))
    print("\nTOP 15 BY TRAIN SHARPE:"); print(R[cols].head(15).to_string(index=False))
    for c in ("entry", "exit", "hedge", "sizing", "skip_if_weekend_volume_above"):
        print(f"\nAverage test Sharpe by {c}:"); print(R.groupby(c, dropna=False).test_sharpe.mean().round(2).to_string())


# ---------------------------------------------------------------- selection without look-ahead
def variants():
    exits = [("time", 21), ("time", 24), ("time", 28), ("target", .5, 28), ("target", .75, 28), ("stop", 100, 28), ("stop", 200, 28),
             ("target_stop", .5, 200, 28), ("target", .5, 24)]
    return [v for v in itertools.product([18, 19], exits, ["1:1", "beta"], ["equal", "scaled"], [None, 3.0, 2.0]) if v[1][-1] > v[0]]


def walk_forward(min_train=8, fill="fair"):
    """Each weekend k, pick the variant with the best Sharpe on weekends < k only, and record its result on weekend k.
    Every recorded return is out of sample for the selection. Also: a single split (choose on the first half once)."""
    P = panel(); dates = sorted(P.date.unique()); half = dates[len(dates) // 2]
    W = {}
    for v in variants():
        T = simulate(P, *v, fill=fill)
        if len(T) == 0: continue
        W[v] = T.groupby("date").apply(lambda g: np.average(g.net, weights=g.w)).reindex(dates)
    W = pd.DataFrame(W)
    sh = lambda x: x.mean() / x.std(ddof=1) if x.count() > 2 and x.std(ddof=1) > 0 else -np.inf
    picks, oos = [], []
    for k in range(min_train, len(dates)):
        past = W.iloc[:k]
        best = max(W.columns, key=lambda c: sh(past[c].dropna()))
        picks.append((dates[k], best)); oos.append(W.iloc[k][best])
    oos = pd.Series(oos, index=[d for d, _ in picks]).fillna(0.0)
    train = W[[d < half for d in dates]]; test = W[[d >= half for d in dates]]
    split_pick = max(W.columns, key=lambda c: sh(train[c].dropna()))
    t_stat = lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    out = {"fill": fill, "min_train_weekends": min_train,
           "walk_forward": {"weekends": len(oos), "mean_bp": float(oos.mean()), "t": float(t_stat(oos)),
                            "sharpe": float(oos.mean() / oos.std(ddof=1) * np.sqrt(52)), "positive": f"{(oos > 0).sum()}/{len(oos)}",
                            "weekly_bp": {d: float(x) for d, x in oos.items()},
                            "picks": [{"date": d, "rule": str(v)} for d, v in picks]},
           "single_split": {"train_end": half, "pick": str(split_pick), "test_mean_bp": float(test[split_pick].mean()),
                            "test_t": float(t_stat(test[split_pick].dropna())),
                            "test_sharpe": float(test[split_pick].mean() / test[split_pick].std(ddof=1) * np.sqrt(52)),
                            "test_positive": f"{(test[split_pick] > 0).sum()}/{test[split_pick].count()}"},
           "all_variants_test": {"n": int(test.shape[1]), "share_positive_mean": float((test.mean() > 0).mean()),
                                 "min_sharpe": float((test.mean() / test.std(ddof=1)).min() * np.sqrt(52))}}
    (RES / f"walk_forward_{fill}.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    import sys
    if "--walk-forward" in sys.argv:
        for f in ("fair", "range25"):
            o = walk_forward(fill=f); w, s_ = o["walk_forward"], o["single_split"]
            print(f"{f}: walk-forward {w['weekends']} weekends, mean {w['mean_bp']:.1f}bp, t {w['t']:.2f}, Sharpe {w['sharpe']:.2f}, {w['positive']} positive")
            print(f"   single split: pick {s_['pick']} -> test {s_['test_mean_bp']:.1f}bp, t {s_['test_t']:.2f}, Sharpe {s_['test_sharpe']:.2f}, {s_['test_positive']}")
    else:
        main()
