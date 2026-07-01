from fastapi import FastAPI

from app.routes import router

app = FastAPI(
    title="Prediction API",
    description="AI Core service. Transforms structured prediction requests into structured AI predictions.",
    version="0.1.0",
    redoc_url=None,
)

app.include_router(router)
