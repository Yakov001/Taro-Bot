import aiosqlite

from config import DB_PATH, DEFAULT_SPREADS, DEFAULT_AI_REQUESTS
from cards_data import TAROT_CARDS


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                spreads_remaining INTEGER DEFAULT 5,
                ai_requests_remaining INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add ai_requests_remaining if missing
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN ai_requests_remaining INTEGER DEFAULT 3"
            )
            await db.commit()
        except Exception:
            pass  # column already exists
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tarot_cards (
                id INTEGER PRIMARY KEY,
                name TEXT,
                image_url TEXT,
                meaning_short TEXT,
                file_id TEXT DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS draw_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                draw_type TEXT CHECK(draw_type IN ('day', 'spread')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
        await _seed_cards(db)


async def _seed_cards(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT COUNT(*) FROM tarot_cards")
    (count,) = await cursor.fetchone()
    if count > 0:
        return
    await db.executemany(
        "INSERT OR IGNORE INTO tarot_cards (id, name, image_url, meaning_short) VALUES (?, ?, ?, ?)",
        [(c["id"], c["name"], c["image_filename"], c["meaning_short"]) for c in TAROT_CARDS],
    )
    await db.commit()


async def get_or_create_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row)


async def get_random_card() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tarot_cards ORDER BY RANDOM() LIMIT 1")
        row = await cursor.fetchone()
        return dict(row)


async def get_random_cards(count: int = 3) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tarot_cards ORDER BY RANDOM() LIMIT ?", (count,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def log_draw(user_id: int, card_id: int, draw_type: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO draw_log (user_id, card_id, draw_type) VALUES (?, ?, ?)",
            (user_id, card_id, draw_type),
        )
        await db.commit()


async def decrement_spreads(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET spreads_remaining = spreads_remaining - 1 WHERE user_id = ? AND spreads_remaining > 0",
            (user_id,),
        )
        await db.commit()
        cursor = await db.execute("SELECT spreads_remaining FROM users WHERE user_id = ?", (user_id,))
        (remaining,) = await cursor.fetchone()
        return remaining


async def get_ai_remaining(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT ai_requests_remaining FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def decrement_ai_requests(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET ai_requests_remaining = ai_requests_remaining - 1 "
            "WHERE user_id = ? AND ai_requests_remaining > 0",
            (user_id,),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT ai_requests_remaining FROM users WHERE user_id = ?", (user_id,)
        )
        (remaining,) = await cursor.fetchone()
        return remaining


async def reset_user_spreads(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE users SET spreads_remaining = ?, ai_requests_remaining = ? WHERE user_id = ?",
            (DEFAULT_SPREADS, DEFAULT_AI_REQUESTS, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_card_file_id(card_id: int, file_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tarot_cards SET file_id = ? WHERE id = ?", (file_id, card_id))
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
        total_users = (await cursor.fetchone())["cnt"]

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM draw_log WHERE draw_type='spread' AND DATE(created_at)=DATE('now')"
        )
        today_spreads = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("""
            SELECT tc.name, COUNT(*) as cnt
            FROM draw_log dl
            JOIN tarot_cards tc ON dl.card_id = tc.id
            WHERE DATE(dl.created_at) = DATE('now')
            GROUP BY dl.card_id
            ORDER BY cnt DESC
            LIMIT 3
        """)
        top_cards = [{"name": row["name"], "count": row["cnt"]} for row in await cursor.fetchall()]

        return {
            "total_users": total_users,
            "today_spreads": today_spreads,
            "top_cards": top_cards,
        }
