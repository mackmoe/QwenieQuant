_MAX_CONTRACTS = 100


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
    contracts = int(allowed_exposure / max_price)
    return max(0, min(contracts, _MAX_CONTRACTS))
