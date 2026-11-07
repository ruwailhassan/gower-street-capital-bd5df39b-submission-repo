"""Exercise generated data against real adapters, including broken submissions."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bench
import testbed

SPEC = importlib.util.spec_from_file_location(
    "baseline_adapter", ROOT / "example_adapter.py"
)
BASELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASELINE)


class DatasetTests(unittest.TestCase):
    def test_same_seed_replays_and_new_seed_changes_unique_cases(self):
        inputs, answers = testbed.generated_cases("mixed", 250, 42)
        self.assertEqual((inputs, answers), testbed.generated_cases("mixed", 250, 42))
        self.assertNotEqual(inputs, testbed.generated_cases("mixed", 250, 43)[0])
        self.assertEqual(len({row["case_id"] for row in inputs}), 250)
        self.assertEqual(len({testbed.digest(row["input"]) for row in inputs}), 250)
        self.assertEqual(
            {row["task"] for row in inputs}, {"cashflow", "transactions", "markets"}
        )
        for row in inputs:
            self.assertEqual(set(row), {"case_id", "task", "input"})
        self.assertEqual(len(testbed.validate_cases(inputs, answers)), 250)

    def test_generated_oracles_match_baseline_across_fresh_seeds(self):
        for seed in (0, 1, 777, 2**63 - 1):
            inputs, answers = testbed.generated_cases("mixed", 120, seed)
            for row, answer in zip(inputs, answers):
                if row["task"] != "markets":
                    output = BASELINE.solve(row)
                    self.assertEqual(
                        testbed.differences(answer["expected"], output), []
                    )

    def test_invalid_sizes_and_seeds_fail_without_creating_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            for count, seed in ((0, 1), (10001, 1), (True, 1), (25, -1), (25, True)):
                output = Path(temporary) / "cases"
                with self.assertRaises(ValueError):
                    testbed.generate(output, "cashflow", count, seed)
                self.assertFalse(output.exists())

    def test_answer_binding_and_file_integrity_prevent_accidental_false_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "cases"
            testbed.generate(folder, "cashflow", 3, 12)
            _, inputs, _ = testbed.load_dataset(folder)
            inputs[0]["input"]["opening_balance_pence"] += 1
            testbed.write_jsonl(folder / "inputs.jsonl", inputs)
            with self.assertRaises(ValueError):
                testbed.load_dataset(folder)

    def test_empty_answers_and_duplicate_case_ids_do_not_pass(self):
        inputs, answers = testbed.generated_cases("cashflow", 3, 10)
        bad = copy.deepcopy(answers)
        bad[0]["expected"] = {}
        with self.assertRaises(ValueError):
            testbed.validate_cases(inputs, bad)
        inputs[1] = inputs[0]
        with self.assertRaises(ValueError):
            testbed.validate_cases(inputs, answers)

    def test_reserved_market_inputs_validate_before_running_adapter(self):
        inputs, answers = testbed.generated_cases("markets", 1, 5)
        for bad in (-1, 0, True):
            changed = copy.deepcopy(inputs)
            changed[0]["input"]["initial_cash_pence"] = bad
            expected = copy.deepcopy(answers)
            expected[0]["input_sha256"] = testbed.digest(changed[0])
            with self.assertRaises(ValueError):
                testbed.validate_cases(changed, expected)


class MarketTests(unittest.TestCase):
    def data(self):
        return {
            "case_id": "known",
            "task": "markets",
            "input": {
                "prices_pence": [900, 1000, 1200, 1500],
                "dates": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
                "initial_cash_pence": 100000,
                "fee_pence": 100,
                "slippage_bps": 10,
            },
        }

    def test_known_fills_fees_and_forced_liquidation(self):
        class BuyAndHold:
            def call(self, request):
                return {
                    "action": "buy" if len(request["input"]["history"]) == 1 else "hold"
                }

        output = bench.play_market(self.data(), BuyAndHold())
        self.assertEqual(output["final_cash_pence"], 149003)
        self.assertEqual(output["fees_paid_pence"], 200)
        self.assertEqual(output["trades"][0]["signal_date"], "2026-01-05")
        self.assertEqual(output["trades"][0]["fill_date"], "2026-01-06")
        self.assertEqual(output["trades"][-1]["action"], "forced_final_sale")

    def test_requests_do_not_include_future_prices_or_answer_keys(self):
        calls = []

        class Observer:
            def call(self, request):
                calls.append(copy.deepcopy(request))
                return {"action": "hold"}

        row = self.data()
        output = bench.play_market(row, Observer())
        self.assertEqual(output["profit_pence"], 0)
        self.assertEqual(output["max_drawdown_bps"], 0)
        for i, request in enumerate(calls):
            self.assertEqual(len(request["input"]["history"]), i + 1)
            self.assertNotIn("expected", request)
            self.assertNotIn("prices_pence", request["input"])
            self.assertEqual(
                request["input"]["history"][-1]["date"], row["input"]["dates"][i]
            )
        original = copy.deepcopy(calls)
        calls.clear()
        row["input"]["prices_pence"][-1] *= 10
        bench.play_market(row, Observer())
        self.assertEqual(original, calls)

    def test_bad_actions_are_errors_and_losses_still_report(self):
        class Bad:
            def call(self, request):
                return {"action": "borrow"}

        with self.assertRaises(ValueError):
            bench.play_market(self.data(), Bad())

        class Buy:
            def call(self, request):
                return {
                    "action": "buy" if len(request["input"]["history"]) == 1 else "hold"
                }

        row = self.data()
        row["input"]["prices_pence"][-1] = 500
        output = bench.play_market(row, Buy())
        self.assertLess(output["profit_pence"], 0)
        self.assertGreater(output["max_drawdown_bps"], 0)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="finance-runner-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def adapter(self, body):
        path = self.root / "participant.py"
        path.write_text(body, encoding="utf-8")
        return [sys.executable, str(path)]

    def test_actual_process_baseline_checks_all_three_packs(self):
        testbed.generate(self.root / "data", "mixed", 60, 99)
        summary = bench.run(
            self.root / "data",
            self.root / "report",
            [sys.executable, str(ROOT / "example_adapter.py")],
            limit=60,
        )
        self.assertEqual(summary["passed"], 40)
        self.assertEqual(summary["strategy_runs_completed"], 20)
        self.assertEqual(summary["errors"] + summary["failed"] + summary["not_run"], 0)
        cases = testbed.read_jsonl(self.root / "report/case-results.jsonl")
        for case in cases:
            if case["task"] == "markets":
                self.assertEqual(
                    case["output"]["final_cash_pence"],
                    case["benchmarks"]["buy_and_hold_final_cash_pence"],
                )

    def test_broken_student_fails_and_unrun_cases_are_counted(self):
        testbed.generate(self.root / "data", "cashflow", 25, 20)
        command = self.adapter(
            "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n print(json.dumps({'request_id':r['request_id'],'output':{'shortfall_pence':0}}),flush=True)\n"
        )
        summary = bench.run(self.root / "data", self.root / "report", command, limit=5)
        self.assertEqual(summary["failed"], 5)
        self.assertEqual(summary["passed"], 0)
        self.assertEqual(summary["not_run"], 20)
        markdown = (self.root / "report/REPORT.md").read_text()
        self.assertIn('"expected"', markdown)
        self.assertIn('"actual"', markdown)

    def test_timeout_stops_protocol_and_never_counts_as_pass(self):
        testbed.generate(self.root / "data", "cashflow", 3, 20)
        command = self.adapter("import time\ntime.sleep(20)\n")
        summary = bench.run(
            self.root / "data", self.root / "report", command, limit=3, timeout=0.1
        )
        self.assertEqual(
            (summary["passed"], summary["errors"], summary["not_run"]), (0, 1, 2)
        )

    def test_wrong_response_id_is_execution_error(self):
        testbed.generate(self.root / "data", "cashflow", 2, 1)
        command = self.adapter(
            "import sys,json\nfor line in sys.stdin:\n print(json.dumps({'request_id':'wrong','output':{}}),flush=True)\n"
        )
        result = bench.run(self.root / "data", self.root / "report", command)
        self.assertEqual((result["errors"], result["not_run"]), (1, 1))

    def test_request_budget_stops_a_market_path_without_a_false_completion(self):
        testbed.generate(self.root / "data", "markets", 3, 1)
        summary = bench.run(
            self.root / "data",
            self.root / "report",
            [sys.executable, str(ROOT / "example_adapter.py")],
            limit=3,
            max_requests=2,
        )
        self.assertEqual(summary["strategy_runs_completed"], 0)
        self.assertEqual((summary["errors"], summary["not_run"]), (1, 2))

    def test_custom_invoice_project_uses_actual_implementation_without_answers(self):
        inputs = [
            {
                "case_id": "invoice-1",
                "task": "invoice_total",
                "input": {
                    "lines": [
                        {"quantity": 3, "unit_pence": 1250},
                        {"quantity": 2, "unit_pence": 100},
                    ]
                },
            }
        ]
        answers = [
            {
                "case_id": "invoice-1",
                "input_sha256": testbed.digest(inputs[0]),
                "expected": {"total_pence": 3950},
            }
        ]
        testbed.save_dataset(
            self.root / "data", inputs, answers, "Authored synthetic invoices"
        )
        command = self.adapter(
            "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n assert set(r)=={'request_id','case_id','task','input'}\n value=sum(x['quantity']*x['unit_pence'] for x in r['input']['lines'])\n print(json.dumps({'request_id':r['request_id'],'output':{'total_pence':value}}),flush=True)\n"
        )
        summary = bench.run(self.root / "data", self.root / "report", command)
        self.assertEqual(summary["passed"], 1)
        self.assertFalse(summary["dataset"]["synthetic"])
        self.assertIn(
            "Authored synthetic invoices",
            (self.root / "report/summary.json").read_text(),
        )

    def test_prediction_scoring_rejects_duplicate_unknown_and_boolean_money(self):
        testbed.generate(self.root / "data", "cashflow", 2, 1)
        _, rows, answers = testbed.load_dataset(self.root / "data")
        key = rows[0]["case_id"]
        for predictions in (
            [{"case_id": "missing", "output": {}}],
            [{"case_id": key, "output": {}}] * 2,
        ):
            testbed.write_jsonl(self.root / "predictions.jsonl", predictions)
            with self.assertRaises(ValueError):
                bench.score(
                    self.root / "data",
                    self.root / "predictions.jsonl",
                    self.root / "report",
                )
        output = copy.deepcopy(answers[key]["expected"])
        output["closing_balance_pence"] = True
        testbed.write_jsonl(
            self.root / "predictions.jsonl", [{"case_id": key, "output": output}]
        )
        result = bench.score(
            self.root / "data", self.root / "predictions.jsonl", self.root / "report"
        )
        self.assertEqual((result["failed"], result["not_run"]), (1, 1))

    def test_cli_custom_import_and_offline_score(self):
        row = {
            "case_id": "invoice",
            "task": "invoice_total",
            "input": {"subtotal_pence": 1000, "discount_pence": 100},
        }
        testbed.write_jsonl(self.root / "inputs.jsonl", [row])
        testbed.write_jsonl(
            self.root / "answers.jsonl",
            [{"case_id": "invoice", "expected": {"total_pence": 900}}],
        )
        command = [
            sys.executable,
            str(ROOT / "bench.py"),
            "import",
            "--inputs",
            str(self.root / "inputs.jsonl"),
            "--answers",
            str(self.root / "answers.jsonl"),
            "--output",
            str(self.root / "data"),
            "--source",
            "Authored invoice fixtures",
            "--seed",
            "42",
            "--synthetic",
            "--record-count",
            "1",
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest, _, _ = testbed.load_dataset(self.root / "data")
        self.assertEqual(manifest["seed"], 42)
        self.assertEqual(manifest["source"], "Authored invoice fixtures")
        self.assertTrue(manifest["synthetic"])
        self.assertEqual(manifest["input_record_count"], 1)
        testbed.write_jsonl(
            self.root / "predictions.jsonl",
            [{"case_id": "invoice", "output": {"total_pence": 900}}],
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "bench.py"),
                "score",
                "--dataset",
                str(self.root / "data"),
                "--predictions",
                str(self.root / "predictions.jsonl"),
                "--output",
                str(self.root / "report"),
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["passed"], 1)


if __name__ == "__main__":
    unittest.main()
