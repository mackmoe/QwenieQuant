"""
Analysis pipeline orchestrator.

Retrieves prediction history, delegates computation to metrics and
summaries, assembles the result, and persists it. No computation logic
lives here — this module only connects the other modules.
"""

from app import metrics, postgres, summaries
from app.models import AnalysisRequest, AnalysisSummary


async def run_analysis(request: AnalysisRequest) -> AnalysisSummary:
    predictions = await postgres.fetch_predictions(
        limit=request.limit,
        since=request.since,
        until=request.until,
    )

    accuracy = metrics.compute_accuracy(predictions)
    avg_confidence = metrics.compute_average_confidence(predictions)
    avg_execution_ms = metrics.compute_average_execution_ms(predictions)
    model_breakdown = metrics.compute_model_breakdown(predictions)
    category_breakdown = metrics.compute_category_breakdown(predictions)
    outcomes_available = sum(
        1 for p in predictions if p.get("outcome") is not None
    )

    obs = summaries.build_observations(
        predictions=predictions,
        accuracy=accuracy,
        avg_confidence=avg_confidence,
        avg_execution_ms=avg_execution_ms,
        model_breakdown=model_breakdown,
        category_breakdown=category_breakdown,
    )

    time_range_start = request.since or (
        min(p["created_at"] for p in predictions) if predictions else None
    )
    time_range_end = request.until or (
        max(p["created_at"] for p in predictions) if predictions else None
    )

    summary = AnalysisSummary(
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        predictions_analyzed=len(predictions),
        outcomes_available=outcomes_available,
        accuracy=accuracy,
        average_confidence=avg_confidence,
        average_execution_ms=avg_execution_ms,
        model_breakdown=model_breakdown,
        category_breakdown=category_breakdown,
        observations=obs,
    )

    await postgres.persist_summary(summary)

    return summary
