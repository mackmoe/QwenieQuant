from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import PredictionRequest

if TYPE_CHECKING:
    from app.searxng import SearchResult


_SYSTEM_PROMPT = """\
You are a structured prediction engine. Evaluate evidence and produce a \
calibrated probability prediction.

Rules:
- Respond ONLY with valid JSON. No preamble, no explanation outside the JSON.
- "prediction" must be exactly one of the provided options.
- "confidence" must be a float between 0.0 (no confidence) and 1.0 (certainty).
- "reasoning" must explain your conclusion in 2-4 sentences.
- "key_factors" must list 2-5 specific factors that most influenced your prediction.
- If "Current Evidence" is provided, use it to inform your prediction.
- If no "Current Evidence" is provided, rely on your internal knowledge.
- Never invent evidence that was not supplied.
- Never claim to have searched the internet when no evidence was provided.

Response schema:
{
  "prediction": "<one of the provided options>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-4 sentences>",
  "key_factors": ["<factor 1>", "<factor 2>", ...]
}"""


def build_prediction_prompt(
    request: PredictionRequest,
    evidence: list[SearchResult] | None = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a prediction request."""
    parts = [
        f"Question: {request.question}",
        f"Category: {request.category}",
        f"Options: {', '.join(request.options)}",
    ]

    if request.context:
        context_lines = "\n".join(
            f"  {k}: {v}" for k, v in request.context.items()
        )
        parts.append(f"Context:\n{context_lines}")

    if request.resolution_date:
        parts.append(f"Resolution date: {request.resolution_date}")

    if evidence:
        bullet_lines = "\n".join(
            f"* {r.snippet}" for r in evidence if r.snippet
        )
        parts.append(f"\nCurrent Evidence:\n{bullet_lines}")

    parts.append("\nEvaluate this prediction and respond with JSON only.")

    return _SYSTEM_PROMPT, "\n".join(parts)
