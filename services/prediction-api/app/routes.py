from fastapi import APIRouter, HTTPException

from app import health as health_module
from app import ollama, postgres, searxng
from app.config import get_settings
from app.models import PredictionRequest, PredictionResponse
from app.prompt_builder import build_prediction_prompt
from app.validators import validate_llm_response

router = APIRouter()


@router.get("/health", response_model=None)
async def health():
    return await health_module.get_health()


@router.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest) -> PredictionResponse:
    settings = get_settings()

    # Stubs — replaced by real implementations in future phases
    await postgres.fetch_historical_context(request.question)
    await searxng.search(request.question)

    system_prompt, user_prompt = build_prediction_prompt(request)

    try:
        content, _thinking = await ollama.chat(system_prompt, user_prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {exc}")

    llm_prediction = validate_llm_response(content, request)

    response = PredictionResponse(
        question=request.question,
        prediction=llm_prediction.prediction,
        confidence=llm_prediction.confidence,
        reasoning=llm_prediction.reasoning,
        key_factors=llm_prediction.key_factors,
        model=settings.ollama_model,
    )

    # Stub — replaced by real persistence in a future phase
    await postgres.persist_prediction(request, response)

    return response
