import logging
from contextlib import asynccontextmanager

from app.api.routes import auth, health, telegram
from app.core.config import settings
from app.core.database import db_manager
from app.core.models import Base
from app.core.tracing import (
    init_phoenix_tracing,
    instrument_langchain,
    instrument_openai,
)
from app.middleware.rate_limit import setup_rate_limiting
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    logger.info(f"Mode: {'DEBUG' if settings.DEBUG else 'PRODUCTION'}")

    init_phoenix_tracing()
    instrument_langchain()
    instrument_openai()

    try:
        engine = db_manager.get_engine()
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise

    yield
    logger.info("Stopping application...")


app = FastAPI(
    title="Places Recommendation Bot",
    description="LLM-агент для рекомендаций мест досуга через Telegram",
    version="1.0.0",
    lifespan=lifespan,
)

setup_rate_limiting(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Bot-Token"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])


@app.get("/")
async def root():
    return {"service": "Places Recommendation API", "version": "1.0.0", "status": "running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
