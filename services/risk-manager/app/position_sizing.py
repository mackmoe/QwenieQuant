import math

_MAX_CONTRACTS = 100


def estimate_taker_fee_cents(price: int, rate: float = 0.07) -> int:
    """Conservative one-contract taker fee, rounded up to cents."""
    if not 1 <= price <= 99 or not 0 <= rate <= 1:
        raise ValueError("Invalid price or fee rate")
    p = price / 100
    return math.ceil(100 * rate * p * (1 - p) - 1e-9)


def calculate_max_price(probability: float, edge: float) -> int:
    """
    Maximum price (cents) to pay for a YES contract.

    We discount half the edge from the probability-implied price so we only
    enter when we genuinely have positive expected value at the execution price.
    """
    raw = probability * 100 - (edge * 100 * 0.5)
    return max(1, min(99, round(raw)))


def calculate_contracts(
    balance: int,
    max_price: int,
    max_position_percent: float,
    fee_cents: int = 0,
) -> int:
    """
    Number of contracts derivable from the bankroll allocation.

    balance             — available cash in cents
    max_price           — per-contract ceiling price in cents
    max_position_percent — fraction of balance allowed per trade (e.g. 5.0 = 5 %)
    """
    if balance <= 0 or max_price <= 0:
        return 0
    allowed_exposure = balance * max_position_percent / 100  # cents
    contracts = int(allowed_exposure / (max_price + max(0, fee_cents)))
    return max(0, min(contracts, _MAX_CONTRACTS))
