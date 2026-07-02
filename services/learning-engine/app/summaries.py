"""
Builds human-readable observations from computed metrics.

All observations describe measurable patterns. No speculative conclusions.
"""

from typing import Optional


def build_observations(
    predictions: list[dict],
    accuracy: Optional[float],
    avg_confidence: Optional[float],
    avg_execution_ms: Optional[float],
    model_breakdown: dict[str, int],
    category_breakdown: dict[str, int],
) -> list[str]:
    n = len(predictions)
    if n == 0:
        return ["No prediction history available for analysis."]

    obs: list[str] = []
    outcomes_available = sum(
        1 for p in predictions if p.get("outcome") is not None
    )

    obs.append(f"{n} prediction(s) analyzed.")

    if accuracy is not None:
        obs.append(
            f"Accuracy is {round(accuracy * 100, 1)}% across "
            f"{outcomes_available} resolved prediction(s)."
        )
    else:
        obs.append(
            f"No resolved outcomes recorded; accuracy cannot be calculated "
            f"from {n} prediction(s)."
        )

    if avg_confidence is not None:
        high_conf_n = sum(1 for p in predictions if p["confidence"] >= 0.70)
        obs.append(
            f"Average model confidence is {round(avg_confidence, 2)}; "
            f"{high_conf_n} of {n} predictions "
            f"({round(high_conf_n / n * 100, 1)}%) have confidence >= 0.70."
        )

    if avg_execution_ms is not None:
        obs.append(
            f"Average inference time is "
            f"{round(avg_execution_ms / 1000, 1)}s per prediction."
        )

    if len(model_breakdown) == 1:
        obs.append(
            f"All predictions used model '{next(iter(model_breakdown))}'."
        )
    elif model_breakdown:
        most_used = max(model_breakdown, key=model_breakdown.__getitem__)
        obs.append(
            f"{len(model_breakdown)} models in use; '{most_used}' accounted "
            f"for {model_breakdown[most_used]} of {n} predictions."
        )

    if category_breakdown:
        most_common = max(category_breakdown, key=category_breakdown.__getitem__)
        obs.append(
            f"Most common category is '{most_common}' "
            f"({category_breakdown[most_common]} of {n} predictions)."
        )

    if accuracy is not None and outcomes_available >= 5:
        high_conf_resolved = [
            p for p in predictions
            if p.get("outcome") is not None and p["confidence"] >= 0.70
        ]
        if high_conf_resolved:
            hc_acc = sum(
                1 for p in high_conf_resolved
                if p["prediction"] == p["outcome"]
            ) / len(high_conf_resolved)
            obs.append(
                f"High-confidence predictions (>= 0.70) achieved "
                f"{round(hc_acc * 100, 1)}% accuracy across "
                f"{len(high_conf_resolved)} resolved prediction(s)."
            )

    return obs
