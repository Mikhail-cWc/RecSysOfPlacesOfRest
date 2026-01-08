import logging

from app.agent.agent import PlacesRecommendationAgent
from app.api.dependencies import get_telegram_id_from_token
from app.api.schemas import (
    ClearSessionResponse,
    InteractionRequest,
    InteractionResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.core.database import DatabaseManager, get_db_manager
from app.middleware.rate_limit import limiter
from app.services.session import SessionManager
from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()


agent: PlacesRecommendationAgent = None
session_manager: SessionManager = None


def get_agent(db_manager: DatabaseManager = Depends(get_db_manager)) -> PlacesRecommendationAgent:
    global agent
    if agent is None:
        agent = PlacesRecommendationAgent(db_manager)
    return agent


def get_session_manager(db_manager: DatabaseManager = Depends(get_db_manager)) -> SessionManager:
    global session_manager
    if session_manager is None:
        session_manager = SessionManager(db_manager)
    return session_manager


@router.post("/send_message", response_model=SendMessageResponse)
@limiter.limit("20/minute")  # 20 запросов в минуту на пользователя
async def send_message(
    request: Request,
    payload: SendMessageRequest,
    telegram_id: int = Depends(get_telegram_id_from_token),
    agent: PlacesRecommendationAgent = Depends(get_agent),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """
    Эндпоинт для отправки сообщений.

    {
        "message": "Хочу уютное кафе",
        "latitude": 55.7558,  # опционально - если передано, сохраняется для будущих запросов
        "longitude": 37.6173  # опционально - если передано, сохраняется для будущих запросов
    }

    Если геоданные не переданы в запросе, используются сохраненные ранее геоданные пользователя.
    """
    try:
        chat_history = await session_mgr.get_chat_history(telegram_id)
        await session_mgr.add_message(telegram_id, "user", payload.message)

        user_latitude = payload.latitude
        user_longitude = payload.longitude

        if user_latitude is not None and user_longitude is not None:
            await session_mgr.save_user_location(telegram_id, user_latitude, user_longitude)
            logger.info(
                f"Saved location from request for user {telegram_id}: ({user_latitude}, {user_longitude})"
            )
        else:
            saved_location = await session_mgr.get_user_location(telegram_id)
            if saved_location:
                user_latitude = saved_location.get("latitude")
                user_longitude = saved_location.get("longitude")
                logger.info(
                    f"Using saved location for user {telegram_id}: ({user_latitude}, {user_longitude})"
                )

        result = await agent.process_message(
            message=payload.message,
            telegram_id=telegram_id,
            chat_history=chat_history,
            user_latitude=user_latitude,
            user_longitude=user_longitude,
        )

        response_text = result.get("text", "") if isinstance(result, dict) else result
        await session_mgr.add_message(telegram_id, "assistant", response_text)

        return SendMessageResponse(ok=True, response=result, telegram_id=telegram_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session", response_model=ClearSessionResponse)
async def clear_session(
    telegram_id: int = Depends(get_telegram_id_from_token),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """
    Очистить сессию текущего пользователя (включая историю чата и геолокацию).
    """
    try:
        await session_mgr.clear_session(telegram_id)
        await session_mgr.clear_user_location(telegram_id)

        return ClearSessionResponse(ok=True, message=f"Session cleared for user {telegram_id}")

    except Exception as e:
        logger.error(f"Error clearing session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/interaction", response_model=InteractionResponse)
@limiter.limit("60/minute")  # 60 запросов в минуту
async def save_interaction(
    request: Request,
    payload: InteractionRequest,
    telegram_id: int = Depends(get_telegram_id_from_token),
    db_manager: DatabaseManager = Depends(get_db_manager),
):
    """
    Сохранение взаимодействия пользователя с местом (like/dislike).

    {
        "place_id": 123,
        "interaction_type": "liked" | "disliked"
    }
    """
    from app.core.models import Place, Tag, UserInteraction, UserProfile, place_tags
    from sqlalchemy.orm import Session

    try:
        place_id = payload.place_id
        interaction_type = payload.interaction_type

        session: Session = db_manager.get_session()

        try:
            profile = session.query(UserProfile).filter_by(telegram_id=telegram_id).first()
            if not profile:
                profile = UserProfile(
                    telegram_id=telegram_id,
                    preferred_tags=[],
                    avoided_tags=[],
                    favorite_districts=[],
                )
                session.add(profile)
                session.flush()

            interaction = UserInteraction(
                telegram_id=telegram_id, place_id=place_id, interaction_type=interaction_type
            )
            session.add(interaction)

            place = session.query(Place).filter_by(id=place_id).first()
            if place:
                place_tags_query = (
                    session.query(Tag.name)
                    .join(place_tags, Tag.id == place_tags.c.tag_id)
                    .filter(place_tags.c.place_id == place_id)
                )
                place_tag_names = [tag.name for tag in place_tags_query.all()]

                if interaction_type == "liked":
                    if place_tag_names:
                        current_preferred = set(profile.preferred_tags or [])
                        current_avoided = set(profile.avoided_tags or [])

                        current_preferred.update(place_tag_names)

                        current_avoided -= set(place_tag_names)

                        profile.preferred_tags = list(current_preferred)
                        profile.avoided_tags = list(current_avoided)

                    if place.district:
                        current_districts = set(profile.favorite_districts or [])
                        current_districts.add(place.district)
                        profile.favorite_districts = list(current_districts)

                elif interaction_type == "disliked":
                    if place_tag_names:
                        current_avoided = set(profile.avoided_tags or [])
                        current_preferred = set(profile.preferred_tags or [])

                        current_avoided.update(place_tag_names)

                        current_preferred -= set(place_tag_names)

                        profile.avoided_tags = list(current_avoided)
                        profile.preferred_tags = list(current_preferred)

                logger.info(
                    f"Updated profile for user {telegram_id}: "
                    f"preferred_tags={len(profile.preferred_tags or [])}, "
                    f"avoided_tags={len(profile.avoided_tags or [])}, "
                    f"favorite_districts={len(profile.favorite_districts or [])}"
                )

            session.commit()

            logger.info(
                f"Saved {interaction_type} interaction: user={telegram_id}, place={place_id}"
            )

            return InteractionResponse(
                ok=True,
                interaction={
                    "telegram_id": telegram_id,
                    "place_id": place_id,
                    "interaction_type": interaction_type,
                },
            )

        finally:
            session.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving interaction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
