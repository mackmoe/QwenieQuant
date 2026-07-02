"""
Extracts strengths, weaknesses, and recommendations from a single learning summary.

All functions are pure — no I/O.
"""

_HIGH_ACCURACY = 0.75
_LOW_ACCURACY = 0.55
_HIGH_CONFIDENCE = 0.75
_LOW_CONFIDENCE = 0.55
_MIN_OUTCOMES_FOR_ACCURACY = 3
_SLOW_EXECUTION_MS = 120_000  # 120 s
_MIN_PREDICTIONS = 5


def extract_strengths(summary: dict) -> list[str]:
    strengths: list[str] = []
    accuracy = summary.get("accuracy")
    outcomes = summary.get("outcomes_available", 0)
    confidence = summary.get("average_confidence")
    execution_ms = summary.get("average_execution_ms")
    predictions = summary.get("predictions_analyzed", 0)

    if (
        accuracy is not None
        and outcomes >= _MIN_OUTCOMES_FOR_ACCURACY
        and accuracy >= _HIGH_ACCURACY
    ):
        strengths.append(
            f"Accuracy is {accuracy * 100:.1f}% across {outcomes} resolved prediction(s),"
            f" above the {_HIGH_ACCURACY * 100:.0f}% threshold."
        )

    if confidence is not None and confidence >= _HIGH_CONFIDENCE:
        strengths.append(
            f"Average confidence is {confidence:.2f}, which is consistently high."
        )

    if execution_ms is not None and execution_ms < _SLOW_EXECUTION_MS:
        strengths.append(
            f"Inference time is {execution_ms / 1000:.1f}s on average,"
            " within acceptable range."
        )

    if predictions >= _MIN_PREDICTIONS:
        strengths.append(
            f"Analysis covers {predictions} prediction(s),"
            " providing a reasonable sample size."
        )

    return strengths


def extract_weaknesses(summary: dict) -> list[str]:
    weaknesses: list[str] = []
    accuracy = summary.get("accuracy")
    outcomes = summary.get("outcomes_available", 0)
    confidence = summary.get("average_confidence")
    execution_ms = summary.get("average_execution_ms")
    predictions = summary.get("predictions_analyzed", 0)

    if accuracy is None:
        weaknesses.append("No resolved outcomes available; accuracy cannot be assessed.")
    elif outcomes < _MIN_OUTCOMES_FOR_ACCURACY:
        weaknesses.append(
            f"Only {outcomes} resolved outcome(s) —"
            " insufficient to draw reliable accuracy conclusions."
        )
    elif accuracy < _LOW_ACCURACY:
        weaknesses.append(
            f"Accuracy is {accuracy * 100:.1f}% across {outcomes} resolved prediction(s),"
            f" below the {_LOW_ACCURACY * 100:.0f}% threshold."
        )

    if confidence is not None and confidence < _LOW_CONFIDENCE:
        weaknesses.append(
            f"Average confidence is {confidence:.2f},"
            " which is low and may indicate model uncertainty."
        )

    if execution_ms is not None and execution_ms >= _SLOW_EXECUTION_MS:
        weaknesses.append(
            f"Inference time averages {execution_ms / 1000:.1f}s,"
            f" which is above the {_SLOW_EXECUTION_MS / 1000:.0f}s threshold."
        )

    if predictions < _MIN_PREDICTIONS:
        weaknesses.append(
            f"Only {predictions} prediction(s) analyzed —"
            " insufficient for statistical confidence."
        )

    return weaknesses


def generate_recommendations(
    strengths: list[str],
    weaknesses: list[str],
    summary: dict,
) -> list[str]:
    recs: list[str] = []
    outcomes = summary.get("outcomes_available", 0)
    accuracy = summary.get("accuracy")
    predictions = summary.get("predictions_analyzed", 0)

    if outcomes == 0:
        recs.append("Record real-world outcomes to enable accuracy measurement.")
    elif outcomes < _MIN_OUTCOMES_FOR_ACCURACY:
        recs.append(
            "Collect more resolved outcomes before drawing accuracy conclusions."
        )

    if accuracy is not None and accuracy < _LOW_ACCURACY:
        recs.append(
            "Investigate confidence calibration —"
            " predictions may be overconfident relative to accuracy."
        )

    if predictions < _MIN_PREDICTIONS:
        recs.append("Increase prediction volume to improve statistical reliability.")

    if not recs:
        recs.append("Continue monitoring; no immediate areas of concern identified.")

    return recs
