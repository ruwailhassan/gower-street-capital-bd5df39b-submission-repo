# Test your own finance project

Tell Antigravity what your idea does and ask it to use `finance-test`. It handles the commands and connects your code. You choose **25 cases (quick), 250 (standard), 2,500 (stress)**, or another number from 1 to 10,000. Each case contains multiple transactions, scheduled payments or prices. Bigger is useful after a small run works; it is not automatically a better test.

The testbed works offline with Python 3.9+ and its standard library. No provider account, model API key, feed, database or hosting is required by these tools. Your own app may have different dependencies. The CLI can test a Python, JavaScript or other local project through the same small adapter, or score saved outputs from an app you have already run.

## Two modes: practise, then prove

| Mode | Command | Use it for | Can a team game it? |
| --- | --- | --- | --- |
| Practice | `generate` + `run` | Debugging. Inputs and answers are files you can open. | Yes: the answer key is on disk. Never quote these numbers as results. |
| **Challenge** | `challenge` | Any result you show judges. | Not through the protocol: see "What challenge mode stops" below. |
| Live | `live` | Forward test of a trading agent on live Binance prices. | Look-ahead is impossible: the future has not happened yet. |

## What is included

| Pack | Data variations | What is checked |
| --- | --- | --- |
| `cashflow` | Personal and small-business schedules; late income; same-day payments; negative opening balance; invalid currency; occasional misleading text in a description | Closing balance, lowest balance, shortfall and first negative event date. Invalid mixed currencies must be rejected. |
| `transactions` | Ordinary flows; single and multiple three-account cycles; decoy 2-, 4- and 5-account loops; large ordinary transfers; duplicate IDs. Cycles reuse ordinary accounts, amounts and dates, so names, degrees or sizes do not reveal them | Planted cycle evidence, independent amount thresholds and total amounts. Invalid duplicate IDs must be rejected. Precision/recall refer to graph-pattern records, not fraud. |
| `markets` | Synthetic rising, falling, flat, volatile, regime-change and jump paths; varied capital, fees and slippage |
| `real-markets` | **Real** hourly/4-hourly Binance windows (8 liquid pairs, 2021 onward), rebased to a fictional GBP asset, real dates and symbol removed, half with returns inverted so drift alone cannot win | Same sequential runner as `markets`. | Your strategy makes sequential decisions using observed history only. The runner executes orders at the next price and reports profit/loss, costs, drawdown, cash and buy-and-hold baselines. Completion is **not** a profitability pass. |
| Custom | Your idea's structured inputs, expected results and explicit assumptions | Required output fields against your independently authored answers. Examples include invoice totals, budget limits or reconciliation. No automatic claim about unconfigured requirements. |

These are synthetic stress/practice cases, not bank records, real exchange prices, regulatory standards or an official hackathon judging benchmark. Eighteen built-in scenario families cover useful mechanics, not every finance product. A graph cycle does not establish fraud. Market paths do not establish realistic returns. Textual reasoning, suitability and professional trust need additional human review or a stated rubric.

## Generate the amount you want

Commands below are for the agent or a technical teammate. `<kit>` is the folder that contains `START-HERE.md`; it may be named `agentverse 2` or similar, so quote paths. Participants need only state their idea and preferred size.

```bash
python3 "<kit>/finance/bench.py" generate --pack cashflow --cases 250 --output cashflow-cases
```

Use `mixed`, `cashflow`, `transactions` or `markets`. No seed means a fresh random seed, recorded in `manifest.json`; `--seed 42` reproduces exactly the same cases with this generator version. Use one seed while developing and a new seed for a later check. Fresh seeds give unseen generated examples, not proven statistical representativeness.

Every dataset contains:

- `inputs.jsonl`: one input case per line, safe to pass to the project.
- `answers.jsonl`: evaluator-side expected results and scenario labels. **Do not send this to the app/model.**
- `manifest.json`: seed, source, counts, coverage and file hashes. Hash checks prevent accidental scoring against edited inputs; they are not tamper-proof certification.

Datasets and reports must go to new directories. Existing work is preserved. The full answer key is locally visible, so this is not a secure hidden benchmark.

## Connect the actual submission

The adapter is a thin wrapper that calls the same functions/agent path the submitted app uses. Keep it in the participant's project. Do not replace the implementation with the kit's reference functions and call that a submission test. Test deterministic mechanics first. If a live model is involved, start with a tiny number of requests through already configured access, then report model behaviour separately.

The runner starts the adapter command once, without a shell. It sends one JSON object per line to stdin and expects one response per line on stdout. Flush every response. Put diagnostic logs on stderr. The adapter runs as ordinary local code with the user's permissions; this is **not an OS security sandbox**. The runner itself has no network or model calls; it cannot prevent arbitrary participant code from making its own calls. Do not embed credentials in commands or fixtures.

Example request:

```json
{"request_id":"abc","case_id":"abc","task":"cashflow","input":{"opening_balance_pence":10000,"events":[{"id":"rent","date":"2026-01-02","amount_pence":-15000,"currency":"GBP"}]}}
```

Expected response shape:

```json
{"request_id":"abc","output":{"closing_balance_pence":-5000,"minimum_balance_pence":-5000,"shortfall_pence":5000,"first_negative_date":"2026-01-02"}}
```

See the first input and answer when writing an adapter; keep answer lookup out of the adapter itself. Cashflow event order is date, then ID; `first_negative_date` is the first negative **event** balance, and is null if there are no negative event balances. A negative opening balance still counts toward minimum/shortfall, even without events. Transaction outputs require sorted unique `cycle_transaction_ids`, sorted `large_transfer_ids` and integer `total_transferred_pence`. Invalid data returns `{"error":"invalid_input"}`. Money is GBP pence, not pounds.

```bash
python3 "<kit>/finance/bench.py" run --dataset cashflow-cases --output my-results --limit 250 --adapter python3 path/to/my_adapter.py
```

For a JavaScript adapter, the last arguments are `--adapter node path/to/my_adapter.mjs`. Options must precede `--adapter`. `--limit` defaults to 25 and unrun cases are reported explicitly. Each response has a default 10-second timeout; the whole run has a default 120-second budget. Tune `--timeout`, `--max-seconds` and `--max-requests` explicitly when needed. A market path uses one request per decision, so a few cases can still use many model calls. For an initial model-backed trial use, for example, `--limit 2 --max-requests 10 --timeout 30 --max-seconds 120`. Request limits are not a billing cap on what an adapter does internally.

For market requests the task is `market_step`, with `input.history`, `cash_pence`, `shares`, `fee_pence`, and `slippage_bps`. Return `{"action":"buy"}`, `{"action":"hold"}` or `{"action":"sell"}` as the output. Buy uses available cash, sell closes the position; integer shares, no leverage or shorting, fixed fees, adverse rounded slippage and forced final liquidation. No future date/price path or expected answer goes to the strategy. This prevents accidental future-price input through the protocol, not deliberate file access by a cheating adapter. Other market mechanisms need a separate simulator.

The provided `example_adapter.py` is a known baseline to check installation, **not the participant's app**:

```bash
python3 "<kit>/finance/bench.py" run --dataset cashflow-cases --output baseline-results --limit 250 --baseline
```

## Use your own project-specific data

For another idea, define the input/output contract and testable requirements first. Generate or import suitable cases and independently checked answers. Keep realistic assumptions and units explicit. Do not derive answers by calling the submitted implementation. Not every project can be reduced to an exact numeric answer; record human-review requirements separately rather than fabricating a score.

Example input file (`my-inputs.jsonl`):

```json
{"case_id":"invoice-1","task":"invoice_total","input":{"lines":[{"quantity":3,"unit_pence":1250},{"quantity":2,"unit_pence":100}]}}
{"case_id":"invoice-2","task":"invoice_total","input":{"lines":[]}}
```

Independent answer file (`my-answers.jsonl`):

```json
{"case_id":"invoice-1","expected":{"total_pence":3950}}
{"case_id":"invoice-2","expected":{"total_pence":0}}
```

```bash
python3 "<kit>/finance/bench.py" import --inputs my-inputs.jsonl --answers my-answers.jsonl --source "Authored synthetic invoices" --synthetic --seed 42 --output invoice-cases
python3 "<kit>/finance/bench.py" run --dataset invoice-cases --output invoice-results --adapter node my-invoice-adapter.mjs
```

Custom imports can record `--source`, the generating `--seed`, and a `--synthetic` declaration; without a declaration, synthetic provenance is unknown. These are importer declarations, not verified provenance. Counts use the first list among events, rows, prices_pence, items or lines; otherwise one record per case. Use `--record-count` for a different schema and preserve your generator/provenance alongside it. Reproducing imported data needs that custom generator too.

Any nonempty task name except reserved `markets` can use this exact-answer mode. Expected object fields are required recursively; extra output fields are allowed. Values and lists match exactly, including types/order; there is no implicit numeric tolerance or currency conversion. An empty expected object is rejected. If your app cannot stream JSONL, export `{"case_id":"invoice-1","output":{"total_pence":3950}}` lines and use `bench.py score --dataset invoice-cases --predictions predictions.jsonl --output invoice-results`. This scores those outputs, not proof that the app was actually run. Markets must use the sequential runner.

## Challenge mode: a result you can claim

```bash
python3 "<kit>/finance/bench.py" challenge --pack mixed --cases 60 --output challenge-1 --project . --adapter python3 path/to/my_adapter.py
```

`--pack` accepts `mixed`, `cashflow`, `transactions`, `markets` or `real-markets` (needs internet; downloads a few small Binance archives into memory). Default budgets: 10 s per response, 900 s per run, 100,000 requests. For a model-backed adapter start with `--cases 6`.

What happens:

1. A fresh secret seed is drawn and its SHA-256 commitment is written to `COMMITMENT.txt` **before** any case exists.
2. Cases are generated **in memory only**. No `inputs.jsonl`, `answers.jsonl` or seed file exists while the adapter runs.
3. The adapter runs with `AGENTVERSE_CHALLENGE=1`, which disables the kit's reference calculations (`core.py`) and evaluator oracles. An adapter that leans on them errors instead of passing.
4. Market strategies see only the observed prefix, one bar at a time, and fill at the next bar.
5. The project is scanned for provenance warnings: imports of kit code, references to answer or seed files, and Binance archive downloads (which could be used to look up historical paths). The adapter file hash and git commit are recorded.
6. After the run, `SEED-REVEAL.txt` publishes the seed, so anyone can check it against the commitment and replay the exact cases.

### What challenge mode stops

| Cheat | Why it fails |
| --- | --- |
| Read the answer key or the future price path from disk | They never exist on disk during the run. |
| Wrap the kit's reference code instead of the team's own implementation | Disabled by the env guard; also flagged by the provenance scan. |
| Spot planted fraud cycles by account naming, degree or amount | Positives and decoys share one population. A regex on names scores 0%. |
| Rebuild the generator's RNG from visible IDs | Each case uses independent hashed streams; IDs come from a different stream than amounts or prices. |
| Tune to the generator's families | Use `real-markets`: real windows, randomly inverted, from a pool of about 8 pairs × 69 months. |
| Rerun until lucky | Self-serve challenges are a team's own check. For judging, organisers use a sealed seed (below). |

What it cannot stop on a machine the team controls: editing `bench.py` itself, or an adapter that downloads Binance history and pattern-matches a `real-markets` window (flagged by the scan, and impossible in `live`). That is why judging uses the organiser procedure.

### Organiser procedure (for judging)

1. Before judging: `python3 bench.py seal --output organiser-seed.json` on an organiser laptop. Post the printed commitment publicly (slides, Discord).
2. Publish the kit fingerprint (any challenge report shows it) so a tampered `bench.py` is visible.
3. Per team, on an organiser machine with a clean kit, or at the team's laptop with `--seed-prompt` (typed, hidden input):
   `bench.py challenge --seed-prompt --team "Team Name" --pack mixed --cases 60 --project <their repo> --output judging/<team> --adapter <their adapter command>`
   Each team gets **different** hidden cases derived from the master seed, so one team's report cannot leak another's answers.
4. After awards, publish the master seed. Anyone can recompute the commitment and replay any team's cases.

## Live forward test (markets)

```bash
python3 "<kit>/finance/bench.py" live --symbol BTCUSDT --interval 1m --steps 30 --output live-1 --adapter python3 my_strategy_adapter.py
```

The strategy receives closed candles only (rebased to 10,000 at the first warm-up candle). After each decision the runner fetches the live price and fills at it with slippage, so the traded price is unknown when the strategy chooses. Default response timeout is 5 s. 30 one-minute steps take about 30 minutes. One live session is one path: it proves honest operation on unseen data, not an edge. Uses Binance's public market-data endpoint (`data-api.binance.vision`, no key).

## Read the result

Adapter stderr goes to `adapter-stderr.log` beside the report. A stray `print` to stdout stops the run, and the report quotes the start of the offending line. For transactions, judge by cycle **recall and F1**: a detector that flags nothing still passes every no-cycle case. For markets, the report gives wins and losses against buy-and-hold across paths, plus a sign-test p-value; completion alone is never a pass.

Open `REPORT.md` for the short explanation; `summary.json` and `case-results.jsonl` contain the full counts, outputs and trade evidence. Failed checks, execution errors and cases not run remain separate. Nonzero CLI exit: 1 means failures, execution errors or incomplete coverage; 2 means setup/dataset errors. A completed market simulation still requires assessment of its performance.

Fix a failed case, reproduce it with the same seed, then test fresh cases. Report the adapter path and what it actually calls, data size/seed, checked requirements and remaining gaps. **Passing these checks does not mean the entire idea works.** It means the named implementation met the named checks on this data.
