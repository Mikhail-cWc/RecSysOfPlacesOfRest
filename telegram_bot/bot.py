import asyncio
import logging
import os
import sys

import httpx
from dotenv import load_dotenv
from telegram import Update
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


class PlacesBot:
    """
    Telegram бот для рекомендаций мест.
    """

    def __init__(self, token: str, api_url: str):
        self.token = token
        self.api_url = api_url
        self.app = Application.builder().token(token).build()

        # HTTP клиент для запросов к API
        self.http_client = httpx.AsyncClient(timeout=30.0)

        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("clear", self.clear_command))

        self.app.add_handler(CallbackQueryHandler(self.button_callback))

        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

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

Чем могу помочь?
"""
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
ℹ️ **Справка**

**Основные команды:**
/start - начало работы
/help - эта справка
/clear - очистить историю диалога

**Как искать места:**
Просто опиши, что ты хочешь! Я понимаю естественный язык.

**Примеры:**
✓ "Уютное кафе с книжками рядом с Арбатом"
✓ "Романтичное место для свидания"
✓ "Музей с интерактивными экспонатами"
✓ "Бар с живой музыкой в центре"

Готов помочь! 🚀
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id

        try:
            response = await self.http_client.delete(
                f"{self.api_url}/api/telegram/session/{telegram_id}"
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

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        message_text = update.message.text

        logger.info(f"Message from {telegram_id}: {message_text[:50]}...")

        await update.message.chat.send_action("typing")

        try:
            response = await self.http_client.post(
                f"{self.api_url}/api/telegram/send_message",
                json={"telegram_id": telegram_id, "message": message_text},
            )

            if response.status_code == 200:
                data = response.json()
                bot_response = data.get("response", "Извините, произошла ошибка.")

                await update.message.reply_text(bot_response, parse_mode=ParseMode.MARKDOWN)

                logger.info(f"Response sent to {telegram_id}")
            else:
                logger.error(f"API error: {response.status_code}")
                await update.message.reply_text("Извините, произошла ошибка. Попробуйте еще раз.")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Произошла техническая ошибка. Пожалуйста, попробуйте снова."
            )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        # Обработка callback_data
        # Формат: "action:place_id" или "action"
        callback_data = query.data

        if callback_data.startswith("like:"):
            place_id = callback_data.split(":")[1]
            await self._handle_like(query, place_id)
        elif callback_data.startswith("dislike:"):
            place_id = callback_data.split(":")[1]
            await self._handle_dislike(query, place_id)
        elif callback_data == "more":
            await query.edit_message_text("Ищу еще варианты...")

    async def _handle_like(self, query, place_id: str):
        telegram_id = query.from_user.id
        logger.info(f"User {telegram_id} liked place {place_id}")

        # TODO: Сохранить взаимодействие в БД через API
        await query.edit_message_text(f"❤️ Отлично! Учту твои предпочтения.\n\n{query.message.text}")

    async def _handle_dislike(self, query, place_id: str):
        telegram_id = query.from_user.id
        logger.info(f"User {telegram_id} disliked place {place_id}")

        # TODO: Сохранить взаимодействие в БД через API
        await query.edit_message_text(f"👎 Понял, учту.\n\n{query.message.text}")

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

    bot = PlacesBot(TELEGRAM_BOT_TOKEN, API_BASE_URL)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
