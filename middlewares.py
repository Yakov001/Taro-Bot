import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from config import FLOOD_RATE_LIMIT, FLOOD_WINDOW_SECONDS, FLOOD_BAN_SECONDS


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
