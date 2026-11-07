#!/usr/bin/env python3
"""Produce a readable local finance demo using only synthetic data. No network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import cashflow_case, investigate_transactions, market_case


def money(pence: int) -> str:
    return (
        ("-" if pence < 0 else "")
        + "£"
        + f"{abs(pence) // 100:,}.{abs(pence) % 100:02d}"
    )


def results() -> dict:
    return {
        "transactions": investigate_transactions(),
        "regular_income": cashflow_case("regular_income"),
        "delayed_salary": cashflow_case("delayed_salary"),
        "market_no_fees": market_case("rising", fee_pence=0),
        "market_with_fees": market_case("rising", fee_pence=100),
        "market_with_fees_and_slippage": market_case(
            "rising", fee_pence=100, slippage_bps=10
        ),
    }


def report(data: dict) -> str:
    risk = data["transactions"]
    regular = data["regular_income"]
    delayed = data["delayed_salary"]
    market = data["market_with_fees"]
    slip = data["market_with_fees_and_slippage"]
    cycles = (
        "; ".join(
            ", ".join(item["transaction_ids"]) for item in risk["three_account_cycles"]
        )
        or "none"
    )
    if regular["closing_balance_pence"] == delayed["closing_balance_pence"]:
        closing = f"Both salary cases finish with **{money(delayed['closing_balance_pence'])}**."
    else:
        closing = (
            f"Regular-income closing balance: **{money(regular['closing_balance_pence'])}**. "
            f"Delayed-salary closing balance: **{money(delayed['closing_balance_pence'])}**."
        )
    timing = (
        f"The balance first turns negative on **{delayed['first_negative_date']}**."
        if delayed["first_negative_date"]
        else "No scheduled balance turns negative in the delayed-salary case."
    )
    lines = [
        "# Finance playground results",
        "",
        "All cases are synthetic practice data. No real money, live prices or account access.",
        "",
        "## 1. Follow the money",
        "",
        f"Checked {risk['transaction_count']} transactions. Found {len(risk['three_account_cycles'])} three-account transfer cycle: **{cycles}**.",
        "A cycle is a reason to investigate context, not proof of fraud. Large transfers alone are not enough to establish wrongdoing.",
        "",
        "**Your challenge:** build an investigator that explains the evidence and avoids treating ordinary salary, rent and supplier payments as proven fraud.",
        "",
        "## 2. A positive balance can hide a cash crunch",
        "",
        closing
        + f" The delayed-salary case has a temporary shortfall of **{money(delayed['shortfall_pence'])}**.",
        timing,
        "",
        "| Date | Event | Change | Balance after event |",
        "| --- | --- | --- | --- |",
    ]
    for event in delayed["timeline"]:
        lines.append(
            f"| {event['date']} | {event['id']} | {money(event['amount_pence'])} | {money(event['balance_after_pence'])} |"
        )
    lines += [
        "",
        "**Your challenge:** explain when the money runs out and compare changed payment timing, without inventing income or making account changes.",
        "",
        "## 3. Paper profits after costs",
        "",
        f"Start: **{money(market['initial_cash_pence'])}**. Same rising price series, three explicit assumptions:",
        "",
        f"- No fees: **{money(data['market_no_fees']['final_cash_pence'])}** final cash.",
        f"- Fixed trading fees: **{money(market['final_cash_pence'])}** final cash.",
        f"- Fees plus 10 basis points of adverse slippage: **{money(slip['final_cash_pence'])}** final cash.",
        "",
        "Differences include position size and rounding, not just fees. This is a buy-and-hold accounting baseline, not evidence of a profitable strategy.",
        "",
        "**Your challenge:** test your own strategy on held-out data, include costs, compare with cash and buy-and-hold, and show it cannot use future prices.",
        "",
        "## Next",
        "",
        "Pick one challenge. Ask Antigravity to use finance-build to make one improvement, then finance-test to check it independently.",
        "The raw calculated evidence is in results.json. These visible practice cases are not a hidden competition benchmark.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="New directory for DEMO-RESULTS.md and results.json"
    )
    args = parser.parse_args()
    data = results()
    markdown = report(data)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "DEMO-RESULTS.md").write_text(markdown, encoding="utf-8")
        (args.output / "results.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
        print(args.output.resolve() / "DEMO-RESULTS.md")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
