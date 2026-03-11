"""
会话元数据持久化：SQLite 存储每个设计会话的基本信息。
LangGraph Checkpoint 数据存储在同一 SQLite 文件的独立表中。
"""
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "roguelike.db")
DB_PATH = os.path.normpath(DB_PATH)


async def init_db() -> None:
    """建表（首次启动时执行）。"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                title        TEXT NOT NULL DEFAULT '未命名游戏',
                requirement  TEXT NOT NULL DEFAULT '',
                stage        TEXT NOT NULL DEFAULT 'start',
                confirmed    INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        await db.commit()


async def upsert_session(
    session_id: str,
    title: str,
    requirement: str,
    stage: str,
    confirmed: bool,
    created_at: str,
    updated_at: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO sessions (session_id, title, requirement, stage, confirmed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                title      = excluded.title,
                stage      = excluded.stage,
                confirmed  = excluded.confirmed,
                updated_at = excluded.updated_at
        """, (session_id, title, requirement, stage, int(confirmed), created_at, updated_at))
        await db.commit()


async def list_sessions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def delete_session(session_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_session_meta(session_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
