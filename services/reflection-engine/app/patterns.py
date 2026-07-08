"""
Detects recurring patterns across a sequence of learning summaries.

Summaries are expected in descending analyzed_at order (most recent first),
matching the fetch_recent_summaries query. Each detector is a pure function
returning a plain-English string or None when insufficient data exists.
"""

from typing import Optional

_MIN_SUMMARIES = 2
_STABLE_ACCURACY_SPREAD = 0.05
_STABLE_CONFIDENCE_SPREAD = 0.10
_DOMINANT_CATEGORY_FRACTION = 0.70
_LOW_VOLUME_THRESHOLD = 5


def detect_accuracy_trend(summaries: list[dict]) -> Optional[str]:
    with_accuracy = [s for s in summaries if s.get("accuracy") is not None]
    if len(with_accuracy) < _MIN_SUMMARIES:
        return None

    # Reverse to chronological order (oldest first) for trend direction.
    values = [s["accuracy"] for s in reversed(with_accuracy)]
    spread = max(values) - min(values)
    n = len(values)

    if spread < _STABLE_ACCURACY_SPREAD:
        return (
            f"Accuracy has been stable across {n} analyses"
            f" (range: {min(values) * 100:.1f}%–{max(values) * 100:.1f}%)."
        )
    if all(values[i] <= values[i + 1] for i in range(n - 1)):
        return (
            f"Accuracy has been improving across {n} analyses"
            f" (latest: {values[-1] * 100:.1f}%)."
        )
    if all(values[i] >= values[i + 1] for i in range(n - 1)):
        return (
            f"Accuracy has been declining across {n} analyses"
            f" (latest: {values[-1] * 100:.1f}%)."
        )
    return (
        f"Accuracy has varied across {n} analyses"
        f" (range: {min(values) * 100:.1f}%–{max(values) * 100:.1f}%)."
    )


def detect_confidence_pattern(summaries: list[dict]) -> Optional[str]:
    with_conf = [s for s in summaries if s.get("average_confidence") is not None]
    if len(with_conf) < _MIN_SUMMARIES:
        return None

    values = [s["average_confidence"] for s in with_conf]
    avg = sum(values) / len(values)
    spread = max(values) - min(values)
    level = "high" if avg >= 0.75 else ("moderate" if avg >= 0.55 else "low")
    n = len(values)

    if spread < _STABLE_CONFIDENCE_SPREAD:
        return (
            f"Confidence has been consistently {level}"
            f" ({avg:.2f} mean) across {n} analyses."
        )
    return (
        f"Confidence has varied across {n} analyses"
        f" (mean {avg:.2f}, spread {spread:.2f})."
    )


def detect_category_dominance(summaries: list[dict]) -> Optional[str]:
    totals: dict[str, int] = {}
    for s in summaries:
        for cat, count in (s.get("category_breakdown") or {}).items():
            totals[cat] = totals.get(cat, 0) + count

    if not totals:
        return None

    total = sum(totals.values())
    top_cat, top_count = max(totals.items(), key=lambda x: x[1])
    fraction = top_count / total
    n = len(summaries)

    if fraction >= _DOMINANT_CATEGORY_FRACTION:
        return (
            f"Category '{top_cat}' dominates prediction history"
            f" ({fraction * 100:.0f}% of all predictions"
            f" across {n} {'analysis' if n == 1 else 'analyses'})."
        )
    if len(totals) >= 3:
        return (
            f"Predictions span {len(totals)} categories,"
            f" with '{top_cat}' most frequent ({fraction * 100:.0f}%)."
        )
    return None


def detect_model_consistency(summaries: list[dict]) -> Optional[str]:
    totals: dict[str, int] = {}
    for s in summaries:
        for model, count in (s.get("model_breakdown") or {}).items():
            totals[model] = totals.get(model, 0) + count

    if not totals:
        return None

    n = len(summaries)
    label = f"{n} {'analysis' if n == 1 else 'analyses'}"

    if len(totals) == 1:
        model = next(iter(totals))
        return f"All predictions across {label} used model '{model}'."

    top_model, top_count = max(totals.items(), key=lambda x: x[1])
    total = sum(totals.values())
    return (
        f"{len(totals)} models used across {label};"
        f" '{top_model}' is most frequent ({top_count}/{total})."
    )


def detect_data_volume_pattern(summaries: list[dict]) -> Optional[str]:
    if len(summaries) < _MIN_SUMMARIES:
        return None

    counts = [s.get("predictions_analyzed", 0) for s in summaries]
    avg = sum(counts) / len(counts)
    if avg < _LOW_VOLUME_THRESHOLD:
        return (
            f"Average prediction volume is {avg:.1f} per analysis —"
            f" consistently low across {len(summaries)} analyses."
        )
    return None


def detect_calibration_gap(summaries: list[dict]) -> Optional[str]:
    """
    Detect poor confidence calibration: high-confidence predictions don't
    meaningfully outperform low-confidence ones.
    """
    recent = next(
        (s for s in summaries
         if isinstance(s.get("diagnostics"), dict)
         and s["diagnostics"].get("confidence_buckets")),
        None,
    )
    if not recent:
        return None

    buckets = recent["diagnostics"]["confidence_buckets"]
    low = next((b for b in buckets if b.get("label") == "50-60%"), None)
    high = next(
        (b for b in buckets if b.get("label") in ("80-90%", "90-100%")),
        None,
    )
    if not low or not high:
        return None
    if low.get("accuracy") is None or high.get("accuracy") is None:
        return None
    if low.get("resolved", 0) < 3 or high.get("resolved", 0) < 3:
        return None

    gap = high["accuracy"] - low["accuracy"]
    if gap < 0.05:
        return (
            f"Confidence calibration gap is narrow ({gap * 100:.0f}pp between "
            f"50-60% and {high['label']} buckets) — high-confidence predictions "
            "don't significantly outperform low-confidence ones."
        )
    return None


def detect_search_impact(summaries: list[dict]) -> Optional[str]:
    """Report the measured accuracy impact of SearXNG search usage."""
    recent = next(
        (s for s in summaries
         if isinstance(s.get("diagnostics"), dict)
         and s["diagnostics"].get("search_effectiveness")),
        None,
    )
    if not recent:
        return None

    se = recent["diagnostics"]["search_effectiveness"]
    delta = se.get("accuracy_delta")
    if delta is None:
        return None
    if se.get("with_search_count", 0) < 3 or se.get("without_search_count", 0) < 3:
        return None

    with_pct = (se.get("with_search_accuracy") or 0) * 100
    without_pct = (se.get("without_search_accuracy") or 0) * 100
    direction = "improves" if delta > 0 else "reduces"
    return (
        f"SearXNG {direction} accuracy by {abs(delta) * 100:.0f}pp"
        f" ({with_pct:.0f}% with search vs {without_pct:.0f}% without)."
    )


def detect_all(summaries: list[dict]) -> list[str]:
    detectors = [
        detect_accuracy_trend,
        detect_confidence_pattern,
        detect_category_dominance,
        detect_model_consistency,
        detect_data_volume_pattern,
        detect_calibration_gap,
        detect_search_impact,
    ]
    return [result for d in detectors if (result := d(summaries)) is not None]
