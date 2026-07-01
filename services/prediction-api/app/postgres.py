"""
PostgreSQL interface — stub only.

No database logic is implemented here yet. These functions define the
interface that future phases will fill in. All return empty/no-op values
so the prediction pipeline can call them unconditionally.
"""

from app.models import PredictionRequest, PredictionResponse


async def fetch_historical_context(question: str) -> list:
    return []


async def persist_prediction(
    request: PredictionRequest, response: PredictionResponse
) -> None:
    pass
