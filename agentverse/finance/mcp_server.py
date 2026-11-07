#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Local stdio tools over synthetic fixtures. No API keys, network calls or orders."""

from core import (
    analyse_transactions,
    cashflow_case,
    forecast_cashflow,
    investigate_transactions,
    list_scenarios,
    market_case,
)
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from testbed import generated_cases

mcp = FastMCP(
    "AgentVerse Finance",
    instructions="Synthetic practice cases only. Amounts are GBP pence. Use calculated results as evidence and disclose limits. No live money actions.",
)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


@mcp.tool(annotations=READ_ONLY)
def finance_scenarios() -> dict:
    """List the bundled synthetic finance cases and their source/units."""
    return list_scenarios()


@mcp.tool(annotations=READ_ONLY)
def finance_investigate_transactions() -> dict:
    """Return practice transfers, graph-cycle evidence and transparent baseline flags. No fraud verdict."""
    return investigate_transactions()


@mcp.tool(annotations=READ_ONLY)
def finance_cashflow(scenario_id: str = "delayed_salary") -> dict:
    """Calculate a practice cashflow timeline. Choose regular_income or delayed_salary; results use GBP pence."""
    return cashflow_case(scenario_id)


@mcp.tool(annotations=READ_ONLY)
def finance_paper_market(
    scenario_id: str = "rising", fee_pence: int = 100, slippage_bps: int = 0
) -> dict:
    """Calculate a synthetic rising/falling/flat buy-and-hold baseline, including integer shares, fees and slippage. No real trades."""
    return market_case(scenario_id, fee_pence, slippage_bps)


@mcp.tool(annotations=READ_ONLY)
def finance_test_cases(pack: str = "cashflow", count: int = 3, seed: int = 42) -> dict:
    """Get 1–20 fresh seeded synthetic inputs, without answers. Packs: cashflow, transactions, markets, mixed. For large datasets and submission evaluation use bench.py; do not send whole market paths to a trading strategy."""
    if (
        type(count) is not int
        or not 1 <= count <= 20
        or type(seed) is not int
        or not 0 <= seed < 2**63
    ):
        raise ValueError(
            "Choose 1 to 20 cases and an integer seed between 0 and 2^63 - 1"
        )
    inputs, _ = generated_cases(pack, count, seed)
    return {
        "synthetic": True,
        "seed": seed,
        "cases": inputs,
        "limits": "Inputs only, not a scored evaluation. Use the CLI runner for independent scoring and prefix-limited market decisions.",
    }


@mcp.tool(annotations=READ_ONLY)
def finance_calculate_cashflow(opening_balance_pence: int, events: list[dict]) -> dict:
    """Calculate arbitrary supplied synthetic GBP events, at most 500. This reference tool alone does not test a student's implementation."""
    return forecast_cashflow(opening_balance_pence, events)


@mcp.tool(annotations=READ_ONLY)
def finance_check_transfers(
    rows: list[dict], large_transfer_pence: int = 70000
) -> dict:
    """Calculate graph-cycle evidence for at most 500 supplied synthetic GBP transfers. Patterns do not establish fraud."""
    return analyse_transactions(rows, large_transfer_pence)


if __name__ == "__main__":
    mcp.run(transport="stdio")
