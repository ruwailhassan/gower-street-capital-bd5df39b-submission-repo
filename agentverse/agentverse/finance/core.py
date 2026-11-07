"""Deterministic practice calculations. No model, network, account or trading calls."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path


def fixtures() -> dict:
    return json.loads(
        Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8")
    )


def challenge_guard() -> None:
    """The challenge runner sets AGENTVERSE_CHALLENGE=1 for the adapter process.
    These reference answers must not stand in for the participant's own code."""
    if os.environ.get("AGENTVERSE_CHALLENGE") == "1":
        raise RuntimeError(
            "Kit reference calculations are disabled in challenge runs; call your own implementation"
        )


def integer(value, name: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(
            f"{name} must be an integer"
            + (f" >= {minimum}" if minimum is not None else "")
        )
    return value


def unique_rows(rows: list[dict]) -> None:
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Provide at most 500 practice records")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Each record must be an object")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(value, str) or not value for value in ids) or len(
        set(ids)
    ) != len(ids):
        raise ValueError("Every record needs a unique nonempty ID")


def analyse_transactions(rows: list[dict], large_transfer_pence: int = 70000) -> dict:
    challenge_guard()
    unique_rows(rows)
    integer(large_transfer_pence, "large_transfer_pence", 1)
    edges = {}
    for row in rows:
        integer(row.get("amount_pence"), "amount_pence", 1)
        if row.get("currency") != "GBP":
            raise ValueError(
                "This example accepts GBP only; do not add different currencies"
            )
        for field in ("sender", "recipient"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError("Each transaction needs sender and recipient IDs")
        date.fromisoformat(row["date"])
        edges.setdefault(row["sender"], []).append(row)
    cycles = {}
    for first in rows:
        for second in edges.get(first["recipient"], []):
            for third in edges.get(second["recipient"], []):
                if third["recipient"] != first["sender"]:
                    continue
                if len({first["sender"], second["sender"], third["sender"]}) != 3:
                    continue
                key = tuple(sorted((first["id"], second["id"], third["id"])))
                cycles[key] = {
                    "transaction_ids": list(key),
                    "reason": "Three transfers form a directed cycle; investigate context. This is not proof of wrongdoing.",
                }
    return {
        "transaction_count": len(rows),
        "total_transferred_pence": sum(row["amount_pence"] for row in rows),
        "large_transfer_ids": [
            row["id"] for row in rows if row["amount_pence"] >= large_transfer_pence
        ],
        "three_account_cycles": list(cycles.values()),
        "records": rows,
        "limits": "A simple graph/threshold baseline. It does not establish fraud, identity or regulatory compliance.",
    }


def forecast_cashflow(opening_balance_pence: int, events: list[dict]) -> dict:
    challenge_guard()
    integer(opening_balance_pence, "opening_balance_pence")
    unique_rows(events)
    for event in events:
        integer(event.get("amount_pence"), "amount_pence")
        if event.get("currency", "GBP") != "GBP":
            raise ValueError(
                "This example accepts GBP only; do not add different currencies"
            )
        date.fromisoformat(event["date"])
    ordered = sorted(events, key=lambda event: (event["date"], event["id"]))
    balance = opening_balance_pence
    minimum = balance
    first_negative = None
    timeline = []
    for event in ordered:
        balance += event["amount_pence"]
        minimum = min(minimum, balance)
        if balance < 0 and first_negative is None:
            first_negative = event["date"]
        timeline.append({**event, "balance_after_pence": balance})
    return {
        "opening_balance_pence": opening_balance_pence,
        "closing_balance_pence": balance,
        "minimum_balance_pence": minimum,
        "shortfall_pence": max(0, -minimum),
        "first_negative_date": first_negative,
        "timeline": timeline,
        "assumptions": "Known scheduled amounts only; no interest, fees or uncertain income. Same-day events use ID order, not a bank settlement guarantee.",
    }


def simulate_buy_and_hold(
    prices_pence: list[int],
    dates: list[str],
    initial_cash_pence: int,
    fee_pence: int = 100,
    slippage_bps: int = 0,
) -> dict:
    challenge_guard()
    integer(initial_cash_pence, "initial_cash_pence", 0)
    integer(fee_pence, "fee_pence", 0)
    integer(slippage_bps, "slippage_bps", 0)
    if slippage_bps > 1000:
        raise ValueError("Keep slippage_bps between 0 and 1000")
    if len(prices_pence) != len(dates) or not 3 <= len(dates) <= 500:
        raise ValueError("Provide 3 to 500 prices with matching dates")
    parsed = [date.fromisoformat(value) for value in dates]
    if parsed != sorted(set(parsed)):
        raise ValueError("Dates must be unique and increasing")
    for price in prices_pence:
        integer(price, "price_pence", 1)
    # Signal at bar zero; execute at the following bar. Round adversely to whole pence.
    entry_price = (prices_pence[1] * (10000 + slippage_bps) + 9999) // 10000
    exit_price = prices_pence[-1] * (10000 - slippage_bps) // 10000
    shares = max(0, initial_cash_pence - fee_pence) // entry_price
    entry_fee = fee_pence if shares else 0
    cash_after_buy = initial_cash_pence - shares * entry_price - entry_fee
    final_cash = cash_after_buy + shares * exit_price - entry_fee
    if final_cash < 0:
        raise ValueError(
            "Available cash and sale proceeds cannot cover the exit fee; borrowing is not modelled"
        )
    return {
        "initial_cash_pence": initial_cash_pence,
        "final_cash_pence": final_cash,
        "profit_pence": final_cash - initial_cash_pence,
        "shares": shares,
        "entry_date": dates[1] if shares else None,
        "entry_price_pence": entry_price,
        "exit_date": dates[-1] if shares else None,
        "exit_price_pence": exit_price,
        "fees_paid_pence": 2 * entry_fee,
        "slippage_bps": slippage_bps,
        "cash_baseline_final_pence": initial_cash_pence,
        "limits": "Synthetic buy-and-hold accounting example, not a learned strategy or evidence of future returns. One next-bar purchase and final-bar sale; integer shares, no leverage or tax.",
    }


def case(group: str, scenario_id: str) -> tuple[dict, dict]:
    data = fixtures()
    choices = data.get(group, {})
    if not isinstance(scenario_id, str) or scenario_id not in choices:
        raise ValueError(
            "Unknown scenario; use list_scenarios to see available choices"
        )
    return data["source"], choices[scenario_id]


def list_scenarios() -> dict:
    data = fixtures()
    return {
        "source": data["source"],
        "transactions": ["transfer_cycle"],
        "cashflow": list(data["cashflow"]),
        "markets": list(data["markets"]),
    }


def investigate_transactions() -> dict:
    data = fixtures()
    return {"source": data["source"], **analyse_transactions(data["transactions"])}


def cashflow_case(scenario_id: str = "delayed_salary") -> dict:
    source, selected = case("cashflow", scenario_id)
    return {
        "source": source,
        "scenario_id": scenario_id,
        **forecast_cashflow(selected["opening_balance_pence"], selected["events"]),
    }


def market_case(
    scenario_id: str = "rising", fee_pence: int = 100, slippage_bps: int = 0
) -> dict:
    source, selected = case("markets", scenario_id)
    return {
        "source": source,
        "scenario_id": scenario_id,
        **simulate_buy_and_hold(
            **selected, fee_pence=fee_pence, slippage_bps=slippage_bps
        ),
    }
