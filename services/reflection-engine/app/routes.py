from fastapi import APIRouter, HTTPException

from app.health import HealthStatus, get_health
from app.reflector import ReflectRequest, ReflectionResult, run_reflection

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def health():
    return await get_health()


@router.post("/reflect", response_model=ReflectionResult)
async def reflect(request: ReflectRequest):
    try:
        return await run_reflection(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Reflection failed: {exc}")
