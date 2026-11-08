"""Portfolio-level Sharpe ratio in dollars (rule v2 + news filter), with the live risk limits applied.

The per-trade 'Sharpe' in final_comparison.csv averages returns per trade and ignores position sizes. This script builds
the actual dollar book each weekend (size = min(cap, 10% of last-hour volume), veto < $5k/hour, <= 15 trades,
<= $250k gross including the beta-sized hedge, <= 3 same-side trades per sector, largest gaps first), then reports:
annualised Sharpe of weekly dollar P&L with a 95% interval (Mertens/Lo standard error, and bootstrap), the deflated
Sharpe ratio for the 216 rule variants tried (Bailey & Lopez de Prado), drawdown and worst week.

  python -m weekend_fade.portfolio_sharpe     # writes results/portfolio_sharpe.json

Not modelled historically: the staleness and order-book-impact vetoes (no historical books), and funding payments.
"""
import json

import numpy as np
import pandas as pd
from scipy import stats

from .backtest import RES
from .config import DEFAULT as C, SECTOR
from .rule_research import panel, simulate

EULER = 0.5772156649
EXTRA_COST_BP = 5.0


def harvey_liu(sr_w, n_obs, n_trials):
    """Harvey & Liu (2015) Bonferroni haircut: inflate the p-value by the number of rules tried, convert back to a Sharpe."""
    t = sr_w * np.sqrt(n_obs); p = 2 * stats.t.sf(abs(t), n_obs - 1); p_adj = min(1.0, p * n_trials)
    return 0.0 if p_adj >= 1 else float(stats.t.isf(p_adj / 2, n_obs - 1) / np.sqrt(n_obs) * np.sqrt(52))


def book(T):
    rows = []
    for d, g in T.groupby("date"):
        gross, n, sec = 0.0, 0, {}
        for r in g.reindex(g.gap.abs().sort_values(ascending=False).index).itertuples():
            if r.hour_usd < C.min_hour_volume_usd: continue
            size = min(C.max_usd_big if r.big else C.max_usd_other, C.max_share_of_hour_volume * r.hour_usd)
            leg, k = size * (1 + r.beta), (r.sector, r.side)
            if n >= C.max_trades or gross + leg > C.max_gross_usd or (r.sector != "other" and sec.get(k, 0) >= C.max_same_sector_same_side):
                continue
            gross += leg; n += 1; sec[k] = sec.get(k, 0) + 1
            rows.append({"date": d, "stock": r.stock, "usd": size, "gross": leg, "pnl": size * r.net / 1e4})
    return pd.DataFrame(rows)


def main():
    P = panel(); dates = sorted(P.date.unique())
    N = pd.DataFrame([json.loads(l) for l in open(RES / "news_checks.jsonl")])[["date", "stock", "action"]]
    rules = json.loads((RES / "rule_research.json").read_text())["rules"]
    var_trials = np.var([r["all_sharpe"] / np.sqrt(52) for r in rules]); n_trials = len(rules)
    sr0 = np.sqrt(var_trials) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n_trials) + EULER * stats.norm.ppf(1 - 1 / (n_trials * np.e)))
    out = {}
    for fill in ("fair", "range25", "range50"):
        T = (simulate(P, 19, ("target", .5, 28), "beta", "equal", None, fill=fill).merge(N, on=["date", "stock"])
             .merge(P[["date", "stock", "hour_usd", "beta", "big"]], on=["date", "stock"]))
        T = T[T.action != "skip"].copy(); T["sector"] = T.stock.map(lambda s: SECTOR.get(s, "other")); T["side"] = -np.sign(T.gap)
        X = book(T); w = X.groupby("date").pnl.sum().reindex(dates, fill_value=0.0)
        sr, n = w.mean() / w.std(ddof=1), len(w); sk, ku = stats.skew(w), stats.kurtosis(w, fisher=False)
        se = np.sqrt((1 - sk * sr + (ku - 1) / 4 * sr ** 2) / (n - 1))
        rng = np.random.default_rng(0)
        boot = [(lambda s: s.mean() / s.std(ddof=1))(rng.choice(w.values, n)) for _ in range(5000)]
        cum = w.cumsum()
        out[fill] = {"trades": int(len(X)), "avg_size_usd": X.usd.mean(), "avg_gross_usd": X.groupby("date").gross.sum().mean(),
                     "max_gross_usd": X.groupby("date").gross.sum().max(), "weekly_pnl_mean_usd": w.mean(), "weekly_pnl_sd_usd": w.std(ddof=1),
                     "total_pnl_usd": w.sum(), "weekends_positive": f"{(w > 0).sum()}/{n}",
                     "sharpe_annual": sr * np.sqrt(52), "sharpe_95ci": [(sr - 1.96 * se) * np.sqrt(52), (sr + 1.96 * se) * np.sqrt(52)],
                     "sharpe_bootstrap_95ci": list(np.percentile(boot, [2.5, 97.5]) * np.sqrt(52)),
                     "deflated_sharpe_prob": stats.norm.cdf((sr - sr0) / se), "deflated_benchmark_sharpe_annual": sr0 * np.sqrt(52),
                     "max_drawdown_usd": (cum - cum.cummax()).min(), "worst_week_usd": w.min(), "worst_trade_usd": X.pnl.min(),
                     "harvey_liu_haircut_sharpe": harvey_liu(sr, n, n_trials)}
        X2 = X.assign(pnl=X.pnl - X.gross * 2 * EXTRA_COST_BP / 1e4)          # stress: extra cost per side on both legs
        w2 = X2.groupby("date").pnl.sum().reindex(dates, fill_value=0.0)
        out[fill]["sharpe_with_extra_5bp_per_side"] = w2.mean() / w2.std(ddof=1) * np.sqrt(52)
    (RES / "portfolio_sharpe.json").write_text(json.dumps(out, indent=1, default=float))
    for k, v in out.items():
        print(f"{k:8s} Sharpe {v['sharpe_annual']:5.2f}  95% CI [{v['sharpe_95ci'][0]:5.2f}, {v['sharpe_95ci'][1]:5.2f}]  "
              f"haircut {v['harvey_liu_haircut_sharpe']:4.2f}  +5bp/side {v['sharpe_with_extra_5bp_per_side']:5.2f}  deflated P {v['deflated_sharpe_prob']:.2f}  weekly ${v['weekly_pnl_mean_usd']:6.0f}  maxDD ${v['max_drawdown_usd']:6.0f}  {v['weekends_positive']}")


if __name__ == "__main__":
    main()
