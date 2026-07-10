"""Tests for app/momentum.py — snapshot deltas and momentum factors."""

from app.config import Settings
from app.momentum import compute_momentum_factors


def _settings(**kwargs) -> Settings:
    defaults = dict(
        postgres_url="",
        volume_momentum_normalization=500.0,
        price_momentum_normalization=10.0,
        liquidity_momentum_normalization=500.0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _market(**kwargs) -> dict:
    d = dict(volume=1000, yes_bid=60, yes_ask=64, open_interest=2000)
    d.update(kwargs)
    return d


def _snapshot(**kwargs) -> dict:
    d = dict(volume=800, yes_bid=55, yes_ask=59, open_interest=1800, rank=10)
    d.update(kwargs)
    return d


def test_no_previous_snapshot_gives_zero_momentum():
    f = compute_momentum_factors(_market(), None, _settings())
    assert f["volume_momentum"] == 0.0
    assert f["price_momentum"] == 0.0
    assert f["liquidity_momentum"] == 0.0
    assert f["volume_delta"] is None
    assert f["price_delta"] is None


def test_volume_delta_computed():
    f = compute_momentum_factors(_market(volume=1000), _snapshot(volume=800), _settings())
    assert f["volume_delta"] == 200


def test_volume_delta_never_negative():
    # Kalshi volume is cumulative; a lower reading means a data glitch, not
    # negative trading — clamp to zero.
    f = compute_momentum_factors(_market(volume=700), _snapshot(volume=800), _settings())
    assert f["volume_delta"] == 0


def test_price_delta_from_mid_prices():
    # mid now = 62, mid prev = 57 → +5 cents
    f = compute_momentum_factors(_market(), _snapshot(), _settings())
    assert f["price_delta"] == 5.0


def test_price_delta_none_when_book_missing():
    f = compute_momentum_factors(
        _market(yes_bid=None), _snapshot(), _settings()
    )
    assert f["price_delta"] is None
    assert f["price_momentum"] == 0.0


def test_spread_delta_negative_when_tightening():
    # spread now = 64-60 = 4; prev = 59-55 = 4 → 0
    f = compute_momentum_factors(_market(), _snapshot(), _settings())
    assert f["spread_delta"] == 0
    # widen previous spread → tightening now
    f2 = compute_momentum_factors(_market(), _snapshot(yes_ask=65), _settings())
    assert f2["spread_delta"] == 4 - 10


def test_liquidity_delta_signed():
    f = compute_momentum_factors(
        _market(open_interest=1500), _snapshot(open_interest=1800), _settings()
    )
    assert f["liquidity_delta"] == -300


def test_volume_momentum_normalized_and_capped():
    f = compute_momentum_factors(
        _market(volume=10_000), _snapshot(volume=800), _settings()
    )
    assert f["volume_momentum"] == 1.0
    f2 = compute_momentum_factors(
        _market(volume=1050), _snapshot(volume=800), _settings()
    )
    assert f2["volume_momentum"] == 0.5


def test_price_momentum_uses_absolute_move():
    # falling price is still movement worth attention
    f = compute_momentum_factors(
        _market(yes_bid=50, yes_ask=54), _snapshot(), _settings()
    )
    assert f["price_delta"] == -5.0
    assert f["price_momentum"] == 0.5


def test_liquidity_momentum_ignores_outflow():
    f = compute_momentum_factors(
        _market(open_interest=1000), _snapshot(open_interest=1800), _settings()
    )
    assert f["liquidity_momentum"] == 0.0
