import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    FSInputFile,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

import db
from config import ADMIN_USER_ID, IMAGES_DIR
from yandex_gpt import interpret_spread

router = Router()
logger = logging.getLogger(__name__)

_main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Карта дня"), KeyboardButton(text="Расклад 3 карты")],
        [KeyboardButton(text="Расклад с вопросом")],
    ],
    resize_keyboard=True,
)


class SpreadQuestion(StatesGroup):
    waiting_for_question = State()


# ── /start ──────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await db.get_or_create_user(message.from_user.id)
    text = (
        "Привет! Я простой таролог-бот.\n"
        "Карта дня — /day\n"
        "Расклад на прошлое-настоящее-будущее — /spread\n"
        "Расклад с вопросом (ИИ-толкование) — /question\n\n"
        f"Осталось персональных толкований: {user['ai_requests_remaining']}"
    )
    await message.answer(text, reply_markup=_main_keyboard)


# ── /day ────────────────────────────────────────────────

@router.message(Command("day"))
@router.message(F.text == "Карта дня")
async def cmd_day(message: Message, bot: Bot) -> None:
    await _send_day_card(message, bot, message.from_user.id)


async def _send_day_card(message: Message, bot: Bot, user_id: int) -> None:
    await db.get_or_create_user(user_id)
    card = await db.get_random_card()
    await db.log_draw(user_id, card["id"], "day")

    caption = f"Ваша карта дня — {card['name']}\n\n{card['meaning_short']}"
    sent = await _send_card_image(message, card, caption)
    if not sent:
        await message.answer(caption)


# ── /spread ─────────────────────────────────────────────

@router.message(Command("spread"))
@router.message(F.text == "Расклад 3 карты")
async def cmd_spread(message: Message, bot: Bot) -> None:
    await _send_spread(message, bot, message.from_user.id)


async def _send_spread(message: Message, bot: Bot, user_id: int) -> None:
    await db.get_or_create_user(user_id)

    cards = await db.get_random_cards(3)

    labels = ["Прошлое", "Настоящее", "Будущее"]
    lines = []
    for label, card in zip(labels, cards):
        await db.log_draw(user_id, card["id"], "spread")
        lines.append(f"{label}: {card['name']} — {card['meaning_short']}")

    await message.answer("\n\n".join(lines))


# ── Расклад с вопросом (AI) ─────────────────────────────

@router.message(Command("question"))
@router.message(F.text == "Расклад с вопросом")
async def cmd_question_spread(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    is_admin = user_id == ADMIN_USER_ID

    # Check AI limit (admin bypasses)
    if not is_admin:
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await message.answer(
                "У тебя закончились персональные толкования.\n"
                "Обычный расклад (/spread) доступен всегда. Полная версия бота — скоро!"
            )
            return
        await message.answer(f"У тебя осталось персональных толкований: {remaining}")

    await state.set_state(SpreadQuestion.waiting_for_question)
    await message.answer("Задай свой вопрос, и я сделаю расклад с толкованием:")


@router.message(SpreadQuestion.waiting_for_question)
async def handle_question(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    question = message.text
    if not question:
        await message.answer("Пожалуйста, напиши вопрос текстом.")
        return

    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    is_admin = user_id == ADMIN_USER_ID

    cards = await db.get_random_cards(3)

    labels = ["Прошлое", "Настоящее", "Будущее"]
    lines = []
    for label, card in zip(labels, cards):
        await db.log_draw(user_id, card["id"], "spread")
        lines.append(f"{label}: {card['name']} — {card['meaning_short']}")

    await message.answer("\n\n".join(lines))

    await message.answer("Толкую карты...")
    ai_text = await interpret_spread(question, cards)
    if ai_text:
        # Decrement and show remaining (admin skips)
        if not is_admin:
            new_remaining = await db.decrement_ai_requests(user_id)
            await message.answer(f"Толкование расклада:\n\n{ai_text}\n\n"
                                 f"Осталось персональных толкований: {new_remaining}")
        else:
            await message.answer(f"Толкование расклада:\n\n{ai_text}")
    else:
        await message.answer("Не удалось получить толкование. Попробуйте позже.")


# ── /reset (admin) ──────────────────────────────────────

@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("Эта команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /reset <user_id>")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return

    found = await db.reset_user_spreads(target_id)
    if found:
        await message.answer(f"Счётчик раскладов и персональных толкований для пользователя {target_id} сброшен.")
    else:
        await message.answer(f"Пользователь {target_id} не найден.")


# ── /stats (admin) ──────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("Эта команда доступна только администратору.")
        return

    stats = await db.get_stats()
    lines = [
        f"Всего пользователей: {stats['total_users']}",
        f"Раскладов сегодня: {stats['today_spreads']}",
    ]
    if stats["top_cards"]:
        lines.append("Топ-3 карты дня:")
        for i, card in enumerate(stats["top_cards"], 1):
            lines.append(f"  {i}. {card['name']} — {card['count']} раз")
    else:
        lines.append("Сегодня ещё не было раскладов.")

    await message.answer("\n".join(lines))


# ── Image helper ────────────────────────────────────────

async def _send_card_image(message: Message, card: dict, caption: str) -> bool:
    # Try cached file_id first
    if card.get("file_id"):
        try:
            await message.answer_photo(photo=card["file_id"], caption=caption)
            return True
        except Exception:
            logger.warning("Stale file_id for card %s, falling back", card["id"])

    # Try local file
    image_path = IMAGES_DIR / card["image_url"]
    if image_path.exists():
        try:
            photo = FSInputFile(str(image_path))
            result = await message.answer_photo(photo=photo, caption=caption)
            new_file_id = result.photo[-1].file_id
            await db.update_card_file_id(card["id"], new_file_id)
            return True
        except Exception:
            logger.warning("Failed to send image for card %s", card["id"], exc_info=True)

    return False
