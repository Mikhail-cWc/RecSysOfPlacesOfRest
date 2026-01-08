import logging
from typing import Optional

from app.core.security import TokenData, verify_telegram_bot_token, verify_token
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """
    Получить текущего пользователя из JWT токена.
    """
    token = credentials.credentials

    token_data = verify_token(token)

    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data


async def verify_bot_token(x_bot_token: Optional[str] = Header(None)) -> bool:
    """
    Проверить, что запрос от Telegram бота (внутренний запрос).
    """
    if not x_bot_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bot token required",
        )

    if not verify_telegram_bot_token(x_bot_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bot token",
        )

    return True


async def get_telegram_id_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """
    Получить telegram_id из JWT токена.
    """
    token_data = await get_current_user(credentials)
    return token_data.telegram_id
