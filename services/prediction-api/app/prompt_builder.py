from app.models import PredictionRequest


_SYSTEM_PROMPT = """\
You are a structured prediction engine. Evaluate evidence and produce a \
calibrated probability prediction.

Rules:
- Respond ONLY with valid JSON. No preamble, no explanation outside the JSON.
- "prediction" must be exactly one of the provided options.
- "confidence" must be a float between 0.0 (no confidence) and 1.0 (certainty).
- "reasoning" must explain your conclusion in 2-4 sentences.
- "key_factors" must list 2-5 specific factors that most influenced your prediction.

Response schema:
{
  "prediction": "<one of the provided options>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-4 sentences>",
  "key_factors": ["<factor 1>", "<factor 2>", ...]
}"""


def build_prediction_prompt(request: PredictionRequest) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a prediction request."""
    parts = [
        f"Question: {request.question}",
        f"Category: {request.category.value}",
        f"Options: {', '.join(request.options)}",
    ]

    if request.context:
        context_lines = "\n".join(
            f"  {k}: {v}" for k, v in request.context.items()
        )
        parts.append(f"Context:\n{context_lines}")

    if request.resolution_date:
        parts.append(f"Resolution date: {request.resolution_date}")

    parts.append("\nEvaluate this prediction and respond with JSON only.")

    return _SYSTEM_PROMPT, "\n".join(parts)
