"""Money, timing and evidence tests. No Gemini, credentials, packages or network."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("finance_core", ROOT / "core.py")
assert SPEC and SPEC.loader
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


class TransactionsTests(unittest.TestCase):
    def test_cycle_evidence_and_separate_large_transfer_flags(self):
        result = CORE.investigate_transactions()
        self.assertEqual(result["transaction_count"], 7)
        self.assertEqual(result["total_transferred_pence"], 688000)
        self.assertEqual(
            result["three_account_cycles"][0]["transaction_ids"], ["T03", "T04", "T05"]
        )
        self.assertEqual(set(result["large_transfer_ids"]), {"T01", "T02", "T07"})
        self.assertNotIn("fraud_probability", result)

    def test_no_cycle_in_ordinary_transfers(self):
        rows = [
            row
            for row in CORE.fixtures()["transactions"]
            if row["id"] in {"T01", "T02", "T06", "T07"}
        ]
        self.assertEqual(CORE.analyse_transactions(rows)["three_account_cycles"], [])

    def test_cycle_result_independent_of_input_order(self):
        rows = CORE.fixtures()["transactions"]
        self.assertEqual(
            CORE.analyse_transactions(rows)["three_account_cycles"],
            CORE.analyse_transactions(list(reversed(rows)))["three_account_cycles"],
        )

    def test_duplicate_ids_are_rejected(self):
        rows = CORE.fixtures()["transactions"]
        with self.assertRaises(ValueError):
            CORE.analyse_transactions(rows + [rows[0]])

    def test_missing_amount_and_mixed_currency_are_rejected(self):
        for field, value in (
            ("amount_pence", None),
            ("currency", "USD"),
            ("amount_pence", True),
        ):
            rows = copy.deepcopy(CORE.fixtures()["transactions"])
            rows[0][field] = value
            with self.assertRaises(ValueError):
                CORE.analyse_transactions(rows)


class CashflowTests(unittest.TestCase):
    def test_equal_closing_balances_hide_different_shortfalls(self):
        regular = CORE.cashflow_case("regular_income")
        delayed = CORE.cashflow_case("delayed_salary")
        self.assertEqual(regular["closing_balance_pence"], 160000)
        self.assertEqual(delayed["closing_balance_pence"], 160000)
        self.assertEqual(regular["shortfall_pence"], 0)
        self.assertEqual(delayed["shortfall_pence"], 40000)
        self.assertEqual(delayed["first_negative_date"], "2026-11-03")

    def test_chronological_sort_preserves_results(self):
        case = CORE.fixtures()["cashflow"]["delayed_salary"]
        self.assertEqual(
            CORE.forecast_cashflow(case["opening_balance_pence"], case["events"]),
            CORE.forecast_cashflow(
                case["opening_balance_pence"], list(reversed(case["events"]))
            ),
        )

    def test_fractional_pence_and_duplicate_events_are_rejected(self):
        for events in (
            [{"id": "a", "date": "2026-11-01", "amount_pence": 1.5}],
            [{"id": "a", "date": "2026-11-01", "amount_pence": 1}] * 2,
        ):
            with self.assertRaises(ValueError):
                CORE.forecast_cashflow(0, events)

    def test_empty_and_negative_opening_balance(self):
        result = CORE.forecast_cashflow(-100, [])
        self.assertEqual(result["closing_balance_pence"], -100)
        self.assertEqual(result["shortfall_pence"], 100)

    def test_unknown_case_is_not_silently_substituted(self):
        with self.assertRaises(ValueError):
            CORE.cashflow_case("missing")

    def test_mixed_cashflow_currencies_are_rejected(self):
        events = [
            {"id": "a", "date": "2026-11-01", "amount_pence": 100, "currency": "GBP"},
            {"id": "b", "date": "2026-11-02", "amount_pence": 100, "currency": "USD"},
        ]
        with self.assertRaises(ValueError):
            CORE.forecast_cashflow(0, events)


class MarketTests(unittest.TestCase):
    def test_known_rising_balances_after_costs(self):
        self.assertEqual(CORE.market_case("rising", 0)["final_cash_pence"], 150000)
        self.assertEqual(CORE.market_case("rising", 100)["final_cash_pence"], 149300)
        self.assertEqual(
            CORE.market_case("rising", 100, 10)["final_cash_pence"], 149003
        )

    def test_flat_prices_cost_money_after_fees(self):
        result = CORE.market_case("flat", 100)
        self.assertEqual(result["profit_pence"], -200)
        self.assertEqual(result["fees_paid_pence"], 200)

    def test_falling_prices_lose_money(self):
        self.assertLess(CORE.market_case("falling")["profit_pence"], 0)

    def test_future_price_does_not_change_initial_position(self):
        case = CORE.fixtures()["markets"]["rising"]
        original = CORE.simulate_buy_and_hold(**case)
        case["prices_pence"][-1] = 5000
        altered = CORE.simulate_buy_and_hold(**case)
        self.assertEqual(original["shares"], altered["shares"])
        self.assertEqual(original["entry_date"], case["dates"][1])
        self.assertEqual(original["entry_price_pence"], altered["entry_price_pence"])

    def test_no_affordable_shares_means_no_fees(self):
        case = CORE.fixtures()["markets"]["rising"]
        case["initial_cash_pence"] = 50
        result = CORE.simulate_buy_and_hold(**case)
        self.assertEqual(result["final_cash_pence"], 50)
        self.assertEqual(result["fees_paid_pence"], 0)

    def test_residual_cash_can_cover_exit_fee(self):
        result = CORE.simulate_buy_and_hold(
            [1000, 1000, 1], ["2026-01-05", "2026-01-06", "2026-01-07"], 10000, 100
        )
        self.assertEqual(result["final_cash_pence"], 809)
        self.assertEqual(result["fees_paid_pence"], 200)

    def test_exit_does_not_silently_borrow_money(self):
        with self.assertRaises(ValueError):
            CORE.simulate_buy_and_hold(
                [1, 1, 1], ["2026-01-05", "2026-01-06", "2026-01-07"], 10000, 6000
            )

    def test_invalid_inputs_are_rejected(self):
        for update in (
            {"fee_pence": -1},
            {"slippage_bps": 1001},
            {"initial_cash_pence": True},
            {"dates": ["2026-01-05"] * 4},
            {"prices_pence": [900, 0, 1200, 1500]},
        ):
            case = {**CORE.fixtures()["markets"]["rising"], **update}
            with self.assertRaises(ValueError):
                CORE.simulate_buy_and_hold(**case)


class DemoTests(unittest.TestCase):
    def test_report_uses_both_actual_balances_after_scenario_change(self):
        spec = importlib.util.spec_from_file_location("finance_demo", ROOT / "demo.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"core": CORE}):
            spec.loader.exec_module(module)
            data = module.results()
        data["regular_income"]["closing_balance_pence"] = 170000
        markdown = module.report(data)
        self.assertIn("Regular-income closing balance: **£1,700.00**", markdown)
        self.assertIn("Delayed-salary closing balance: **£1,600.00**", markdown)
        self.assertNotIn("Both salary cases finish", markdown)

    def test_output_files_contain_actual_results_and_preserve_existing_directory(self):
        with tempfile.TemporaryDirectory(prefix="finance-demo-") as temporary:
            output = Path(temporary) / "results"
            args = [sys.executable, str(ROOT / "demo.py"), "--output", str(output)]
            result = subprocess.run(args, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            values = json.loads((output / "results.json").read_text())
            self.assertEqual(values["delayed_salary"]["shortfall_pence"], 40000)
            markdown = (output / "DEMO-RESULTS.md").read_text()
            self.assertIn("£400.00", markdown)
            self.assertIn("£1,490.03", markdown)
            self.assertIn("synthetic", markdown)
            repeated = subprocess.run(args, capture_output=True, check=False)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual((output / "DEMO-RESULTS.md").read_text(), markdown)


if __name__ == "__main__":
    unittest.main()
