import logging

from app.core.database import DatabaseManager, get_db_manager
from fastapi import APIRouter, Depends
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check(db_manager: DatabaseManager = Depends(get_db_manager)):
    status = {"status": "healthy", "services": {}}

    # PostgreSQL
    try:
        session = db_manager.get_session()
        try:
            session.execute(text("SELECT 1"))
            status["services"]["postgresql"] = "ok"
        finally:
            session.close()
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        status["services"]["postgresql"] = "error"
        status["status"] = "unhealthy"

    # Qdrant
    try:
        qdrant = db_manager.get_qdrant()
        qdrant.get_collections()
        status["services"]["qdrant"] = "ok"
    except Exception as e:
        logger.error(f"Qdrant health check failed: {e}")
        status["services"]["qdrant"] = "error"
        status["status"] = "unhealthy"

    # Redis
    try:
        redis = await db_manager.get_redis()
        await redis.ping()
        status["services"]["redis"] = "ok"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        status["services"]["redis"] = "error"
        status["status"] = "unhealthy"

    return status
