# database.py

import asyncpg
from datetime import datetime
import os
from typing import List, Dict, Any, Optional

# URL подключения к базе данных Render PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')

class Database:
    """
    Класс для асинхронной работы с базой данных PostgreSQL.
    Использует пул соединений и $1, $2, $3... для плейсхолдеров.
    """
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        """Создает пул асинхронных соединений к БД."""
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(dsn=self.db_url)
                print("Успешно подключено к PostgreSQL.")
            except Exception as e:
                print(f"Ошибка подключения к БД: {e}")
                raise e
    
    async def close(self):
        """Закрывает пул соединений."""
        if self.pool:
            await self.pool.close()

    async def _execute(self, query: str, *args, fetch: bool = False, fetchval: bool = False, fetchrow: bool = False) -> Optional[Any]:
        """Вспомогательный метод для выполнения запросов с пулом."""
        if not self.pool:
            raise ConnectionError("Соединение с БД не установлено.")
            
        async with self.pool.acquire() as conn:
            if fetch:
                # fetch возвращает список записей (List[asyncpg.Record])
                return await conn.fetch(query, *args) 
            elif fetchrow:
                # fetchrow возвращает одну запись (asyncpg.Record)
                return await conn.fetchrow(query, *args)
            elif fetchval:
                # fetchval возвращает значение первой колонки первой строки
                return await conn.fetchval(query, *args)
            else:
                # execute для INSERT, UPDATE, DELETE, CREATE
                return await conn.execute(query, *args)

    async def create_tables(self):
        """Создает таблицы. Использует SERIAL PRIMARY KEY и BIGINT для ID."""
        await self._execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                manager_id BIGINT UNIQUE,
                budget REAL DEFAULT 0,
                stadium_level INTEGER DEFAULT 0
            )
        """)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
                amount REAL,
                reason TEXT,
                date TIMESTAMP
            )
        """)
        await self._execute("CREATE TABLE IF NOT EXISTS admins (user_id BIGINT PRIMARY KEY)")
        await self._execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

    async def ensure_initial_settings(self):
        """Добавляет начальные настройки, если их нет (ON CONFLICT DO NOTHING)."""
        await self._execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING", 
                            'maintenance_mode', 'OFF')

    # --- Методы для Команд ---
    async def add_team(self, name, description, manager_id, initial_budget):
        try:
            # $1, $2, $3, $4, $5 вместо ?
            await self._execute("INSERT INTO teams (name, description, manager_id, budget, stadium_level) VALUES ($1, $2, $3, $4, 0)",
                                name, description, manager_id, initial_budget)
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False

    async def get_team_by_user(self, user_id):
        # fetchrow возвращает один объект Record (словарь)
        return await self._execute("SELECT * FROM teams WHERE manager_id = $1", 
                                  user_id, fetchrow=True)

    async def get_all_teams(self):
        # fetch возвращает список объектов Record (List[Dict])
        return await self._execute("SELECT * FROM teams", fetch=True)

    async def get_team_by_id(self, team_id):
        return await self._execute("SELECT * FROM teams WHERE id = $1", team_id, fetchrow=True)

    async def delete_team(self, team_id):
        await self._execute("DELETE FROM transactions WHERE team_id = $1", team_id)
        await self._execute("DELETE FROM teams WHERE id = $1", team_id)

    async def update_team_manager(self, team_id, new_manager_id):
        try:
            await self._execute("UPDATE teams SET manager_id = $1 WHERE id = $2", new_manager_id, team_id)
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False

    # --- Методы для Транзакций ---
    async def add_transaction(self, team_id, amount, reason):
        date = datetime.now()
        await self._execute("INSERT INTO transactions (team_id, amount, reason, date) VALUES ($1, $2, $3, $4)",
                            team_id, amount, reason, date)
        await self._execute("UPDATE teams SET budget = budget + $1 WHERE id = $2", amount, team_id)

    async def get_transactions(self, team_id, trans_type=None):
        query = "SELECT * FROM transactions WHERE team_id = $1"
        params = [team_id]
        if trans_type == 'income':
            query += " AND amount > 0"
        elif trans_type == 'expense':
            query += " AND amount < 0"
        query += " ORDER BY date DESC LIMIT 20"
        return await self._execute(query, *params, fetch=True)

    # --- Методы для Админов/Настроек ---
    async def add_admin(self, user_id):
        try:
            await self._execute("INSERT INTO admins (user_id) VALUES ($1)", user_id)
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False 

    async def remove_admin(self, user_id):
        await self._execute("DELETE FROM admins WHERE user_id = $1", user_id)

    async def get_admins(self):
        # Возвращаем список ID
        rows = await self._execute("SELECT user_id FROM admins", fetch=True)
        return [row[0] for row in rows]

    async def is_admin_in_db(self, user_id):
        # fetchval вернет 1 или None
        result = await self._execute("SELECT 1 FROM admins WHERE user_id = $1", user_id, fetchval=True)
        return result is not None

    async def get_setting(self, key):
        return await self._execute("SELECT value FROM settings WHERE key = $1", key, fetchval=True)

    async def set_setting(self, key, value):
        await self._execute("UPDATE settings SET value = $1 WHERE key = $2", value, key)

    async def upgrade_stadium(self, team_id, cost, new_level):
        # Обновляем только уровень стадиона (списание происходит через add_transaction)
        await self._execute("UPDATE teams SET stadium_level = $1 WHERE id = $2", 
                            new_level, team_id)
