"""
Builds human-readable observations from computed metrics.

All observations describe measurable patterns. No speculative conclusions.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Diagnostics

_MIN_RESOLVED_FOR_DIAGNOSTIC = 3


def _build_diagnostic_observations(diagnostics: "Diagnostics") -> list[str]:
    """Generate up to 5 diagnostic observations from per-segment resolved counts."""
    obs: list[str] = []

    # Category Performance — strongest vs weakest
    with_acc = [
        c for c in diagnostics.category_performance
        if c.accuracy is not None and c.resolved >= _MIN_RESOLVED_FOR_DIAGNOSTIC
    ]
    if len(with_acc) >= 2:
        best = max(with_acc, key=lambda c: c.accuracy)  # type: ignore[arg-type]
        worst = min(with_acc, key=lambda c: c.accuracy)  # type: ignore[arg-type]
        if best.category != worst.category:
            obs.append(
                f"Strongest category: '{best.category}'"
                f" ({best.accuracy * 100:.0f}%);"
                f" weakest: '{worst.category}'"
                f" ({worst.accuracy * 100:.0f}%)."
            )

    # YES vs NO direction bias
    yn = diagnostics.yes_no_analysis
    if yn is not None and yn.yes.resolved >= _MIN_RESOLVED_FOR_DIAGNOSTIC \
            and yn.no.resolved >= _MIN_RESOLVED_FOR_DIAGNOSTIC:
        ya, na = yn.yes.accuracy, yn.no.accuracy
        if ya is not None and na is not None:
            delta = abs(ya - na)
            if delta >= 0.10:
                better = "YES" if ya > na else "NO"
                obs.append(
                    f"{better} predictions outperform the other direction"
                    f" by {delta * 100:.0f}pp"
                    f" ({ya * 100:.0f}% vs {na * 100:.0f}%)."
                )

    # SearXNG effectiveness
    se = diagnostics.search_effectiveness
    if se is not None and se.accuracy_delta is not None:
        if (se.with_search_count >= _MIN_RESOLVED_FOR_DIAGNOSTIC
                and se.without_search_count >= _MIN_RESOLVED_FOR_DIAGNOSTIC):
            if abs(se.accuracy_delta) >= 0.05:
                direction = "improves" if se.accuracy_delta > 0 else "degrades"
                with_pct = (se.with_search_accuracy or 0) * 100
                without_pct = (se.without_search_accuracy or 0) * 100
                obs.append(
                    f"SearXNG search {direction} accuracy"
                    f" by {abs(se.accuracy_delta) * 100:.0f}pp"
                    f" ({with_pct:.0f}% with search vs {without_pct:.0f}% without)."
                )

    # Risk Manager: were approved predictions more accurate?
    rm = diagnostics.risk_effectiveness
    if rm is not None and rm.approved_resolved >= _MIN_RESOLVED_FOR_DIAGNOSTIC \
            and rm.rejected_resolved >= _MIN_RESOLVED_FOR_DIAGNOSTIC:
        aa, ra = rm.approved_accuracy, rm.rejected_accuracy
        if aa is not None and ra is not None:
            delta = abs(aa - ra)
            if delta >= 0.08:
                direction = "outperform" if aa > ra else "underperform"
                obs.append(
                    f"Risk-approved predictions {direction} rejected ones"
                    f" by {delta * 100:.0f}pp"
                    f" ({aa * 100:.0f}% vs {ra * 100:.0f}%)."
                )

    return obs[:5]


def build_observations(
    predictions: list[dict],
    accuracy: Optional[float],
    avg_confidence: Optional[float],
    avg_execution_ms: Optional[float],
    model_breakdown: dict[str, int],
    category_breakdown: dict[str, int],
    diagnostics: Optional["Diagnostics"] = None,
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
                if p["prediction"].lower() == p["outcome"].lower()
            ) / len(high_conf_resolved)
            obs.append(
                f"High-confidence predictions (>= 0.70) achieved "
                f"{round(hc_acc * 100, 1)}% accuracy across "
                f"{len(high_conf_resolved)} resolved prediction(s)."
            )

    if diagnostics is not None:
        obs.extend(_build_diagnostic_observations(diagnostics))

    return obs
