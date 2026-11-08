# Forward test plan (written 2026-11-08, before any live result)

The rule is frozen exactly as in `weekend_fade/config.py`, `risk.py`, `signals.py` and `sentiment_agent.py` at this commit (rule v2 + news filter):

- **Signal:** each US stock perp's move minus the Nasdaq-100 perp's (`xyz:XYZ100`) move, Friday 16:00 ET → Sunday 17:00 ET.
- **Trigger:** fade the gap if it is ≥ 50bp for big names (NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, AVGO, NFLX) or ≥ 150bp for other
  stocks. Gaps ≥ 800bp are left alone. Stocks without Blue Ocean overnight pricing are excluded.
- **News filter:** weekend headlines (Google News, Fri 16:00 → Sun 17:00 ET) judged by `gemini-3.5-flash-lite` (temperature 0, fixed
  schema, one call per weekend). Skip the trade if the news explains the move in the same direction with confidence ≥ 0.6.
  No headlines: trade. Model unavailable: skip (fail safe).
- **Risk limits:** as coded in `risk.py`. Size is the smaller of $50k / $10k and 10% of the last hour's volume.
- **Trade:** paper entry Sunday 19:00 ET against the live order book, hedged with beta × the dollars in `xyz:XYZ100`
  (beta from the last 60 weekday closes). Take profit once half the entry gap has been recovered (checked hourly, executed at
  the next check). Time stop Monday 04:00 ET. Fully automatic; kill switch blocks entries and flattens.
- **Measured on actual paper fills** from the live order book, not candle prices, with the news fetched in real time.

**Pass after 20 weekends:** mean net return per trade > 0 with t > 2 across weekends.
**Stop** if after 20 weekends the mean is ≤ 0, or a single weekend loses more than 3% of gross exposure.
