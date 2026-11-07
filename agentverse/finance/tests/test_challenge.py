"""Challenge mode must resist the cheats a hackathon team would actually try.
Offline: Binance responses are faked with the documented archive/REST formats."""

import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bench
import marketdata
import testbed

# An honest participant implementation written independently of core.py.
HONEST = r'''
import json, sys
from datetime import date
def cashflow(d):
    events = d["events"]
    ids = [e.get("id") for e in events]
    if len(set(ids)) != len(ids) or any(e.get("currency", "GBP") != "GBP" for e in events):
        return {"error": "invalid_input"}
    bal = low = d["opening_balance_pence"]; first = None
    for e in sorted(events, key=lambda e: (e["date"], e["id"])):
        bal += e["amount_pence"]; low = min(low, bal)
        if bal < 0 and first is None: first = e["date"]
    return {"closing_balance_pence": bal, "minimum_balance_pence": low,
            "shortfall_pence": max(0, -low), "first_negative_date": first}
def transactions(d):
    rows = d["rows"]; ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids): return {"error": "invalid_input"}
    out = {}
    for r in rows: out.setdefault(r["sender"], []).append(r)
    hit = set()
    for a in rows:
        for b in out.get(a["recipient"], []):
            for c in out.get(b["recipient"], []):
                if c["recipient"] == a["sender"] and len({a["sender"], b["sender"], c["sender"]}) == 3:
                    hit |= {a["id"], b["id"], c["id"]}
    big = d["large_transfer_pence"]
    return {"cycle_transaction_ids": sorted(hit),
            "large_transfer_ids": sorted(r["id"] for r in rows if r["amount_pence"] >= big),
            "total_transferred_pence": sum(r["amount_pence"] for r in rows)}
for line in sys.stdin:
    r = json.loads(line)
    if r["task"] == "market_step":
        out = {"action": "buy" if len(r["input"]["history"]) == 1 else "hold"}
    else:
        out = {"cashflow": cashflow, "transactions": transactions}[r["task"]](r["input"])
    print(json.dumps({"request_id": r["request_id"], "output": out}), flush=True)
'''

# Tries every file-based shortcut: answer keys, input files, seed reveals.
SNOOPER = r'''
import json, sys, os, glob
found = []
for root in (os.getcwd(), sys.argv[1]):
    for pattern in ("**/answers.jsonl", "**/inputs.jsonl", "**/SEED-REVEAL.txt"):
        found += glob.glob(os.path.join(root, pattern), recursive=True)
open(sys.argv[2], "w").write(json.dumps(found))
for line in sys.stdin:
    r = json.loads(line)
    print(json.dumps({"request_id": r["request_id"], "output": {"error": "invalid_input"}}), flush=True)
'''


def fake_archive(rows, micro=False):
    """A Binance monthly kline zip: 12 columns, no header."""
    text = io.StringIO()
    for i, close in enumerate(rows):
        opened = 1700000000000 + i * 3600000
        if micro:
            opened *= 1000
        text.write(f"{opened},{close},{close},{close},{close},1,{opened + 1},1,1,1,1,0\n")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("X-1h-2024-01.csv", text.getvalue())
    return buffer.getvalue()


class FakeArchive:
    def __init__(self):
        self.calls = []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        name = url.rsplit("/", 1)[1].replace(".CHECKSUM", "")
        rng_seed = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
        closes, price = [], 100.0 + rng_seed % 900
        for i in range(720):
            price *= 1 + (((rng_seed >> (i % 24)) % 7) - 3) / 1000
            closes.append(f"{price:.8f}")
        payload = fake_archive(closes, micro="2025" in name or "2026" in name)
        if url.endswith(".CHECKSUM"):
            return f"{hashlib.sha256(payload).hexdigest()}  {name}\n".encode()
        return payload


class GeneratorIntegrity(unittest.TestCase):
    def test_label_cannot_be_read_off_names_degrees_or_ordering(self):
        inputs, answers = testbed.generated_cases("transactions", 600, 9)
        cheats = {
            "names": lambda rows: sorted(r["id"] for r in rows if not re.fullmatch(r"A\d+", r["sender"])),
            "low_degree": lambda rows: (lambda d: sorted(
                r["id"] for r in rows if d[r["sender"]] <= 2 and d[r["recipient"]] <= 2
            ))(Counter(x for r in rows for x in (r["sender"], r["recipient"]))),
        }
        positives = [(i, a) for i, a in zip(inputs, answers) if a["expected"].get("cycle_transaction_ids")]
        self.assertGreater(len(positives), 150)
        for name, cheat in cheats.items():
            hits = sum(cheat(i["input"]["rows"]) == a["expected"]["cycle_transaction_ids"] for i, a in positives)
            self.assertLess(hits / len(positives), 0.1, name)

    def test_decoy_loops_are_not_three_cycles_and_oracle_is_exact(self):
        rows = [
            {"id": "a", "sender": "x", "recipient": "y"},
            {"id": "b", "sender": "y", "recipient": "x"},
            {"id": "c", "sender": "p", "recipient": "q"},
            {"id": "d", "sender": "q", "recipient": "r"},
            {"id": "e", "sender": "r", "recipient": "s"},
            {"id": "f", "sender": "s", "recipient": "p"},
            {"id": "g", "sender": "m", "recipient": "n"},
            {"id": "h", "sender": "n", "recipient": "o"},
            {"id": "i", "sender": "o", "recipient": "m"},
            {"id": "j", "sender": "o", "recipient": "m"},
        ]
        self.assertEqual(testbed.three_cycle_ids(rows), ["g", "h", "i", "j"])

    def test_case_streams_are_independent(self):
        a = testbed.stream(1, 0, "ids").getrandbits(64)
        self.assertNotEqual(a, testbed.stream(1, 0, "data").getrandbits(64))
        self.assertNotEqual(a, testbed.stream(1, 1, "ids").getrandbits(64))
        self.assertEqual(a, testbed.stream(1, 0, "ids").getrandbits(64))


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="challenge-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "project").mkdir()

    def script(self, name, body):
        path = self.root / "project" / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_honest_implementation_passes_and_seed_commitment_verifies(self):
        adapter = self.script("adapter.py", HONEST)
        out = self.root / "report"
        summary = bench.challenge(out, [sys.executable, str(adapter)], "mixed", 45, project=self.root / "project")
        self.assertEqual((summary["passed"], summary["failed"], summary["errors"]), (30, 0, 0))
        self.assertEqual(summary["strategy_runs_completed"], 15)
        reveal = json.loads((out / "SEED-REVEAL.txt").read_text())
        self.assertEqual((out / "COMMITMENT.txt").read_text().strip(), bench.commitment(reveal["seed"]))
        self.assertEqual(summary["challenge"]["provenance"]["warnings"], [])
        self.assertIn("Challenge integrity", (out / "REPORT.md").read_text())
        self.assertIsNotNone(summary["market_summary"]["verdict"])

    def test_no_answer_or_input_file_exists_while_adapter_runs(self):
        seen = self.root / "seen.json"
        adapter = self.script("snoop.py", SNOOPER)
        out = self.root / "report"
        summary = bench.challenge(
            out, [sys.executable, str(adapter), str(self.root), str(seen)], "cashflow", 12,
            project=self.root / "project",
        )
        self.assertEqual(json.loads(seen.read_text()), [])
        self.assertLess(summary["passed"], 12)  # guessing "invalid" only passes invalid cases

    def test_kit_reference_code_is_disabled_and_flagged(self):
        wrapper = self.script(
            "lazy.py",
            f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom core import forecast_cashflow\n"
            f"exec(open({str(ROOT / 'example_adapter.py')!r}).read())\n",
        )
        summary = bench.challenge(
            self.root / "report", [sys.executable, str(wrapper)], "cashflow", 6, project=self.root / "project"
        )
        self.assertEqual(summary["passed"], 0)
        self.assertGreaterEqual(summary["errors"], 1)
        reasons = [w["reason"] for w in summary["challenge"]["provenance"]["warnings"]]
        self.assertTrue(any("reference code" in r for r in reasons))

    def test_organiser_seed_gives_each_team_different_reproducible_cases(self):
        master = 123456789
        self.assertEqual(bench.team_seed(master, "Team A"), bench.team_seed(master, " team a "))
        self.assertNotEqual(bench.team_seed(master, "Team A"), bench.team_seed(master, "Team B"))
        adapter = self.script("adapter.py", HONEST)
        out = self.root / "report"
        summary = bench.challenge(out, [sys.executable, str(adapter)], "transactions", 6, master=master,
                                  team="Team A", project=self.root / "project")
        self.assertEqual(summary["passed"], 6)
        self.assertFalse((out / "SEED-REVEAL.txt").exists())
        self.assertEqual((out / "COMMITMENT.txt").read_text().strip(), bench.commitment(master))
        with self.assertRaises(ValueError):
            bench.challenge(self.root / "r2", [sys.executable, str(adapter)], master=master, team="")

    def test_seal_never_overwrites(self):
        path = self.root / "seed.json"
        sealed = bench.seal(path)
        self.assertEqual(sealed["commitment"], bench.commitment(json.loads(path.read_text())["master_seed"]))
        with self.assertRaises(ValueError):
            bench.seal(path)

    def test_stray_stdout_is_explained_and_stderr_is_logged(self):
        adapter = self.script(
            "noisy.py",
            "import sys\nprint('debug starting')\nprint('to stderr', file=sys.stderr, flush=True)\n" + HONEST,
        )
        out = self.root / "report"
        bench.challenge(out, [sys.executable, str(adapter)], "cashflow", 3, project=self.root / "project")
        report = (out / "REPORT.md").read_text()
        self.assertIn("print logs to stderr", report)
        self.assertIn("to stderr", (out / "adapter-stderr.log").read_text())

    def test_sign_test(self):
        self.assertAlmostEqual(bench.sign_test_p(10, 0), 2 / 1024)
        self.assertEqual(bench.sign_test_p(5, 5), 1.0)
        self.assertIsNone(bench.sign_test_p(0, 0))


class RealDataTests(unittest.TestCase):
    def test_parse_handles_milliseconds_microseconds_and_header(self):
        for micro in (False, True):
            rows = marketdata.parse_klines(fake_archive([f"{100 + i}.5" for i in range(20)], micro))
            self.assertEqual(rows[0], (1700000000000, "100.5"))
            self.assertEqual(len(rows), 20)

    def test_checksum_mismatch_is_refused(self):
        payload = fake_archive(["1.0"] * 20)

        def bad(url, timeout=30):
            return b"0" * 64 + b"  x.zip" if url.endswith(".CHECKSUM") else payload

        with self.assertRaises(ValueError):
            marketdata.fetch_month("BTCUSDT", "1h", 2024, 1, getter=bad)

    def test_anonymised_window_keeps_returns_and_hides_identity(self):
        import random
        closes = ["100", "110", "99", "120"]
        prices, dates = marketdata.anonymised_window(closes, random.Random(1), 4, invert=False)
        self.assertAlmostEqual(prices[1] / prices[0], 1.1, places=3)
        inverted, _ = marketdata.anonymised_window(closes, random.Random(1), 4, invert=True)
        self.assertAlmostEqual(inverted[1] / inverted[0], 1 / 1.1, places=3)
        self.assertTrue(all(d.startswith("20") and d < "2010" for d in dates))

    def test_real_challenge_runs_end_to_end_with_documented_formats(self):
        fake = FakeArchive()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "adapter.py").write_text(HONEST)
            summary = bench.challenge(
                root / "report", [sys.executable, str(root / "adapter.py")], "real-markets", 4,
                project=root, getter=fake,
            )
            self.assertEqual(summary["strategy_runs_completed"], 4)
            self.assertTrue(all("data.binance.vision" in url for url in fake.calls))
            self.assertTrue(any(url.endswith(".CHECKSUM") for url in fake.calls))
            dataset = bench.fetch(root / "practice", 3, seed=5, getter=fake)
            self.assertEqual(dataset["case_count"], 3)
            self.assertFalse(dataset["synthetic"])

    def test_months_exclude_unpublished_archives(self):
        months = marketdata.available_months(date(2026, 11, 6))
        self.assertEqual(months[0], (2021, 1))
        self.assertEqual(months[-1], (2026, 9))


class LiveTests(unittest.TestCase):
    def test_fills_use_price_fetched_after_decision(self):
        state = {"now": 1_800_000_000.0, "tick": 0}

        def clock():
            return state["now"]

        def sleep(seconds):
            state["now"] += seconds

        def getter(url, timeout=10):
            minute = int(state["now"] // 60)
            if "/klines" in url:
                rows = []
                for m in range(minute - 40, minute + 1):
                    opened = m * 60000
                    rows.append([opened, "0", "0", "0", str(100 + m % 7), "0", opened + 59999])
                return json.dumps(rows).encode()
            state["tick"] += 1
            return json.dumps({"symbol": "BTCUSDT", "price": str(200 + state["tick"])}).encode()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "seen.jsonl"
            (root / "adapter.py").write_text(
                "import json,sys\nfor line in sys.stdin:\n r=json.loads(line)\n"
                f" open({str(log)!r},'a').write(json.dumps(r['input']['history'][-1])+'\\n')\n"
                " a='buy' if r['input']['shares']==0 else 'hold'\n"
                " print(json.dumps({'request_id':r['request_id'],'output':{'action':a}}),flush=True)\n"
            )
            result = bench.live(root / "live", [sys.executable, str(root / "adapter.py")], steps=3,
                                getter=getter, clock=clock, sleep=sleep)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["decisions"], 3)
            seen = [json.loads(x)["price_pence"] for x in log.read_text().splitlines()]
            fill = result["trades"][0]["fill_price_pence"]
            self.assertNotIn(fill, seen)  # traded price was unknown at decision time
            self.assertTrue((root / "live" / "REPORT.md").exists())


if __name__ == "__main__":
    unittest.main()
