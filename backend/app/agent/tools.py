import logging
from typing import Any, Optional

from app.core.config import settings
from app.core.database import DatabaseManager
from app.core.models import Place, Tag, UserInteraction, UserProfile, place_tags
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter
from sqlalchemy import column, func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SearchTools:
    """
    Инструменты для поиска мест.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.openai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_EMBEDDING_BASE_URL
        )
        self.embedding_model = settings.OPENAI_EMBEDDING_MODEL

    def search_by_preferences(
        self, query: str, tags: Optional[list[str]] = None, min_rating: float = 4.0, limit: int = 25
    ) -> list[dict[str, Any]]:
        """
        Семантический поиск мест по описанию предпочтений.

        Используется для нечетких параметров (уютное, романтичное, необычное).
        """
        logger.info(f"search_by_preferences: query='{query}', tags={tags}, min_rating={min_rating}")

        try:
            embedding_response = self.openai_client.embeddings.create(
                model=self.embedding_model, input=query
            )
            query_vector = embedding_response.data[0].embedding

            qdrant = self.db_manager.get_qdrant()

            query_filter = None
            if min_rating > 0:
                conditions = []
                conditions.append(FieldCondition(key="rating", range={"gte": min_rating}))
                query_filter = Filter(must=conditions)

            qdrant_limit = limit * 3 if tags else limit

            search_results = qdrant.search(
                collection_name=settings.QDRANT_COLLECTION,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=qdrant_limit,
            )

            places = []
            for result in search_results:
                place = {
                    "id": result.id,
                    "name": result.payload.get("name"),
                    "description": result.payload.get("description"),
                    "tags": result.payload.get("tags"),
                    "district": result.payload.get("district"),
                    "rating": result.payload.get("rating"),
                    "reviews_count": result.payload.get("reviews_count"),
                    "similarity_score": result.score,
                }

                if tags:
                    place_tags_str = place.get("tags", "").lower()
                    # Проверяем, что хотя бы один из запрошенных тегов есть в строке тегов места
                    if any(tag.lower() in place_tags_str for tag in tags):
                        places.append(place)
                else:
                    places.append(place)

                if len(places) >= limit:
                    break

            logger.info(f"Found {len(places)} places by preferences (after tag filtering)")
            return places

        except Exception as e:
            logger.error(f"Error in search_by_preferences: {e}", exc_info=True)
            return []

    def search_by_geo(
        self,
        location: str,
        radius_meters: int = 1500,
        tags: Optional[list[str]] = None,
        min_rating: float = 4.0,
        limit: int = 50,
        user_latitude: Optional[float] = None,
        user_longitude: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """
        Поиск мест рядом с указанной локацией.

        Используется когда пользователь указывает конкретное место или хочет найти что-то рядом.
        """
        logger.info(f"search_by_geo: location='{location}', radius={radius_meters}m, tags={tags}")

        session: Session = self.db_manager.get_session()
        try:
            if (
                user_latitude
                and user_longitude
                and (
                    not location
                    or location.lower()
                    in ["текущая геолокация", "рядом со мной", "близко", "здесь", "тут"]
                )
            ):
                lat, lon = user_latitude, user_longitude
                logger.info(f"Using user location: ({lat}, {lon})")
            else:
                lat, lon = self._geocode_location(location)

            if lat is None or lon is None:
                logger.warning(f"Failed to geocode: {location}")
                return []

            sql_limit = limit * 3 if tags else limit

            query = select(
                column("id"),
                column("name"),
                column("rating"),
                column("distance_meters"),
                column("address"),
                column("district"),
                column("tag_list").label("tags"),
            ).select_from(
                func.find_places_nearby(lat, lon, radius_meters, min_rating, sql_limit).alias(
                    "places"
                )
            )

            result = session.execute(query)

            places = []
            for row in result:
                place_data = {
                    "id": row.id,
                    "name": row.name,
                    "rating": row.rating,
                    "distance_meters": row.distance_meters,
                    "address": row.address,
                    "district": row.district,
                    "tags": row.tags,
                }

                if tags:
                    place_tags_str = (row.tags or "").lower()
                    if any(tag.lower() in place_tags_str for tag in tags):
                        places.append(place_data)
                else:
                    places.append(place_data)

                if len(places) >= limit:
                    break

            logger.info(f"Found {len(places)} places by geo location (after tag filtering)")
            return places

        except Exception as e:
            logger.error(f"Error in search_by_geo: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def _geocode_location(self, location: str) -> tuple[Optional[float], Optional[float]]:
        """
        Геокодирование адреса.

        TODO: надо бы использовать полноценный геокодер (Яндекс.Карты API).
        """
        known_locations = {
            "кремль": (55.7520, 37.6175),
            "красная площадь": (55.7539, 37.6208),
            "пушкинская": (55.7657, 37.6039),
            "тверская": (55.7658, 37.6050),
            "арбат": (55.7503, 37.5892),
            "чистые пруды": (55.7642, 37.6430),
            "центр": (55.7558, 37.6173),
            "москва": (55.7558, 37.6173),
        }

        location_lower = location.lower()
        for key, coords in known_locations.items():
            if key in location_lower:
                logger.info(f"Geocoded '{location}' to {coords} using known location '{key}'")
                return coords

        fallback_coords = (55.7558, 37.6173)
        logger.warning(
            f"Location '{location}' not found in known locations, using fallback (Moscow center): {fallback_coords}"
        )
        return fallback_coords

    def get_user_profile(self, telegram_id: int) -> dict[str, Any]:
        """
        Получить профиль и историю пользователя.

        Используется для персонализации и когда запрос неопределенный.
        """
        logger.info(f"get_user_profile: telegram_id={telegram_id}")

        session: Session = self.db_manager.get_session()
        try:
            profile = session.query(UserProfile).filter_by(telegram_id=telegram_id).first()

            if not profile:
                return {
                    "telegram_id": telegram_id,
                    "preferred_tags": [],
                    "avoided_tags": [],
                    "favorite_districts": [],
                    "visited_places": [],
                    "is_empty": True,
                }

            interactions = (
                session.query(UserInteraction.place_id, UserInteraction.interaction_type)
                .filter(UserInteraction.telegram_id == telegram_id)
                .order_by(UserInteraction.created_at.desc())
                .limit(50)
                .all()
            )

            visited_places = [
                interaction.place_id
                for interaction in interactions
                if interaction.interaction_type in ("liked")
            ]

            result = {
                "telegram_id": profile.telegram_id,
                "preferred_tags": profile.preferred_tags or [],
                "avoided_tags": profile.avoided_tags or [],
                "favorite_districts": profile.favorite_districts or [],
                "visited_places": visited_places,
                "is_empty": False,
            }

            logger.info(f"Profile loaded: {len(visited_places)} visits")
            return result

        except Exception as e:
            logger.error(f"Error in get_user_profile: {e}", exc_info=True)
            return {
                "telegram_id": telegram_id,
                "preferred_tags": [],
                "avoided_tags": [],
                "favorite_districts": [],
                "visited_places": [],
                "is_empty": True,
            }
        finally:
            session.close()

    def rank_personalized(self, place_ids: list[int], telegram_id: int) -> list[dict[str, Any]]:
        """
        Переранжировать результаты с учетом профиля пользователя.

        Используется для returning users после получения кандидатов.
        """
        logger.info(f"rank_personalized: {len(place_ids)} мест для user {telegram_id}")

        session: Session = self.db_manager.get_session()
        try:
            if not place_ids:
                return []

            profile = self.get_user_profile(telegram_id)

            tags_subquery = (
                session.query(
                    place_tags.c.place_id,
                    func.array_agg(Tag.name).label("tags_array"),
                )
                .join(Tag, place_tags.c.tag_id == Tag.id)
                .group_by(place_tags.c.place_id)
                .subquery()
            )

            query = (
                session.query(
                    Place.id,
                    Place.name,
                    Place.rating,
                    Place.reviews_count,
                    Place.district,
                    Place.address,
                    tags_subquery.c.tags_array,
                )
                .outerjoin(tags_subquery, Place.id == tags_subquery.c.place_id)
                .filter(Place.id.in_(place_ids))
            )

            results = query.all()

            places = []
            for row in results:
                places.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "rating": row.rating,
                        "reviews_count": row.reviews_count,
                        "district": row.district,
                        "address": row.address,
                        "tags": (
                            row.tags_array
                            if row.tags_array and row.tags_array[0] is not None
                            else []
                        ),
                    }
                )

            preferred_tags = set(profile.get("preferred_tags", []))
            avoided_tags = set(profile.get("avoided_tags", []))
            favorite_districts = set(profile.get("favorite_districts", []))

            for place in places:
                current_place_tags = set(place.get("tags") or [])

                # Базовый скор - рейтинг
                base_score = place["rating"] / 5.0

                # Бонус за совпадение с предпочтениями
                tag_overlap = len(current_place_tags & preferred_tags)
                tag_bonus = 0.2 * min(tag_overlap / max(len(preferred_tags), 1), 1.0)

                # Штраф за избегаемые теги
                avoided_overlap = len(current_place_tags & avoided_tags)
                tag_penalty = 0.3 * (avoided_overlap / max(len(current_place_tags), 1))

                # Бонус за любимый район
                district_bonus = 0.15 if place.get("district") in favorite_districts else 0

                # Бонус за популярность
                popularity_score = min(place["reviews_count"] / 100, 1.0) * 0.1

                # Итоговый скор
                personalization_score = (
                    base_score + tag_bonus - tag_penalty + district_bonus + popularity_score
                )

                place["personalization_score"] = max(0, min(1, personalization_score))

            places.sort(key=lambda x: x["personalization_score"], reverse=True)

            logger.info(f"Ranking completed: {len(places)} places")
            return places

        except Exception as e:
            logger.error(f"Error in rank_personalized: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def get_places_details(self, place_ids: list[int]) -> list[dict[str, Any]]:
        """
        Получить полную информацию о местах по их ID.
        """
        logger.info(f"get_places_details: {len(place_ids)} places")

        if not place_ids:
            return []

        session: Session = None
        try:
            session = self.db_manager.get_session()

            tags_subquery = (
                session.query(
                    place_tags.c.place_id,
                    func.array_agg(Tag.name).label("tags_array"),
                )
                .join(Tag, place_tags.c.tag_id == Tag.id)
                .group_by(place_tags.c.place_id)
                .subquery()
            )

            query = (
                session.query(
                    Place.id,
                    Place.name,
                    Place.rating,
                    Place.reviews_count,
                    Place.district,
                    Place.address,
                    Place.phone,
                    Place.website,
                    Place.working_hours,
                    tags_subquery.c.tags_array,
                )
                .outerjoin(tags_subquery, Place.id == tags_subquery.c.place_id)
                .filter(Place.id.in_(place_ids))
            )

            results = query.all()

            places = []
            for row in results:
                places.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "rating": row.rating,
                        "reviews_count": row.reviews_count,
                        "district": row.district,
                        "address": row.address,
                        "phone": row.phone,
                        "website": row.website,
                        "working_hours": row.working_hours,
                        "tags": (
                            row.tags_array
                            if row.tags_array and row.tags_array[0] is not None
                            else []
                        ),
                    }
                )

            logger.info(f"Retrieved {len(places)} places details")
            return places

        except Exception as e:
            logger.error(f"Error in get_places_details (DB unavailable): {e}", exc_info=True)
            return []
        finally:
            if session:
                try:
                    session.close()
                except Exception:
                    pass

    def get_all_tags(self) -> list[str]:
        """
        Получить список всех доступных тегов из базы данных.
        """
        logger.info("get_all_tags: loading tags from database")

        session: Session = None
        try:
            session = self.db_manager.get_session()
            tags = session.query(Tag.name).order_by(Tag.name).all()
            tag_list = [tag[0] for tag in tags]
            logger.info(f"Loaded {len(tag_list)} tags")
            return tag_list
        except Exception as e:
            logger.error(f"Error loading tags: {e}", exc_info=True)
            return []
        finally:
            if session:
                try:
                    session.close()
                except Exception:
                    pass

    def get_all_districts(self) -> list[str]:
        """
        Получить список всех районов из базы данных.
        """
        logger.info("get_all_districts: loading districts from database")

        session: Session = None
        try:
            session = self.db_manager.get_session()
            districts = (
                session.query(Place.district)
                .filter(Place.district.isnot(None))
                .distinct()
                .order_by(Place.district)
                .all()
            )
            district_list = [d[0] for d in districts if d[0]]
            logger.info(f"Loaded {len(district_list)} districts")
            return district_list
        except Exception as e:
            logger.error(f"Error loading districts: {e}", exc_info=True)
            return []
        finally:
            if session:
                try:
                    session.close()
                except Exception:
                    pass
