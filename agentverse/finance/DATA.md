# Finance playground data

## Test data for your own project

Use [TESTING.md](TESTING.md) to generate fresh datasets, connect the actual submission and produce a failure/coverage report. Choose 25, 250, 2,500 or a custom count up to 10,000 cases; each contains multiple records. A random seed gives fresh variations and a recorded seed reproduces them. The generator covers 18 scenario families across cashflow, transaction patterns and sequential market simulation. The manifest records case counts and total input records. Generator data is authored synthetic. The `real-markets` pack uses real exchange prices (see below).

`inputs.jsonl` and `answers.jsonl` are separate. The runner sends only the former to an adapter that invokes the student's code. It checks independent expected values for calculations, or runs a strategy against prices revealed one step at a time. Custom inputs/answer keys support other finance ideas, such as invoices or budgeting. Custom data provenance must be checked separately. A passing baseline tests the infrastructure, not the submission. Real-world correctness, reasoning quality and unconfigured requirements are not automatically established.

## Immediate worked examples

All bundled accounts, transactions, cashflows and prices are **authored synthetic practice cases**. They were created for this kit. No real bank records, market quotes, credentials or external datasets are included or required. There is no data-provider account, payment card, licence purchase or network request in the demo/calculation code; only the optional `real-markets`, `fetch` and `live` commands use the network.

## What you can actually demonstrate

- **Transaction investigation:** seven transactions contain a three-account cycle (`T03`, `T04`, `T05`) plus ordinary-looking salary, rent, supplier and personal transfers. A transparent baseline finds graph cycles and flags large amounts separately. These patterns justify questions, not accusations.
- **Cashflow support:** `regular_income` and `delayed_salary` both finish at £1,600. Delayed salary creates a temporary £400 shortfall, first negative on 3 November 2026. Dates are fixed scenario dates, not a live forecast.
- **Paper markets:** `rising`, `falling` and `flat` are four-price toy paths. The example buys integer shares on the bar after its initial signal and sells on the last bar. Costs and rounding are explicit. It is a buy-and-hold accounting example, not a strategy predictor or market realism benchmark.

`fixtures.json` records units/source alongside data. Money is integer GBP pence throughout (`100` = £1). Cashflow event amounts may be negative; transfer amounts and prices must be positive. Records need unique IDs and valid dates. Mixed currencies require an explicitly designed conversion model; this example refuses them rather than adding unlike amounts.

The tests include known answers and counterexamples. They are visible practice checks. A team could memorise them, so they are not a hidden competition evaluation. Test new cases and time-ordered holdouts before claiming accuracy, robustness or financial performance. Keep any later evaluation labels separate from model-visible inputs.

## Local run

```bash
python3 "<kit>/finance/demo.py" --output finance-results
python3 -m unittest discover -s "<kit>/finance/tests" -v
```

Use actual kit paths; on Windows try `py -3`. The demo and tests use Python 3.9+ and its standard library, with no Python package installation. Antigravity can handle permitted runtime setup. The output directory must be new so existing work is preserved. `example-results/` contains generated sample outputs for immediate viewing before setup.

The optional local MCP uses the free official MCP SDK and Python 3.11+. Its first setup may download packages; see `MCP.md`. No hosted server, financial feed or model API call is made by it.

## Model access and cost boundary

Use the event-provided Argon access through Antigravity. Its account limits still apply. The kit does not buy credits, enable billing, change overages or fall back to another paid service. Calculation tests and demo outputs remain available without model access. Google currently lists some Gemini API models with free tiers, but not Gemini 4 Argon; event access is separate from an unlimited public free tier. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing)

## Real market data (Binance Vision)

`bench.py fetch` (practice) and `bench.py challenge --pack real-markets` download monthly kline archives from [data.binance.vision](https://data.binance.vision/) ([binance-public-data](https://github.com/binance/binance-public-data)), verify each against Binance's published SHA-256 `.CHECKSUM`, and cut anonymised windows. No account or key. Spot timestamps from 2025 are microseconds; the parser handles both. `live` uses the public market-data REST endpoint `data-api.binance.vision`.

Licence: CC BY-NC-SA 4.0 under the Binance Vision Dataset Terms. Hackathon prototypes and backtests are non-commercial educational use. A team turning its project into a commercial product needs a separate Binance licence. Attribute "Binance Vision"; do not imply Binance endorsement. The kit never bundles the data: it is downloaded on the participant's machine.

Other sources considered and **not** wired in: `finance_calendars` (unmaintained since 2021, works by bypassing NASDAQ's anti-scraping headers), `finance-websocket-API` (closed-source binaries, last updated 2022), `Ultimate-API-List` (mostly paid Apify actors), the `prediction-market-analysis` dataset (36 GiB, too big for event wifi), and `polymarket-subgraph` (needs a hosted Goldsky endpoint; resolved markets can be looked up by a web-searching agent, so they cannot be a hidden test). Teams may still use them as features in their own app, with their own provenance check.

Teams wanting larger public datasets can investigate [IBM AMLSim's sample outputs](https://github.com/IBM/AMLSim/tree/master/sample/outputs) or other appropriately licensed sources. These are optional extensions, not dependencies or claims about what is bundled. Inspect provenance, licence, schema, units, time range and download size before using them. Never import participants' real financial records by default.
