import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from db import init_db
from handlers import router
from middlewares import AntifloodMiddleware


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()
    logging.info("Database initialized, 78 cards seeded")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    antiflood = AntifloodMiddleware()
    dp.message.middleware(antiflood)
    dp.callback_query.middleware(antiflood)

    dp.include_router(router)

    logging.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
