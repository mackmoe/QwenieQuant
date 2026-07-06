import pytest

from app.position_sizing import calculate_contracts, calculate_max_price


# ── calculate_max_price ─────────────────────────────────────────────────────


def test_max_price_typical():
    # probability=0.65, edge=0.10 → 65 - 5 = 60
    assert calculate_max_price(0.65, 0.10) == 60


def test_max_price_high_probability():
    # probability=0.90, edge=0.05 → 90 - 2.5 = 87.5 → 88
    assert calculate_max_price(0.90, 0.05) == 88


def test_max_price_low_probability():
    # probability=0.30, edge=0.05 → 30 - 2.5 = 27.5 → 28
    assert calculate_max_price(0.30, 0.05) == 28


def test_max_price_clamped_to_minimum_1():
    # Negative or near-zero result clamps to 1
    assert calculate_max_price(0.01, 0.10) >= 1


def test_max_price_clamped_to_maximum_99():
    # Even at probability=1.0, edge=0, should not exceed 99
    assert calculate_max_price(1.0, 0.0) <= 99


def test_max_price_zero_edge():
    # probability=0.55, edge=0 → 55 - 0 = 55
    assert calculate_max_price(0.55, 0.0) == 55


def test_max_price_always_integer():
    result = calculate_max_price(0.63, 0.07)
    assert isinstance(result, int)


def test_max_price_large_edge_clamps_to_1():
    # edge > probability → raw price < 0 → clamp to 1
    result = calculate_max_price(0.10, 0.30)
    assert result == 1


# ── calculate_contracts ─────────────────────────────────────────────────────


def test_calculate_contracts_typical():
    # balance=$1000 (100000 cents), 5%, price=55 → 100000*0.05/55 = 90.9 → 90
    result = calculate_contracts(100_000, 55, 5.0)
    assert result == 90


def test_calculate_contracts_zero_balance():
    assert calculate_contracts(0, 55, 5.0) == 0


def test_calculate_contracts_zero_price():
    assert calculate_contracts(100_000, 0, 5.0) == 0


def test_calculate_contracts_negative_balance():
    assert calculate_contracts(-1, 55, 5.0) == 0


def test_calculate_contracts_capped_at_100():
    # Very large balance would produce more than 100 — must be capped
    result = calculate_contracts(100_000_000, 1, 5.0)
    assert result == 100


def test_calculate_contracts_small_balance_returns_zero_or_one():
    # balance=100 cents ($1), 5%, price=55 → 100*0.05/55 = 0.09 → 0
    result = calculate_contracts(100, 55, 5.0)
    assert result == 0


def test_calculate_contracts_exact_allocation():
    # balance=11000, 5%, price=55 → 11000*0.05/55 = 10 exactly
    result = calculate_contracts(11_000, 55, 5.0)
    assert result == 10


def test_calculate_contracts_returns_integer():
    result = calculate_contracts(100_000, 55, 5.0)
    assert isinstance(result, int)
