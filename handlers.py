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
from yandex_gpt import interpret_spread, interpret_theme

router = Router()
logger = logging.getLogger(__name__)

# ── Keyboards ──────────────────────────────────────────

BTN_SPREADS = "🃏 Расклады"
BTN_PERSONAL = "✨ Персональные толкования"
BTN_PAYMENT = "💳 Оплата"
BTN_BACK = "◀️ Назад"

BTN_DAY = "🌅 Карта дня"
BTN_SPREAD3 = "🔮 Расклад 3 карты"

BTN_QUESTION = "❓ Расклад с вопросом"
BTN_THEME = "🎯 Расклад по теме"

BTN_LOVE = "❤️ Любовь"
BTN_HEALTH = "🍀 Здоровье"
BTN_CAREER = "💼 Карьера"


def _main_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=BTN_SPREADS), KeyboardButton(text=BTN_PERSONAL)]]
    if not is_admin:
        rows.append([KeyboardButton(text=BTN_PAYMENT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


_spreads_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_DAY), KeyboardButton(text=BTN_SPREAD3)],
        [KeyboardButton(text=BTN_BACK)],
    ],
    resize_keyboard=True,
)

_personal_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_QUESTION), KeyboardButton(text=BTN_THEME)],
        [KeyboardButton(text=BTN_BACK)],
    ],
    resize_keyboard=True,
)

_theme_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_LOVE), KeyboardButton(text=BTN_HEALTH), KeyboardButton(text=BTN_CAREER)],
        [KeyboardButton(text=BTN_BACK)],
    ],
    resize_keyboard=True,
)


# ── FSM States ─────────────────────────────────────────

class BotStates(StatesGroup):
    waiting_for_question = State()
    waiting_for_theme_choice = State()


# ── Helpers ────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


# ── /start ─────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_or_create_user(message.from_user.id)
    text = (
        "Привет! Я простой таролог-бот.\n\n"
        "Расклады — карта дня и расклад 3 карты\n"
        "Персональные толкования — ИИ-расклад по вопросу или теме\n\n"
        f"Осталось персональных толкований: {user['ai_requests_remaining']}"
    )
    await message.answer(text, reply_markup=_main_kb(_is_admin(message.from_user.id)))


# ── Menu navigation ───────────────────────────────────

@router.message(F.text == BTN_SPREADS)
async def menu_spreads(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Выбери тип расклада:", reply_markup=_spreads_kb)


@router.message(F.text == BTN_PERSONAL)
async def menu_personal(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Выбери тип толкования:", reply_markup=_personal_kb)


@router.message(F.text == BTN_PAYMENT)
async def menu_payment(message: Message) -> None:
    await message.answer("Оплата будет доступна в ближайшее время. Следите за обновлениями!")


@router.message(F.text == BTN_BACK)
async def menu_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню:", reply_markup=_main_kb(_is_admin(message.from_user.id)))


# ── /day ───────────────────────────────────────────────

@router.message(Command("day"))
@router.message(F.text == BTN_DAY)
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


# ── /spread ────────────────────────────────────────────

@router.message(Command("spread"))
@router.message(F.text == BTN_SPREAD3)
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


# ── Расклад с вопросом (AI) ────────────────────────────

@router.message(Command("question"))
@router.message(F.text == BTN_QUESTION)
async def cmd_question_spread(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    if not _is_admin(user_id):
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await message.answer(
                "У тебя закончились персональные толкования.\n"
                "Обычный расклад доступен всегда. Полная версия бота — скоро!"
            )
            return
        await message.answer(f"Осталось персональных толкований: {remaining}")

    await state.set_state(BotStates.waiting_for_question)
    await message.answer("Задай свой вопрос, и я сделаю расклад с толкованием:")


@router.message(BotStates.waiting_for_question)
async def handle_question(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    question = message.text
    if not question:
        await message.answer("Пожалуйста, напиши вопрос текстом.")
        return

    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

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
        if not _is_admin(user_id):
            new_remaining = await db.decrement_ai_requests(user_id)
            await message.answer(
                f"Толкование расклада:\n\n{ai_text}\n\n"
                f"Осталось персональных толкований: {new_remaining}"
            )
        else:
            await message.answer(f"Толкование расклада:\n\n{ai_text}")
    else:
        await message.answer("Не удалось получить толкование. Попробуйте позже.")


# ── Расклад по теме (AI) ──────────────────────────────

@router.message(F.text == BTN_THEME)
async def cmd_theme_spread(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    if not _is_admin(user_id):
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await message.answer(
                "У тебя закончились персональные толкования.\n"
                "Обычный расклад доступен всегда. Полная версия бота — скоро!"
            )
            return
        await message.answer(f"Осталось персональных толкований: {remaining}")

    await state.set_state(BotStates.waiting_for_theme_choice)
    await message.answer("Выбери тему расклада:", reply_markup=_theme_kb)


@router.message(BotStates.waiting_for_theme_choice, F.text.in_({BTN_LOVE, BTN_HEALTH, BTN_CAREER}))
async def handle_theme_choice(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    theme = message.text
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    cards = await db.get_random_cards(3)

    labels = ["Прошлое", "Настоящее", "Будущее"]
    lines = [f"Тема: {theme}\n"]
    for label, card in zip(labels, cards):
        await db.log_draw(user_id, card["id"], "spread")
        lines.append(f"{label}: {card['name']} — {card['meaning_short']}")

    await message.answer("\n\n".join(lines), reply_markup=_main_kb(_is_admin(user_id)))

    await message.answer("Толкую карты...")
    ai_text = await interpret_theme(theme, cards)
    if ai_text:
        if not _is_admin(user_id):
            new_remaining = await db.decrement_ai_requests(user_id)
            await message.answer(
                f"Толкование расклада:\n\n{ai_text}\n\n"
                f"Осталось персональных толкований: {new_remaining}"
            )
        else:
            await message.answer(f"Толкование расклада:\n\n{ai_text}")
    else:
        await message.answer("Не удалось получить толкование. Попробуйте позже.")


@router.message(BotStates.waiting_for_theme_choice, F.text == BTN_BACK)
async def handle_theme_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Выбери тип толкования:", reply_markup=_personal_kb)


# ── /reset (admin) ─────────────────────────────────────

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
        await message.answer(f"Счётчик для пользователя {target_id} сброшен.")
    else:
        await message.answer(f"Пользователь {target_id} не найден.")


# ── /stats (admin) ─────────────────────────────────────

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


# ── Image helper ───────────────────────────────────────

async def _send_card_image(message: Message, card: dict, caption: str) -> bool:
    if card.get("file_id"):
        try:
            await message.answer_photo(photo=card["file_id"], caption=caption)
            return True
        except Exception:
            logger.warning("Stale file_id for card %s, falling back", card["id"])

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
