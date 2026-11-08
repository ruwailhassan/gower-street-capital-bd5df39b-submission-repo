"""Charts for the pitch deck (rule v2 + news filter). Writes results/charts/*.png and results/charts/numbers.json.

  python -m weekend_fade.pitch_charts      # needs data/ (backtest --fetch) and results/news_checks.jsonl
"""
import json
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from .backtest import DATA, RES
from .config import DEFAULT, INDEX
from .rule_research import panel, simulate

ET = ZoneInfo("America/New_York")
OUT = RES / "charts"
INK, MUTED, BG, TEAL, AMBER, BLUE, GRID = "#14202B", "#4A5560", "#F4F6F3", "#0F6E6A", "#B7791F", "#3F6FB5", "#D5DAD6"
V2 = (19, ("target", .5, 28), "beta", "equal", None)
WIN, SKIP = ("2026-07-12", "NVDA"), ("2026-06-14", "NBIS")

plt.rcParams.update({"font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 19, "axes.edgecolor": GRID,
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG})


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.15); plt.close(fig)


def trades(P, N, fill="fair"):
    T = simulate(P, *V2, fill=fill).merge(N, on=["date", "stock"], how="left")
    return T[T.action != "skip"], T


def weekly(T):
    return T.groupby("date").net.mean() / 100        # % per trade, averaged within each weekend


def equity(P, N):
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for fill, label, col, ls in [("fair", "Fair fills", TEAL, "-"), ("range25", "Fills a bit worse", BLUE, "-"), ("range50", "Worst price every time", AMBER, "--")]:
        w = weekly(trades(P, N, fill)[0]); c = w.cumsum()
        x = pd.to_datetime(c.index); ax.plot(x, c.values, color=col, lw=4, ls=ls)
        ax.text(x[-1] + pd.Timedelta(days=3), c.values[-1], f"{label}\n{c.values[-1]:+.0f}%", color=col, va="center", fontsize=19, fontweight="bold")
    ax.axhline(0, color=MUTED, lw=1.5); ax.text(pd.Timestamp("2026-09-20"), 0.6, "Do nothing = 0", color=MUTED, fontsize=17)
    import matplotlib.dates as mdates; ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_ylabel("Cumulative return, % (sum of weekly average per trade)")
    ax.grid(axis="y", color=GRID); ax.set_xlim(right=pd.Timestamp("2026-11-30"))
    save(fig, "equity_v2.png")


def out_of_sample(P, N, half):
    w = weekly(trades(P, N)[0]); x = np.arange(len(w)); test = np.array([d >= half for d in w.index])
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.axvspan(test.argmax() - .5, len(w) - .5, color="#DCEDEA", zorder=0)
    ax.bar(x, w.values, color=[TEAL if v > 0 else AMBER for v in w.values], width=.75)
    ax.axhline(0, color=MUTED, lw=1.5)
    ax.text(test.argmax() / 2 - .5, w.max() * 1.38, "Rule chosen using\nonly these weekends", ha="center", va="top", fontsize=18, color=MUTED)
    ax.text((test.argmax() + len(w)) / 2 - .5, w.max() * 1.38, "Never seen when choosing:\n14 of 15 weekends positive", ha="center", va="top", fontsize=18, color=TEAL, fontweight="bold")
    ticks = [0, test.argmax(), len(w) - 1]; ax.set_xticks(ticks, [pd.Timestamp(w.index[i]).strftime("%-d %b") for i in ticks])
    ax.set_ylabel("Average return per trade that weekend, %"); ax.set_ylim(top=w.max() * 1.42); ax.grid(axis="y", color=GRID)
    save(fig, "out_of_sample.png")


def path(C, sun, stock):
    sun = pd.Timestamp(sun); fri = (sun - pd.Timedelta(days=2) + pd.Timedelta(hours=16)).tz_localize(ET)
    end = (sun + pd.Timedelta(hours=29)).tz_localize(ET)
    X = C.loc[fri - pd.Timedelta(hours=1):end, [stock, INDEX]].ffill().dropna()
    rel = 100 * (np.log(X[stock] / X[stock].iloc[0]) - np.log(X[INDEX] / X[INDEX].iloc[0]))
    return rel, fri


def trade_chart(C, sun, stock, name, title_side, outcome, exit_h, col):
    rel, fri = path(C, sun, stock); sun = pd.Timestamp(sun).tz_localize(ET)
    hrs = (rel.index - fri).total_seconds() / 3600
    fig, ax = plt.subplots(figsize=(11, 5.6))
    sw = (sun + pd.Timedelta(hours=20, minutes=5) - fri).total_seconds() / 3600
    ax.axvspan(4, sw, color="#E2E6E3", zorder=0)
    ax.plot(hrs, rel.values, color=INK, lw=3.5)
    ax.axhline(0, color=MUTED, lw=1.2)
    tr = lambda h: (sun + pd.Timedelta(hours=h) - fri).total_seconds() / 3600
    ent, ex = tr(19), tr(exit_h)
    ax.axvspan(ent, ex, color=col, alpha=.18, zorder=0)
    ax.axvline(sw, color=TEAL, lw=2.5, ls="--")
    lo, hi = ax.get_ylim()
    ax.text(sw + .8, lo + (hi - lo) * .06, "20:05 Sun\nreal prices return", color=TEAL, fontsize=17, fontweight="bold")
    ax.text(28, hi - (hi - lo) * .04, "Weekend: no real price, thin trading", color=MUTED, fontsize=17, va="top", ha="center")
    v = lambda h: float(np.interp(h, hrs, rel.values))
    ax.plot([ent], [v(ent)], "o", color=col, ms=13); ax.plot([ex], [v(ex)], "s", color=col, ms=13)
    box = dict(facecolor=BG, edgecolor="none", alpha=.9, pad=3)
    ax.text(ent - 1.5, v(ent), title_side, color=col, fontsize=18, fontweight="bold", ha="right", va="center", bbox=box)
    ax.annotate(outcome, (ex, v(ex)), xytext=(tr(29) + 1.5, lo + (hi - lo) * .5), color=col, fontsize=18, fontweight="bold",
                ha="left", va="center", bbox=box, arrowprops=dict(arrowstyle="-", color=col, lw=1.5))
    days = [(0, "Fri 16:00"), (tr(0), "Sun 00:00"), (tr(24), "Mon 00:00")]
    ax.set_xticks([d for d, _ in days], [l for _, l in days]); ax.set_xlim(-1, tr(29) + 13)
    ax.set_ylabel(f"{stock} minus Nasdaq-100 since Friday close, %"); ax.grid(axis="y", color=GRID)
    save(fig, name)


def main():
    OUT.mkdir(exist_ok=True)
    P = panel(); dates = sorted(P.date.unique()); half = dates[len(dates) // 2]
    N = pd.DataFrame([json.loads(l) for l in open(RES / "news_checks.jsonl")])[["date", "stock", "action", "n_headlines", "answer", "headlines"]]
    d = pd.read_parquet(DATA / "candles_1h.parquet"); d["ts"] = pd.to_datetime(d.t, unit="ms", utc=True).dt.tz_convert(ET)
    C = d.pivot_table(index="ts", columns="coin", values="c")
    equity(P, N); out_of_sample(P, N, half)
    K, T = trades(P, N)
    nums = {"train_end": half}
    for name, X in [("all", K), ("train", K[K.date < half]), ("test", K[K.date >= half])]:
        w = weekly(X); t, p = stats.ttest_1samp(w, 0)
        nums[name] = {"trades": len(X), "avg_pct": float(X.net.mean() / 100), "t": float(t), "p": float(p), "weekends_pos": f"{(w > 0).sum()}/{len(w)}"}
    for key, (sun, stock) in {"win": WIN, "skip": SKIP}.items():
        r = T[(T.date == sun) & (T.stock == stock)].iloc[0]; p = P[(P.date == sun) & (P.stock == stock)].iloc[0]
        cap = DEFAULT.max_usd_big if p.big else DEFAULT.max_usd_other
        size = min(cap, DEFAULT.max_share_of_hour_volume * p.hour_usd)
        nums[key] = {"date": sun, "stock": stock, "gap_pct": float(r.gap / 100), "net_pct": float(r.net / 100), "hold_h": int(r.hold_h),
                     "beta": float(p.beta), "size_usd": float(size), "pnl_usd": float(size * r.net / 1e4), "action": r.action,
                     "answer": r.answer, "headlines": [h["title"] for h in r.headlines]}
    w, s = nums["win"], nums["skip"]
    trade_chart(C, w["date"], w["stock"], "trade_win.png", "Enter 19:00\nshort NVDA", f"Exit {19 + w['hold_h']}:00\n{w['net_pct']:+.2f}%", 19 + w["hold_h"], TEAL)
    trade_chart(C, s["date"], s["stock"], "trade_skip.png", "Would have\nshorted here", f"Mon 04:00\n{s['net_pct']:+.2f}%\n(avoided)", 28, AMBER)
    (OUT / "numbers.json").write_text(json.dumps(nums, indent=1, default=str))
    print(json.dumps({k: v for k, v in nums.items()}, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main()
