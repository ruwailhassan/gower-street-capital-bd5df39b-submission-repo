"""Weekend-fade paper-trading agent (rule v2, fully automatic).

  python -m weekend_fade.agent scan       # Sun 17:00 ET: measure gaps, propose (deterministic), risk-check, news check
  python -m weekend_fade.agent enter      # Sun 19:00 ET: paper-fill trades against live books, beta-hedged
  python -m weekend_fade.agent monitor    # hourly 20:00-03:00 ET: take profit once half the gap has closed
  python -m weekend_fade.agent exit       # Mon 04:00 ET: close everything still open, report P&L after fees
  python -m weekend_fade.agent autopilot  # runs all of the above on schedule, unattended
  python -m weekend_fade.agent halt       # kill switch: blocks scans/entries; next hourly check (or 'exit') flattens
  python -m weekend_fade.agent status     # recent log lines

Who decides what:
  deterministic engine (signals.py, risk.py, config.py)  -> gap, trigger, side, size, beta, risk limits, exits
  news agent (news.py + sentiment_agent.py, Gemini)      -> only: "does weekend news explain this move?"
  fixed rule (sentiment_agent.decision)                   -> skip if news explains it with confidence >= 0.6
Every step appends to logs/<friday-date>/decisions.jsonl. PAPER ONLY: this package cannot place orders.
"""
from __future__ import annotations

import argparse, json, math, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import hyperliquid as hl
from .config import BIG, DEFAULT, DEX, INDEX, NOT_US_STOCK
from .news import NAMES, headlines, weekend_window
from .risk import size_and_check
from .sentiment_agent import decision as news_decision, judge_batch
from .signals import beta as calc_beta, impact_bp, pair_pnl_bp, propose, take_profit_hit, vwap_fill

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
HALT = LOGS / "HALT"
CFG = DEFAULT


def now_et() -> datetime:
    return datetime.now(ET)


def weekend_id(t: datetime) -> str:
    """The Friday that starts the weekend (Monday morning still belongs to the previous Friday)."""
    back = (t.weekday() - 4) % 7
    return (t - timedelta(days=back)).date().isoformat()


def wk_dir(wk: str) -> Path:
    d = LOGS / wk; d.mkdir(parents=True, exist_ok=True); return d


def log(wk: str, event: str, **data) -> None:
    with open(wk_dir(wk) / "decisions.jsonl", "a") as f:
        f.write(json.dumps({"time_et": now_et().isoformat(timespec="seconds"), "event": event, **data}, default=str) + "\n")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def friday_close(t: datetime) -> datetime:
    return (t - timedelta(days=(t.weekday() - 4) % 7)).replace(hour=16, minute=0, second=0, microsecond=0)


def close_before(coin: str, at: datetime) -> float | None:
    ms = int(at.timestamp() * 1000)
    c = [x for x in hl.candles(f"{DEX}:{coin}", "1h", ms - 6 * 3600_000, ms) if x["T"] < ms]
    return float(c[-1]["c"]) if c else None


def recent_activity(coin: str, now_ms: int) -> dict:
    c = hl.candles(f"{DEX}:{coin}", "5m", now_ms - 3 * 3600_000, now_ms)
    traded = [x for x in c if int(x["n"]) > 0]
    return {"hour_volume_usd": sum(float(x["v"]) * float(x["c"]) for x in c if x["t"] >= now_ms - 3600_000),
            "minutes_since_last_trade": (now_ms - traded[-1]["T"]) / 60_000 if traded else 1e9}


def daily_returns(coin: str, end: datetime, days: int = 100) -> dict:
    """Weekday 16:00 ET closes -> log returns keyed by date (for the beta)."""
    ms = int(end.timestamp() * 1000)
    c = hl.candles(f"{DEX}:{coin}", "1h", ms - days * 86400_000, ms)
    closes = {}
    for x in c:
        t = datetime.fromtimestamp(x["t"] / 1000, ET)
        if t.weekday() < 5 and t.hour == 15: closes[t.date()] = float(x["c"])
    ds = sorted(closes)
    return {d: math.log(closes[d] / closes[p]) for p, d in zip(ds, ds[1:])}


def _safe_headlines(sym, a, b):
    try: return headlines(sym, a, b)
    except Exception: return None


# ---------------------------------------------------------------- scan (deterministic engine + news check)
def cmd_scan(args) -> None:
    t = now_et(); wk = weekend_id(t); now_ms = int(time.time() * 1000); fri = friday_close(t)
    say(f"Weekend of {wk}. Gap = stock perp move minus Nasdaq-100 perp move since Friday 16:00 ET.\n")
    stocks = sorted(u["name"].split(":")[1] for u in hl.universe(DEX) if u["name"].split(":")[1] not in NOT_US_STOCK and not u.get("isDelisted"))
    if args.only: stocks = [s for s in stocks if s in args.only.split(",")]
    i_fri, i_now = close_before(INDEX, fri), hl.book(f"{DEX}:{INDEX}")["mid"]
    log(wk, "scan_start", rule="v2", config={k: getattr(CFG, k) for k in CFG.__dataclass_fields__}, index_fri_close=i_fri, index_now=i_now)
    proposals, market = [], {}
    for s in stocks:
        try:
            p_fri, act, bk = close_before(s, fri), recent_activity(s, now_ms), hl.book(f"{DEX}:{s}")
        except Exception as e:
            log(wk, "data_error", symbol=s, error=str(e)); continue
        if not p_fri or not bk["bids"] or not bk["asks"]: continue
        p = propose(s, p_fri, bk["mid"], i_fri, i_now, CFG)
        size_guess = min(CFG.max_usd_big if s in BIG else CFG.max_usd_other, CFG.max_share_of_hour_volume * act["hour_volume_usd"])
        fill = vwap_fill(bk["asks"] if p.stock_side > 0 else bk["bids"], size_guess) if p.stock_side else None
        market[s] = act | {"book_impact_bp": round(impact_bp(bk["mid"], fill[0], p.stock_side), 2) if fill else None}
        if p.stock_side and CFG.hedge == "beta":        # hedge ratio is needed before the risk check: gross exposure counts the hedge leg
            sr, ir = daily_returns(s, fri), daily_returns(INDEX, fri)
            common = sorted(set(sr) & set(ir))[-60:]
            market[s]["beta"] = calc_beta([sr[x] for x in common], [ir[x] for x in common], CFG.beta_floor, CFG.beta_cap)
        proposals.append(p); time.sleep(0.15)
    decisions = size_and_check(proposals, market, CFG)
    for d in decisions: log(wk, "engine_decision", **d)
    passed = [d for d in decisions if d["status"] == "approved"]
    say(f"{len(proposals)} stocks scanned; over trigger: {sum(d['proposal']['stock_side'] != 0 for d in decisions)}; "
        f"passed risk limits: {len(passed)}; vetoed: {sum(d['status'] == 'vetoed' for d in decisions)}; "
        f"too large, left alone: {sum(d['status'] == 'human review' for d in decisions)}\n")
    for d in decisions:
        if d["status"] == "vetoed":
            say(f"[VETOED ] {d['proposal']['symbol']:6s} gap {d['proposal']['gap_bp']:+6.0f}bp  by {', '.join(d['vetoed_by'])}")
    # news check: fetch every candidate's weekend headlines in parallel, then ONE model call for the weekend
    win_start, win_end = weekend_window(t)
    heads = {}
    if CFG.use_news_check and passed:
        from concurrent.futures import ThreadPoolExecutor
        syms = [d["proposal"]["symbol"] for d in passed]
        with ThreadPoolExecutor(6) as ex:
            for s_, h in zip(syms, ex.map(lambda x: _safe_headlines(x, win_start, win_end), syms)): heads[s_] = h
        items = [{"symbol": d["proposal"]["symbol"], "name": NAMES.get(d["proposal"]["symbol"], d["proposal"]["symbol"]),
                  "stock_move_bp": d["proposal"]["inputs"]["stock_move_bp"], "index_move_bp": d["proposal"]["inputs"]["index_move_bp"],
                  "gap_bp": d["proposal"]["gap_bp"], "headlines": heads[d["proposal"]["symbol"]] or []}
                 for d in passed if heads.get(d["proposal"]["symbol"])]
        answers, model = {}, None
        if items:
            try:
                j = judge_batch(items); answers, model = j["answers"], j["model"]
                log(wk, "news_model_call", model=model, symbols=[i["symbol"] for i in items], prompt=j["prompt"])
            except Exception as e:
                log(wk, "news_model_error", error=str(e))
    final = []
    for d in passed:
        p = d["proposal"]; s = p["symbol"]
        if CFG.use_news_check:
            h = heads.get(s)
            ans = answers.get(s) if h else None
            action, why = news_decision(ans, len(h)) if h is not None else ("skip", "news fetch failed: fail safe")
            log(wk, "news_check", symbol=s, action=action, why=why, headlines=h, answer=ans)
        else:
            action, why = "trade", "news check off"
        if action != "trade":
            say(f"[SKIPPED] {s:6s} gap {p['gap_bp']:+6.0f}bp  {why}"); continue
        b = market[s].get("beta", 1.0)
        d["beta"] = round(b, 3); d["news"] = why
        if CFG.require_human or args.human:
            ok = input(f"Approve PAPER trade {s} ({p['action']}, ${d['size_usd']:,.0f}, beta {b:.2f})? [y/N] ").strip().lower() == "y"
            log(wk, "human_decision", symbol=s, approved=ok)
            if not ok: continue
        final.append(d)
        say(f"[TRADE  ] {s:6s} gap {p['gap_bp']:+6.0f}bp  {p['action']:26s} ${d['size_usd']:>9,.0f}  hedge {b:.2f}x index  ({why})")
        say(f"          why: {p['reason']}")
    (wk_dir(wk) / "approved.json").write_text(json.dumps(final, indent=1, default=str))
    log(wk, "scan_done", trades=[d["proposal"]["symbol"] for d in final])
    say(f"\n{len(final)} trade(s) queued for entry at {CFG.entry_time} ET. Log: {wk_dir(wk) / 'decisions.jsonl'}")


# ---------------------------------------------------------------- paper fills
def _fill(coin: str, usd: float, buy: bool) -> dict:
    bk = hl.book(f"{DEX}:{coin}")
    f = vwap_fill(bk["asks"] if buy else bk["bids"], usd)
    return {"px": f[0] if f else None, "mid": bk["mid"], "filled_usd": f[1] if f else 0.0,
            "cost_bp": round(impact_bp(bk["mid"], f[0], 1 if buy else -1), 2) if f else None}


def cmd_enter(args) -> None:
    wk = weekend_id(now_et())
    if HALT.exists():
        log(wk, "entry_blocked", reason="kill switch"); say("Kill switch ON (logs/HALT). No new positions."); return
    queued = json.loads((wk_dir(wk) / "approved.json").read_text()) if (wk_dir(wk) / "approved.json").exists() else []
    positions = []
    for d in queued:
        p = d["proposal"]; side = p["stock_side"]; b = d.get("beta", 1.0)
        st = _fill(p["symbol"], d["size_usd"], buy=side > 0); ix = _fill(INDEX, b * d["size_usd"], buy=side < 0)
        pos = {"symbol": p["symbol"], "side": side, "usd": d["size_usd"], "beta": b, "entry_gap_bp": p["gap_bp"],
               "entry": {"stock": st, "index": ix, "time": now_et().isoformat()}, "status": "open"}
        positions.append(pos); log(wk, "paper_entry", **pos)
        say(f"PAPER ENTRY {p['symbol']:6s} {'LONG' if side > 0 else 'SHORT'} ${d['size_usd']:,.0f} @ {st['px']} (vs mid {st['cost_bp']}bp); index {'SHORT' if side > 0 else 'LONG'} ${b * d['size_usd']:,.0f} @ {ix['px']}")
    (wk_dir(wk) / "positions.json").write_text(json.dumps(positions, indent=1, default=str))


def _close(wk: str, pos: dict, reason: str) -> dict:
    side, b = pos["side"], pos["beta"]
    st = _fill(pos["symbol"], pos["usd"], buy=side < 0); ix = _fill(INDEX, b * pos["usd"], buy=side > 0)
    e = pos["entry"]
    gross = pair_pnl_bp(side, e["stock"]["px"], st["px"], e["index"]["px"], ix["px"], hedge_ratio=b)
    fees = 2 * CFG.fee_bp_growth + 2 * b * CFG.fee_bp_growth
    net = gross - fees; usd = pos["usd"] * net / 1e4
    pos.update(status="closed", exit={"stock": st, "index": ix, "time": now_et().isoformat(), "reason": reason}, gross_bp=round(gross, 2), net_bp=round(net, 2), pnl_usd=round(usd, 2))
    log(wk, "paper_exit", **pos)
    say(f"PAPER EXIT  {pos['symbol']:6s} ({reason}) net {net:+.1f}bp  ${usd:+,.2f}")
    return pos


def cmd_monitor(args) -> None:
    """Hourly: a take-profit seen on the previous check is executed now (one-hour delay, as in the backtest)."""
    wk = weekend_id(now_et()); path = wk_dir(wk) / "positions.json"
    if not path.exists(): return
    positions = json.loads(path.read_text())
    if HALT.exists():                                   # kill switch: flatten everything at this check
        for pos in positions:
            if pos["status"] == "open": _close(wk, pos, "kill switch")
        path.write_text(json.dumps(positions, indent=1, default=str)); return
    ix_mid = hl.book(f"{DEX}:{INDEX}")["mid"]
    for pos in positions:
        if pos["status"] != "open": continue
        if pos.get("tp_seen"):
            _close(wk, pos, "take profit"); continue
        mid = hl.book(f"{DEX}:{pos['symbol']}")["mid"]
        pnl = pair_pnl_bp(pos["side"], pos["entry"]["stock"]["mid"], mid, pos["entry"]["index"]["mid"], ix_mid, hedge_ratio=pos["beta"])
        if take_profit_hit(pnl, pos["entry_gap_bp"], CFG.take_profit_frac):
            pos["tp_seen"] = now_et().isoformat()
        log(wk, "monitor", symbol=pos["symbol"], pnl_bp=round(pnl, 1), target_bp=round(CFG.take_profit_frac * abs(pos["entry_gap_bp"]), 1), take_profit_seen=bool(pos.get("tp_seen")))
    path.write_text(json.dumps(positions, indent=1, default=str))


def cmd_exit(args) -> None:
    t = now_et(); wk = weekend_id(t); path = wk_dir(wk) / "positions.json"
    positions = json.loads(path.read_text()) if path.exists() else []
    for pos in positions:
        if pos["status"] == "open": _close(wk, pos, "kill switch" if HALT.exists() else "time stop")
    closed = [p for p in positions if p["status"] == "closed"]
    total = sum(p["pnl_usd"] for p in closed)
    log(wk, "weekend_result", trades=len(closed), pnl_usd=round(total, 2), rows=[{k: p[k] for k in ("symbol", "net_bp", "pnl_usd")} for p in closed])
    path.write_text(json.dumps(positions, indent=1, default=str))
    say(f"\nWeekend {wk}: {len(closed)} paper trades, total ${total:+,.2f} after fees.")


def cmd_autopilot(args) -> None:
    def wait_until(dt: datetime) -> None:
        while now_et() < dt: time.sleep(min(60, max(1, (dt - now_et()).total_seconds())))
    t = now_et(); sun = (t + timedelta(days=(6 - t.weekday()) % 7)).replace(second=0, microsecond=0)
    mon = sun + timedelta(days=1)
    plan = [(sun.replace(hour=17, minute=0), "scan"), (sun.replace(hour=19, minute=0), "enter")]
    plan += [((sun if h >= 20 else mon).replace(hour=h, minute=0), "monitor") for h in (20, 21, 22, 23, 0, 1, 2, 3)]
    plan += [(mon.replace(hour=4, minute=0), "exit")]
    say("Autopilot (ET): " + ", ".join(f"{lab} {dt:%a %H:%M}" for dt, lab in plan))
    log(weekend_id(t), "autopilot_start", plan=[(dt.isoformat(), lab) for dt, lab in plan])
    run = {"scan": lambda: cmd_scan(argparse.Namespace(only=None, human=False)), "enter": lambda: cmd_enter(args),
           "monitor": lambda: cmd_monitor(args), "exit": lambda: cmd_exit(args)}
    for dt, lab in plan:
        if dt < now_et() - timedelta(minutes=30): continue
        wait_until(dt)
        if HALT.exists() and lab in ("scan", "enter"):
            say(f"Kill switch ON: skipping {lab}."); log(weekend_id(now_et()), "skipped_by_kill_switch", step=lab); continue
        say(f"\n=== {lab} at {now_et():%a %H:%M} ET ===")
        try: run[lab]()
        except Exception as e: log(weekend_id(now_et()), "step_error", step=lab, error=str(e)); say(f"{lab} failed: {e}")


def cmd_halt(args) -> None:
    LOGS.mkdir(exist_ok=True)
    if args.off: HALT.unlink(missing_ok=True); log(weekend_id(now_et()), "kill_switch", state="off"); say("Kill switch OFF.")
    else: HALT.write_text(now_et().isoformat()); log(weekend_id(now_et()), "kill_switch", state="on"); say("Kill switch ON: no new scans or entries; open positions close at the next hourly check (or now with 'exit').")


def cmd_status(args) -> None:
    f = wk_dir(weekend_id(now_et())) / "decisions.jsonl"
    say(f"Kill switch: {'ON' if HALT.exists() else 'off'}. Log: {f}")
    if f.exists():
        for line in f.read_text().splitlines()[-args.n:]:
            r = json.loads(line); sym = r.get("symbol") or r.get("proposal", {}).get("symbol", "")
            say(f"{r['time_et']}  {r['event']:16s} {sym:6s} {r.get('status') or r.get('action') or ''}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--only", help="comma-separated symbols"); s.add_argument("--human", action="store_true", help="ask before each trade")
    for c in ("enter", "monitor", "exit", "autopilot"): sub.add_parser(c)
    h = sub.add_parser("halt"); h.add_argument("--off", action="store_true")
    st = sub.add_parser("status"); st.add_argument("-n", type=int, default=30)
    a = ap.parse_args(argv)
    {"scan": cmd_scan, "enter": cmd_enter, "monitor": cmd_monitor, "exit": cmd_exit, "autopilot": cmd_autopilot,
     "halt": cmd_halt, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
