"""
Analysis pipeline orchestrator.

Retrieves prediction history, delegates computation to metrics and
summaries, assembles the result, and persists it. No computation logic
lives here — this module only connects the other modules.
"""

from app import metrics, postgres, summaries
from app.models import (
    AnalysisRequest,
    AnalysisSummary,
    CategoryStat,
    ConfidenceBucket,
    Diagnostics,
    DirectionStat,
    ModelStat,
    RankingTier,
    RiskEffectiveness,
    SearchEffectiveness,
    WeeklyDriftPoint,
    YesNoAnalysis,
)


def _build_diagnostics(predictions: list[dict]) -> Diagnostics:
    cat_perf = metrics.compute_category_performance(predictions)
    yes_no_raw = metrics.compute_yes_no_analysis(predictions)
    conf_buckets_raw = metrics.compute_confidence_buckets(predictions)
    search_eff_raw = metrics.compute_search_effectiveness(predictions)
    ranking_raw = metrics.compute_ranking_effectiveness(predictions)
    risk_raw = metrics.compute_risk_effectiveness(predictions)
    drift_raw = metrics.compute_weekly_drift(predictions)
    model_perf_raw = metrics.compute_model_performance(predictions)
    failures, successes = metrics.compute_extremes(
        cat_perf, yes_no_raw, conf_buckets_raw, model_perf_raw, search_eff_raw
    )

    category_performance = [CategoryStat(**c) for c in cat_perf]

    yn = yes_no_raw
    yes_no = YesNoAnalysis(
        yes=DirectionStat(**yn["yes"]),
        no=DirectionStat(**yn["no"]),
    )

    confidence_buckets = [ConfidenceBucket(**b) for b in conf_buckets_raw]

    se = search_eff_raw
    search_effectiveness = SearchEffectiveness(**se)

    ranking_tiers = [RankingTier(**t) for t in ranking_raw]

    risk_effectiveness = RiskEffectiveness(**risk_raw)

    weekly_drift = [WeeklyDriftPoint(**w) for w in drift_raw]

    model_performance = [ModelStat(**m) for m in model_perf_raw]

    return Diagnostics(
        category_performance=category_performance,
        yes_no_analysis=yes_no,
        confidence_buckets=confidence_buckets,
        search_effectiveness=search_effectiveness,
        ranking_tiers=ranking_tiers,
        risk_effectiveness=risk_effectiveness,
        weekly_drift=weekly_drift,
        model_performance=model_performance,
        top_failures=failures,
        top_successes=successes,
    )


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

    diagnostics = _build_diagnostics(predictions) if predictions else Diagnostics()

    obs = summaries.build_observations(
        predictions=predictions,
        accuracy=accuracy,
        avg_confidence=avg_confidence,
        avg_execution_ms=avg_execution_ms,
        model_breakdown=model_breakdown,
        category_breakdown=category_breakdown,
        diagnostics=diagnostics,
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
        diagnostics=diagnostics,
    )

    await postgres.persist_summary(summary)

    return summary
