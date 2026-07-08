"""
Historical confidence calibration.

After the model returns a prediction+confidence, this module queries
resolved historical outcomes and adjusts confidence downward when the
model has historically been overconfident relative to actual accuracy.

Rules (from SPEC-022):
  - Confidence may only decrease or stay the same. Never increases.
  - No adjustment when history < CONFIDENCE_MIN_HISTORY resolved outcomes.
  - Algorithm is deterministic and explainable. No ML, no retraining.
  - Calibration is transparent: original/calibrated/reason are logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CATEGORY_WEIGHT_THRESHOLD = 10   # min category samples to blend category accuracy
_CATEGORY_FULL_WEIGHT_AT  = 50   # category weight reaches 1.0 at this many samples
_TREND_INFLUENCE          = 0.15  # how much recent_trend modifies the sample_factor


@dataclass
class CalibrationHistory:
    """Distilled statistics from resolved historical predictions."""
    overall_accuracy: float | None
    overall_count: int
    category_accuracy: float | None
    category_count: int
    model_accuracy: float | None
    model_count: int
    recent_trend: float | None   # positive = improving, negative = declining


@dataclass
class CalibrationResult:
    """Outcome of one calibration pass."""
    original_confidence: float
    calibrated_confidence: float
    reason: str
    adjusted: bool


def _empty_history() -> CalibrationHistory:
    return CalibrationHistory(
        overall_accuracy=None,
        overall_count=0,
        category_accuracy=None,
        category_count=0,
        model_accuracy=None,
        model_count=0,
        recent_trend=None,
    )


def compute_history(
    predictions: list[dict],
    *,
    category: str,
    model: str,
) -> CalibrationHistory:
    """
    Derive calibration statistics from a list of resolved prediction dicts.

    Each dict must have keys: prediction, outcome, category, model.
    Only rows where outcome is not None are meaningful (resolved).
    """
    resolved = [p for p in predictions if p.get("outcome") is not None]
    if not resolved:
        return _empty_history()

    total = len(resolved)
    correct = sum(1 for p in resolved if p["prediction"].lower() == p["outcome"].lower())
    overall_accuracy = correct / total

    cat_rows = [p for p in resolved if p.get("category") == category]
    cat_count = len(cat_rows)
    cat_accuracy: float | None = None
    if cat_count > 0:
        cat_correct = sum(1 for p in cat_rows if p["prediction"].lower() == p["outcome"].lower())
        cat_accuracy = cat_correct / cat_count

    model_rows = [p for p in resolved if p.get("model") == model]
    model_count = len(model_rows)
    model_accuracy: float | None = None
    if model_count > 0:
        model_correct = sum(1 for p in model_rows if p["prediction"].lower() == p["outcome"].lower())
        model_accuracy = model_correct / model_count

    # Recent trend: compare newer half vs older half (rows come in DESC order from DB)
    recent_trend: float | None = None
    if total >= 10:
        half = total // 2
        recent = resolved[:half]      # newer rows
        older  = resolved[half:]      # older rows
        recent_acc = sum(1 for p in recent if p["prediction"].lower() == p["outcome"].lower()) / len(recent)
        older_acc  = sum(1 for p in older  if p["prediction"].lower() == p["outcome"].lower()) / len(older)
        recent_trend = recent_acc - older_acc

    return CalibrationHistory(
        overall_accuracy=overall_accuracy,
        overall_count=total,
        category_accuracy=cat_accuracy,
        category_count=cat_count,
        model_accuracy=model_accuracy,
        model_count=model_count,
        recent_trend=recent_trend,
    )


def calibrate(
    *,
    model_confidence: float,
    history: CalibrationHistory,
    settings,
) -> CalibrationResult:
    """
    Deterministic confidence calibration.

    Returns a CalibrationResult. Confidence never increases.
    """
    if not settings.confidence_calibration_enabled:
        return CalibrationResult(
            original_confidence=model_confidence,
            calibrated_confidence=model_confidence,
            reason="calibration_disabled",
            adjusted=False,
        )

    if history.overall_count < settings.confidence_min_history:
        reason = (
            f"insufficient_history:"
            f"{history.overall_count}/{settings.confidence_min_history}"
        )
        return CalibrationResult(
            original_confidence=model_confidence,
            calibrated_confidence=model_confidence,
            reason=reason,
            adjusted=False,
        )

    # Reference accuracy: blend category accuracy into overall by sample size.
    # Falls back to overall when category has < _CATEGORY_WEIGHT_THRESHOLD samples.
    overall_acc = history.overall_accuracy  # guaranteed non-None at this point
    assert overall_acc is not None

    if (
        history.category_accuracy is not None
        and history.category_count >= _CATEGORY_WEIGHT_THRESHOLD
    ):
        cat_weight = min(
            1.0, history.category_count / _CATEGORY_FULL_WEIGHT_AT
        )
        ref_accuracy = (
            cat_weight * history.category_accuracy
            + (1.0 - cat_weight) * overall_acc
        )
        source = (
            f"category(n={history.category_count},"
            f"overall_n={history.overall_count})"
        )
    else:
        ref_accuracy = overall_acc
        source = f"overall(n={history.overall_count})"

    # Sample-size factor: ramps from 0 → 1 over [MIN_HISTORY, 4×MIN_HISTORY].
    # Ensures small samples produce weaker adjustments.
    sample_range = settings.confidence_min_history * 3  # spans MIN to 4×MIN
    sample_factor = min(
        1.0,
        (history.overall_count - settings.confidence_min_history) / sample_range,
    )

    # Trend modifier: positive trend (improving) slightly reduces aggression;
    # negative trend (declining) slightly increases it.
    if history.recent_trend is not None:
        trend_mod = history.recent_trend * _TREND_INFLUENCE
        effective_factor = max(0.0, min(1.0, sample_factor + trend_mod))
    else:
        effective_factor = sample_factor

    gap = model_confidence - ref_accuracy
    if gap <= 0:
        return CalibrationResult(
            original_confidence=model_confidence,
            calibrated_confidence=model_confidence,
            reason=f"no_overconfidence:{source}",
            adjusted=False,
        )

    reduction = min(gap * effective_factor, settings.confidence_max_reduction)
    if reduction < 1e-4:
        return CalibrationResult(
            original_confidence=model_confidence,
            calibrated_confidence=model_confidence,
            reason=f"negligible_adjustment:{source}",
            adjusted=False,
        )

    calibrated = round(max(0.0, model_confidence - reduction), 4)

    reason = (
        f"reduced:{source},"
        f"hist_acc={ref_accuracy:.4f},"
        f"gap={gap:.4f},"
        f"factor={effective_factor:.4f},"
        f"reduction={reduction:.4f}"
    )

    logger.info(
        "confidence_calibrated original=%.4f -> hist_acc=%.4f -> reduction=%.4f -> final=%.4f | %s",
        model_confidence,
        ref_accuracy,
        reduction,
        calibrated,
        reason,
    )

    return CalibrationResult(
        original_confidence=model_confidence,
        calibrated_confidence=calibrated,
        reason=reason,
        adjusted=True,
    )


async def apply_calibration(
    *,
    pool,
    model_confidence: float,
    category: str,
    model: str,
    settings,
) -> CalibrationResult:
    """
    Fetch resolved history from Postgres, derive statistics, and calibrate.

    Degrades gracefully: if the pool is None or the query fails, returns
    model_confidence unchanged (cold-start behaviour).
    """
    from app.postgres import fetch_resolved_predictions

    try:
        predictions = await fetch_resolved_predictions(limit=500)
    except Exception:
        logger.warning("calibration_fetch_failed — returning model confidence unchanged")
        return CalibrationResult(
            original_confidence=model_confidence,
            calibrated_confidence=model_confidence,
            reason="fetch_failed",
            adjusted=False,
        )

    history = compute_history(predictions, category=category, model=model)
    return calibrate(
        model_confidence=model_confidence,
        history=history,
        settings=settings,
    )
