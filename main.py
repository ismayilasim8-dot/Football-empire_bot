# main.py - AIogram 3 minimal bot (polling) for Render
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read token from env
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("Environment variable BOT_TOKEN is not set. Exiting.")
    raise SystemExit("BOT_TOKEN not set")

# Create bot and dispatcher
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Simple /start handler
@dp.message(Command(commands=["start"]))
async def cmd_start(message: Message):
    user = message.from_user
    text = (
        f"Привет, <b>{user.full_name}</b>!\n\n"
        "Это Football Empire (мини). Бот успешно работает на Aiogram 3 ✅\n\n"
        "Команды:\n"
        "/start - это сообщение\n"
    )
    await message.answer(text)

# Example echo handler (optional)
@dp.message()
async def echo_message(message: Message):
    # простая логика — отвечает тем же текстом
    # можно удалить или заменить на собственные хендлеры
    await message.reply(f"Вы написали: {message.text}")

async def main():
    # Запускаем polling в event loop
    try:
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down bot...")
        await bot.session.close()

if __name__ == "__main__":
    # Запуск через asyncio.run, чтобы корректно завершать сессии
    asyncio.run(main())
