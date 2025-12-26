import aiosqlite
import asyncio
from pathlib import Path

DB_INIT_SQL = """
CREATE TABLE IF NOT EXISTS warnings (
    user_id INTEGER PRIMARY KEY,
    last_warning_ts INTEGER
);
"""

_db_lock = asyncio.Lock()


async def init_db(path: str = "data/bot.sqlite3"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with _db_lock:
        async with aiosqlite.connect(path) as db:
            await db.execute(DB_INIT_SQL)
            await db.commit()


async def set_last_warning(db_path: str, user_id: int, ts: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO warnings(user_id, last_warning_ts) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_warning_ts=excluded.last_warning_ts",
            (user_id, ts),
        )
        await db.commit()


async def get_last_warning(db_path: str, user_id: int):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT last_warning_ts FROM warnings WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_warnings(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT user_id, last_warning_ts FROM warnings")
        rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}