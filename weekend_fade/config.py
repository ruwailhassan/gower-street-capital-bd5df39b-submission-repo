"""Every number the agent uses, in one place. Changing a value here changes behaviour; nothing is hidden in code."""
from dataclasses import dataclass, field

# Hyperliquid HIP-3 deployer that lists US single-stock perps (trade[XYZ]) and its Nasdaq-100 index perp.
DEX = "xyz"
INDEX = "XYZ100"

# Big, heavily traded names: they drift less, so the trigger is smaller.
BIG = frozenset({"NVDA", "TSLA", "AAPL", "MSFT", "META", "AMZN", "GOOGL", "AVGO", "NFLX"})

# Names with no Blue Ocean overnight price: they stay on the internal price until Monday 09:30, so the
# Sunday-night re-anchoring the strategy relies on does not happen for them.
NO_BLUE_OCEAN = frozenset({"DKNG", "BX", "ZM", "EBAY", "BB", "ICE", "URNM", "BIRD", "NCLD", "BOT", "SHAZ"})

# Not single US stocks: indices, ETFs, FX, commodities, non-US listings, private companies.
NOT_US_STOCK = frozenset("""XYZ100 GOLD JPY EUR SILVER CL COPPER NATGAS URANIUM ALUMINIUM PLATINUM URNM PALLADIUM DXY KR200 JP225
EWY EWJ BRENTOIL VIX SP500 CORN XLE WHEAT TTF PURRDAT BIRD VOL DRAM EWZ KRW H100 NIFTY EWT GBP IBOV SMH NCLD SOXL MAGS XBI
TLT HO KORU MUU SNXX BOT SKHX SMSN SOFTBANK HYUNDAI KIOXIA IBIDEN GIGADEV CAMBRICON INNOLIGHT AMEC CATL RELIANCE JIO CXMT
YMTC UNITREE ZHIPU MINIMAX SHEIN ANT OURA SKHY KSTR SPCX CBRS""".split())

# Sectors whose stocks tend to move together; used by the concentration limit.
SECTOR = {
    **{k: "semis" for k in ("NVDA", "AMD", "AVGO", "TSM", "ASML", "QCOM", "MU", "INTC", "MRVL", "ARM", "LRCX", "AMAT", "SNDK",
                            "WDC", "STX", "UMC", "AAOI", "LITE", "DELL", "SMH")},
    **{k: "crypto-linked" for k in ("COIN", "MSTR", "HOOD", "CRCL", "BMNR", "IREN", "STRC")},
}


@dataclass(frozen=True)
class Config:
    # --- signal ---
    trigger_bp_big: int = 50          # fade a big name when its weekend move differs from the index by >= 0.50%
    trigger_bp_other: int = 150       # fade any other stock at >= 1.50%
    review_bp: int = 800              # a gap this large is probably real news (deal, crash): never auto-trade, human only
    # --- sizing (paper dollars) ---
    max_usd_big: int = 50_000
    max_usd_other: int = 10_000
    max_share_of_hour_volume: float = 0.10   # never more than 10% of what the stock traded in the last hour
    max_book_impact_bp: int = 25              # skip if filling the order would move the price more than this
    # --- portfolio limits ---
    max_trades: int = 15
    max_gross_usd: int = 250_000
    max_same_sector_same_side: int = 3       # e.g. no more than three 'long semis' bets on one night
    min_hour_volume_usd: int = 5_000         # too thin to trade below this
    max_minutes_since_last_trade: int = 90   # a stale price is not a signal
    # --- costs used in the backtest (bp) ---
    fee_bp_growth: float = 0.9
    fee_bp_standard: float = 9.0
    half_spread_bp_big: float = 1.0
    half_spread_bp_other: float = 5.0
    index_slippage_bp: float = 0.5
    # --- trade management (rule v2, chosen on the first half of weekends, confirmed on the second; see rule_research.py) ---
    hedge: str = "beta"                      # index notional = beta x stock notional (beta from the last 60 weekday closes)
    beta_floor: float = 0.3
    beta_cap: float = 3.0
    take_profit_frac: float = 0.5            # close once half of the entry gap has been recovered (checked hourly)
    # --- news check ---
    use_news_check: bool = True              # skip trades whose move weekend news explains (sentiment_agent.py)
    # --- schedule (US/Eastern) ---
    signal_time: str = "Sun 17:00"           # gap measured Friday 16:00 -> Sunday 17:00
    entry_time: str = "Sun 19:00"
    exit_time: str = "Mon 04:00"             # time stop for anything the take-profit has not closed
    require_human: bool = False              # fully automatic; risk limits, kill switch and logs still apply
    paper_only: bool = field(default=True)   # there is no order-placing code in this package; this flag documents it


DEFAULT = Config()
