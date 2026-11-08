"""Pure calculation functions. No network, no model, no randomness: each output can be recomputed by hand from its inputs."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from .config import BIG, Config, DEFAULT, NO_BLUE_OCEAN, SECTOR


def log_return_bp(p0: float, p1: float) -> float:
    """Price change in basis points (1bp = 0.01%), as a log return so moves add up across legs."""
    if p0 <= 0 or p1 <= 0:
        raise ValueError("prices must be positive")
    return 1e4 * math.log(p1 / p0)


def weekend_gap_bp(stock_fri: float, stock_now: float, index_fri: float, index_now: float) -> float:
    """How far the stock moved *more than the market* since Friday's close. Positive = stock ran ahead."""
    return log_return_bp(stock_fri, stock_now) - log_return_bp(index_fri, index_now)


def trigger_bp(symbol: str, cfg: Config = DEFAULT) -> int:
    return cfg.trigger_bp_big if symbol in BIG else cfg.trigger_bp_other


@dataclass
class Proposal:
    symbol: str
    gap_bp: float
    trigger_bp: int
    action: str            # "short stock / long index", "long stock / short index", "no trade", "human review"
    stock_side: int        # -1 short, +1 long, 0 none
    sector: str
    reason: str
    inputs: dict

    def to_dict(self) -> dict:
        return asdict(self)


def propose(symbol: str, stock_fri: float, stock_now: float, index_fri: float, index_now: float, cfg: Config = DEFAULT) -> Proposal:
    """Turn four prices into a decision, with the arithmetic written into the reason."""
    gap = weekend_gap_bp(stock_fri, stock_now, index_fri, index_now)
    trig = trigger_bp(symbol, cfg)
    s_move, i_move = log_return_bp(stock_fri, stock_now), log_return_bp(index_fri, index_now)
    inputs = {"stock_fri_close": stock_fri, "stock_now": stock_now, "index_fri_close": index_fri, "index_now": index_now,
              "stock_move_bp": round(s_move, 1), "index_move_bp": round(i_move, 1)}
    sector = SECTOR.get(symbol, "other")
    base = (f"{symbol} moved {s_move:+.0f}bp since Friday's close, the Nasdaq-100 perp {i_move:+.0f}bp, "
            f"so {symbol} is {gap:+.0f}bp {'ahead of' if gap > 0 else 'behind'} the market (trigger {trig}bp).")
    if symbol in NO_BLUE_OCEAN:
        return Proposal(symbol, gap, trig, "no trade", 0, sector, base + " No Blue Ocean price on Sunday night, so nothing pulls it back.", inputs)
    if abs(gap) < trig:
        return Proposal(symbol, gap, trig, "no trade", 0, sector, base + " Below trigger.", inputs)
    if abs(gap) >= cfg.review_bp:
        return Proposal(symbol, gap, trig, "human review", 0, sector,
                        base + f" Gap over {cfg.review_bp}bp: likely real news (deal, guidance, crash). Not auto-traded.", inputs)
    side = -1 if gap > 0 else 1
    action = "short stock / long index" if side < 0 else "long stock / short index"
    return Proposal(symbol, gap, trig, action, side, sector,
                    base + f" Bet that part of the gap closes when real prices return at 20:05 ET: {action}.", inputs)


def vwap_fill(levels: list[tuple[float, float]], usd: float) -> tuple[float, float] | None:
    """Average price for buying/selling `usd` of notional by walking order-book levels [(price, size), ...] best first.
    Returns (avg_price, filled_usd) or None if the book is empty."""
    if not levels or usd <= 0:
        return None
    left, cost, qty = usd, 0.0, 0.0
    for px, sz in levels:
        take = min(left, px * sz)
        cost += take; qty += take / px; left -= take
        if left <= 1e-9:
            break
    return (cost / qty, cost) if qty > 0 else None


def impact_bp(mid: float, avg_px: float, side: int) -> float:
    """Cost of a fill versus the mid price, in bp (positive = worse than mid)."""
    return side * log_return_bp(mid, avg_px)


def pair_pnl_bp(stock_side: int, stock_entry: float, stock_exit: float, index_entry: float, index_exit: float, hedge_ratio: float = 1.0) -> float:
    """P&L of a hedged pair per $ of stock notional: stock leg plus the opposite index leg (hedge_ratio x the dollars)."""
    return stock_side * log_return_bp(stock_entry, stock_exit) - stock_side * hedge_ratio * log_return_bp(index_entry, index_exit)


def beta(stock_returns: list[float], index_returns: list[float], floor: float = 0.3, cap: float = 3.0) -> float:
    """Sensitivity of the stock to the index from paired past returns, clipped to [floor, cap]. 1.0 if too little data."""
    pairs = [(s, i) for s, i in zip(stock_returns, index_returns) if s == s and i == i]
    if len(pairs) < 20: return 1.0
    ms = sum(s for s, _ in pairs) / len(pairs); mi = sum(i for _, i in pairs) / len(pairs)
    cov = sum((s - ms) * (i - mi) for s, i in pairs); var = sum((i - mi) ** 2 for _, i in pairs)
    return max(floor, min(cap, cov / var)) if var > 0 else 1.0


def take_profit_hit(pnl_bp: float, entry_gap_bp: float, frac: float = 0.5) -> bool:
    """True once the trade has recovered at least `frac` of the gap it was opened on."""
    return pnl_bp >= frac * abs(entry_gap_bp)
