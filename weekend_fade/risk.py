"""Risk limits enforced in code. Every proposal comes out approved or vetoed with the rule that decided it."""
from __future__ import annotations

from .config import BIG, Config, DEFAULT
from .signals import Proposal


def size_and_check(proposals: list[Proposal], market: dict[str, dict], cfg: Config = DEFAULT) -> list[dict]:
    """market[symbol] = {"hour_volume_usd": float, "minutes_since_last_trade": float, "book_impact_bp": float|None}
    Returns one record per proposal with 'status' (approved/vetoed/no trade/human review), 'size_usd' and 'checks'."""
    out, gross, by_sector = [], 0.0, {}
    # strongest signals first, so limits cut the weakest
    ranked = sorted(proposals, key=lambda p: -abs(p.gap_bp) / p.trigger_bp)
    for p in ranked:
        rec = {"proposal": p.to_dict(), "status": p.action if p.stock_side == 0 else "pending", "size_usd": 0, "checks": []}
        if p.stock_side == 0:
            out.append(rec); continue
        m = market.get(p.symbol, {})
        vol, stale, imp = m.get("hour_volume_usd", 0.0), m.get("minutes_since_last_trade", 1e9), m.get("book_impact_bp")
        cap = cfg.max_usd_big if p.symbol in BIG else cfg.max_usd_other
        size = min(cap, cfg.max_share_of_hour_volume * vol)
        checks = [
            ("enough volume", vol >= cfg.min_hour_volume_usd, f"last-hour volume ${vol:,.0f} vs minimum ${cfg.min_hour_volume_usd:,}"),
            ("fresh price", stale <= cfg.max_minutes_since_last_trade, f"last trade {stale:.0f} min ago vs limit {cfg.max_minutes_since_last_trade}"),
            ("book can absorb it", imp is None or imp <= cfg.max_book_impact_bp, f"estimated impact {imp if imp is not None else 'n/a'}bp vs limit {cfg.max_book_impact_bp}bp"),
            ("trade count", sum(r["status"] == "approved" for r in out) < cfg.max_trades, f"limit {cfg.max_trades} trades"),
            ("gross exposure", gross + 2 * size <= cfg.max_gross_usd, f"would take gross to ${gross + 2 * size:,.0f} vs limit ${cfg.max_gross_usd:,}"),
            ("sector concentration", by_sector.get((p.sector, p.stock_side), 0) < cfg.max_same_sector_same_side or p.sector == "other",
             f"{by_sector.get((p.sector, p.stock_side), 0)} '{p.sector}' trades on this side already, limit {cfg.max_same_sector_same_side}"),
        ]
        rec["checks"] = [{"rule": r, "passed": bool(ok), "detail": d} for r, ok, d in checks]
        if all(ok for _, ok, _ in checks) and size > 0:
            rec["status"], rec["size_usd"] = "approved", round(size, 2)
            gross += 2 * size
            by_sector[(p.sector, p.stock_side)] = by_sector.get((p.sector, p.stock_side), 0) + 1
        else:
            rec["status"] = "vetoed"
            rec["vetoed_by"] = [c["rule"] for c in rec["checks"] if not c["passed"]] or ["zero size"]
        out.append(rec)
    return out
