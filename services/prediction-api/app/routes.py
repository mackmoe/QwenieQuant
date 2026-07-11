import logging
import time

from fastapi import APIRouter, HTTPException

from app import calibrator, health as health_module
from app import ollama, postgres, searxng
from app.config import get_settings
from app.models import PredictionRequest, PredictionResponse
from app.prompt_builder import build_prediction_prompt
from app.validators import validate_llm_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=None)
async def health():
    return await health_module.get_health()


@router.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest) -> PredictionResponse:
    settings = get_settings()

    await postgres.fetch_historical_context(request.question)

    # Deterministic search decision — model is never consulted.
    evidence: list[searxng.SearchResult] = []
    search_attempted = searxng.needs_search(request.question, request.category)
    if search_attempted:
        logger.info(
            "question=%r category=%s search=required",
            request.question[:80],
            request.category,
        )
        query = searxng.build_search_query(request.question, request.category)
        evidence = await searxng.search(query)
        if not evidence:
            logger.info(
                "search returned no results for query=%r — continuing without evidence",
                query[:80],
            )
    else:
        logger.info(
            "question=%r category=%s search=skipped",
            request.question[:80],
            request.category,
        )

    system_prompt, user_prompt = build_prediction_prompt(request, evidence or None)

    start = time.monotonic()
    try:
        content, _thinking = await ollama.chat(system_prompt, user_prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {exc}")
    execution_ms = int((time.monotonic() - start) * 1000)

    llm_prediction = validate_llm_response(content, request)

    calibration = await calibrator.apply_calibration(
        pool=postgres._pool,
        model_confidence=llm_prediction.confidence,
        category=request.category,
        model=settings.ollama_model,
        settings=settings,
    )

    sources = [r.url for r in evidence if r.url]
    response = PredictionResponse(
        question=request.question,
        prediction=llm_prediction.prediction,
        confidence=calibration.calibrated_confidence,
        reasoning=llm_prediction.reasoning,
        key_factors=llm_prediction.key_factors,
        model=settings.ollama_model,
        search_context_used=bool(evidence),
        search_attempted=search_attempted,
        sources=sources,
    )

    await postgres.persist_prediction(request, response, execution_ms, calibration_result=calibration)

    return response
