#!/usr/bin/env python3
"""Generate cases, run a participant adapter, and report actual checked outcomes."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import math
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import marketdata

from testbed import (
    MAX_CASES,
    PACKS,
    differences,
    digest,
    encoded,
    generate,
    generated_cases,
    load_dataset,
    market_rows,
    money,
    read_jsonl,
    save_dataset,
    write_jsonl,
)


class AdapterError(ValueError):
    pass


class Adapter:
    """One local JSONL process. Timeout covers both request write and response read."""

    def __init__(
        self,
        command: list[str],
        timeout: float,
        max_requests: int = 1000000,
        env: dict | None = None,
        stderr_path: Path | None = None,
    ):
        if not command or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Provide an adapter command and a positive finite timeout")
        self.timeout = timeout
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("Request budget must be a positive integer")
        self.max_requests, self.request_count = max_requests, 0
        # Participant diagnostics go to a log file beside the report, never into it.
        self.stderr = (
            open(stderr_path, "w", encoding="utf-8") if stderr_path else subprocess.DEVNULL
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=os.name == "posix",
        )
        self.worker = None

    def call(self, request: dict) -> dict:
        if self.request_count >= self.max_requests:
            raise AdapterError(
                "Adapter request budget reached; remaining cases were not run"
            )
        self.request_count += 1
        result = queue.Queue(maxsize=1)

        def exchange():
            try:
                self.process.stdin.write(encoded(request) + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline(262145)
                if not line or len(line) > 262144 or not line.endswith("\n"):
                    raise AdapterError(
                        "Adapter closed, or response exceeded 256 KiB / lacked a newline"
                    )
                try:
                    response = json.loads(line)
                except ValueError:
                    raise AdapterError(
                        "stdout line was not JSON (print logs to stderr instead): starts "
                        + json.dumps(line[:60])
                    ) from None
                if (
                    not isinstance(response, dict)
                    or response.get("request_id") != request["request_id"]
                ):
                    raise AdapterError("Adapter must return the same request_id")
                output = response.get("output")
                if not isinstance(output, dict):
                    raise AdapterError("Adapter must return an output object")
                # Reject NaN/Infinity even if Python's JSON parser accepted it.
                encoded(output)
                result.put((True, output))
            except (OSError, ValueError, TypeError) as error:
                result.put((False, error))

        worker = threading.Thread(target=exchange, daemon=True)
        self.worker = worker
        worker.start()
        try:
            ok, value = result.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise AdapterError(
                "Adapter timed out; remaining cases were not run"
            ) from None
        if not ok:
            # Only kit-authored reasons reach the report; stderr stays in its log file.
            reason = str(value) if isinstance(value, AdapterError) else "process exited or pipe closed"
            raise AdapterError(
                f"Adapter returned invalid JSON/protocol output or exited ({reason}). See adapter-stderr.log"
            ) from value
        return value

    def close(self):
        if os.name == "posix":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        if self.worker:
            self.worker.join(timeout=1)
            if self.worker.is_alive():
                return
        if self.stderr is not subprocess.DEVNULL:
            self.stderr.close()
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except (BrokenPipeError, OSError):
                pass


def play_market(row: dict, adapter: Adapter) -> dict:
    """Adapter sees only observed history; orders execute at the NEXT price."""
    data = row["input"]
    prices, dates = data["prices_pence"], data["dates"]
    cash, shares = data["initial_cash_pence"], 0
    fee, bps = data["fee_pence"], data["slippage_bps"]
    fees, trades = 0, []
    equity = [cash]
    for index in range(len(prices) - 1):
        request = {
            "request_id": f"{row['case_id']}:{index}",
            "case_id": row["case_id"],
            "task": "market_step",
            "input": {
                "history": [
                    {"date": dates[i], "price_pence": prices[i]}
                    for i in range(index + 1)
                ],
                "cash_pence": cash,
                "shares": shares,
                "fee_pence": fee,
                "slippage_bps": bps,
            },
        }
        action = adapter.call(request).get("action")
        if action not in ("buy", "hold", "sell"):
            raise ValueError("Market output.action must be buy, hold or sell")
        next_price = prices[index + 1]
        if action == "buy":
            fill = (next_price * (10000 + bps) + 9999) // 10000
            units = max(0, cash - fee) // fill
            if units:
                cash -= units * fill + fee
                shares += units
                fees += fee
                trades.append(
                    {
                        "signal_date": dates[index],
                        "fill_date": dates[index + 1],
                        "action": action,
                        "shares": units,
                        "fill_price_pence": fill,
                    }
                )
        elif action == "sell" and shares:
            fill = next_price * (10000 - bps) // 10000
            cash += shares * fill - fee
            fees += fee
            trades.append(
                {
                    "signal_date": dates[index],
                    "fill_date": dates[index + 1],
                    "action": action,
                    "shares": shares,
                    "fill_price_pence": fill,
                }
            )
            shares = 0
        if cash < 0:
            raise ValueError("Order cannot cover fees; borrowing is not supported")
        equity.append(cash + shares * next_price)
    if shares:
        fill = prices[-1] * (10000 - bps) // 10000
        cash += shares * fill - fee
        fees += fee
        trades.append(
            {
                "fill_date": dates[-1],
                "action": "forced_final_sale",
                "shares": shares,
                "fill_price_pence": fill,
            }
        )
        if cash < 0:
            raise ValueError("Final liquidation cannot cover fees")
    equity.append(cash)
    peak, max_drawdown = equity[0], 0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) * 10000 // peak)
    return {
        "final_cash_pence": cash,
        "profit_pence": cash - data["initial_cash_pence"],
        "max_drawdown_bps": max_drawdown,
        "fees_paid_pence": fees,
        "trades": trades,
        "decision_count": len(prices) - 1,
        "execution": "next-bar with forced final liquidation; no leverage",
    }


def field_metrics(row, answer, output):
    if row["task"] != "transactions" or not isinstance(
        answer["expected"].get("cycle_transaction_ids"), list
    ):
        return {}
    predicted = output.get("cycle_transaction_ids")
    if not isinstance(predicted, list) or any(
        not isinstance(x, str) for x in predicted
    ):
        predicted = []
    actual, expected = set(predicted), set(answer["expected"]["cycle_transaction_ids"])
    return {
        "true_positive_records": len(actual & expected),
        "false_positive_records": len(actual - expected),
        "missed_records": len(expected - actual),
    }


def score_one(row, answer, output):
    if row["task"] == "markets":
        raise ValueError(
            "Market strategies must use the walk-forward runner, not a supplied final-balance prediction"
        )
    errors = differences(answer["expected"], output)
    result = {
        "case_id": row["case_id"],
        "task": row["task"],
        "family": answer.get("family", "custom"),
        "status": "fail" if errors else "pass",
        "checks": errors[:20],
        "metrics": field_metrics(row, answer, output),
        "output": output,
    }
    if errors:
        result["expected"] = answer["expected"]
        result["input"] = row["input"]
    return result


def sign_test_p(wins: int, losses: int) -> float | None:
    """Two-sided exact binomial test of wins vs losses (ties excluded) at p=0.5."""
    n = wins + losses
    if not n:
        return None
    tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n
    return min(1.0, 2 * tail)


def market_statistics(simulations: list[dict]) -> dict | None:
    """Skill vs luck across paths. Completion is never a pass; this is the judged number."""
    if not simulations:
        return None
    excess, wins, losses, beat_cash, drawdowns = [], 0, 0, 0, []
    for item in simulations:
        final = item["output"]["final_cash_pence"]
        hold = item["benchmarks"]["buy_and_hold_final_cash_pence"]
        cash = item["benchmarks"]["cash_baseline_final_pence"]
        excess.append((final - hold) * 10000 // cash)
        wins += final > hold
        losses += final < hold
        beat_cash += final > cash
        drawdowns.append(item["output"]["max_drawdown_bps"])
    ordered = sorted(excess)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) // 2
    p_value = sign_test_p(wins, losses)
    if p_value is not None and p_value < 0.05 and median > 0:
        verdict = "Beat buy-and-hold more often than chance would explain on these paths."
    elif p_value is not None and p_value < 0.05 and median < 0:
        verdict = "Lost to buy-and-hold more often than chance would explain on these paths."
    else:
        verdict = "Not distinguishable from buy-and-hold on these paths; more paths or a better edge is needed."
    return {
        "paths": len(simulations),
        "wins_vs_buy_and_hold": wins,
        "losses_vs_buy_and_hold": losses,
        "ties": len(simulations) - wins - losses,
        "beat_cash": beat_cash,
        "median_excess_vs_buy_and_hold_bps_of_capital": median,
        "mean_max_drawdown_bps": sum(drawdowns) // len(drawdowns),
        "sign_test_p_value": p_value,
        "verdict": verdict,
    }


def report(output: Path, manifest, rows, results, label, extra=None):
    output.mkdir(parents=True, exist_ok=True)
    counts = Counter(item["status"] for item in results)
    untested = len(rows) - len(results)
    totals = Counter()
    for item in results:
        totals.update(item.get("metrics", {}))
    tp, fp, fn = (
        totals[k]
        for k in ("true_positive_records", "false_positive_records", "missed_records")
    )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    record_metrics = {
        "cycle_precision": precision,
        "cycle_recall": recall,
        "cycle_f1": 2 * precision * recall / (precision + recall)
        if precision and recall
        else (0.0 if tp + fp + fn else None),
        **dict(totals),
    }
    market_summary = market_statistics(
        [item for item in results if item["status"] == "simulated"]
    )
    summary = {
        "label": label,
        "dataset": manifest,
        "dataset_cases": len(rows),
        "attempted": len(results),
        "passed": counts["pass"],
        "failed": counts["fail"],
        "errors": counts["error"],
        "strategy_runs_completed": counts["simulated"],
        "not_run": untested,
        "cycle_record_metrics": record_metrics,
        "market_summary": market_summary,
        **(extra or {}),
        "limits": "Passing defined checks does not validate an entire product. Market completion is not profitability. Synthetic data is not a real-world benchmark. This runner is not an OS security sandbox.",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_jsonl(output / "case-results.jsonl", results)
    write_jsonl(
        output / "predictions.jsonl",
        (
            {"case_id": item["case_id"], "output": item["output"]}
            for item in results
            if "output" in item and item["task"] != "markets"
        ),
    )
    lines = [
        "# Finance project test report",
        "",
        f"**{label}**",
        "",
        f"Dataset: {len(rows)} cases; seed: {manifest.get('seed')}; source: {manifest['source']}.",
        "",
        f"Exact checks: **{counts['pass']} passed, {counts['fail']} failed, {counts['error']} execution errors**.",
        f"Market simulations completed: **{counts['simulated']}**. Cases not run: **{untested}**.",
        "",
        "Only the configured adapter and defined checks were exercised. A baseline run tests the kit, not your submission.",
    ]
    challenge_info = (extra or {}).get("challenge")
    if challenge_info:
        lines += [
            "",
            "## Challenge integrity",
            "",
            f"- Cases were generated in memory after the adapter was fixed; no input or answer file existed during the run.",
            f"- Seed commitment (published before scoring): `{challenge_info['commitment']}`",
            f"- Seed: {challenge_info['seed_status']}",
            f"- Kit fingerprint: `{challenge_info['kit_fingerprint']}` (compare with the organisers' published value)",
            f"- Project commit: `{challenge_info['provenance'].get('git_head')}`, uncommitted changes: {challenge_info['provenance'].get('git_dirty_files')}",
        ]
        warnings = challenge_info["provenance"].get("warnings", [])
        lines.append(
            "- Provenance review: "
            + ("none flagged." if not warnings else f"**{len(warnings)} item(s) need a human look:**")
        )
        for warning in warnings[:15]:
            lines.append(f"  - `{warning['file']}`: {warning['reason']}")
    lines += [
        "",
        "## Coverage",
        "",
        "| Task / scenario family | Pass | Fail | Error | Simulated |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    groups = sorted({(item["task"], item["family"]) for item in results})
    for task, family in groups:
        group = Counter(
            item["status"]
            for item in results
            if (item["task"], item["family"]) == (task, family)
        )
        lines.append(
            f"| {task} / {family} | {group['pass']} | {group['fail']} | {group['error']} | {group['simulated']} |"
        )
    if tp + fp + fn:
        precision_text = (
            f"{record_metrics['cycle_precision']:.1%}"
            if record_metrics["cycle_precision"] is not None
            else "undefined (no alerts)"
        )
        recall_text = (
            f"{record_metrics['cycle_recall']:.1%}"
            if record_metrics["cycle_recall"] is not None
            else "undefined (no positive labels)"
        )
        lines += [
            "",
            "## Transaction-cycle evidence",
            "",
            f"Record precision: {precision_text}; recall: {recall_text}; F1: {record_metrics['cycle_f1']:.1%}. False alerts: {fp}; missed cycle records: {fn}.",
            "Judge detection by recall and F1, not the pass count: a detector that flags nothing still passes every case with no cycle.",
            "These labels identify planted graph patterns, not actual fraud or regulatory compliance.",
        ]
    simulations = [item for item in results if item["status"] == "simulated"]
    if simulations:
        lines += [
            "",
            "## Strategy results after costs",
            "",
            "| Case | Final cash | Profit / loss | Buy-and-hold final | Cash baseline | Max drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in simulations[:30]:
            data, expected = item["output"], item["benchmarks"]
            lines.append(
                f"| {item['case_id']} | {money(data['final_cash_pence'])} | {money(data['profit_pence'])} | {money(expected['buy_and_hold_final_cash_pence'])} | {money(expected['cash_baseline_final_pence'])} | {data['max_drawdown_bps'] / 100:.2f}% |"
            )
        lines += [
            "",
            f"Showing {min(30, len(simulations))} of {len(simulations)} paths; every result and trade is in case-results.jsonl.",
            "Completing a simulation does not mean the strategy is good. Compare losses, costs, baselines and drawdown. These price paths do not model real market liquidity or predict returns.",
            "",
            f"**Across {market_summary['paths']} paths:** {market_summary['wins_vs_buy_and_hold']} wins, {market_summary['losses_vs_buy_and_hold']} losses, {market_summary['ties']} ties vs buy-and-hold; beat cash on {market_summary['beat_cash']}. "
            f"Median excess {market_summary['median_excess_vs_buy_and_hold_bps_of_capital'] / 100:.2f}% of capital; mean max drawdown {market_summary['mean_max_drawdown_bps'] / 100:.2f}%; sign-test p = "
            + (f"{market_summary['sign_test_p_value']:.3f}" if market_summary["sign_test_p_value"] is not None else "n/a (all ties)")
            + ".",
            f"**{market_summary['verdict']}**",
        ]
    problems = [item for item in results if item["status"] in {"fail", "error"}]
    lines += ["", "## Next action", ""]
    if problems:
        for item in problems[:10]:
            lines.append(
                f"- Case `{item['case_id']}` ({item['task']}): "
                + "; ".join(item.get("checks", ["execution error"]))
            )
        lines.append(
            "\nFix one failed case, rerun the same seed, then generate a fresh seed to check generalisation."
        )
        for item in problems[:3]:
            if "expected" in item:
                detail = json.dumps(
                    {
                        "input": item["input"],
                        "expected": item["expected"],
                        "actual": item["output"],
                    },
                    indent=2,
                )
                if len(detail) > 8000:
                    detail = (
                        detail[:8000]
                        + "\n... (preview truncated; full case in case-results.jsonl)"
                    )
                lines += [
                    "",
                    f"### Failure example: {item['case_id']}",
                    "",
                    "```json",
                    detail,
                    "```",
                ]
    else:
        lines.append(
            "Run your actual submission adapter if this was a baseline. Add project-specific checks, then rerun with a fresh seed. Anything outside these checks remains untested."
        )
    if untested:
        lines.append(
            f"\n**{untested} cases were not run.** They are not passes. Increase the chosen limit or fix the execution error before testing them."
        )
    lines += [
        "",
        "Hidden challenge run: no input or answer file existed while the adapter ran, and the kit's reference calculations were disabled for it."
        if challenge_info
        else "Expected answers stayed with the evaluator; adapter requests contained inputs only. The local answer files remain visible to developers, so this practice run is not cheat-proof. Use `bench.py challenge` for a result you can claim.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run(
    dataset: Path,
    output: Path,
    command,
    limit=25,
    timeout=10.0,
    label="Participant adapter",
    max_seconds=120.0,
    max_requests=1000000,
):
    manifest, rows, answers = load_dataset(dataset)
    return execute(
        manifest, rows, answers, output, command, limit, timeout, label, max_seconds, max_requests
    )


def execute(
    manifest,
    rows,
    answers,
    output: Path,
    command,
    limit=25,
    timeout=10.0,
    label="Participant adapter",
    max_seconds=120.0,
    max_requests=1000000,
    env=None,
    extra=None,
    fresh_output=True,
):
    if type(limit) is not int or not 1 <= limit <= MAX_CASES:
        raise ValueError(f"Limit must be 1 to {MAX_CASES}")
    if fresh_output and output.exists():
        raise ValueError("Choose a new output directory")
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("Total time budget must be positive and finite")
    output.mkdir(parents=True, exist_ok=not fresh_output)
    results = []
    adapter = Adapter(
        command, timeout, max_requests, env=env, stderr_path=output / "adapter-stderr.log"
    )
    started = time.monotonic()
    try:
        for row in rows[:limit]:
            if time.monotonic() - started >= max_seconds:
                break
            answer = answers[row["case_id"]]
            try:
                if row["task"] == "markets":
                    # Each step also checks the run-wide deadline.
                    class BoundedAdapter:
                        def call(self, request):
                            remaining = max_seconds - (time.monotonic() - started)
                            if remaining <= 0:
                                raise AdapterError(
                                    "Total run time budget reached; remaining cases were not run"
                                )
                            adapter.timeout = min(timeout, remaining)
                            return adapter.call(request)

                    value = play_market(row, BoundedAdapter())
                    item = {
                        "case_id": row["case_id"],
                        "task": row["task"],
                        "family": answer.get("family", "custom"),
                        "status": "simulated",
                        "output": value,
                        "benchmarks": answer["expected"],
                    }
                else:
                    adapter.timeout = min(
                        timeout, max_seconds - (time.monotonic() - started)
                    )
                    value = adapter.call({"request_id": row["case_id"], **row})
                    item = score_one(row, answer, value)
                results.append(item)
            except (ValueError, OSError) as error:
                checks = (
                    [str(error)]
                    if isinstance(error, AdapterError)
                    else ["Invalid market action or accounting: " + str(error)]
                )
                results.append(
                    {
                        "case_id": row["case_id"],
                        "task": row["task"],
                        "family": answer.get("family", "custom"),
                        "status": "error",
                        "checks": checks,
                    }
                )
                # A broken protocol must not continue with a stale response queue.
                if isinstance(error, AdapterError):
                    break
    finally:
        adapter.close()
    return report(output, manifest, rows, results, label, extra)


def score(dataset, predictions, output):
    if output.exists():
        raise ValueError("Choose a new output directory")
    manifest, rows, answers = load_dataset(dataset)
    predictions = read_jsonl(predictions)
    by_id = {}
    known = {row["case_id"] for row in rows}
    for prediction in predictions:
        key = prediction.get("case_id")
        if (
            key not in known
            or key in by_id
            or not isinstance(prediction.get("output"), dict)
        ):
            raise ValueError(
                "Predictions need known unique case IDs and output objects"
            )
        by_id[key] = prediction["output"]
    results = [
        score_one(row, answers[row["case_id"]], by_id[row["case_id"]])
        for row in rows
        if row["case_id"] in by_id
    ]
    return report(output, manifest, rows, results, "Supplied participant predictions")

KIT = Path(__file__).resolve().parent
SCAN_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".ipynb", ".sh"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".agents", "dist", "build"}
SCAN_RULES = (
    (
        re.compile(r"\b(from|import)\s+(core|testbed|bench|example_adapter)\b|finance[/\\.](core|testbed|bench)"),
        "imports the kit's reference code; the adapter must call the team's own implementation",
    ),
    (re.compile(r"answers\.jsonl|SEED-REVEAL|organiser-seed"), "references answer keys or seed files"),
    (re.compile(r"AGENTVERSE_CHALLENGE|agentverse-v2:|agentverse-seal"), "references challenge internals"),
    (
        re.compile(r"data\.binance\.vision|/api/v3/klines"),
        "downloads Binance history; fine for features, but check it is not used to look up hidden historical paths",
    ),
)


def kit_fingerprint() -> str:
    """SHA-256 over the kit's evaluator files. Organisers publish the expected value."""
    hasher = hashlib.sha256()
    for name in ("bench.py", "testbed.py", "marketdata.py", "core.py"):
        hasher.update(name.encode() + b"\0" + (KIT / name).read_bytes() + b"\0")
    return hasher.hexdigest()


def scan_project(project: Path, command: list[str]) -> dict:
    """Static provenance evidence for judges. Flags are prompts for review, not verdicts."""
    project = project.resolve()
    warnings, scanned = [], 0
    kit_root = KIT.parent
    for path in sorted(project.rglob("*")):
        if scanned >= 3000:
            warnings.append({"file": ".", "reason": "scan stopped at 3,000 files"})
            break
        if path.suffix not in SCAN_SUFFIXES or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(project).parts):
            continue
        if kit_root == path or kit_root in path.parents:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:1_000_000]
        except OSError:
            continue
        for pattern, reason in SCAN_RULES:
            if pattern.search(text):
                warnings.append({"file": str(path.relative_to(project)), "reason": reason})
    adapter_files = {}
    for part in command:
        candidate = Path(part)
        if candidate.is_file() and candidate.suffix in SCAN_SUFFIXES:
            adapter_files[str(candidate)] = hashlib.sha256(candidate.read_bytes()).hexdigest()

    def git(*args):
        try:
            done = subprocess.run(
                ["git", "-C", str(project), *args], capture_output=True, text=True, timeout=10
            )
            return done.stdout.strip() if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    status = git("status", "--porcelain")
    return {
        "project": str(project),
        "files_scanned": scanned,
        "adapter_command": command,
        "adapter_file_sha256": adapter_files,
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty_files": None if status is None else len(status.splitlines()),
        "warnings": warnings,
    }


def commitment(seed: int) -> str:
    return hashlib.sha256(f"agentverse-seal-v2:{seed}".encode()).hexdigest()


def team_seed(master: int, team: str) -> int:
    """Each team gets different hidden cases from one sealed master seed, so one
    team's report cannot leak another team's answers."""
    digest_bytes = hashlib.sha256(f"agentverse-team-v2:{master}:{team.strip().lower()}".encode()).digest()
    return int.from_bytes(digest_bytes[:8], "big") >> 1


def seal(output: Path) -> dict:
    if output.exists():
        raise ValueError("Choose a new seed file path; never overwrite a sealed seed")
    master = secrets.randbits(63)
    output.write_text(json.dumps({"master_seed": master}) + "\n", encoding="utf-8")
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    return {"seed_file": str(output), "commitment": commitment(master), "publish": "Share the commitment now; keep the seed file off team machines until results are final."}


def read_master(seed_file: Path | None, prompt: bool):
    if prompt:
        value = getpass.getpass("Organiser master seed (input hidden): ").strip()
        return int(json.loads(value)["master_seed"]) if value.startswith("{") else int(value)
    if seed_file:
        return int(json.loads(seed_file.read_text(encoding="utf-8"))["master_seed"])
    return None


def challenge(
    output: Path,
    command,
    pack="mixed",
    cases=60,
    master=None,
    team="",
    project: Path | None = None,
    timeout=10.0,
    max_seconds=900.0,
    max_requests=100000,
    getter=None,
):
    """Hidden evaluation. Fresh secret seed (or organiser's sealed seed), cases built
    in memory only, kit reference disabled in the adapter, provenance recorded."""
    if output.exists():
        raise ValueError("Choose a new output directory")
    if pack not in PACKS + ("real-markets",):
        raise ValueError("Choose mixed, cashflow, transactions, markets or real-markets")
    if master is not None and not team.strip():
        raise ValueError("Organiser mode needs --team so each team gets its own hidden cases")
    sealed = master is not None
    seed = team_seed(master, team) if sealed else secrets.randbits(63)
    sealed_with = commitment(master) if sealed else commitment(seed)
    output.mkdir(parents=True)
    (output / "COMMITMENT.txt").write_text(sealed_with + "\n", encoding="utf-8")
    print(f"Seed commitment: {sealed_with}", file=sys.stderr)
    if pack == "real-markets":
        datas, months = marketdata.real_market_cases(
            cases, seed, getter=getter or marketdata.http_get, cache=None
        )
        inputs, answers = market_rows(datas, seed)
        source = f"{marketdata.ATTRIBUTION} Months drawn: {len(months)} (hidden until reveal)."
    else:
        inputs, answers = generated_cases(pack, cases, seed)
        months = None
        source = "AgentVerse seeded generator v2 (hidden challenge)"
    by_id = {answer["case_id"]: answer for answer in answers}
    manifest = {
        "version": 2,
        "mode": "challenge",
        "source": source,
        "seed": None,
        "pack": pack,
        "case_count": len(inputs),
        "tasks": dict(Counter(row["task"] for row in inputs)),
    }
    provenance = scan_project(project or Path.cwd(), list(command))
    info = {
        "commitment": sealed_with,
        "seed_status": f"organiser master seed, team '{team}'; revealed by organisers after judging"
        if sealed
        else "fresh random; revealed in SEED-REVEAL.txt after this run",
        "kit_fingerprint": kit_fingerprint(),
        "provenance": provenance,
    }
    env = {**os.environ, "AGENTVERSE_CHALLENGE": "1"}
    summary = execute(
        manifest,
        inputs,
        by_id,
        output,
        list(command),
        limit=len(inputs),
        timeout=timeout,
        label=f"CHALLENGE ({'organiser-sealed' if sealed else 'self-serve'}): hidden {pack} cases",
        max_seconds=max_seconds,
        max_requests=max_requests,
        env=env,
        extra={"challenge": info},
        fresh_output=False,
    )
    if not sealed:
        reveal = {"seed": seed, "commitment_check": commitment(seed), "real_months": months}
        (output / "SEED-REVEAL.txt").write_text(json.dumps(reveal, indent=2) + "\n", encoding="utf-8")
    return summary


def fetch(output: Path, cases: int, seed=None, cache: Path | None = None, getter=None) -> dict:
    """Practice dataset of anonymised real Binance paths (inputs + answers on disk)."""
    seed = secrets.randbits(63) if seed is None else seed
    datas, months = marketdata.real_market_cases(
        cases, seed, getter=getter or marketdata.http_get, cache=cache
    )
    inputs, answers = market_rows(datas, seed)
    return save_dataset(
        output,
        inputs,
        answers,
        f"{marketdata.ATTRIBUTION} Practice set; months: {', '.join(months)}",
        seed,
        "real-markets",
        synthetic=False,
    )


INTERVAL_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "1h": 3600}


def live(
    output: Path,
    command,
    symbol="BTCUSDT",
    interval="1m",
    steps=30,
    warmup=30,
    initial_cash_pence=1000000,
    fee_pence=100,
    slippage_bps=10,
    timeout=5.0,
    getter=None,
    clock=time.time,
    sleep=time.sleep,
):
    """Forward test on live Binance prices. Decisions use closed candles only; each
    order fills at the live price fetched after the decision arrives, so no strategy
    can see the price it trades at before choosing."""
    if output.exists():
        raise ValueError("Choose a new output directory")
    if symbol not in marketdata.SYMBOLS or interval not in INTERVAL_SECONDS:
        raise ValueError(f"Use a symbol from {marketdata.SYMBOLS} and interval from {tuple(INTERVAL_SECONDS)}")
    if not (1 <= steps <= 500 and 1 <= warmup <= 500):
        raise ValueError("Use 1 to 500 steps and warm-up candles")
    getter = getter or marketdata.http_get
    output.mkdir(parents=True)
    candles = marketdata.live_closed_klines(symbol, interval, warmup, getter, int(clock() * 1000))
    if len(candles) < 2:
        raise ValueError("Live feed returned too few closed candles")
    anchor = float(candles[0][1])

    def pence(value: str) -> int:
        return max(1, round(10000 * float(value) / anchor))

    def stamp(opened_ms: int) -> str:
        return datetime.fromtimestamp(opened_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

    history = [{"date": stamp(opened), "price_pence": pence(close)} for opened, close in candles]
    last_opened = candles[-1][0]
    cash, shares, fees, trades, equity = initial_cash_pence, 0, 0, [], [initial_cash_pence]
    first_fill = None
    adapter = Adapter(
        list(command), timeout, steps + 1, env={**os.environ, "AGENTVERSE_CHALLENGE": "1"},
        stderr_path=output / "adapter-stderr.log",
    )
    status = "completed"
    try:
        for step in range(steps):
            if step:
                deadline = clock() + INTERVAL_SECONDS[interval] + 60
                while True:
                    fresh = marketdata.live_closed_klines(symbol, interval, 3, getter, int(clock() * 1000))
                    new = [c for c in fresh if c[0] > last_opened]
                    if new:
                        history += [{"date": stamp(o), "price_pence": pence(c)} for o, c in new]
                        last_opened = new[-1][0]
                        break
                    if clock() > deadline:
                        raise AdapterError("Live feed stalled; run stopped")
                    sleep(2)
            request = {
                "request_id": f"live:{step}",
                "case_id": f"live-{symbol}-{interval}",
                "task": "market_step",
                "input": {"history": history[-500:], "cash_pence": cash, "shares": shares,
                          "fee_pence": fee_pence, "slippage_bps": slippage_bps},
            }
            action = adapter.call(request).get("action")
            if action not in ("buy", "hold", "sell"):
                raise ValueError("Market output.action must be buy, hold or sell")
            price = pence(marketdata.live_price(symbol, getter))  # fetched AFTER the decision
            first_fill = first_fill or price
            if action == "buy":
                fill = (price * (10000 + slippage_bps) + 9999) // 10000
                units = max(0, cash - fee_pence) // fill
                if units:
                    cash -= units * fill + fee_pence
                    shares += units
                    fees += fee_pence
                    trades.append({"step": step, "action": "buy", "shares": units, "fill_price_pence": fill})
            elif action == "sell" and shares:
                fill = price * (10000 - slippage_bps) // 10000
                cash += shares * fill - fee_pence
                fees += fee_pence
                trades.append({"step": step, "action": "sell", "shares": shares, "fill_price_pence": fill})
                shares = 0
            equity.append(cash + shares * price)
    except (AdapterError, ValueError, OSError) as error:
        status = f"stopped: {error}"
    finally:
        adapter.close()
    final_price = pence(marketdata.live_price(symbol, getter))
    if shares:
        fill = final_price * (10000 - slippage_bps) // 10000
        cash += shares * fill - fee_pence
        fees += fee_pence
        trades.append({"action": "forced_final_sale", "shares": shares, "fill_price_pence": fill})
    equity.append(cash)
    peak, drawdown = equity[0], 0
    for value in equity:
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) * 10000 // peak)
    hold = initial_cash_pence
    if first_fill:
        entry = (first_fill * (10000 + slippage_bps) + 9999) // 10000
        units = max(0, initial_cash_pence - fee_pence) // entry
        exit_fill = final_price * (10000 - slippage_bps) // 10000
        hold = initial_cash_pence + units * (exit_fill - entry) - (2 * fee_pence if units else 0)
    result = {
        "mode": "live forward test",
        "status": status,
        "symbol_interval": f"{symbol} {interval}",
        "decisions": len(equity) - 2,
        "final_cash_pence": cash,
        "profit_pence": cash - initial_cash_pence,
        "buy_and_hold_final_cash_pence": hold,
        "max_drawdown_bps": drawdown,
        "fees_paid_pence": fees,
        "trades": trades,
        "prices": "rebased to 10,000 at the first warm-up candle; fills at live price after each decision",
        "source": marketdata.ATTRIBUTION,
        "kit_fingerprint": kit_fingerprint(),
        "limits": "One live session is one path: it shows the agent runs honestly on unseen data, not that it has an edge.",
    }
    (output / "live-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "REPORT.md").write_text(
        "\n".join(
            [
                "# Live forward test",
                "",
                f"**{status}** on {symbol} {interval}: {result['decisions']} decisions.",
                "",
                f"Final cash {money(cash)} (profit {money(cash - initial_cash_pence)}); buy-and-hold {money(hold)}; cash {money(initial_cash_pence)}; max drawdown {drawdown / 100:.2f}%; fees {money(fees)}.",
                "",
                "The strategy saw closed candles only and every fill used a price fetched after its decision, so look-ahead was impossible.",
                result["limits"],
                "",
                marketdata.ATTRIBUTION,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("generate", help="Generate new labelled synthetic cases")
    create.add_argument("--pack", choices=PACKS, default="mixed")
    create.add_argument("--cases", type=int, default=25)
    create.add_argument("--seed", type=int)
    create.add_argument("--output", type=Path, required=True)
    execute = sub.add_parser("run", help="Test your actual JSONL adapter")
    execute.add_argument("--dataset", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--limit", type=int, default=25)
    execute.add_argument("--timeout", type=float, default=10)
    execute.add_argument("--max-seconds", type=float, default=120)
    execute.add_argument("--max-requests", type=int, default=1000000)
    adapter = execute.add_mutually_exclusive_group(required=True)
    adapter.add_argument(
        "--baseline",
        action="store_true",
        help="Test the kit only, not a participant submission",
    )
    adapter.add_argument(
        "--adapter",
        nargs=argparse.REMAINDER,
        help="Command + arguments, placed last; no shell",
    )
    compare = sub.add_parser(
        "score", help="Score saved outputs against an exact answer key"
    )
    compare.add_argument("--dataset", type=Path, required=True)
    compare.add_argument("--predictions", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    custom = sub.add_parser(
        "import", help="Use your own project-specific JSONL inputs and expected answers"
    )
    custom.add_argument("--inputs", type=Path, required=True)
    custom.add_argument("--answers", type=Path, required=True)
    custom.add_argument("--output", type=Path, required=True)
    custom.add_argument(
        "--source", default="Participant-supplied cases; provenance must be reviewed"
    )
    custom.add_argument(
        "--seed", type=int, help="Record the seed used by your own generator"
    )
    custom.add_argument(
        "--synthetic",
        action="store_true",
        default=None,
        help="Declare authored synthetic provenance rather than leaving it unknown",
    )
    custom.add_argument(
        "--record-count",
        type=int,
        help="Explicit underlying record count when automatic list counting is unsuitable",
    )
    sealer = sub.add_parser("seal", help="Organisers: create a sealed master seed and print its commitment")
    sealer.add_argument("--output", type=Path, required=True)
    hidden = sub.add_parser(
        "challenge", help="Hidden, ungameable run: cases exist only in memory during the run"
    )
    hidden.add_argument("--pack", choices=PACKS + ("real-markets",), default="mixed")
    hidden.add_argument("--cases", type=int, default=60)
    hidden.add_argument("--output", type=Path, required=True)
    hidden.add_argument("--project", type=Path, help="Team project root for provenance (default: current folder)")
    hidden.add_argument("--team", default="", help="Team name; required with an organiser seed")
    seeds = hidden.add_mutually_exclusive_group()
    seeds.add_argument("--seed-file", type=Path, help="Organiser master seed file from `seal`")
    seeds.add_argument("--seed-prompt", action="store_true", help="Organiser types the master seed (hidden input)")
    hidden.add_argument("--timeout", type=float, default=10)
    hidden.add_argument("--max-seconds", type=float, default=900)
    hidden.add_argument("--max-requests", type=int, default=100000)
    hidden.add_argument("--adapter", nargs=argparse.REMAINDER, required=True)
    real = sub.add_parser("fetch", help="Practice dataset of anonymised real Binance price paths")
    real.add_argument("--cases", type=int, default=25)
    real.add_argument("--seed", type=int)
    real.add_argument("--output", type=Path, required=True)
    real.add_argument("--cache", type=Path, help="Optional folder to keep downloaded monthly archives")
    forward = sub.add_parser("live", help="Forward test a strategy on live Binance prices (look-ahead impossible)")
    forward.add_argument("--symbol", default="BTCUSDT", choices=marketdata.SYMBOLS)
    forward.add_argument("--interval", default="1m", choices=tuple(INTERVAL_SECONDS))
    forward.add_argument("--steps", type=int, default=30)
    forward.add_argument("--warmup", type=int, default=30)
    forward.add_argument("--timeout", type=float, default=5)
    forward.add_argument("--output", type=Path, required=True)
    forward.add_argument("--adapter", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "generate":
            result = generate(args.output, args.pack, args.cases, args.seed)
        elif args.operation == "seal":
            result = seal(args.output)
        elif args.operation == "challenge":
            if not args.adapter:
                raise ValueError("Give the team's adapter command after --adapter")
            result = challenge(
                args.output,
                args.adapter,
                args.pack,
                args.cases,
                read_master(args.seed_file, args.seed_prompt),
                args.team,
                args.project,
                args.timeout,
                args.max_seconds,
                args.max_requests,
            )
        elif args.operation == "fetch":
            result = fetch(args.output, args.cases, args.seed, args.cache)
        elif args.operation == "live":
            result = live(
                args.output, args.adapter, args.symbol, args.interval, args.steps,
                args.warmup, timeout=args.timeout,
            )
        elif args.operation == "import":
            inputs, answers = read_jsonl(args.inputs), read_jsonl(args.answers)
            indexed = {row.get("case_id"): row for row in inputs}
            for answer in answers:
                if answer.get("case_id") not in indexed:
                    raise ValueError("Answer case IDs must match inputs")
                answer["input_sha256"] = digest(indexed[answer["case_id"]])
            result = save_dataset(
                args.output,
                inputs,
                answers,
                args.source,
                args.seed,
                synthetic=args.synthetic,
                record_count=args.record_count,
            )
        elif args.operation == "score":
            result = score(args.dataset, args.predictions, args.output)
        else:
            command = (
                [sys.executable, str(Path(__file__).with_name("example_adapter.py"))]
                if args.baseline
                else args.adapter
            )
            result = run(
                args.dataset,
                args.output,
                command,
                args.limit,
                args.timeout,
                "KIT BASELINE ONLY: not the student's submission"
                if args.baseline
                else "Participant adapter",
                args.max_seconds,
                args.max_requests,
            )
        print(json.dumps(result, indent=2))
        if args.operation in {"run", "score", "challenge"} and (
            result["failed"] or result["errors"] or result["not_run"]
        ):
            return 1
        return 0
    except (ValueError, TypeError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(f"Cannot complete check: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
