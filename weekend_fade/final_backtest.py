"""Headline comparison: rule v1 vs rule v2, with and without the news filter, under three fill assumptions.

  python -m weekend_fade.final_backtest      # writes results/final_comparison.csv (needs data/ and results/news_checks.jsonl)
"""
import json

import numpy as np
import pandas as pd

from .backtest import RES
from .rule_research import panel, simulate

RULES = {"v1: Sun 18:00, 1:1 hedge, exit 04:00": (18, ("time", 28), "1:1"),
         "v2: Sun 19:00, beta hedge, take 50% else 04:00": (19, ("target", .5, 28), "beta")}
FILLS = {"fair": "price seen + half-spread", "range25": "25% of the hour's range against you", "range50": "worst price of the hour"}


def main():
    P = panel()
    N = pd.DataFrame([json.loads(l) for l in open(RES / "news_checks.jsonl")])[["date", "stock", "action"]]
    rows = []
    for rule, args in RULES.items():
        for fill, fill_name in FILLS.items():
            T = simulate(P, *args, "equal", None, fill=fill).merge(N, on=["date", "stock"], how="left")
            for news in ("no news filter", "with news filter"):
                X = T if news == "no news filter" else T[T.action != "skip"]
                w = X.groupby("date").net.mean()
                rows.append({"rule": rule, "news": news, "fill": fill_name, "trades": len(X), "avg_trade_pct": X.net.mean() / 100,
                             "win_pct": 100 * (X.net > 0).mean(), "weekly_t": w.mean() / (w.std(ddof=1) / np.sqrt(len(w))),
                             "sharpe_annual": w.mean() / w.std(ddof=1) * np.sqrt(52), "weekends_positive": f"{(w > 0).sum()}/{len(w)}",
                             "worst_trade_pct": X.net.min() / 100})
    R = pd.DataFrame(rows)
    R.to_csv(RES / "final_comparison.csv", index=False)
    pd.set_option("display.width", 230); pd.options.display.float_format = "{:,.2f}".format
    print(R.to_string(index=False))


if __name__ == "__main__":
    main()
