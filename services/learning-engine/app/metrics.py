"""
Pure metric computation functions.

All functions take a list of prediction dicts and return a scalar or mapping.
No side effects, no I/O. Each function has exactly one job.
"""

from typing import Optional


def compute_accuracy(predictions: list[dict]) -> Optional[float]:
    with_outcomes = [p for p in predictions if p.get("outcome") is not None]
    if not with_outcomes:
        return None
    correct = sum(
        1 for p in with_outcomes if p["prediction"] == p["outcome"]
    )
    return correct / len(with_outcomes)


def compute_average_confidence(predictions: list[dict]) -> Optional[float]:
    if not predictions:
        return None
    return sum(p["confidence"] for p in predictions) / len(predictions)


def compute_average_execution_ms(predictions: list[dict]) -> Optional[float]:
    if not predictions:
        return None
    return sum(p["execution_ms"] for p in predictions) / len(predictions)


def compute_model_breakdown(predictions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in predictions:
        counts[p["model"]] = counts.get(p["model"], 0) + 1
    return counts


def compute_category_breakdown(predictions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in predictions:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    return counts
