"""Weekend-fade paper-trading agent.

  python -m weekend_fade.agent scan     # Sunday 17:00 ET: measure weekend gaps, propose trades, run risk checks, ask a human
  python -m weekend_fade.agent enter    # Sunday 18:00 ET: paper-fill approved trades against the live order book
  python -m weekend_fade.agent exit     # Monday 04:00 ET: paper-close everything, report P&L after fees
  python -m weekend_fade.agent halt     # kill switch: blocks new entries and makes 'exit' close everything now
  python -m weekend_fade.agent status   # what is open, what was decided, and why

Every step appends to logs/<weekend>/decisions.jsonl. PAPER ONLY: this package cannot place orders.
"""
from __future__ import annotations

import argparse, json, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import hyperliquid as hl
from .config import BIG, DEFAULT, DEX, INDEX, NOT_US_STOCK
from .risk import size_and_check
from .signals import impact_bp, pair_pnl_bp, propose, vwap_fill

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
HALT = LOGS / "HALT"


def now_et() -> datetime:
    return datetime.now(ET)


def weekend_id(t: datetime) -> str:
    fri = (t - timedelta(days=(t.weekday() - 4) % 7)).date()
    return fri.isoformat()


def log(wk: str, event: str, **data) -> None:
    d = LOGS / wk; d.mkdir(parents=True, exist_ok=True)
    rec = {"time_et": now_et().isoformat(timespec="seconds"), "event": event, **data}
    with open(d / "decisions.jsonl", "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def friday_close_ms(t: datetime) -> int:
    fri = (t - timedelta(days=(t.weekday() - 4) % 7)).replace(hour=16, minute=0, second=0, microsecond=0)
    return int(fri.timestamp() * 1000)


def price_at(coin: str, at_ms: int) -> float | None:
    """Close of the last 1h candle that ended at or before at_ms (the Friday-close price)."""
    c = hl.candles(f"{DEX}:{coin}", "1h", at_ms - 6 * 3600_000, at_ms)
    done = [x for x in c if x["T"] < at_ms]
    return float(done[-1]["c"]) if done else None


def recent_activity(coin: str, now_ms: int) -> dict:
    c = hl.candles(f"{DEX}:{coin}", "5m", now_ms - 3 * 3600_000, now_ms)
    last_hour = [x for x in c if x["t"] >= now_ms - 3600_000]
    traded = [x for x in c if int(x["n"]) > 0]
    return {"hour_volume_usd": sum(float(x["v"]) * float(x["c"]) for x in last_hour),
            "minutes_since_last_trade": (now_ms - traded[-1]["T"]) / 60_000 if traded else 1e9,
            "last_price": float(c[-1]["c"]) if c else None}


def cmd_scan(args) -> None:
    t = now_et(); wk = weekend_id(t); now_ms = int(time.time() * 1000); fri_ms = friday_close_ms(t)
    say(f"Weekend of {wk}. Measuring each stock perp against the Nasdaq-100 perp since Friday 16:00 ET.\n")
    stocks = sorted(u["name"].split(":")[1] for u in hl.universe(DEX) if u["name"].split(":")[1] not in NOT_US_STOCK and not u.get("isDelisted"))
    if args.only:
        stocks = [s for s in stocks if s in args.only.split(",")]
    i_fri, i_now = price_at(INDEX, fri_ms), hl.book(f"{DEX}:{INDEX}")["mid"]
    log(wk, "scan_start", index_fri_close=i_fri, index_now=i_now, universe=stocks)
    proposals, market = [], {}
    for s in stocks:
        try:
            fri = price_at(s, fri_ms); act = recent_activity(s, now_ms); bk = hl.book(f"{DEX}:{s}")
        except Exception as e:  # one bad symbol must not stop the scan
            log(wk, "data_error", symbol=s, error=str(e)); continue
        if not fri or not bk["bids"] or not bk["asks"]:
            continue
        p = propose(s, fri, bk["mid"], i_fri, i_now)
        size_guess = min(DEFAULT.max_usd_big if s in BIG else DEFAULT.max_usd_other, 0.1 * act["hour_volume_usd"])
        fill = vwap_fill(bk["asks"] if p.stock_side > 0 else bk["bids"], size_guess) if p.stock_side else None
        market[s] = act | {"book_impact_bp": round(impact_bp(bk["mid"], fill[0], p.stock_side), 2) if fill else None}
        proposals.append(p); time.sleep(0.15)
    decisions = size_and_check(proposals, market)
    for d in decisions:
        log(wk, "decision", **d)
    trades = [d for d in decisions if d["status"] == "approved"]
    say(f"{len(proposals)} stocks scanned. Candidates over trigger: {sum(d['proposal']['stock_side'] != 0 for d in decisions)}; "
        f"passed risk checks: {len(trades)}; vetoed: {sum(d['status'] == 'vetoed' for d in decisions)}; "
        f"sent to human review (gap too big): {sum(d['status'] == 'human review' for d in decisions)}\n")
    for d in decisions:
        if d["status"] in ("approved", "vetoed", "human review"):
            p = d["proposal"]
            say(f"[{d['status'].upper():12s}] {p['symbol']:6s} gap {p['gap_bp']:+6.0f}bp  {p['action']:26s} size ${d['size_usd']:>9,.0f}")
            say(f"               why: {p['reason']}")
            for c in d["checks"]:
                if not c["passed"]:
                    say(f"               blocked by '{c['rule']}': {c['detail']}")
    approved = []
    for d in trades:
        p = d["proposal"]
        if args.yes:
            ok = True
        else:
            ok = input(f"\nApprove PAPER trade {p['symbol']} ({p['action']}, ${d['size_usd']:,.0f})? [y/N] ").strip().lower() == "y"
        log(wk, "human_decision", symbol=p["symbol"], approved=ok, by="--yes flag" if args.yes else "operator prompt")
        if ok:
            approved.append(d)
    (LOGS / wk).mkdir(parents=True, exist_ok=True)
    (LOGS / wk / "approved.json").write_text(json.dumps(approved, indent=1, default=str))
    say(f"\n{len(approved)} trade(s) approved by the human and saved for entry at 18:00 ET. Log: {LOGS / wk / 'decisions.jsonl'}")


def _fill_pair(sym: str, side: int, usd: float, opening: bool) -> dict:
    """Paper fill: walk the live book for the stock and the index (opposite side, same dollars)."""
    sb, ib = hl.book(f"{DEX}:{sym}"), hl.book(f"{DEX}:{INDEX}")
    trade_side = side if opening else -side           # +1 buy, -1 sell
    s = vwap_fill(sb["asks"] if trade_side > 0 else sb["bids"], usd)
    i = vwap_fill(ib["bids"] if trade_side > 0 else ib["asks"], usd)
    return {"stock_px": s[0] if s else None, "stock_mid": sb["mid"], "stock_filled_usd": s[1] if s else 0,
            "index_px": i[0] if i else None, "index_mid": ib["mid"],
            "stock_cost_bp": round(impact_bp(sb["mid"], s[0], trade_side), 2) if s else None}


def cmd_enter(args) -> None:
    t = now_et(); wk = weekend_id(t)
    if HALT.exists():
        log(wk, "entry_blocked", reason="kill switch is on"); say("Kill switch is ON (logs/HALT). No new positions."); return
    path = LOGS / wk / "approved.json"
    approved = json.loads(path.read_text()) if path.exists() else []
    positions = []
    for d in approved:
        p = d["proposal"]
        f = _fill_pair(p["symbol"], p["stock_side"], d["size_usd"], opening=True)
        pos = {"symbol": p["symbol"], "side": p["stock_side"], "usd": d["size_usd"], "entry": f, "entry_time": t.isoformat()}
        positions.append(pos); log(wk, "paper_entry", **pos)
        say(f"PAPER ENTRY {p['symbol']:6s} {'LONG' if p['stock_side'] > 0 else 'SHORT'} ${d['size_usd']:,.0f} at {f['stock_px']} (cost vs mid {f['stock_cost_bp']}bp), index hedge at {f['index_px']}")
    (LOGS / wk / "positions.json").write_text(json.dumps(positions, indent=1, default=str))


def cmd_exit(args) -> None:
    t = now_et(); wk = weekend_id(t - timedelta(days=1) if t.weekday() == 0 else t)
    path = LOGS / wk / "positions.json"
    positions = json.loads(path.read_text()) if path.exists() else []
    total_usd, rows = 0.0, []
    for pos in positions:
        f = _fill_pair(pos["symbol"], pos["side"], pos["usd"], opening=False)
        e = pos["entry"]
        gross = pair_pnl_bp(pos["side"], e["stock_px"], f["stock_px"], e["index_px"], f["index_px"])
        fees = 4 * DEFAULT.fee_bp_growth
        net = gross - fees
        usd = pos["usd"] * net / 1e4; total_usd += usd
        rows.append({"symbol": pos["symbol"], "net_bp": round(net, 1), "pnl_usd": round(usd, 2)})
        log(wk, "paper_exit", symbol=pos["symbol"], exit=f, gross_bp=round(gross, 2), fees_bp=fees, net_bp=round(net, 2), pnl_usd=round(usd, 2),
            reason="kill switch" if HALT.exists() else "scheduled exit")
        say(f"PAPER EXIT  {pos['symbol']:6s} net {net:+.1f}bp  ${usd:+,.2f}")
    log(wk, "weekend_result", trades=len(rows), pnl_usd=round(total_usd, 2), rows=rows)
    say(f"\nWeekend {wk}: {len(rows)} paper trades, total ${total_usd:+,.2f} after fees.")
    if rows:
        path.rename(path.with_suffix(".closed.json"))


def cmd_halt(args) -> None:
    LOGS.mkdir(exist_ok=True)
    if args.off:
        HALT.unlink(missing_ok=True); log(weekend_id(now_et()), "kill_switch", state="off"); say("Kill switch OFF.")
    else:
        HALT.write_text(now_et().isoformat()); log(weekend_id(now_et()), "kill_switch", state="on")
        say("Kill switch ON: no new entries; run 'exit' to flatten everything now.")


def cmd_status(args) -> None:
    wk = weekend_id(now_et()); f = LOGS / wk / "decisions.jsonl"
    say(f"Kill switch: {'ON' if HALT.exists() else 'off'}. Log: {f}")
    if f.exists():
        for line in f.read_text().splitlines()[-args.n:]:
            r = json.loads(line); say(f"{r['time_et']}  {r['event']}  {r.get('symbol') or r.get('proposal', {}).get('symbol', '')}  {r.get('status', '')}")


def cmd_autopilot(args) -> None:
    """Unattended paper run for one weekend: scan at Sun 17:00, enter 18:00, exit Mon 04:00 (ET).
    Trades still pass every risk check; approval is recorded as 'autopilot' and the kill switch still works."""
    def wait_until(dt: datetime, label: str):
        while now_et() < dt:
            if HALT.exists() and label != "exit":
                say(f"Kill switch ON: skipping {label}."); return False
            time.sleep(min(60, max(1, (dt - now_et()).total_seconds())))
        return True
    t = now_et(); sun = (t + timedelta(days=(6 - t.weekday()) % 7)).replace(second=0, microsecond=0)
    plan = [(sun.replace(hour=17, minute=0), "scan"), (sun.replace(hour=18, minute=0), "enter"),
            ((sun + timedelta(days=1)).replace(hour=4, minute=0), "exit")]
    say("Autopilot plan (ET): " + ", ".join(f"{lab} at {dt:%a %H:%M}" for dt, lab in plan))
    log(weekend_id(t), "autopilot_start", plan=[(dt.isoformat(), lab) for dt, lab in plan])
    for dt, lab in plan:
        if dt < now_et() - timedelta(minutes=30):
            continue
        if wait_until(dt, lab):
            say(f"\n=== {lab} at {now_et():%a %H:%M} ET ===")
            {"scan": lambda: cmd_scan(argparse.Namespace(yes=True, only=None)), "enter": lambda: cmd_enter(args), "exit": lambda: cmd_exit(args)}[lab]()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--yes", action="store_true", help="approve every trade that passes risk checks (unattended demo)")
    s.add_argument("--only", help="comma-separated symbols, for a quick demo")
    sub.add_parser("enter"); sub.add_parser("exit"); sub.add_parser("autopilot")
    h = sub.add_parser("halt"); h.add_argument("--off", action="store_true")
    st = sub.add_parser("status"); st.add_argument("-n", type=int, default=30)
    a = ap.parse_args(argv)
    {"scan": cmd_scan, "enter": cmd_enter, "exit": cmd_exit, "halt": cmd_halt, "status": cmd_status, "autopilot": cmd_autopilot}[a.cmd](a)


if __name__ == "__main__":
    main()
