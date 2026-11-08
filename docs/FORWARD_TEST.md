# Forward test plan (written 2026-11-08, before any live result)

The rule is frozen exactly as in `weekend_fade/config.py` and `weekend_fade/risk.py` at this commit:

- **Signal:** each US stock perp's move minus the Nasdaq-100 perp's (`xyz:XYZ100`) move, from Friday 16:00 ET to Sunday 17:00 ET.
- **Trigger:** fade the gap if it is ≥ 50bp for big names (NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, AVGO, NFLX) or ≥ 150bp for other
  stocks. A gap ≥ 800bp goes to human review and is never auto-traded. Stocks without Blue Ocean overnight pricing are excluded.
- **Risk limits:** as coded in `risk.py`. Size is the smaller of $50k / $10k and 10% of the last hour's volume.
- **Schedule:** scan Sunday 17:00 ET, paper entry Sunday 18:00 ET against the live order book (stock leg and an equal-dollar
  opposite `xyz:XYZ100` hedge), paper exit Monday 04:00 ET.
- **Measured on actual paper fills** from the live order book, not candle prices. Fees as charged by trade[XYZ].

**Pass after 20 weekends:** mean net return per trade > 0 with t > 2 across weekends.

**Fail and stop** if after 20 weekends the mean is ≤ 0, or the kill switch is triggered by a loss larger than 3% of gross on a single weekend.
