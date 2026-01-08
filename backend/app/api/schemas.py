from typing import Optional

from pydantic import BaseModel, Field, model_validator


class SendMessageRequest(BaseModel):
    """
    Запрос на отправку сообщения.
    """

    message: str = Field(..., min_length=1, max_length=5000)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "SendMessageRequest":
        """
        Validate that both latitude and longitude are provided together.

        :raises ValueError: if only one of latitude/longitude is provided
        :return: validated model instance
        """
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Both latitude and longitude must be provided together")
        return self


class SendMessageResponse(BaseModel):
    """
    Ответ на отправку сообщения.
    """

    ok: bool
    response: dict
    telegram_id: int


class InteractionRequest(BaseModel):
    """
    Запрос на сохранение взаимодействия пользователя с местом.
    """

    place_id: int = Field(..., gt=0)
    interaction_type: str = Field(..., pattern="^(liked|disliked)$")


class InteractionResponse(BaseModel):
    """
    Ответ на сохранение взаимодействия.
    """

    ok: bool
    interaction: dict


class ClearSessionResponse(BaseModel):
    """
    Ответ на очистку сессии.
    """

    ok: bool
    message: str
