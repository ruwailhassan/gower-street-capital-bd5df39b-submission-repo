# Finance project test report

**KIT BASELINE ONLY: not the student's submission**

Dataset: 25 cases; seed: 42; source: AgentVerse seeded generator v2.

Exact checks: **17 passed, 0 failed, 0 execution errors**.
Market simulations completed: **8**. Cases not run: **0**.

Only the configured adapter and defined checks were exercised. A baseline run tests the kit, not your submission.

## Coverage

| Task / scenario family | Pass | Fail | Error | Simulated |
| --- | ---: | ---: | ---: | ---: |
| cashflow / invalid_currency | 1 | 0 | 0 | 0 |
| cashflow / late_income | 2 | 0 | 0 | 0 |
| cashflow / negative_opening | 1 | 0 | 0 | 0 |
| cashflow / regular | 2 | 0 | 0 | 0 |
| cashflow / same_day | 1 | 0 | 0 | 0 |
| cashflow / small_business | 2 | 0 | 0 | 0 |
| markets / falling | 0 | 0 | 0 | 2 |
| markets / flat | 0 | 0 | 0 | 1 |
| markets / jump | 0 | 0 | 0 | 1 |
| markets / regime_change | 0 | 0 | 0 | 1 |
| markets / rising | 0 | 0 | 0 | 2 |
| markets / volatile | 0 | 0 | 0 | 1 |
| transactions / decoy_loops | 1 | 0 | 0 | 0 |
| transactions / duplicate_id | 1 | 0 | 0 | 0 |
| transactions / large_ordinary | 1 | 0 | 0 | 0 |
| transactions / multiple_cycles | 1 | 0 | 0 | 0 |
| transactions / one_cycle | 2 | 0 | 0 | 0 |
| transactions / ordinary | 2 | 0 | 0 | 0 |

## Transaction-cycle evidence

Record precision: 100.0%; recall: 100.0%; F1: 100.0%. False alerts: 0; missed cycle records: 0.
Judge detection by recall and F1, not the pass count: a detector that flags nothing still passes every case with no cycle.
These labels identify planted graph patterns, not actual fraud or regulatory compliance.

## Strategy results after costs

| Case | Final cash | Profit / loss | Buy-and-hold final | Cash baseline | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8988628061d7affd5ac2 | £6,879.52 | £2,614.75 | £6,879.52 | £4,264.77 | 0.63% |
| 8720ab66e154cb2dc50e | £2,088.11 | -£1,192.92 | £2,088.11 | £3,281.03 | 36.35% |
| d8118a2a0e9b07cc77c9 | £9,417.42 | -£41.66 | £9,417.42 | £9,459.08 | 0.44% |
| e619be0a65b6cad688a6 | £7,933.75 | £2,684.08 | £7,933.75 | £5,249.67 | 22.07% |
| b2b2bcaa50661c76efbd | £7,713.92 | -£207.36 | £7,713.92 | £7,921.28 | 33.87% |
| 9959f1cf1ab6d82e0c05 | £5,113.92 | -£2,234.42 | £5,113.92 | £7,348.34 | 30.73% |
| b3062579f60f8e00de25 | £2,121.05 | £473.42 | £2,121.05 | £1,647.63 | 0.81% |
| 0871e8121cb419668fdf | £2,761.24 | -£1,407.17 | £2,761.24 | £4,168.41 | 33.75% |

Showing 8 of 8 paths; every result and trade is in case-results.jsonl.
Completing a simulation does not mean the strategy is good. Compare losses, costs, baselines and drawdown. These price paths do not model real market liquidity or predict returns.

**Across 8 paths:** 0 wins, 0 losses, 8 ties vs buy-and-hold; beat cash on 3. Median excess 0.00% of capital; mean max drawdown 19.83%; sign-test p = n/a (all ties).
**Not distinguishable from buy-and-hold on these paths; more paths or a better edge is needed.**

## Next action

Run your actual submission adapter if this was a baseline. Add project-specific checks, then rerun with a fresh seed. Anything outside these checks remains untested.

Expected answers stayed with the evaluator; adapter requests contained inputs only. The local answer files remain visible to developers, so this practice run is not cheat-proof. Use `bench.py challenge` for a result you can claim.
