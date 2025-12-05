import asyncio
import logging
import os
import traceback
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

# Импортируем асинхронный класс Database
from database import Database 

# --- КОНФИГУРАЦИЯ (ЧТЕНИЕ ИЗ ОКРУЖЕНИЯ) ---
API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
try:
    OWNER_ID = int(os.environ.get('OWNER_ID'))
except (TypeError, ValueError):
    # Если OWNER_ID не установлен или не число, присваиваем 0, но бот не запустится без TOKEN и URL.
    OWNER_ID = 0 

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
if DATABASE_URL and API_TOKEN:
    db = Database(DATABASE_URL) 
    bot = Bot(token=API_TOKEN)
else:
    logging.critical("API_TOKEN или DATABASE_URL не установлены. Бот не запустится.")
    # Присваиваем заглушки, чтобы код мог быть импортирован, но запуска не будет.
    db = None
    bot = None

# --- КЛАСС ДЛЯ ПРОВЕРКИ ТО ---
class Maintenance:
    @staticmethod
    async def is_on():
        """Асинхронно проверяет статус режима ТО"""
        if not db: return True
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

# --- ИНИЦИАЛИЗАЦИЯ ДИСПЕТЧЕРА ---
dp = Dispatcher(storage=MemoryStorage())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И КЛАВИАТУРЫ ---
async def check_is_admin(user_id):
    """Асинхронная проверка прав администратора."""
    if not db: return False
    if user_id == OWNER_ID:
        return True
    return await db.is_admin_in_db(user_id)

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

def get_user_kb():
    kb = [
        [InlineKeyboardButton(text="🏟 Мой Клуб", callback_data="usr_info")],
        [InlineKeyboardButton(text="🛠 Улучшить Стадион", callback_data="usr_upgrade_stadium")],
        [InlineKeyboardButton(text="📉 Расходы", callback_data="usr_expenses"),
         InlineKeyboardButton(text="📈 Прибыль", callback_data="usr_incomes")],
        [InlineKeyboardButton(text="🔄 История операций", callback_data="usr_history")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_team_actions_kb(team_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить бюджет", callback_data="team_action_budget")],
        [InlineKeyboardButton(text="👤 Сменить менеджера", callback_data="team_action_manager")],
        [InlineKeyboardButton(text="❌ Удалить команду", callback_data="team_action_delete")],
        [InlineKeyboardButton(text="🔙 К выбору команды", callback_data="adm_manage_money")]
    ])


# --- ХЕНДЛЕРЫ: START ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not db: 
        await message.answer("Ошибка конфигурации: Не установлена база данных или токен.")
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
            # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
            team_dict = dict(team) 
            await message.answer(f"👋 Добро пожаловать, менеджер клуба <b>{team_dict['name']}</b>!", parse_mode="HTML", reply_markup=get_user_kb())
        else:
            await message.answer(f"⛔ У вас нет доступа к управлению клубом.\nВаш ID: <code>{user_id}</code>\nОтправьте этот ID администратору.", parse_mode="HTML")

# --- ХЕНДЛЕРЫ: СУПЕР-АДМИН (ТО) ---
@dp.callback_query(F.data == "super_toggle_maintenance")
async def super_toggle_maintenance(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: 
        await callback.answer("У вас нет прав на это действие.", show_alert=True)
        return

    current_mode = await db.get_setting('maintenance_mode')
    new_mode = 'OFF' if current_mode == 'ON' else 'ON'
    await db.set_setting('maintenance_mode', new_mode)

    await callback.message.edit_text(
        f"⚙️ Режим технического обслуживания переключен на: <b>{new_mode}</b>",
        parse_mode="HTML",
        reply_markup=await get_admin_kb(callback.from_user.id) 
    )
    await callback.answer(f"Режим ТО: {new_mode}", show_alert=True)

# --- ХЕНДЛЕРЫ: АДМИН (УПРАВЛЕНИЕ АДМИНАМИ) ---
@dp.callback_query(F.data == "super_manage_admins")
async def super_admin_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: 
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    admins = await db.get_admins()
    text = f"👮‍♂️ <b>Список администраторов:</b>\n\n👑 Владелец: <code>{OWNER_ID}</code>\n"
    
    kb_builder = []
    
    if admins:
        for admin_id in admins:
            text += f"👤 <code>{admin_id}</code>\n"
            kb_builder.append([InlineKeyboardButton(text=f"❌ Удалить {admin_id}", callback_data=f"del_admin_{admin_id}")])
    else:
        text += "\nДополнительных администраторов нет."

    kb_builder.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_new_admin")])
    kb_builder.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_builder))
    await callback.answer()

@dp.callback_query(F.data == "add_new_admin")
async def super_add_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.answer("Введите Telegram ID пользователя, которого вы хотите назначить администратором:")
    await state.set_state(AdminStates.waiting_new_admin_id)
    await callback.answer()

@dp.message(AdminStates.waiting_new_admin_id)
async def super_add_admin_finish(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID должен состоять только из цифр.")
        return
    
    new_admin_id = int(message.text)
    user_id = message.from_user.id
    if await db.add_admin(new_admin_id):
        await message.answer(f"✅ Пользователь <code>{new_admin_id}</code> назначен администратором.", parse_mode="HTML", reply_markup=await get_admin_kb(user_id))
    else:
        await message.answer("⚠️ Этот пользователь уже является администратором.", parse_mode="HTML", reply_markup=await get_admin_kb(user_id))
    
    await state.clear()

@dp.callback_query(F.data.startswith("del_admin_"))
async def super_delete_admin(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    
    admin_to_delete = int(callback.data.split("_")[2])
    await db.remove_admin(admin_to_delete)
    
    await callback.answer(f"Администратор {admin_to_delete} удален.", show_alert=True)
    await super_admin_menu(callback)

# --- ХЕНДЛЕРЫ: АДМИН (ОТМЕНА/НАЗАД) ---
@dp.callback_query(F.data == "admin_back")
async def admin_back_main(callback: CallbackQuery, state: FSMContext):
    if not await check_is_admin(callback.from_user.id): 
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.clear()
    await callback.message.edit_text("⚽ Панель администратора", reply_markup=await get_admin_kb(callback.from_user.id))
    await callback.answer()

# --- ХЕНДЛЕРЫ: АДМИН (СОЗДАНИЕ КОМАНДЫ) ---
@dp.callback_query(F.data == "adm_create_team")
async def adm_create_start(callback: CallbackQuery, state: FSMContext):
    if not await check_is_admin(callback.from_user.id): 
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
        
    await callback.message.answer("Введите название футбольного клуба:")
    await state.set_state(AdminStates.waiting_team_name)
    await callback.answer()

@dp.message(AdminStates.waiting_team_name)
async def adm_set_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите краткое описание/информацию о клубе:")
    await state.set_state(AdminStates.waiting_team_desc)

@dp.message(AdminStates.waiting_team_desc)
async def adm_set_desc(message: Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await message.answer("Введите Telegram ID пользователя (менеджера), который получит доступ:")
    await state.set_state(AdminStates.waiting_manager_id)

@dp.message(AdminStates.waiting_manager_id)
async def adm_set_manager(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID должен быть числом. Попробуйте еще раз.")
        return
    await state.update_data(manager_id=int(message.text))
    await message.answer("Введите начальный бюджет (число):")
    await state.set_state(AdminStates.waiting_budget)

@dp.message(AdminStates.waiting_budget)
async def adm_finish_team(message: Message, state: FSMContext):
    try:
        budget = float(message.text)
    except ValueError:
        await message.answer("Бюджет должен быть числом. Повторите ввод.")
        return
        
    data = await state.get_data()
    success = await db.add_team(data['name'], data['desc'], data['manager_id'], budget)
    user_id = message.from_user.id
    
    if success:
        await message.answer(f"✅ Клуб <b>{data['name']}</b> успешно создан!\nМенеджер ID: {data['manager_id']}\nБюджет: {budget:,.2f}", parse_mode="HTML", reply_markup=await get_admin_kb(user_id))
    else:
        await message.answer("❌ Ошибка. Возможно, у этого пользователя уже есть команда.", reply_markup=await get_admin_kb(user_id))
    
    await state.clear()

# --- ХЕНДЛЕРЫ: АДМИН (СПИСОК КОМАНД) ---
@dp.callback_query(F.data == "adm_list_teams")
async def adm_show_teams(callback: CallbackQuery):
    if not await check_is_admin(callback.from_user.id): 
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    teams = await db.get_all_teams()
    text = "📋 <b>Список команд:</b>\n\n"
    if not teams: text += "Команд пока нет."
    
    for t in teams:
        # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
        team_dict = dict(t)
        stadium_info = STADIUM_LEVELS[team_dict['stadium_level']]
        text += f"🔹 <b>{team_dict['name']}</b> (ID: {team_dict['id']})\n💰 {team_dict['budget']:,.2f} | 👤 Менеджер: {team_dict['manager_id']}\n🏟 Стадион: {stadium_info['name']} ({stadium_info['capacity']:,})\n\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

# --- ХЕНДЛЕРЫ: АДМИН (УПРАВЛЕНИЕ КОМАНДОЙ - Выбор) ---
@dp.callback_query(F.data == "adm_manage_money")
async def adm_manage_team_start(callback: CallbackQuery, state: FSMContext):
    if not await check_is_admin(callback.from_user.id): 
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.clear()
    
    teams = await db.get_all_teams()
    if not teams:
        await callback.message.edit_text("Команд пока нет.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
        await callback.answer()
        return

    kb_builder = []
    for team in teams:
        # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
        team_dict = dict(team) 
        kb_builder.append([InlineKeyboardButton(text=f"{team_dict['name']} (ID: {team_dict['id']})", callback_data=f"sel_team_for_action_{team_dict['id']}")])
    
    kb_builder.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    
    await callback.message.edit_text("Выберите команду для управления:", reply_markup=keyboard)
    await state.set_state(AdminStates.waiting_team_select)
    await callback.answer()

@dp.callback_query(AdminStates.waiting_team_select, F.data.startswith("sel_team_for_action_"))
async def adm_team_actions_menu(callback: CallbackQuery, state: FSMContext):
    team_id = int(callback.data.split("_")[-1])
    team = await db.get_team_by_id(team_id)
    
    await state.update_data(team_id=team_id)
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
    
    text = (
        f"⚽ <b>{team_dict['name']}</b> (ID: {team_id})\n"
        f"💰 Бюджет: {team_dict['budget']:,.2f} $\n"
        f"👤 Менеджер: <code>{team_dict['manager_id']}</code>"
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_team_actions_kb(team_id))
    await callback.answer()

# --- ХЕНДЛЕРЫ: АДМИН (УДАЛЕНИЕ КОМАНДЫ) ---
@dp.callback_query(F.data == "team_action_delete")
async def adm_confirm_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    team_id = data.get('team_id')
    team = await db.get_team_by_id(team_id)
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 ПОДТВЕРДИТЬ УДАЛЕНИЕ", callback_data="team_delete_execute")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="sel_team_for_action_" + str(team_id))]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>ВНИМАНИЕ! Вы собираетесь удалить команду {team_dict['name']}.</b>\n"
        f"Это удалит все транзакции и команду без возможности восстановления.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "team_delete_execute")
async def adm_execute_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    team_id = data.get('team_id')
    team = await db.get_team_by_id(team_id)
    
    if team:
        # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
        team_dict = dict(team)
        await db.delete_team(team_id)
        await state.clear()
        
        await callback.message.edit_text(
            f"✅ Команда <b>{team_dict['name']}</b> (ID: {team_id}) и все ее данные успешно удалены.", 
            parse_mode="HTML",
            reply_markup=await get_admin_kb(callback.from_user.id)
        )
    else:
        await callback.message.edit_text("❌ Ошибка. Команда не найдена.", parse_mode="HTML", reply_markup=await get_admin_kb(callback.from_user.id))
        
    await callback.answer("Команда удалена.", show_alert=True)

# --- ХЕНДЛЕРЫ: АДМИН (СМЕНА МЕНЕДЖЕРА) ---
@dp.callback_query(F.data == "team_action_manager")
async def adm_start_change_manager(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    team_id = data.get('team_id')
    team = await db.get_team_by_id(team_id)
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
    
    await callback.message.edit_text(
        f"👤 Введите Telegram ID нового менеджера для команды <b>{team_dict['name']}</b>.\n"
        f"Текущий менеджер: <code>{team_dict['manager_id']}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="sel_team_for_action_" + str(team_id))]])
    )
    await state.set_state(AdminStates.waiting_new_manager_id)
    await callback.answer()

@dp.message(AdminStates.waiting_new_manager_id)
async def adm_finish_change_manager(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID должен быть числом. Повторите ввод или нажмите отмена.")
        return

    new_manager_id = int(message.text)
    data = await state.get_data()
    team_id = data.get('team_id')
    team = await db.get_team_by_id(team_id)
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)

    success = await db.update_team_manager(team_id, new_manager_id)
    
    if success:
        await message.answer(
            f"✅ Менеджер команды <b>{team_dict['name']}</b> успешно изменен!\n"
            f"Новый ID: <code>{new_manager_id}</code>",
            parse_mode="HTML",
            reply_markup=await get_admin_kb(message.from_user.id)
        )
    else:
        await message.answer(
            f"❌ Ошибка! Пользователь <code>{new_manager_id}</code> уже управляет другой командой. "
            f"Сначала освободите его.",
            parse_mode="HTML",
            reply_markup=await get_admin_kb(message.from_user.id)
        )
    
    await state.clear()


# --- ХЕНДЛЕРЫ: АДМИН (ФИНАНСЫ, продолжение) ---
@dp.callback_query(F.data == "team_action_budget")
async def adm_money_start_from_menu(callback: CallbackQuery, state: FSMContext):
    if not await check_is_admin(callback.from_user.id): 
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await callback.message.answer("Введите сумму (положительная для прибыли, отрицательная для расхода). \nНапример: `1000000` или `-500000`", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_trans_amount)
    await callback.answer()

@dp.message(AdminStates.waiting_trans_amount)
async def adm_money_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        await state.update_data(amount=amount)
        await message.answer("Укажите причину/категорию (например: 'Покупка игрока', 'Спонсорский контракт', 'Админ пополнил'):")
        await state.set_state(AdminStates.waiting_trans_reason)
    except ValueError:
        await message.answer("Введите корректное число.")

@dp.message(AdminStates.waiting_trans_reason)
async def adm_money_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.add_transaction(data['team_id'], data['amount'], message.text)
    
    # Получаем обновленные данные команды
    team = await db.get_team_by_id(data['team_id'])
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
    
    verb = "зачислено" if data['amount'] > 0 else "списано"
    await message.answer(f"✅ Успешно {verb} {abs(data['amount']):,.2f} ({message.text})\nКлуб: {team_dict['name']}\nНовый баланс: {team_dict['budget']:,.2f}", reply_markup=await get_admin_kb(message.from_user.id))
    
    try:
        # Отправка уведомления менеджеру
        await bot.send_message(team_dict['manager_id'], f"🔔 <b>Финансовое уведомление</b>\nСумма: {data['amount']:,.2f}\nПричина: {message.text}\nТекущий баланс: {team_dict['budget']:,.2f}", parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение менеджеру {team_dict['manager_id']}: {e}")
        
    await state.clear()

# --- ХЕНДЛЕРЫ: ПОЛЬЗОВАТЕЛЬ ---

@dp.callback_query(F.data == "usr_info")
async def usr_show_info(callback: CallbackQuery):
    user_id = callback.from_user.id
    team = await db.get_team_by_user(user_id)
    if not team: 
        await callback.answer("Команда не найдена.", show_alert=True)
        return
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
    
    stadium_info = STADIUM_LEVELS[team_dict['stadium_level']]
    
    text = (
        f"🏆 <b>Клуб:</b> {team_dict['name']}\n"
        f"📝 <b>Инфо:</b> {team_dict['description']}\n"
        f"💰 <b>Текущий бюджет:</b> {team_dict['budget']:,.2f} $\n"
        f"🏟 <b>Стадион:</b> {stadium_info['name']} (Вместимость: {stadium_info['capacity']:,})\n"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_user_kb())
    await callback.answer()

@dp.callback_query(F.data == "usr_upgrade_stadium")
async def usr_show_upgrade_stadium(callback: CallbackQuery):
    user_id = callback.from_user.id
    team = await db.get_team_by_user(user_id)
    if not team: 
        await callback.answer("Команда не найдена.", show_alert=True)
        return
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)

    current_level = team_dict['stadium_level']
    current_capacity = STADIUM_LEVELS[current_level]["capacity"]
    
    if current_level >= MAX_STADIUM_LEVEL:
        text = f"🏟 Ваш стадион уже максимального уровня ({STADIUM_LEVELS[current_level]['name']} - Вместимость: {current_capacity:,})."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="usr_info")]])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        return

    next_level = current_level + 1
    next_info = STADIUM_LEVELS[next_level]
    
    cost = next_info["cost"]
    budget = team_dict['budget']
    can_afford = budget >= cost
    
    text = (
        f"🏟 <b>Текущий стадион:</b> {STADIUM_LEVELS[current_level]['name']} ({current_capacity:,})\n"
        f"➡️ <b>Следующий уровень:</b> {next_info['name']} ({next_info['capacity']:,})\n\n"
        f"💰 <b>Цена улучшения:</b> {cost:,} $\n"
        f"💵 <b>Ваш бюджет:</b> {budget:,.2f} $\n"
    )
    
    kb_builder = []
    if can_afford:
        text += "✅ Вы можете себе это позволить!"
        kb_builder.append([InlineKeyboardButton(text=f"🚀 Улучшить за {cost:,} $", callback_data=f"do_upgrade_{next_level}")])
    else:
        text += "❌ Недостаточно средств для улучшения."

    kb_builder.append([InlineKeyboardButton(text="🔙 Назад", callback_data="usr_info")])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_builder))
    await callback.answer()

@dp.callback_query(F.data.startswith("do_upgrade_"))
async def usr_do_upgrade_stadium(callback: CallbackQuery):
    user_id = callback.from_user.id
    team = await db.get_team_by_user(user_id)
    if not team: 
        await callback.answer("Ошибка: Команда не найдена.", show_alert=True)
        return
    
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)
        
    team_id = team_dict['id']
    new_level = int(callback.data.split("_")[2])
    cost = STADIUM_LEVELS[new_level]["cost"]
    
    if team_dict['budget'] < cost:
        await callback.answer("Недостаточно средств!", show_alert=True)
        return

    # ❗️ ИСПРАВЛЕНО: Удален лишний аргумент 'cost'
    await db.upgrade_stadium(team_id, new_level)
    
    reason = f"Улучшение стадиона до уровня {STADIUM_LEVELS[new_level]['name']}"
    await db.add_transaction(team_id, -cost, reason) 

    updated_team = await db.get_team_by_user(user_id)
    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    updated_team_dict = dict(updated_team)
    
    new_budget = updated_team_dict['budget']
    new_capacity = STADIUM_LEVELS[new_level]["capacity"]

    await callback.message.edit_text(
        f"✅ <b>Улучшение завершено!</b>\n\n"
        f"🏟 Новый стадион: {STADIUM_LEVELS[new_level]['name']} ({new_capacity:,})\n"
        f"➖ Списано: {cost:,} $\n"
        f"💰 Текущий бюджет: {new_budget:,.2f} $",
        parse_mode="HTML",
        reply_markup=get_user_kb()
    )
    await callback.answer("Стадион успешно улучшен!", show_alert=True)

@dp.callback_query(F.data.in_({"usr_expenses", "usr_incomes", "usr_history"}))
async def usr_show_finance(callback: CallbackQuery):
    user_id = callback.from_user.id
    team = await db.get_team_by_user(user_id)
    if not team: return

    # ✅ ИСПРАВЛЕНО: Преобразование Record в dict
    team_dict = dict(team)

    mode = callback.data
    trans_type = None
    title = "История операций"
    
    if mode == "usr_expenses":
        trans_type = 'expense'
        title = "📉 Расходы"
    elif mode == "usr_incomes":
        trans_type = 'income'
        title = "📈 Прибыль"

    transactions = await db.get_transactions(team_dict['id'], trans_type)
    
    report = f"<b>{title} (последние 20):</b>\n\n"
    if not transactions:
        report += "Операций не найдено."
    
    for t in transactions:
        icon = "🟢" if t['amount'] > 0 else "🔴"
        # ❗️ ИСПРАВЛЕНО: Правильное форматирование объекта datetime
        formatted_date = t['date'].strftime("%Y-%m-%d") 
        
        report += f"{icon} <b>{t['amount']:,.0f}</b> | {formatted_date}\n└ <i>{t['reason']}</i>\n\n"
        
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="usr_info")]])
    
    await callback.message.edit_text(report, parse_mode="HTML", reply_markup=back_kb)
    await callback.answer()

# --- ОБРАБОТЧИК КРИТИЧЕСКИХ ОШИБОК ---
async def on_error(event: types.ErrorEvent):
    """Функция для логирования и обработки критических ошибок в хендлерах."""
    logging.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {event.exception}", exc_info=True)
    logging.error(traceback.format_exc()) 
    
    # Попытка ответить Telegram, чтобы разблокировать кнопку, если это колбэк
    try:
        if isinstance(event.update, types.CallbackQuery):
            await event.update.answer("❌ Внутренняя ошибка. Повторите позже.", show_alert=True)
    except Exception:
        pass 

# --- ЗАПУСК ---
async def main():
    if not API_TOKEN or not DATABASE_URL:
        logging.critical("Критическая ошибка: Токен бота или URL базы данных не установлен в переменных окружения.")
        return
        
    # Регистрация обработчика ошибок
    dp.errors.register(on_error)
    
    # 1. Подключение к БД
    await db.connect() 
    
    # 2. Создание таблиц (будет проигнорировано, если таблицы уже есть)
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
