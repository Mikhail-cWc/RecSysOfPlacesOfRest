import asyncio
import logging
import os
import sys

import httpx
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
BOT_API_TOKEN = os.getenv("BOT_API_TOKEN", "")


class PlacesBot:
    """
    Telegram бот для рекомендаций мест.
    """

    def __init__(self, token: str, api_url: str, bot_api_token: str):
        self.token = token
        self.api_url = api_url
        self.bot_api_token = bot_api_token
        self.app = Application.builder().token(token).build()

        # HTTP клиент для запросов к API
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Кэш JWT токенов пользователей (telegram_id -> jwt_token)
        self.user_tokens = {}

        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("clear", self.clear_command))
        self.app.add_handler(CommandHandler("location", self.request_location_command))

        self.app.add_handler(CallbackQueryHandler(self.button_callback))

        self.app.add_handler(MessageHandler(filters.LOCATION, self.handle_location))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def _send_markdown_text(self, message, text: str, **kwargs):
        try:
            return await message.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to send with Markdown: {e}")
            return await message.reply_text(text.replace("**", "").replace("*", ""), **kwargs)

    async def _edit_markdown_text(self, query, text: str, **kwargs):
        try:
            return await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to edit with Markdown: {e}")
            return await query.edit_message_text(text.replace("**", ""), **kwargs)

    @staticmethod
    def _remove_feedback_prefix(text: str) -> str:
        if "❤️ **Отлично!" in text or "👎 **Понял," in text:
            return text.split("\n\n", 1)[-1]
        return text

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        telegram_id = user.id

        logger.info(f"User {telegram_id} started bot")

        welcome_text = f"""
👋 Привет, {user.first_name}!

Я помогу тебе найти идеальное место для досуга в Москве!

🔍 **Как я работаю:**
- Просто напиши, что ты ищешь (например: "уютное кафе с книжками")
- Я пойму твои предпочтения и предложу подходящие варианты
- Учту локацию, атмосферу, рейтинг и твои прошлые предпочтения

💡 **Примеры запросов:**
• "Хочу романтичный ресторан для свидания"
• "Кафе рядом с Пушкинской с хорошим кофе"
• "Что-то необычное и интересное"
• "Музей для детей в центре"

📍 **Команды:**
/help - справка
/clear - начать новый диалог
"""
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

        keyboard = [
            [KeyboardButton("📍 Поделиться геолокацией", request_location=True)],
            [KeyboardButton("Пропустить")],
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            "📍 Хочешь, чтобы я искал места рядом с тобой?\n"
            "Поделись геолокацией, и я смогу показывать самые близкие варианты!",
            reply_markup=reply_markup,
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
ℹ️ **Справка**

**Основные команды:**
/start - начало работы
/help - эта справка
/clear - очистить историю диалога
/location - поделиться геолокацией

**Как искать места:**
Просто опиши, что ты хочешь! Я понимаю естественный язык.

**Примеры:**
✓ "Уютное кафе с книжками рядом с Арбатом"
✓ "Романтичное место для свидания"
✓ "Музей с интерактивными экспонатами"
✓ "Бар с живой музыкой в центре"

**Поиск рядом с тобой:**
Напиши "рядом со мной" или "близко" - я автоматически предложу поделиться геолокацией!
Или используй команду /location в любой момент.

Готов помочь! 🚀
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def request_location_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [KeyboardButton("📍 Поделиться моей геолокацией", request_location=True)],
            [KeyboardButton("❌ Отмена")],
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            "📍 Чтобы я мог искать места рядом с тобой, поделись своей геолокацией.\n\n"
            "Нажми на кнопку ниже или отправь геолокацию вручную через 📎 → Геопозиция",
            reply_markup=reply_markup,
        )

    async def get_user_jwt(self, telegram_id: int) -> str:
        if telegram_id in self.user_tokens:
            return self.user_tokens[telegram_id]

        try:
            # Запрашиваем токен у API
            response = await self.http_client.post(
                f"{self.api_url}/api/auth/telegram/login",
                json={"telegram_id": telegram_id},
                headers={"X-Bot-Token": self.bot_api_token},
            )

            if response.status_code == 200:
                data = response.json()
                jwt_token = data.get("access_token")
                self.user_tokens[telegram_id] = jwt_token
                return jwt_token
            else:
                logger.error(f"Failed to get JWT token: {response.status_code}")

        except Exception as e:
            logger.error(f"Error getting JWT token: {e}", exc_info=True)

        return None

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id

        try:
            jwt_token = await self.get_user_jwt(telegram_id)
            if not jwt_token:
                await update.message.reply_text("Ошибка аутентификации. Попробуй позже.")
                return

            response = await self.http_client.delete(
                f"{self.api_url}/api/telegram/session",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

            if response.status_code == 200:
                await update.message.reply_text(
                    "История диалога очищена. Начнем заново!\n\nЧем могу помочь?"
                )
            else:
                await update.message.reply_text("Не удалось очистить историю. Попробуй позже.")

        except Exception as e:
            logger.error(f"Error clearing session: {e}", exc_info=True)
            await update.message.reply_text("Произошла ошибка. Попробуй позже.")

    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        location = update.message.location
        telegram_id = update.effective_user.id

        if not location:
            await update.message.reply_text("Не удалось получить геолокацию. Попробуй еще раз.")
            return

        latitude = location.latitude
        longitude = location.longitude

        logger.info(f"User {telegram_id} shared location: ({latitude}, {longitude})")

        context.user_data["user_location"] = {"latitude": latitude, "longitude": longitude}

        await update.message.reply_text(
            "✅ Отлично! Твоя геолокация сохранена.\n"
            "Теперь я могу искать места рядом с тобой!\n\n"
            "Что ты ищешь?",
            reply_markup=ReplyKeyboardRemove(),
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        message_text = update.message.text

        logger.info(f"Message from {telegram_id}: {message_text[:50]}...")

        if message_text == "Пропустить":
            await update.message.reply_text(
                "Хорошо! Ты всегда можешь поделиться геолокацией позже, используя /location\n\n"
                "Чем могу помочь?",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if message_text == "❌ Отмена":
            await update.message.reply_text(
                "Хорошо, отменил. Чем могу помочь?", reply_markup=ReplyKeyboardRemove()
            )
            return

        location_keywords = [
            "рядом со мной",
            "близко",
            "недалеко",
            "рядом",
            "около меня",
            "возле меня",
            "поблизости",
            "здесь",
            "тут",
        ]
        needs_location = any(keyword in message_text.lower() for keyword in location_keywords)
        has_location = context.user_data.get("user_location") is not None

        if needs_location and not has_location:
            keyboard = [
                [KeyboardButton("📍 Поделиться геолокацией", request_location=True)],
                [KeyboardButton("Искать по всей Москве")],
            ]
            reply_markup = ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            )

            await update.message.reply_text(
                "📍 Чтобы искать места рядом с тобой, мне нужна твоя геолокация.\n"
                "Поделись ей, или я буду искать по всей Москве.",
                reply_markup=reply_markup,
            )
            return

        if message_text == "Искать по всей Москве":
            await update.message.reply_text(
                "Хорошо, буду искать по всей Москве. Что ты ищешь?",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        try:
            await update.message.chat.send_action("typing")
        except Exception as e:
            logger.debug(f"Failed to send typing action: {e}")

        try:
            jwt_token = await self.get_user_jwt(telegram_id)
            if not jwt_token:
                await update.message.reply_text(
                    "Ошибка аутентификации. Пожалуйста, попробуй команду /start снова."
                )
                return

            payload = {"message": message_text}

            user_location = context.user_data.get("user_location")
            if user_location:
                payload["latitude"] = user_location["latitude"]
                payload["longitude"] = user_location["longitude"]
                logger.info(
                    f"Sending location with message: ({user_location['latitude']}, {user_location['longitude']})"
                )

            response = await self.http_client.post(
                f"{self.api_url}/api/telegram/send_message",
                json=payload,
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

            if response.status_code == 200:
                data = response.json()
                bot_response = data.get("response", {})

                text_response = bot_response.get("text", "")
                places = bot_response.get("places", [])

                if text_response:
                    await self._send_markdown_text(update.message, text_response)

                response_type = bot_response.get("response_type", "recommendation")
                if places and response_type == "recommendation":
                    await self._send_place_cards(update, places)
                elif places and response_type == "question":
                    logger.info(
                        f"Skipping places display for question response (response_type={response_type})"
                    )

                logger.info(f"Response sent to {telegram_id}")
            else:
                logger.error(f"API error: {response.status_code}")
                await update.message.reply_text("Извините, произошла ошибка. Попробуйте еще раз.")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Произошла техническая ошибка. Пожалуйста, попробуйте снова."
            )

    async def _send_place_cards(self, update: Update, places: list[dict]):
        for place in places[:5]:  # Ограничиваем до 5 мест за раз
            place_id = place.get("id")
            name = place.get("name", "Без названия")
            rating = place.get("rating", 0)
            district = place.get("district", "")
            address = place.get("address", "")
            tags = place.get("tags", [])
            description = place.get("description", "")

            card_text = f"📍 **{name}**\n\n"

            if rating:
                stars = "⭐" * int(rating)
                card_text += f"{stars} {rating}/5\n"

            if district:
                card_text += f"📌 {district}\n"

            if address:
                card_text += f"🏠 {address}\n"

            if tags:
                tags_str = ", ".join(tags[:5])
                card_text += f"\n🏷 {tags_str}\n"

            if description:
                desc_short = description[:200] + "..." if len(description) > 200 else description
                card_text += f"\n{desc_short}\n"

            keyboard = [
                [
                    InlineKeyboardButton("❤️ Нравится", callback_data=f"like:{place_id}"),
                    InlineKeyboardButton("👎 Не нравится", callback_data=f"dislike:{place_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self._send_markdown_text(update.message, card_text, reply_markup=reply_markup)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        callback_data = query.data

        if callback_data.endswith(":disabled"):
            await query.answer("Вы уже выбрали этот вариант", show_alert=False)
            return

        message_text = query.message.text or ""
        if "❤️ **Отлично!" in message_text or "👎 **Понял," in message_text:
            await query.answer("Вы уже выбрали этот вариант", show_alert=False)
            return

        if callback_data.startswith("like:"):
            place_id = callback_data.split(":")[1]
            await self._handle_like(query, place_id)
        elif callback_data.startswith("dislike:"):
            place_id = callback_data.split(":")[1]
            await self._handle_dislike(query, place_id)

    async def _handle_like(self, query, place_id: str):
        telegram_id = query.from_user.id
        logger.info(f"User {telegram_id} liked place {place_id}")

        try:
            jwt_token = await self.get_user_jwt(telegram_id)
            if not jwt_token:
                await query.answer("Ошибка аутентификации.", show_alert=True)
                return

            response = await self.http_client.post(
                f"{self.api_url}/api/telegram/interaction",
                json={
                    "place_id": int(place_id),
                    "interaction_type": "liked",
                },
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

            if response.status_code == 200:
                original_text = self._remove_feedback_prefix(query.message.text)
                new_text = f"❤️ **Отлично! Учту твои предпочтения.**\n\n{original_text}"

                keyboard = [
                    [InlineKeyboardButton("❤️ Нравится", callback_data=f"like:{place_id}:disabled")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await self._edit_markdown_text(query, new_text, reply_markup=reply_markup)
            else:
                logger.error(f"Failed to save like: {response.status_code}")
                await query.answer("Ошибка сохранения. Попробуйте позже.", show_alert=True)

        except Exception as e:
            logger.error(f"Error handling like: {e}", exc_info=True)
            await query.answer("Произошла ошибка.", show_alert=True)

    async def _handle_dislike(self, query, place_id: str):
        telegram_id = query.from_user.id
        logger.info(f"User {telegram_id} disliked place {place_id}")

        try:
            jwt_token = await self.get_user_jwt(telegram_id)
            if not jwt_token:
                await query.answer("Ошибка аутентификации.", show_alert=True)
                return

            response = await self.http_client.post(
                f"{self.api_url}/api/telegram/interaction",
                json={
                    "place_id": int(place_id),
                    "interaction_type": "disliked",
                },
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

            if response.status_code == 200:
                original_text = self._remove_feedback_prefix(query.message.text)
                new_text = f"👎 **Понял, учту это.**\n\n{original_text}"

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "👎 Не нравится", callback_data=f"dislike:{place_id}:disabled"
                        )
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await self._edit_markdown_text(query, new_text, reply_markup=reply_markup)
            else:
                logger.error(f"Failed to save dislike: {response.status_code}")
                await query.answer("Ошибка сохранения. Попробуйте позже.", show_alert=True)

        except Exception as e:
            logger.error(f"Error handling dislike: {e}", exc_info=True)
            await query.answer("Произошла ошибка.", show_alert=True)

    async def run(self):
        logger.info("Starting Telegram bot...")

        try:
            response = await self.http_client.get(f"{self.api_url}/api/health")
            if response.status_code == 200:
                logger.info("API is available")
            else:
                logger.warning(f"API returned status {response.status_code}")
        except Exception as e:
            logger.error(f"API is not available: {e}")
            logger.warning("Bot will start, but there may be problems")

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("Bot started and waiting for messages")

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            await self.http_client.aclose()
            logger.info("Bot stopped")


async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    if not BOT_API_TOKEN:
        logger.error("BOT_API_TOKEN is not set")
        sys.exit(1)

    bot = PlacesBot(TELEGRAM_BOT_TOKEN, API_BASE_URL, BOT_API_TOKEN)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
