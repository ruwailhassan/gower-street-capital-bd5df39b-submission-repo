#!/usr/bin/env python3
"""Kit baseline only. Replace solve() with calls into the student's actual project."""

import json
import sys

from core import analyse_transactions, forecast_cashflow


def solve(request):
    data = request["input"]
    if request["task"] == "market_step":
        # Buy once at the first signal, then hold. The RUNNER executes and liquidates.
        return {"action": "buy" if len(data["history"]) == 1 else "hold"}
    try:
        if request["task"] == "cashflow":
            return forecast_cashflow(**data)
        if request["task"] == "transactions":
            result = analyse_transactions(**data)
            return {
                "cycle_transaction_ids": sorted(
                    {
                        tx_id
                        for cycle in result["three_account_cycles"]
                        for tx_id in cycle["transaction_ids"]
                    }
                ),
                "large_transfer_ids": sorted(result["large_transfer_ids"]),
                "total_transferred_pence": result["total_transferred_pence"],
            }
    except (ValueError, TypeError, KeyError):
        return {"error": "invalid_input"}
    # Custom tasks must connect to the participant's implementation, never auto-pass.
    return {"error": "unsupported_task"}


def main():
    for line in sys.stdin:
        request = json.loads(line)
        output = solve(request)
        print(
            json.dumps({"request_id": request["request_id"], "output": output}),
            flush=True,
        )


if __name__ == "__main__":
    main()
