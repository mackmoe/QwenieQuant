from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import postgres
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await postgres.startup()
    yield
    await postgres.shutdown()


app = FastAPI(title="Reflection Engine", lifespan=lifespan)
app.include_router(router)
