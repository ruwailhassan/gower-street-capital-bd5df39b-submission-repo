---
name: finance-test
description: Test a team's AgentVerse finance-track project against hidden generated or real-market cases and report what passed, failed and was not tested. Use when a participant asks to test, evaluate, benchmark or prove a finance agent (cashflow help, transaction monitoring or anomaly flags, a trading strategy, or a custom finance idea), or when preparing evidence for judges.
---

# Test the team's actual finance project

**Locate the kit.** It is the folder holding `START-HERE.md` and `finance/bench.py`. The name may differ (`agentverse`, `agentverse 2`), so search for `finance/bench.py` and quote every path. Read `finance/TESTING.md` for the protocol, schemas and commands. Do the setup and adapter work yourself; the participant should not need the terminal.

## 1. Pin down what to test

Work out from the code what the idea does. Ask for one sentence only if it is unclear. Name the testable requirements and pick the matching pack:

- **Risk and compliance** (transfers, anomalies): `transactions`.
- **Financial inclusion** (cashflow, budgeting): `cashflow`.
- **Markets** (strategies): `real-markets` for evidence, `markets` for quick synthetic checks, and `live` for a forward test.
- **Anything else**: custom cases via `bench.py import`, with answers worked out independently of the submission. These are self-assessment only, because the team writes both sides.

Do not force an idea into an unrelated pack. Where no automatic oracle exists, say what needs human review.

## 2. Build a thin adapter in the team's project

It calls the same function or agent path the app uses, in the app's language. It never re-implements the answers, never imports the kit's `core.py`/`testbed.py` (challenge mode disables them and flags the import), and never reads dataset files. If the app's logic is tangled into UI code, extract one function that both the app and the adapter call. Logs go to stderr; stdout carries only response lines.

## 3. Practise, then prove

1. **Practice** (debugging): `generate` + `run`, starting at 25 cases. Fix failures using the same seed, then a fresh one. Practice files sit on disk with the answers, so **never report practice numbers as results.**
2. **Challenge** (evidence): `bench.py challenge --pack <pack> --cases 60 --project <team root> --output <new dir> --adapter <command>`. Cases exist only in memory, the seed is committed before the run and revealed after, and provenance is recorded. Offer 60 standard, 300 thorough, or up to 10,000.
3. **Markets extra**: a `real-markets` challenge (needs internet), then optionally a `live` session of 30 one-minute steps for a forward test the team can demo.

For a model-backed adapter, use the event's Argon access through Antigravity: no new keys, no paid fallback, no billing changes. Start with `--cases 6 --max-requests 50`. A market path costs one request per bar (48–240 bars for real paths). A timeout or budget stop means incomplete, never a pass.

## 4. Report honestly

Open the generated `REPORT.md` and tell the participant:

- **passed / failed / not run**, plus the adapter path and what it actually calls;
- for transactions, **recall and F1** (a detector that flags nothing passes every no-cycle case);
- for markets, **wins vs buy-and-hold, the sign-test p-value and drawdown**. "Not distinguishable from buy-and-hold" is the usual honest outcome; say so plainly;
- any **provenance warnings** and the commitment and seed lines;
- **one next fix**, with the failing case's input and expected/actual fields.

Never edit answers, the kit, or the grading contract to make a run pass. Numeric checks do not cover reasoning quality, honesty under uncertainty or handling of the misleading text planted in some cashflow descriptions. Judges look for exactly those, so point the team at a short human-reviewed demo of them.

For judging, organisers follow the sealed-seed procedure in `TESTING.md` (`seal`, then `challenge --seed-prompt --team`). Kit tests (`python3 -m unittest discover -s "<kit>/finance/tests"`) check infrastructure only. A test request does not authorise publishing; that is `review-and-push`. Use `finance-build` to make fixes.
