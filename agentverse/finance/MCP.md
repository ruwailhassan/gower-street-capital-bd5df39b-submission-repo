# Optional local finance MCP

The first demo works without this. This connector lets Antigravity invoke the same deterministic calculations as named tools. It is a local `stdio` process: no account, API key, hosted endpoint, open network port or model call is required by the server.

It exposes only:

- `finance_scenarios`
- `finance_investigate_transactions`
- `finance_cashflow`
- `finance_paper_market`
- `finance_test_cases`: small seeded input samples without answer labels (1–20 cases)
- `finance_calculate_cashflow`: calculations on supplied synthetic events
- `finance_check_transfers`: graph checks on supplied synthetic transfers

These tools read bundled synthetic fixtures, generate samples and calculate supplied data. They cannot open bank accounts, query arbitrary files/SQL, execute shell commands, transfer funds or place orders. Use [the test runner](TESTING.md) for large datasets and evaluation of a student's actual implementation. Reference-tool results alone do not establish that their app works. Use the walk-forward runner for strategies; never hand a whole future price path to the strategy being evaluated.

## Setup for Antigravity to handle

Use an existing `uv` or install it from its official distribution within host permissions. `mcp_server.py` declares Python 3.11+ and the tested `mcp==1.30.0` dependency. `uv run --script` creates an isolated environment and can provision a compatible interpreter; the participant does not need to manage packages manually. Use a native interpreter for the machine, particularly on Apple Silicon. If dependency setup fails, report it and keep the standard-library demo/tests usable.

First verify the local transport, without invoking Gemini:

```bash
uv run --python 3.12 --script /absolute/path/to/agentverse/finance/smoke_mcp.py
```

Then merge this entry into Antigravity's existing MCP configuration, substituting actual absolute paths and preserving all other entries. Follow the host's connection/permission flow. Do not overwrite a different server already named `agentverse-finance`.

```json
{
  "mcpServers": {
    "agentverse-finance": {
      "command": "uv",
      "args": ["run", "--python", "3.12", "--script", "/absolute/path/to/agentverse/finance/mcp_server.py"],
      "enabledTools": ["finance_scenarios", "finance_investigate_transactions", "finance_cashflow", "finance_paper_market", "finance_test_cases", "finance_calculate_cashflow", "finance_check_transfers"],
      "timeoutSeconds": 300
    }
  }
}
```

If Antigravity cannot find `uv`, use its verified absolute executable path. Refresh/reconnect the server and check the actual tool list in the current app. Ask the agent to call `finance_cashflow` for `delayed_salary`; the returned shortfall is 40,000 pence, or £400.

Configuring tools in Antigravity gives its agent those capabilities. A separately built application needs its own tool connection. Both can reuse `core.py`, but editor configuration does not automatically wire a submitted app.

The connector is tested separately from model reasoning. A passing smoke test is not proof of a successful Antigravity GUI connection, Argon tool selection or the participant's new application.

Sources: [Antigravity local MCP configuration](https://antigravity.google/docs/mcp), [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [uv installation](https://docs.astral.sh/uv/getting-started/installation/).
