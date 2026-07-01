from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import postgres
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await postgres.startup()
    yield
    await postgres.shutdown()


app = FastAPI(
    title="Prediction API",
    description="AI Core service. Transforms structured prediction requests into structured AI predictions.",
    version="0.1.0",
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(router)
