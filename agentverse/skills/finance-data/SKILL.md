---
name: finance-data
description: Give an AgentVerse finance team data to build with - the worked demo, fresh synthetic cashflow/transaction/market cases at a chosen size, anonymised real Binance price paths, or custom cases for their own idea. Use when a participant wants examples, test data, a dataset, real market prices, or help choosing a finance idea.
---

# Give the team useful data

**Locate the kit**: the folder holding `START-HERE.md` and `finance/bench.py`. It may be named `agentverse 2` or similar, so search and quote paths. Read `finance/DATA.md` and the relevant parts of `finance/TESTING.md`. Fit the data to their idea instead of steering everyone into the same demo.

- **Unsure what to build:** run `finance/demo.py --output <new dir>` and open its report. If setup is slow, show `finance/example-results/DEMO-RESULTS.md` first, labelled as the bundled example. Explain the transfer cycle, the cashflow shortfall and the cost-adjusted paper trade, then map them to the track's three areas: risk and compliance, markets, and financial inclusion. Ask which problem they want; cashflow is the easiest start.
- **Synthetic cases:** `bench.py generate --pack <cashflow|transactions|markets|mixed> --cases N --output <new dir>`. Offer 25 quick, 250 standard or 2,500 stress (1–10,000). Show one input, the case and record counts and the seed. Keep `answers.jsonl` away from the app and model.
- **Real market prices:** `bench.py fetch --cases N --output <new dir> [--cache <dir>]` builds practice paths from Binance Vision archives (needs internet, checksum-verified, no key). Credit "Binance Vision", licence CC BY-NC-SA 4.0: fine for the hackathon, not for a commercial product without Binance's licence. Tell strategy builders to develop on these and keep a fresh `real-markets` challenge for evaluation. Tuning on the paths you score on is the classic way to fool yourself.
- **Their own idea:** write custom JSONL inputs and independently worked answers, then `bench.py import`. Never import real personal financial records by default.

Python 3.9+ standard library only; MCP setup must not delay first data. Large datasets go through the CLI, not into model context. Data generation is not testing: continue with `finance-test`, or `finance-build` if nothing exists yet. Use the event's Argon access without enabling billing. Publishing is a separate request.
