# main.py

import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

# Импортируем асинхронный класс Database
from database import Database 

# --- КОНФИГУРАЦИЯ ---
# ! ЧТЕНИЕ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ !
# ВАЖНО: На Render вы должны установить TELEGRAM_BOT_TOKEN, OWNER_ID и DATABASE_URL
API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
try:
    OWNER_ID = int(os.environ.get('OWNER_ID'))
except (TypeError, ValueError):
    logging.error("OWNER_ID не установлен или не является числом в переменных окружения.")
    OWNER_ID = 0 # Заглушка, бот не будет работать без ID

DATABASE_URL = os.environ.get('DATABASE_URL')
if not API_TOKEN or not DATABASE_URL:
    logging.critical("API_TOKEN или DATABASE_URL не установлены. Бот не запустится.")

# Цены и уровни вместимости стадиона
STADIUM_LEVELS = {
    0: {"name": "Базовый стадион", "capacity": 10000, "cost": 0},
    1: {"name": "Малый", "capacity": 25000, "cost": 5000000},
    2: {"name": "Средний", "capacity": 50000, "cost": 15000000},
    3: {"name": "Крупный", "capacity": 80000, "cost": 35000000},
}
MAX_STADIUM_LEVEL = 3

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- Инициализация и подключение ---
if DATABASE_URL:
    db = Database(DATABASE_URL) 
else:
    # Заглушка, если URL не найден (бот все равно не запустится без него)
    db = None 

# --- КЛАСС ДЛЯ ПРОВЕРКИ ТО ---
class Maintenance:
    @staticmethod
    async def is_on():
        if not db: return True # Если БД не подключена, считаем, что ТО включено
        return await db.get_setting('maintenance_mode') == 'ON'

# --- СТЕЙТЫ (FSM) ---
class AdminStates(StatesGroup):
    waiting_team_name = State()
    waiting_team_desc = State()
    waiting_manager_id = State()
    waiting_budget = State()
    waiting_team_select = State()
    waiting_trans_amount = State()
    waiting_trans_reason = State()
    waiting_new_manager_id = State()
    waiting_new_admin_id = State()

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И КЛАВИАТУРЫ (Оставлены без изменений) ---
# ... (async def check_is_admin(user_id):)
async def check_is_admin(user_id):
    if not db: return False
    if user_id == OWNER_ID:
        return True
    return await db.is_admin_in_db(user_id)

# ... (async def get_admin_kb(user_id):)
async def get_admin_kb(user_id):
    if not db: return None
    kb = [
        [InlineKeyboardButton(text="➕ Создать команду", callback_data="adm_create_team")],
        [InlineKeyboardButton(text="💰 Управление бюджетом/командой", callback_data="adm_manage_money")], 
        [InlineKeyboardButton(text="📋 Список команд", callback_data="adm_list_teams")]
    ]
    if user_id == OWNER_ID:
        kb.append([InlineKeyboardButton(text="👮‍♂️ Управление админами", callback_data="super_manage_admins")])
        mode = await db.get_setting('maintenance_mode') or "OFF" 
        kb.append([InlineKeyboardButton(text=f"⚙️ ТО: {mode}", callback_data="super_toggle_maintenance")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ... (def get_user_kb():)
def get_user_kb():
    kb = [
        [InlineKeyboardButton(text="🏟 Мой Клуб", callback_data="usr_info")],
        [InlineKeyboardButton(text="🛠 Улучшить Стадион", callback_data="usr_upgrade_stadium")],
        [InlineKeyboardButton(text="📉 Расходы", callback_data="usr_expenses"),
         InlineKeyboardButton(text="📈 Прибыль", callback_data="usr_incomes")],
        [InlineKeyboardButton(text="🔄 История операций", callback_data="usr_history")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ... (def get_team_actions_kb(team_id):)
def get_team_actions_kb(team_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить бюджет", callback_data="team_action_budget")],
        [InlineKeyboardButton(text="👤 Сменить менеджера", callback_data="team_action_manager")],
        [InlineKeyboardButton(text="❌ Удалить команду", callback_data="team_action_delete")],
        [InlineKeyboardButton(text="🔙 К выбору команды", callback_data="adm_manage_money")]
    ])

# --- ХЕНДЛЕРЫ: START (остаются прежними, т.к. используют db) ---
# ...
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not db: 
        await message.answer("Ошибка конфигурации: Не установлена база данных.")
        return
    user_id = message.from_user.id
    
    is_admin = await check_is_admin(user_id)
    if not is_admin and await Maintenance.is_on():
        await message.answer("⚠️ Бот временно находится на техническом обслуживании. Приносим извинения за неудобства.")
        return

    if is_admin:
        role = "Владелец" if user_id == OWNER_ID else "Администратор"
        await message.answer(
            f"⚽ Привет, {role}!\nСистема управления трансферами готова.", 
            reply_markup=await get_admin_kb(user_id) 
        )
    else:
        team = await db.get_team_by_user(user_id)
        if team:
            # Преобразование Record (PostgreSQL) в Dict для доступа по ключу
            team_dict = dict(team) 
            await message.answer(f"👋 Добро пожаловать, менеджер клуба <b>{team_dict['name']}</b>!", parse_mode="HTML", reply_markup=get_user_kb())
        else:
            await message.answer(f"⛔ У вас нет доступа к управлению клубом.\nВаш ID: <code>{user_id}</code>\nОтправьте этот ID администратору.", parse_mode="HTML")
# ... (Остальные хендлеры также остаются, используя db.* и dict(record) для доступа)
# ВНИМАНИЕ: Все хендлеры, обращающиеся к результату fetchrow/fetch,
# должны использовать team['name'] или dict(team)['name'] для доступа к полям, 
# так как asyncpg возвращает объекты Record, похожие на dict.

# --- ЗАПУСК (ИСПРАВЛЕНО) ---
async def main():
    if not API_TOKEN:
        logging.critical("Критическая ошибка: Токен бота не установлен в переменной окружения TELEGRAM_BOT_TOKEN.")
        return
    if not DATABASE_URL:
        logging.critical("Критическая ошибка: URL базы данных не установлен в переменной окружения DATABASE_URL.")
        return
        
    # 1. Подключение к БД
    await db.connect() 
    
    # 2. Создание таблиц
    await db.create_tables()
    await db.ensure_initial_settings()
    
    print("Бот запущен и подключен к БД...")
    try:
        # 3. Запуск пуллинга
        await dp.start_polling(bot)
    finally:
        # 4. Закрытие соединения при остановке
        await db.close()
        print("Бот остановлен. Соединение с БД закрыто.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")
    except Exception as e:
        logging.critical(f"Критическая ошибка при запуске: {e}")
