import logging

from app.api.dependencies import verify_bot_token
from app.core.security import create_access_token
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class TelegramLoginRequest(BaseModel):
    """
    Запрос на создание JWT токена для пользователя TG.
    """

    telegram_id: int


class TokenResponse(BaseModel):
    """
    Ответ с JWT токеном.
    """

    access_token: str
    token_type: str = "bearer"


@router.post("/telegram/login", response_model=TokenResponse)
async def telegram_login(
    request: TelegramLoginRequest,
    _bot_verified: bool = Depends(verify_bot_token),
):
    """
    Создать JWT токен для пользователя Telegram.

    Этот эндпоинт доступен только для внутренних запросов от Telegram бота.
    Бот должен передать X-Bot-Token в заголовке.
    """
    try:
        access_token = create_access_token(telegram_id=request.telegram_id)

        logger.info(f"JWT token created for user {request.telegram_id}")

        return TokenResponse(access_token=access_token)

    except Exception as e:
        logger.error(f"Error creating token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create token",
        )
