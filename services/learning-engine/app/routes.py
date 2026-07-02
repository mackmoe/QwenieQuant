from fastapi import APIRouter, HTTPException

from app import health as health_module
from app.analyzer import run_analysis
from app.models import AnalysisRequest, AnalysisSummary

router = APIRouter()


@router.get("/health", response_model=None)
async def health():
    return await health_module.get_health()


@router.post("/analyze", response_model=AnalysisSummary)
async def analyze(request: AnalysisRequest) -> AnalysisSummary:
    try:
        return await run_analysis(request)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Analysis failed: {exc}")
