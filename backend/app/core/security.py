import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt
from app.core.config import settings
from passlib.context import CryptContext
from pydantic import BaseModel

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenData(BaseModel):
    """
    JWT токен данные.
    """

    telegram_id: int
    exp: Optional[datetime] = None


def create_access_token(telegram_id: int, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta is None:
        expires_delta = timedelta(days=7)

    expire = datetime.utcnow() + expires_delta
    to_encode = {"telegram_id": telegram_id, "exp": expire}

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        telegram_id: int = payload.get("telegram_id")

        if telegram_id is None:
            return None

        return TokenData(telegram_id=telegram_id)

    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None


def verify_telegram_bot_token(token: str) -> bool:
    return token == settings.BOT_API_TOKEN
