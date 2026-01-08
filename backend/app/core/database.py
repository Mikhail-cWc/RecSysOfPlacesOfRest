import logging
from typing import Optional

import redis.asyncio as aioredis
from app.core.config import settings
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Менеджер подключений к базам данных"""

    def __init__(self):
        self._qdrant_client: Optional[QdrantClient] = None
        self._redis_client: Optional[aioredis.Redis] = None
        self._engine = None
        self._session_factory = None

    def get_engine(self):
        if self._engine is None:
            self._engine = create_engine(
                settings.postgres_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
            logger.info("SQLAlchemy engine created")
        return self._engine

    def get_session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            engine = self.get_engine()
            self._session_factory = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
            )
            logger.info("SQLAlchemy session factory created")
        return self._session_factory

    def get_session(self) -> Session:
        factory = self.get_session_factory()
        return factory()

    def get_qdrant(self) -> QdrantClient:
        if self._qdrant_client is None:
            self._qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            logger.info("Qdrant client created")
        return self._qdrant_client

    async def get_redis(self) -> aioredis.Redis:
        if self._redis_client is None:
            self._redis_client = await aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
            logger.info("Redis client created")
        return self._redis_client

    def close_all(self):
        if self._engine:
            self._engine.dispose()
            logger.info("SQLAlchemy engine closed")

        if self._qdrant_client:
            self._qdrant_client.close()
            logger.info("Qdrant client closed")


db_manager = DatabaseManager()


def get_db_manager() -> DatabaseManager:
    return db_manager
