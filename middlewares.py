import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

import db
from config import FLOOD_RATE_LIMIT, FLOOD_WINDOW_SECONDS, FLOOD_BAN_SECONDS

logger = logging.getLogger(__name__)


class UsernameSyncMiddleware(BaseMiddleware):
    """Keep users.username in sync on every incoming update.

    Caches recently-seen (uid -> username) pairs so we only write when the
    value actually changed. This ensures the admin panel can always look
    up by @username, not just when the user re-sends /start.
    """

    def __init__(self) -> None:
        self._last_seen: dict[int, str | None] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None:
            uname = user.username  # may be None
            if self._last_seen.get(user.id) != uname:
                try:
                    await db.get_or_create_user(user.id, username=uname)
                    self._last_seen[user.id] = uname
                except Exception:
                    logger.warning("Failed to sync username for user %s", user.id, exc_info=True)
        return await handler(event, data)


class AntifloodMiddleware(BaseMiddleware):

    def __init__(self) -> None:
        self.users: dict[int, dict] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        uid = user.id
        now = time.monotonic()

        if uid in self.users:
            rec = self.users[uid]

            if rec["ban_until"] and now < rec["ban_until"]:
                left = int(rec["ban_until"] - now)
                await event.answer(f"Слишком много запросов. Подождите {left} сек.")
                return None

            if now - rec["window_start"] > FLOOD_WINDOW_SECONDS:
                rec["count"] = 1
                rec["window_start"] = now
                rec["ban_until"] = 0
            else:
                rec["count"] += 1
                if rec["count"] > FLOOD_RATE_LIMIT:
                    rec["ban_until"] = now + FLOOD_BAN_SECONDS
                    await event.answer("Вы временно заблокированы за спам. Подождите 5 минут.")
                    return None
        else:
            self.users[uid] = {"count": 1, "window_start": now, "ban_until": 0}

        return await handler(event, data)
