#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Verify the actual stdio MCP connection and tool outputs without a model or key."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def value(result) -> dict:
    if result.isError:
        raise AssertionError("MCP returned a tool error")
    return json.loads(next(item.text for item in result.content if item.type == "text"))


async def main() -> None:
    server = StdioServerParameters(
        command=sys.executable, args=[str(Path(__file__).with_name("mcp_server.py"))]
    )
    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "finance_scenarios",
            "finance_investigate_transactions",
            "finance_cashflow",
            "finance_paper_market",
            "finance_test_cases",
            "finance_calculate_cashflow",
            "finance_check_transfers",
        }
        for tool in tools.tools:
            assert (
                tool.annotations.readOnlyHint
                and tool.annotations.openWorldHint is False
            )
        cases = value(await session.call_tool("finance_scenarios", {}))
        assert cases["source"]["synthetic"] is True
        risk = value(await session.call_tool("finance_investigate_transactions", {}))
        assert risk["three_account_cycles"][0]["transaction_ids"] == [
            "T03",
            "T04",
            "T05",
        ]
        cash = value(
            await session.call_tool(
                "finance_cashflow", {"scenario_id": "delayed_salary"}
            )
        )
        assert cash["shortfall_pence"] == 40000
        market = value(
            await session.call_tool(
                "finance_paper_market", {"scenario_id": "rising", "fee_pence": 100}
            )
        )
        assert market["final_cash_pence"] == 149300
        generated = value(
            await session.call_tool(
                "finance_test_cases", {"pack": "cashflow", "count": 3, "seed": 99}
            )
        )
        assert len(generated["cases"]) == 3
        assert all(
            set(row) == {"case_id", "task", "input"} for row in generated["cases"]
        )
        calculated = value(
            await session.call_tool(
                "finance_calculate_cashflow",
                {"opening_balance_pence": 1000, "events": []},
            )
        )
        assert calculated["closing_balance_pence"] == 1000
        transfers = value(
            await session.call_tool("finance_check_transfers", {"rows": []})
        )
        assert transfers["transaction_count"] == 0
        missing = await session.call_tool(
            "finance_cashflow", {"scenario_id": "unknown"}
        )
        assert missing.isError
        print(
            "PASS: initialized local MCP, listed 7 read-only tools, verified demos, generated inputs, supplied-data calculations and an invalid-case error. No Gemini calls or API keys."
        )


if __name__ == "__main__":
    asyncio.run(main())
