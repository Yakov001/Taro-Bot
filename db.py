import secrets
import string

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                package_id TEXT NOT NULL,
                stars_amount INTEGER NOT NULL,
                readings_granted INTEGER NOT NULL,
                telegram_payment_charge_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blind_invites (
                invite_code TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blind_sessions (
                code TEXT PRIMARY KEY,
                invite_code TEXT,
                user_a INTEGER NOT NULL,
                user_b INTEGER,
                card_a INTEGER,
                card_b INTEGER,
                confirmed_a INTEGER DEFAULT 0,
                confirmed_b INTEGER DEFAULT 0,
                status TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        for column, definition in (
            ("invite_code", "TEXT"),
            ("confirmed_a", "INTEGER DEFAULT 0"),
            ("confirmed_b", "INTEGER DEFAULT 0"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE blind_sessions ADD COLUMN {column} {definition}"
                )
                await db.commit()
            except Exception:
                pass
        await db.commit()
        await _seed_cards(db)


async def _seed_cards(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT COUNT(*) FROM tarot_cards")
    (count,) = await cursor.fetchone()
    if count == 0:
        await db.executemany(
            "INSERT INTO tarot_cards (id, name, image_url, meaning_short) VALUES (?, ?, ?, ?)",
            [(c["id"], c["name"], c["image_filename"], c["meaning_short"]) for c in TAROT_CARDS],
        )
    else:
        # Update image filenames and names from cards_data
        await db.executemany(
            "UPDATE tarot_cards SET image_url = ?, name = ?, meaning_short = ? WHERE id = ?",
            [(c["image_filename"], c["name"], c["meaning_short"], c["id"]) for c in TAROT_CARDS],
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


async def add_ai_requests(user_id: int, amount: int) -> int:
    """Add AI requests to user balance. Returns new balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET ai_requests_remaining = ai_requests_remaining + ? WHERE user_id = ?",
            (amount, user_id),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT ai_requests_remaining FROM users WHERE user_id = ?", (user_id,)
        )
        (remaining,) = await cursor.fetchone()
        return remaining


async def log_payment(
    user_id: int,
    package_id: str,
    stars_amount: int,
    readings_granted: int,
    telegram_payment_charge_id: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (user_id, package_id, stars_amount, readings_granted, telegram_payment_charge_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, package_id, stars_amount, readings_granted, telegram_payment_charge_id),
        )
        await db.commit()


async def update_card_file_id(card_id: int, file_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tarot_cards SET file_id = ? WHERE id = ?", (file_id, card_id))
        await db.commit()


async def get_card_by_id(card_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tarot_cards WHERE id = ?", (card_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ── Blind Pair Tarot ─────────────────────────────────

_BLIND_CODE_ALPHABET = string.ascii_uppercase + string.digits


async def _generate_blind_code(db: aiosqlite.Connection) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_BLIND_CODE_ALPHABET) for _ in range(4))
        cursor = await db.execute(
            "SELECT 1 FROM blind_invites WHERE invite_code = ? "
            "UNION SELECT 1 FROM blind_sessions WHERE code = ?",
            (code, code),
        )
        if not await cursor.fetchone():
            return code
    raise RuntimeError("Could not generate unique blind code")


async def create_blind_invite(owner_user_id: int) -> str:
    """Always create a fresh invite code valid for 24h."""
    async with aiosqlite.connect(DB_PATH) as db:
        code = await _generate_blind_code(db)
        await db.execute(
            "UPDATE blind_invites SET expires_at = datetime('now') "
            "WHERE owner_user_id = ? AND expires_at > datetime('now')",
            (owner_user_id,),
        )
        await db.execute(
            "INSERT INTO blind_invites (invite_code, owner_user_id, expires_at) "
            "VALUES (?, ?, datetime('now', '+24 hours'))",
            (code, owner_user_id),
        )
        await db.commit()
        return code


async def get_blind_invite(invite_code: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM blind_invites "
            "WHERE invite_code = ? AND expires_at > datetime('now')",
            (invite_code,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_blind_session_from_invite(
    invite_code: str, owner_user_id: int, friend_user_id: int
) -> str:
    return await create_direct_blind_session(owner_user_id, friend_user_id, invite_code)


async def create_direct_blind_session(
    user_a: int, user_b: int, invite_code: str | None = None
) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        code = await _generate_blind_code(db)
        await db.execute(
            "INSERT INTO blind_sessions "
            "(code, invite_code, user_a, user_b, status, expires_at) "
            "VALUES (?, ?, ?, ?, 'pending_confirmation', datetime('now', '+24 hours'))",
            (code, invite_code, user_a, user_b),
        )
        await db.commit()
        return code


async def find_incomplete_pair_session(
    owner_user_id: int, friend_user_id: int
) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM blind_sessions "
            "WHERE user_a = ? AND user_b = ? "
            "AND status IN ('pending_confirmation', 'processing') "
            "AND expires_at > datetime('now') "
            "ORDER BY created_at DESC LIMIT 1",
            (owner_user_id, friend_user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_blind_session(code: str) -> dict | None:
    """Return session row if it exists and has not expired, else None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM blind_sessions "
            "WHERE code = ? AND expires_at > datetime('now')",
            (code,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def confirm_blind_session_user(code: str, user_id: int) -> dict | None:
    """Mark one participant as confirmed and return the refreshed session."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_a, user_b FROM blind_sessions "
            "WHERE code = ? AND expires_at > datetime('now')",
            (code,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        if user_id == row["user_a"]:
            await db.execute(
                "UPDATE blind_sessions SET confirmed_a = 1 "
                "WHERE code = ? AND expires_at > datetime('now')",
                (code,),
            )
        elif user_id == row["user_b"]:
            await db.execute(
                "UPDATE blind_sessions SET confirmed_b = 1 "
                "WHERE code = ? AND expires_at > datetime('now')",
                (code,),
            )
        else:
            return None

        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM blind_sessions "
            "WHERE code = ? AND expires_at > datetime('now')",
            (code,),
        )
        refreshed = await cursor.fetchone()
        return dict(refreshed) if refreshed else None


async def start_blind_session_if_ready(code: str, card_a: int, card_b: int) -> bool:
    """Lock a confirmed session for processing so the forecast starts only once."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE blind_sessions "
            "SET card_a = ?, card_b = ?, status = 'processing' "
            "WHERE code = ? "
            "AND user_b IS NOT NULL "
            "AND confirmed_a = 1 "
            "AND confirmed_b = 1 "
            "AND status = 'pending_confirmation' "
            "AND expires_at > datetime('now')",
            (card_a, card_b, code),
        )
        await db.commit()
        return cursor.rowcount > 0


async def complete_blind_session(code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE blind_sessions "
            "SET status = 'completed' "
            "WHERE code = ? AND status = 'processing'",
            (code,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def reject_blind_session(code: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "UPDATE blind_sessions "
            "SET status = 'rejected' "
            "WHERE code = ? AND status = 'pending_confirmation' "
            "AND expires_at > datetime('now')",
            (code,),
        )
        await db.commit()
        if cursor.rowcount <= 0:
            return None

        cursor = await db.execute(
            "SELECT * FROM blind_sessions "
            "WHERE code = ? AND expires_at > datetime('now')",
            (code,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


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
