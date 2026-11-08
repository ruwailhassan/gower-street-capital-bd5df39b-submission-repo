# Weekend Fade: a paper-trading agent for 24/7 stock perps

**Agentverse 2026, Finance Track. Gower Street Capital.**

US stock perpetuals on Hyperliquid (the trade[XYZ] markets) trade all weekend, but the real stock market doesn't. From
Friday 20:00 to Sunday 20:05 ET each stock perp's reference price is an average of its own order book, so a few thin
trades can push a single stock away from where the rest of the market says it should be. At 20:05 ET on Sunday the
perps switch back to real prices (Blue Ocean ATS overnight trading) and part of that drift gets corrected.

The agent measures each stock's weekend drift **relative to the Nasdaq-100 perp**, proposes trades that fade large
drifts (hedged against the index), checks each one against risk limits written in code, asks a human to approve it,
paper-fills it against the live order book at 18:00 ET Sunday and closes it at 04:00 ET Monday. Every step is logged.

**Who it's for:** a trader testing the hunch "weekend crypto-venue stock prices overshoot". The agent turns that into
a rule they can check line by line, refuses the trades that would hurt them (thin books, stale prices, real news,
five bets on the same sector) and shows its evidence, including where it fails.

**Paper trading only.** The package has no wallet, signing or order code; it only reads public market data.

## Quick start

```bash
cd weekend_fade && uv sync && cd ..                      # Python 3.12, deps: requests, pandas, numpy, matplotlib
weekend_fade/.venv/bin/python -m pytest weekend_fade/tests -q
weekend_fade/.venv/bin/python -m weekend_fade.agent scan          # measure gaps now, propose trades, ask you to approve
weekend_fade/.venv/bin/python -m weekend_fade.agent enter         # paper-fill approved trades at the live book (Sun 18:00 ET)
weekend_fade/.venv/bin/python -m weekend_fade.agent exit          # paper-close and report P&L after fees (Mon 04:00 ET)
weekend_fade/.venv/bin/python -m weekend_fade.agent halt          # kill switch: blocks entries (halt --off to clear)
weekend_fade/.venv/bin/python -m weekend_fade.agent autopilot     # run tonight's 17:00 / 18:00 / 04:00 schedule unattended
weekend_fade/.venv/bin/python -m weekend_fade.backtest --fetch    # rebuild the backtest from Hyperliquid's public API (~5 min)
```

Logs: `weekend_fade/logs/<friday-date>/decisions.jsonl` (one JSON line per scan, decision, risk check, human approval,
paper fill and result).

## How a decision is made (traceable)

1. **Data:** Friday 16:00 ET close (1h candle) and the live order-book mid for every US stock perp and for `xyz:XYZ100`.
2. **Maths (pure functions, `signals.py`):** gap = stock move − index move since Friday close, in basis points.
3. **Rule:** fade the gap if it is ≥ 0.50% for big names (NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, AVGO, NFLX) or
   ≥ 1.50% for other stocks. A gap ≥ 8% goes to **human review**, not the agent (probably real news).
4. **Risk (`risk.py`):** size = min($50k big / $10k other, 10% of the last hour's volume). The trade is vetoed if
   volume is under $5k/hr, the last trade is over 90 min old, filling it would move the price more than 25bp, the
   sector already has 3 bets on the same side, or gross exposure would exceed $250k.
5. **Human approval** of each trade (interactive), then **paper fills** by walking the live order book.

Every proposal carries its own explanation, for example:
`AVGO moved +79bp since Friday's close, the Nasdaq-100 perp -6bp, so AVGO is +86bp ahead of the market (trigger 50bp)...`

## Evidence

Reproducible with `python -m weekend_fade.backtest`. 29 weekends, 58 US stock perps, Apr–Nov 2026, Hyperliquid 1h candles.
**In-sample**: the rule was designed on this period. Prices are candle opens (last trades), so three fill models
bracket the real cost.

| | Trades | Avg per trade | Win rate | t (by weekend) |
|---|---|---|---|---|
| **Strategy, fair fills** (price seen + half-spread) | 254 | **+0.76%** | 68% | 4.1 |
| Strategy, fills a bit worse (25% of the hour's range) | 254 | +0.33% | 58% | 1.8 |
| Strategy, worst price of the hour | 254 | −0.25% | 43% | −1.6 |
| Baseline: follow the gap (momentum) | 254 | −1.03% | 26% | −5.6 |
| Baseline: fade every gap, no trigger | 1,275 | +0.22% | 55% | 2.5 |
| **Placebo: same rule on weeknights** | 350 | **−0.20%** | 42% | −0.5 |

Share of the weekend gap that comes back by Monday 04:00: **39%**. On weeknights: **−2%** (none). That matches the
mechanism: on weeknights the perps follow real prices all night, so a gap is usually real news.

**Unseen data.** The agent ran live on the current weekend (8 Nov 2026, 06:34 ET): 65 stocks scanned, 4 over the
trigger, 3 approved (AVGO, NVDA, IREN), 1 vetoed for thin volume (UMC, $718 in the last hour). The forward test
written down in advance (`docs/FORWARD_TEST.md`) adds one new weekend per week.

## Limits (read these)

- **Execution decides it.** The edge is about half of a typical hourly price range in the traded names. With
  slightly worse fills it is marginal (t 1.8), and with bad fills it loses.
- **Small.** Volume-capped sizes average about $14k a trade, which is a few hundred dollars a week of paper P&L.
- **In-sample, 29 weekends.** The earlier Nov 2025–Apr 2026 period (4-hour candles only) shows the same direction
  but a much weaker, non-significant strategy result.
- **Correlated bets.** On big weekends many trades are one sector bet (e.g. all semis bouncing), hence the sector limit.
- **Venue and model risk.** If trade[XYZ] changes its weekend price rules (it changed them in April and August 2026), the effect may change or disappear.

## Data and licences

- **Hyperliquid public info API** (1h/5m candles, live order books, market metadata for the trade[XYZ] markets): the only
  data source for both the agent and the backtest. Public market data, no key or account needed. The backtest is
  rebuilt from it with `python -m weekend_fade.backtest --fetch`.
