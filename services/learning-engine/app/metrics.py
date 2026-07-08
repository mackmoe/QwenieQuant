"""
Pure metric computation functions.

All functions take a list of prediction dicts and return a scalar or mapping.
No side effects, no I/O. Each function has exactly one job.
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Existing aggregate metrics
# ---------------------------------------------------------------------------


def compute_accuracy(predictions: list[dict]) -> Optional[float]:
    with_outcomes = [p for p in predictions if p.get("outcome") is not None]
    if not with_outcomes:
        return None
    correct = sum(
        1 for p in with_outcomes
        if p["prediction"].lower() == p["outcome"].lower()
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


# ---------------------------------------------------------------------------
# Diagnostic helpers (SPEC-030)
# ---------------------------------------------------------------------------


def _accuracy_of(preds: list[dict]) -> Optional[float]:
    resolved = [p for p in preds if p.get("outcome") is not None]
    if not resolved:
        return None
    correct = sum(
        1 for p in resolved
        if p["prediction"].lower() == p["outcome"].lower()
    )
    return correct / len(resolved)


def _avg_conf(preds: list[dict]) -> Optional[float]:
    if not preds:
        return None
    return sum(p["confidence"] for p in preds) / len(preds)


# ---------------------------------------------------------------------------
# Diagnostic compute functions (SPEC-030)
# ---------------------------------------------------------------------------


def compute_category_performance(predictions: list[dict]) -> list[dict]:
    cats: dict[str, list[dict]] = {}
    for p in predictions:
        cat = (p.get("category") or "other").lower()
        cats.setdefault(cat, []).append(p)
    result = []
    for cat in sorted(cats):
        preds = cats[cat]
        resolved = [p for p in preds if p.get("outcome") is not None]
        result.append({
            "category": cat,
            "count": len(preds),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(preds),
            "average_confidence": _avg_conf(preds),
        })
    return result


def compute_yes_no_analysis(predictions: list[dict]) -> dict:
    yes_preds = [p for p in predictions if p.get("prediction", "").lower() == "yes"]
    no_preds = [p for p in predictions if p.get("prediction", "").lower() == "no"]

    def _stat(preds: list[dict]) -> dict:
        resolved = [p for p in preds if p.get("outcome") is not None]
        return {
            "count": len(preds),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(preds),
            "average_confidence": _avg_conf(preds),
        }

    return {"yes": _stat(yes_preds), "no": _stat(no_preds)}


_CONFIDENCE_BUCKETS = [
    ("50-60%", 0.50, 0.60),
    ("60-70%", 0.60, 0.70),
    ("70-80%", 0.70, 0.80),
    ("80-90%", 0.80, 0.90),
    ("90-100%", 0.90, 1.01),
]


def compute_confidence_buckets(predictions: list[dict]) -> list[dict]:
    result = []
    for label, lo, hi in _CONFIDENCE_BUCKETS:
        bucket = [p for p in predictions if lo <= p.get("confidence", 0) < hi]
        resolved = [p for p in bucket if p.get("outcome") is not None]
        result.append({
            "label": label,
            "range_low": lo,
            "range_high": min(hi, 1.0),
            "count": len(bucket),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(bucket),
        })
    return result


def compute_search_effectiveness(predictions: list[dict]) -> dict:
    with_search = [p for p in predictions if p.get("search_used")]
    without_search = [p for p in predictions if not p.get("search_used")]
    wa = _accuracy_of(with_search)
    woa = _accuracy_of(without_search)
    delta = (wa - woa) if (wa is not None and woa is not None) else None
    return {
        "with_search_count": len(with_search),
        "without_search_count": len(without_search),
        "with_search_accuracy": wa,
        "without_search_accuracy": woa,
        "with_search_confidence": _avg_conf(with_search),
        "without_search_confidence": _avg_conf(without_search),
        "accuracy_delta": delta,
    }


_RANKING_TIERS = [
    ("High (≥80)", 80.0, 100.0),
    ("Medium (50–79)", 50.0, 80.0),
    ("Low (<50)", 0.0, 50.0),
]


def compute_ranking_effectiveness(predictions: list[dict]) -> list[dict]:
    ranked = [p for p in predictions if p.get("queue_priority_score") is not None]
    if not ranked:
        return []
    result = []
    for label, lo, hi in _RANKING_TIERS:
        tier = [p for p in ranked if lo <= p["queue_priority_score"] <= hi]
        if not tier:
            continue
        resolved = [p for p in tier if p.get("outcome") is not None]
        result.append({
            "label": label,
            "min_score": lo,
            "max_score": hi,
            "count": len(tier),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(tier),
            "average_confidence": _avg_conf(tier),
        })
    return result


def compute_risk_effectiveness(predictions: list[dict]) -> dict:
    approved = [p for p in predictions if p.get("approved") is True]
    rejected = [p for p in predictions if p.get("approved") is False]
    return {
        "approved_count": len(approved),
        "approved_resolved": len([p for p in approved if p.get("outcome") is not None]),
        "approved_accuracy": _accuracy_of(approved),
        "rejected_count": len(rejected),
        "rejected_resolved": len([p for p in rejected if p.get("outcome") is not None]),
        "rejected_accuracy": _accuracy_of(rejected),
    }


def compute_weekly_drift(predictions: list[dict]) -> list[dict]:
    weeks: dict[str, list[dict]] = {}
    for p in predictions:
        dt = p.get("created_at")
        if dt is None:
            continue
        if hasattr(dt, "isocalendar"):
            cal = dt.isocalendar()
            week_key = f"{cal[0]}-W{cal[1]:02d}"
        else:
            week_key = "unknown"
        weeks.setdefault(week_key, []).append(p)
    result = []
    for week in sorted(weeks):
        preds = weeks[week]
        resolved = [p for p in preds if p.get("outcome") is not None]
        result.append({
            "week": week,
            "count": len(preds),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(preds),
            "average_confidence": _avg_conf(preds),
        })
    return result


def compute_model_performance(predictions: list[dict]) -> list[dict]:
    models: dict[str, list[dict]] = {}
    for p in predictions:
        m = p.get("model") or "unknown"
        models.setdefault(m, []).append(p)
    result = []
    for model in sorted(models):
        preds = models[model]
        resolved = [p for p in preds if p.get("outcome") is not None]
        result.append({
            "model": model,
            "count": len(preds),
            "resolved": len(resolved),
            "accuracy": _accuracy_of(preds),
            "average_confidence": _avg_conf(preds),
            "average_execution_ms": sum(p.get("execution_ms", 0) for p in preds) / len(preds),
        })
    return result


def compute_extremes(
    category_perf: list[dict],
    yes_no: dict,
    conf_buckets: list[dict],
    model_perf: list[dict],
    search_eff: dict,
) -> tuple[list[str], list[str]]:
    """
    Identify the 5 weakest and 5 strongest segments across all diagnostic dimensions.
    Only segments with >= 3 resolved predictions are considered.
    """
    segments: list[tuple[str, float, int]] = []

    for cat in category_perf:
        if cat.get("accuracy") is not None and cat["resolved"] >= 3:
            segments.append((f"Category: {cat['category']}", cat["accuracy"], cat["resolved"]))

    yn_yes = yes_no.get("yes", {})
    yn_no = yes_no.get("no", {})
    if yn_yes.get("accuracy") is not None and yn_yes.get("resolved", 0) >= 3:
        segments.append(("Direction: YES", yn_yes["accuracy"], yn_yes["resolved"]))
    if yn_no.get("accuracy") is not None and yn_no.get("resolved", 0) >= 3:
        segments.append(("Direction: NO", yn_no["accuracy"], yn_no["resolved"]))

    for bucket in conf_buckets:
        if bucket.get("accuracy") is not None and bucket["resolved"] >= 3:
            segments.append((f"Confidence {bucket['label']}", bucket["accuracy"], bucket["resolved"]))

    for m in model_perf:
        if m.get("accuracy") is not None and m["resolved"] >= 3:
            segments.append((f"Model: {m['model']}", m["accuracy"], m["resolved"]))

    if (search_eff.get("with_search_count", 0) >= 3
            and search_eff.get("with_search_accuracy") is not None):
        segments.append(("SearXNG: with search", search_eff["with_search_accuracy"],
                         search_eff["with_search_count"]))
    if (search_eff.get("without_search_count", 0) >= 3
            and search_eff.get("without_search_accuracy") is not None):
        segments.append(("SearXNG: without search", search_eff["without_search_accuracy"],
                         search_eff["without_search_count"]))

    if not segments:
        return [], []

    segments.sort(key=lambda x: x[1])
    failures = [f"{label}: {acc * 100:.0f}%" for label, acc, _ in segments[:5]]
    successes = [f"{label}: {acc * 100:.0f}%" for label, acc, _ in reversed(segments[-5:])]
    return failures, successes
