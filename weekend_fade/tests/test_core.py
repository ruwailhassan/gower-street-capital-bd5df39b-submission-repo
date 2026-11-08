"""Tests for the pure calculations and the risk limits, including counterexamples."""
import math

import pytest

from weekend_fade.config import Config
from weekend_fade.risk import size_and_check
from weekend_fade.signals import impact_bp, log_return_bp, pair_pnl_bp, propose, vwap_fill, weekend_gap_bp


def test_log_return_is_additive_and_signed():
    assert log_return_bp(100, 101) == pytest.approx(1e4 * math.log(1.01))
    assert log_return_bp(100, 110) + log_return_bp(110, 121) == pytest.approx(log_return_bp(100, 121))
    with pytest.raises(ValueError):
        log_return_bp(0, 1)


def test_gap_is_stock_minus_market():
    # stock +2%, market +2%: no gap
    assert weekend_gap_bp(100, 102, 50, 51) == pytest.approx(0, abs=1e-9)
    # stock +3%, market +1%: about +197bp
    assert weekend_gap_bp(100, 103, 100, 101) == pytest.approx(1e4 * (math.log(1.03) - math.log(1.01)))


def test_big_name_fades_at_half_percent_small_name_does_not():
    p_big = propose("NVDA", 100, 100.6, 100, 100)     # +60bp vs market
    p_small = propose("RKLB", 100, 100.6, 100, 100)   # same gap, but small names need 150bp
    assert p_big.stock_side == -1 and "short stock" in p_big.action
    assert p_small.stock_side == 0 and p_small.action == "no trade"


def test_lagging_stock_is_bought_and_reason_shows_the_arithmetic():
    p = propose("AMD", 100, 97.0, 100, 100)           # -305bp vs market
    assert p.stock_side == 1 and p.action == "long stock / short index"
    assert "-305bp" in p.reason and "trigger 150bp" in p.reason


def test_huge_gap_goes_to_a_human_not_the_robot():
    p = propose("MU", 100, 112, 100, 100)             # +1133bp: probably real news
    assert p.action == "human review" and p.stock_side == 0


def test_stocks_without_sunday_reanchoring_are_skipped():
    p = propose("ZM", 100, 95, 100, 100)
    assert p.action == "no trade" and "Blue Ocean" in p.reason


def test_vwap_walks_the_book():
    levels = [(10.0, 100), (10.1, 1000)]               # $1,000 at 10.00, then $10,100 at 10.10
    px, usd = vwap_fill(levels, 2000)
    assert usd == pytest.approx(2000) and 10.0 < px < 10.1
    assert vwap_fill([], 100) is None


def test_impact_and_pair_pnl_signs():
    assert impact_bp(100, 100.1, +1) > 0 and impact_bp(100, 99.9, -1) > 0     # paying up costs money on both sides
    # short the stock, it falls 1% while the index is flat: about +100bp
    assert pair_pnl_bp(-1, 100, 99, 50, 50) == pytest.approx(-1e4 * math.log(0.99))
    # counterexample: the whole market falls 1% with the stock -> hedged pair makes ~0
    assert pair_pnl_bp(-1, 100, 99, 50, 49.5) == pytest.approx(0, abs=1e-9)


def _mk(sym, gap, sector="other"):
    p = propose(sym, 100, 100 * math.exp(gap / 1e4), 100, 100)
    p.sector = sector
    return p


def test_risk_vetoes_thin_stale_and_concentrated_trades():
    cfg = Config(max_same_sector_same_side=2)
    props = [_mk("AMD", -300, "semis"), _mk("MU", -250, "semis"), _mk("ARM", -200, "semis"), _mk("RKLB", -400), _mk("GME", 300)]
    market = {"AMD": {"hour_volume_usd": 1e6, "minutes_since_last_trade": 2, "book_impact_bp": 3},
              "MU": {"hour_volume_usd": 1e6, "minutes_since_last_trade": 2, "book_impact_bp": 3},
              "ARM": {"hour_volume_usd": 1e6, "minutes_since_last_trade": 2, "book_impact_bp": 3},     # third semis long -> vetoed
              "RKLB": {"hour_volume_usd": 1_000, "minutes_since_last_trade": 2, "book_impact_bp": 3},   # too thin
              "GME": {"hour_volume_usd": 1e6, "minutes_since_last_trade": 300, "book_impact_bp": 3}}    # stale price
    res = {r["proposal"]["symbol"]: r for r in size_and_check(props, market, cfg)}
    assert res["AMD"]["status"] == "approved" and res["MU"]["status"] == "approved"
    assert res["ARM"]["status"] == "vetoed" and "sector concentration" in res["ARM"]["vetoed_by"]
    assert res["RKLB"]["status"] == "vetoed" and "enough volume" in res["RKLB"]["vetoed_by"]
    assert res["GME"]["status"] == "vetoed" and "fresh price" in res["GME"]["vetoed_by"]


def test_size_is_capped_by_volume_and_by_name():
    p = _mk("NVDA", 80)
    r = size_and_check([p], {"NVDA": {"hour_volume_usd": 200_000, "minutes_since_last_trade": 1, "book_impact_bp": 1}})[0]
    assert r["size_usd"] == pytest.approx(20_000)          # 10% of $200k, below the $50k big-name cap
    r = size_and_check([p], {"NVDA": {"hour_volume_usd": 5e7, "minutes_since_last_trade": 1, "book_impact_bp": 1}})[0]
    assert r["size_usd"] == pytest.approx(50_000)


def test_gross_exposure_limit_holds():
    cfg = Config(max_gross_usd=30_000)
    props = [_mk(s, -300) for s in ("AAA", "BBB", "CCC")]
    mk = {s: {"hour_volume_usd": 1e6, "minutes_since_last_trade": 1, "book_impact_bp": 1} for s in ("AAA", "BBB", "CCC")}
    res = size_and_check(props, mk, cfg)
    assert sum(r["status"] == "approved" for r in res) == 1   # each pair uses $20k gross (stock + hedge)
