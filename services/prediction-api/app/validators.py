import json

from fastapi import HTTPException

from app.models import LLMPrediction, PredictionRequest


def validate_llm_response(raw: str, request: PredictionRequest) -> LLMPrediction:
    """
    Parse and validate a raw JSON string from the model.

    Raises HTTP 502 if the JSON is malformed, required fields are missing,
    or the model chose a prediction not in request.options.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail=f"Model returned invalid JSON: {exc}"
        )

    try:
        parsed = LLMPrediction(**data)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model response missing required fields: {exc}",
        )

    if parsed.prediction not in request.options:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Model prediction '{parsed.prediction}' is not one of the "
                f"valid options: {request.options}"
            ),
        )

    return parsed
