import logging
from typing import Optional

from app.agent.tools import SearchTools
from app.core.config import settings
from app.core.database import DatabaseManager
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import StructuredTool, Tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchByPreferencesInput(BaseModel):
    """
    Входные данные для инструмента search_by_preferences.
    """

    query: str = Field(description="Описание предпочтений в свободной форме на русском языке")
    tags: Optional[list[str]] = Field(default=None, description="Список тегов для фильтрации")
    min_rating: float = Field(default=4.0, description="Минимальный рейтинг (0-5)")
    limit: int = Field(default=50, description="Максимальное количество результатов")


class SearchByGeoInput(BaseModel):
    """
    Входные данные для инструмента search_by_geo.
    """

    location: str = Field(description="Адрес или название места (например, 'Кремль', 'Пушкинская')")
    radius_meters: int = Field(default=1500, description="Радиус поиска в метрах")
    tags: Optional[list[str]] = Field(default=None, description="Фильтр по типу места")
    min_rating: float = Field(default=4.0, description="Минимальный рейтинг (0-5)")
    limit: int = Field(default=50, description="Максимальное количество результатов")


class PlacesRecommendationAgent:
    """
    LLM-агент для рекомендаций мест досуга.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.search_tools = SearchTools(db_manager)

        self.llm = ChatOpenAI(
            base_url=settings.LLM_BASE_URL,
            model=settings.OPENAI_MODEL,
            temperature=settings.OPENAI_TEMPERATURE,
            api_key=settings.OPENAI_API_KEY,
        )

        self.available_tags = self.search_tools.get_all_tags()
        self.available_districts = self.search_tools.get_all_districts()

        self.prompt = self._create_prompt()

        self.user_coordinates = {}

    def _create_tools(
        self,
        telegram_id: Optional[int] = None,
        user_latitude: Optional[float] = None,
        user_longitude: Optional[float] = None,
    ) -> list[StructuredTool]:

        def get_user_profile_tool(dummy: str = "") -> dict:
            """
            Получить профиль пользователя.

            dummy: Фиктивный параметр (игнорируется)
            """
            if telegram_id is None:
                raise ValueError("telegram_id not provided for get_user_profile")

            return self.search_tools.get_user_profile(telegram_id)

        def rank_personalized_tool(tool_input: str) -> list[dict]:
            """
            Переранжировать места с учетом профиля пользователя.
            """
            import json

            try:
                if isinstance(tool_input, str):
                    data = json.loads(tool_input)
                elif isinstance(tool_input, dict):
                    data = tool_input
                else:
                    raise ValueError(f"Unexpected input type: {type(tool_input)}")

                place_ids = data.get("place_ids", [])
            except (json.JSONDecodeError, AttributeError) as e:
                raise ValueError(f"Invalid input format: {e}")

            if not place_ids:
                raise ValueError("place_ids is required for rank_personalized")

            if telegram_id is None:
                raise ValueError("telegram_id not provided for rank_personalized")

            if isinstance(place_ids, list):
                place_ids = [int(pid) if isinstance(pid, str) else pid for pid in place_ids]

            return self.search_tools.rank_personalized(place_ids, telegram_id)

        tags_description = ""
        if self.available_tags:
            tags_description = f"\n\nДОСТУПНЫЕ ТЕГИ В БАЗЕ ({len(self.available_tags)} всего):\n"
            tags_description += ", ".join(self.available_tags)

        districts_description = ""
        if self.available_districts:
            districts_description = (
                f"\n\nДОСТУПНЫЕ РАЙОНЫ В БАЗЕ ({len(self.available_districts)} всего):\n"
            )
            districts_description += ", ".join(self.available_districts)

        def search_by_geo_wrapper(
            location: str,
            radius_meters: int = 1500,
            tags: Optional[list[str]] = None,
            min_rating: float = 4.0,
            limit: int = 50,
        ) -> list[dict]:
            """
            Поиск мест рядом с адресом или координатами пользователя.
            """
            import json

            if location and location.strip().startswith("{") and location.strip().endswith("}"):
                try:
                    data = json.loads(location)
                    location = data.get("location", location)
                    radius_meters = data.get("radius_meters", radius_meters)
                    tags = data.get("tags", tags)
                    min_rating = data.get("min_rating", min_rating)
                    limit = data.get("limit", limit)
                    logger.info(
                        f"Parsed JSON from location param: location={location}, tags={tags}"
                    )
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning(f"Failed to parse JSON from location: {e}")

            return self.search_tools.search_by_geo(
                location=location,
                radius_meters=radius_meters,
                tags=tags,
                min_rating=min_rating,
                limit=limit,
                user_latitude=user_latitude,
                user_longitude=user_longitude,
            )

        return [
            StructuredTool.from_function(
                func=self.search_tools.search_by_preferences,
                name="search_by_preferences",
                description=f"""Семантический поиск мест по описанию предпочтений.
                
КОГДА ИСПОЛЬЗОВАТЬ:
- Есть нечеткие параметры (уютное, романтичное, необычное, стильное, активный отдых, лыжи, etc)
- Пользователь описывает атмосферу, стиль или тип активности
- Нужен поиск по смыслу, а не по точным тегам

ВАЖНО: используй русский язык в параметре query!
{tags_description}

Возвращает список мест с полями: id, name, description, tags, district, rating, similarity_score""",
                args_schema=SearchByPreferencesInput,
            ),
            StructuredTool.from_function(
                func=search_by_geo_wrapper,
                name="search_by_geo",
                description=f"""Поиск мест рядом с адресом или координатами.
                
КОГДА ИСПОЛЬЗОВАТЬ:
- Указана конкретная локация (адрес, метро, район, достопримечательность)
- Нужен поиск "рядом с" или "недалеко от"
- География - главный критерий
- Пользователь хочет найти места "рядом со мной" или "близко"

ВАЖНО: Если пользователь хочет найти места "рядом со мной" или не указывает конкретное место, 
используй location="текущая геолокация" - система автоматически использует координаты пользователя если они доступны.
{districts_description}

Возвращает список мест с полями: id, name, rating, distance_meters, address, district, tags""",
                args_schema=SearchByGeoInput,
            ),
            Tool(
                name="get_user_profile",
                func=get_user_profile_tool,
                description="""Получить профиль и историю пользователя.
                
КОГДА ИСПОЛЬЗОВАТЬ:
- Запрос неопределенный (нужен контекст предпочтений)
- Returning user (для персонализации)
- Пользователь ссылается на прошлый опыт

ВАЖНО: не требует параметров - просто вызывай без input или с пустой строкой

Возвращает профиль с полями: preferred_tags, avoided_tags, favorite_districts, visited_places, is_empty""",
            ),
            Tool(
                name="rank_personalized",
                func=rank_personalized_tool,
                description="""Переранжировать результаты с учетом профиля пользователя.
                
КОГДА ИСПОЛЬЗОВАТЬ:
- После получения кандидатов из search_by_preferences или search_by_geo
- Для returning users (когда is_empty=False в профиле)
- Когда нужна персонализация рекомендаций

ВАЖНО: требуется только place_ids в формате JSON: {"place_ids": [123, 456, 789]}
Telegram_id автоматически используется для текущего пользователя

Возвращает отранжированный список мест с дополнительным полем personalization_score""",
            ),
        ]

    def _create_prompt(self) -> PromptTemplate:
        """
        Создание системного промпта для ReAct агента.
        """
        tags_info = ""
        if self.available_tags:
            tags_info = (
                f"\n\nДОСТУПНЫЕ ТЕГИ В БАЗЕ ({len(self.available_tags)} всего):\n"
                + ", ".join(self.available_tags)
            )

        districts_info = ""
        if self.available_districts:
            districts_info = (
                f"\n\nДОСТУПНЫЕ РАЙОНЫ В БАЗЕ ({len(self.available_districts)} всего):\n"
                + ", ".join(self.available_districts)
            )

        template = f"""Ты ассистент по выбору мест досуга в Москве. У тебя есть база из 60,000+ мест.{tags_info}{districts_info}

================================
КРИТИЧЕСКИ ВАЖНО!!!
================================
ТЫ ДОЛЖЕН ОБЯЗАТЕЛЬНО ИСПОЛЬЗОВАТЬ ИНСТРУМЕНТЫ (tools) ДЛЯ ПОИСКА МЕСТ!
НИКОГДА не придумывай места из головы - ВСЕГДА вызывай search_by_preferences или search_by_geo!

================================
ТВОЯ РОЛЬ
================================
1. Понять предпочтения пользователя через диалог
2. ОБЯЗАТЕЛЬНО использовать инструменты (tools) для поиска
3. Предлагать найденные места

================================
ОБЯЗАТЕЛЬНЫЙ АЛГОРИТМ
================================
ДЛЯ КАЖДОГО ЗАПРОСА О МЕСТАХ:

1. АНАЛИЗ: что хочет пользователь?
2. ОЦЕНКА: достаточно ли информации для поиска?
   - Если запрос СЛИШКОМ НЕЯСЕН (например: "хочу куда-то", "что посоветуешь?", "скучно") → ЗАДАЙ УТОЧНЯЮЩИЙ ВОПРОС
   - Если есть хоть какие-то критерии (место, атмосфера, активность) → продолжай к шагу 3
3. ВЫБОР ИНСТРУМЕНТА:
   - Если упоминается атмосфера/стиль/активность → search_by_preferences
   - Если указана конкретная локация → search_by_geo
4. ВЫЗОВ ИНСТРУМЕНТА с правильными параметрами
5. ОТВЕТ на основе полученных результатов

================================
ПРИМЕРЫ
================================

Пример 1: НЕЯСНЫЙ ЗАПРОС - задаём вопрос
User: "Хочу куда-то сходить"
Thought: Запрос слишком неясен - нет никаких критериев. Нужно уточнить
Final Answer: [TYPE: question]
Подскажи, какой отдых тебе интересен? Например:
- Кафе или ресторан?
- Культурное место (музей, театр)?
- Активный отдых?
- Или что-то ещё?

Пример 2: ЕСТЬ КРИТЕРИИ - ищем места
User: "Хочу активный отдых, может быть лыжи?"
Thought: Пользователь хочет активный отдых и лыжи - есть конкретные критерии, нужен семантический поиск
Action: search_by_preferences
Action Input: {{{{"query": "активный отдых лыжи сноуборд", "min_rating": 4.0, "limit": 50}}}}
Observation: [список найденных мест...]
Thought: Нашёл подходящие места. Дам краткий ответ без деталей - они будут в карточках
Final Answer: [TYPE: recommendation]
Нашёл для тебя несколько отличных мест для активного отдыха с лыжами! Смотри варианты ниже 👇

Пример 3: ЛОКАЦИЯ - геопоиск
User: "Кафе рядом с Кремлем"
Thought: Указана конкретная локация (Кремль) - нужен геопоиск
Action: search_by_geo
Action Input: {{{{"location": "Кремль", "radius_meters": 1500, "min_rating": 4.0, "limit": 50}}}}
Observation: [список найденных мест...]
Thought: Нашёл кафе рядом с Кремлём. Дам краткий ответ
Final Answer: [TYPE: recommendation]
Вот уютные кафе неподалёку от Кремля 😊

Пример 4: ИСПОЛЬЗОВАНИЕ ПРОФИЛЯ
User: "Напомни, где я был?"
Thought: Пользователь хочет вспомнить свои предпочтения - нужен профиль
Action: get_user_profile
Action Input: ""
Observation: {{{{"preferred_tags": ["кафе", "бары"], "visited_places": [123, 456], "is_empty": false}}}}
Thought: У пользователя есть история. Могу предложить похожие места
Final Answer: [TYPE: recommendation]
Вижу, тебе нравятся кафе и бары! Вот несколько новых мест в этом стиле 😊

Пример 5: ПЕРСОНАЛИЗИРОВАННОЕ РАНЖИРОВАНИЕ
User: "Покажи кафе в центре"
Thought: Нужен геопоиск в центре
Action: search_by_geo
Action Input: {{{{"location": "центр", "radius_meters": 2000, "tags": ["Кафе"], "min_rating": 4.0, "limit": 50}}}}
Observation: [список из 50 кафе с их id...]
Thought: Много результатов. Если у пользователя есть история, можно переранжировать
Action: get_user_profile
Action Input: ""
Observation: {{{{"is_empty": false, "preferred_tags": ["Кафе", "Бары"]}}}}
Thought: У пользователя есть профиль, переранжирую результаты
Action: rank_personalized
Action Input: {{{{"place_ids": [123, 456, 789, ...]}}}}
Observation: [отранжированный список с personalization_score...]
Thought: Готово! Даю персонализированные рекомендации
Final Answer: [TYPE: recommendation]
Нашёл для тебя кафе в центре, отсортированные по твоим предпочтениям! 😊

================================
ПРАВИЛА (ОБЯЗАТЕЛЬНЫ К ВЫПОЛНЕНИЮ!)
================================
✓ Если запрос слишком неясен - ЗАДАЙ УТОЧНЯЮЩИЙ ВОПРОС (используй [TYPE: question])
✓ Если запрос содержит хоть какие-то критерии - вызывай tools для поиска
✓ НЕ придумывай места - используй ТОЛЬКО результаты tools
✓ Если tools вернули пустой результат - скажи об этом и предложи расширить поиск
✓ Используй русский язык в параметре query для search_by_preferences
✓ Используй ТОЛЬКО параметры, определенные в схеме инструмента (не добавляй query в search_by_geo!)

ВАЖНО ПРИ РЕКОМЕНДАЦИИ МЕСТ:
✓ НЕ описывай подробно каждое место в тексте - места будут показаны отдельно в карточках
✓ Дай краткий вводный текст (1-2 предложения) о том, что нашёл
✓ Можешь упомянуть общие характеристики (например: "Нашёл 5 уютных кафе в центре")
✓ НЕ перечисляй названия, адреса, теги и описания мест - это будет в карточках

У тебя есть доступ к следующим инструментам:

{{tools}}

Используй следующий формат СТРОГО:

Question: входной вопрос/запрос пользователя
Thought: подумай, что нужно сделать
Action: действие из [{{tool_names}}]
Action Input: ввод для действия в формате JSON
Observation: результат действия
... (этот Thought/Action/Action Input/Observation может повторяться N раз)
Thought: Теперь я знаю окончательный ответ
Final Answer: [TYPE: question|recommendation]
окончательный ответ на основе результатов инструментов (не придумывай места!)

КРИТИЧЕСКИ ВАЖНО О ФОРМАТЕ:
- После каждого "Thought:" ОБЯЗАТЕЛЬНО должен быть "Action:" (если еще не готов к финальному ответу)
- ИЛИ после "Thought:" должен быть "Final Answer:" (если готов дать финальный ответ)
- НИКОГДА не пиши только "Thought:" без последующего "Action:" или "Final Answer:"
- Формат Action Input должен быть валидным JSON

ВАЖНО: В начале Final Answer ОБЯЗАТЕЛЬНО укажи тип ответа:
- [TYPE: question] - если задаешь уточняющий вопрос пользователю (запрос неясен, нужны дополнительные детали)
- [TYPE: recommendation] - если предлагаешь конкретные места для посещения (нашел места через инструменты и готов их рекомендовать)

================================
ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ
================================
Инструменты get_user_profile и rank_personalized автоматически работают с текущим пользователем.
Тебе НЕ НУЖНО передавать telegram_id - он уже встроен в инструменты!

Начнем!

Question: {{input}}
Thought:{{agent_scratchpad}}"""

        return PromptTemplate.from_template(template)

    def _handle_parsing_error(self, error: Exception) -> str:
        error_str = str(error)
        logger.warning(f"Parsing error: {error_str}")

        return (
            "ОШИБКА ФОРМАТА! Ты должен строго следовать формату ReAct:\n"
            "Thought: твоя мысль\n"
            "Action: название_инструмента\n"
            "Action Input: JSON с параметрами\n"
            "Observation: результат\n\n"
            "ИЛИ если готов дать финальный ответ:\n"
            "Thought: Теперь я знаю окончательный ответ\n"
            "Final Answer: [TYPE: question|recommendation]\n"
            "твой ответ\n\n"
            "Повтори попытку с правильным форматом."
        )

    def create_executor(
        self,
        telegram_id: int,
        user_latitude: Optional[float] = None,
        user_longitude: Optional[float] = None,
    ) -> AgentExecutor:
        """
        Создание executor для конкретного пользователя с инъекцией telegram_id и координат.
        """
        tools = self._create_tools(
            telegram_id=telegram_id, user_latitude=user_latitude, user_longitude=user_longitude
        )

        agent = create_react_agent(llm=self.llm, tools=tools, prompt=self.prompt)

        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=settings.DEBUG,
            max_iterations=10,
            max_execution_time=60,
            return_intermediate_steps=True,
            handle_parsing_errors=self._handle_parsing_error,
        )

        return executor

    async def process_message(
        self,
        message: str,
        telegram_id: int,
        chat_history: Optional[list[dict[str, str]]] = None,
        user_latitude: Optional[float] = None,
        user_longitude: Optional[float] = None,
    ) -> dict:
        """
        Обработка сообщения пользователя.

        dict: Ответ агента с текстом и структурированными данными о местах
            {
                "text": "текстовый ответ",
                "places": [список мест с полной информацией],
                "response_type": "question" | "recommendation"
            }
        """
        try:
            logger.info(f"User {telegram_id} sent message: {message[:50]}...")

            if user_latitude and user_longitude:
                logger.info(f"User location: ({user_latitude}, {user_longitude})")

            executor = self.create_executor(telegram_id, user_latitude, user_longitude)

            input_text = message
            if chat_history:
                history_context = "Контекст предыдущего диалога:\n"
                for msg in chat_history[-4:]:
                    role = "Пользователь" if msg["role"] == "user" else "Ассистент"
                    history_context += f"{role}: {msg['content']}\n"
                input_text = history_context + f"\nТекущий запрос: {message}"

            input_dict = {"input": input_text}

            result = await executor.ainvoke(input_dict)

            response_text = result.get("output", "Извините, произошла ошибка. Попробуйте еще раз.")

            places = self._extract_places_from_result(result)

            response_type = self._parse_response_type(response_text, places)

            cleaned_text = self._clean_response_text(response_text)

            logger.info(
                f"Response generated: type={response_type}, text={cleaned_text[:100]}... with {len(places)} places"
            )

            return {"text": cleaned_text, "places": places, "response_type": response_type}

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "text": "Извините, произошла техническая ошибка. Пожалуйста, попробуйте снова через несколько секунд.",
                "places": [],
                "response_type": "question",
            }

    def _extract_places_from_result(self, result: dict) -> list[dict]:
        """
        Извлечение информации о местах из результата выполнения агента.
        """
        places = []
        seen_ids = set()

        intermediate_steps = result.get("intermediate_steps", [])

        for step in intermediate_steps:
            if len(step) >= 2:
                action, observation = step[0], step[1]

                if isinstance(observation, list):
                    for place in observation:
                        if isinstance(place, dict) and "id" in place:
                            place_id = place["id"]
                            if place_id not in seen_ids:
                                seen_ids.add(place_id)
                                places.append(place)

        places = places[:10]

        if places:
            place_ids = [p["id"] for p in places]
            try:
                detailed_places = self.search_tools.get_places_details(place_ids)

                if detailed_places:
                    details_map = {p["id"]: p for p in detailed_places}

                    enriched_places = []
                    for place in places:
                        place_id = place["id"]
                        if place_id in details_map:
                            enriched = details_map[place_id].copy()

                            if "similarity_score" in place:
                                enriched["similarity_score"] = place["similarity_score"]
                            if "personalization_score" in place:
                                enriched["personalization_score"] = place["personalization_score"]
                            if "distance_meters" in place:
                                enriched["distance_meters"] = place["distance_meters"]

                            enriched_places.append(enriched)
                        else:
                            enriched_places.append(place)

                    return enriched_places
                else:
                    logger.warning(
                        "DB unavailable or returned empty results, using search results as-is"
                    )
                    return places
            except Exception as e:
                logger.error(f"Error enriching places from DB: {e}", exc_info=True)
                return places

        return places

    def _parse_response_type(self, response_text: str, places: list[dict]) -> str:
        """
        Определяет тип ответа агента на основе текста и наличия мест.
        """
        if "[TYPE: question]" in response_text:
            return "question"
        if "[TYPE: recommendation]" in response_text:
            return "recommendation"

        if places and len(places) > 0:
            return "recommendation"

        return "question"

    def _clean_response_text(self, response_text: str) -> str:
        """
        Удаляет маркеры типа ответа из текста для пользователя.
        """
        cleaned = response_text.replace("[TYPE: question]", "").replace(
            "[TYPE: recommendation]", ""
        )

        cleaned = cleaned.strip()
        return cleaned
