import json
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import DatabaseManager

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Менеджер сессий пользователей.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def get_session_key(self, telegram_id: int) -> str:
        return f"session:{telegram_id}"

    async def get_chat_history(self, telegram_id: int) -> list[dict[str, str]]:
        try:
            redis = await self.db_manager.get_redis()
            session_key = await self.get_session_key(telegram_id)

            history_json = await redis.get(session_key)

            if history_json:
                return json.loads(history_json)
            return []

        except Exception as e:
            logger.error(f"Error getting history: {e}", exc_info=True)
            return []

    async def add_message(self, telegram_id: int, role: str, content: str):
        try:
            redis = await self.db_manager.get_redis()
            session_key = await self.get_session_key(telegram_id)

            history = await self.get_chat_history(telegram_id)

            history.append(
                {"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()}
            )

            if len(history) > 20:
                history = history[-20:]

            await redis.setex(
                session_key, settings.SESSION_TTL, json.dumps(history, ensure_ascii=False)
            )

        except Exception as e:
            logger.error(f"Error adding message: {e}", exc_info=True)

    async def clear_session(self, telegram_id: int):
        try:
            redis = await self.db_manager.get_redis()
            session_key = await self.get_session_key(telegram_id)

            await redis.delete(session_key)
            logger.info(f"Session cleared for user {telegram_id}")

        except Exception as e:
            logger.error(f"Error clearing session: {e}", exc_info=True)

    async def get_location_key(self, telegram_id: int) -> str:
        return f"location:{telegram_id}"

    async def save_user_location(self, telegram_id: int, latitude: float, longitude: float) -> None:
        try:
            redis = await self.db_manager.get_redis()
            location_key = await self.get_location_key(telegram_id)

            location_data = {"latitude": latitude, "longitude": longitude}
            await redis.setex(
                location_key,
                settings.SESSION_TTL,
                json.dumps(location_data, ensure_ascii=False),
            )
            logger.info(f"Saved location for user {telegram_id}: ({latitude}, {longitude})")

        except Exception as e:
            logger.error(f"Error saving location: {e}", exc_info=True)

    async def get_user_location(self, telegram_id: int) -> dict[str, float] | None:
        try:
            redis = await self.db_manager.get_redis()
            location_key = await self.get_location_key(telegram_id)

            location_json = await redis.get(location_key)

            if location_json:
                location_data = json.loads(location_json)
                logger.info(
                    f"Retrieved location for user {telegram_id}: "
                    f"({location_data.get('latitude')}, {location_data.get('longitude')})"
                )
                return location_data
            return None

        except Exception as e:
            logger.error(f"Error getting location: {e}", exc_info=True)
            return None

    async def clear_user_location(self, telegram_id: int) -> None:
        try:
            redis = await self.db_manager.get_redis()
            location_key = await self.get_location_key(telegram_id)

            await redis.delete(location_key)
            logger.info(f"Cleared location for user {telegram_id}")

        except Exception as e:
            logger.error(f"Error clearing location: {e}", exc_info=True)
