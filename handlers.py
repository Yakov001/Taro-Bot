import asyncio
import logging
import random  # <-- Добавлен импорт

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

import analytics
import db
from config import ADMIN_USER_ID, IMAGES_DIR, PAYMENT_PACKAGES, PEEK_COST_STARS
from yandex_gpt import generate_pair_forecast, interpret_spread, interpret_theme

router = Router()
logger = logging.getLogger(__name__)

# ── Keyboards ──────────────────────────────────────────

BTN_SPREADS = "🃏 Расклады"
BTN_PERSONAL_PREFIX = "✨ Персональные толкования"
BTN_BLIND = "👥 Парное гадание"
BTN_PAYMENT = "💳 Оплата"
BTN_BACK = "◀️ Назад"

BTN_DAY = "🌅 Карта дня"
BTN_SPREAD3 = "🔮 Расклад 3 карты"

BTN_QUESTION = "❓ Расклад с вопросом"
BTN_THEME = "🎯 Расклад по теме"

BTN_LOVE = "❤️ Любовь"
BTN_HEALTH = "🍀 Здоровье"
BTN_CAREER = "💼 Карьера"

BTN_PAY_5 = "🌟 5 толкований (25⭐)"
BTN_PAY_10 = "📦 10 толкований (50⭐)"
BTN_PAY_25 = "💎 25 толкований (100⭐)"

# Map button text → package_id from config
_BTN_TO_PACKAGE = {
    BTN_PAY_5: "pack_5",
    BTN_PAY_10: "pack_10",
    BTN_PAY_25: "pack_25",
}


def _main_kb(is_admin: bool, ai_remaining: int = 0) -> ReplyKeyboardMarkup:
    personal_text = f"{BTN_PERSONAL_PREFIX} (Осталось: {ai_remaining})"
    rows = [
        [KeyboardButton(text=BTN_SPREADS)],
        [KeyboardButton(text=personal_text)],
        [KeyboardButton(text=BTN_BLIND)],
    ]
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

_payment_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_PAY_5)],
        [KeyboardButton(text=BTN_PAY_10)],
        [KeyboardButton(text=BTN_PAY_25)],
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


_THINKING_PHASES = [
    "🔮 Раскладываю карты...",
    "✨ Вглядываюсь в символы...",
    "🌙 Составляю толкование...",
]


async def _animate_thinking(message: Message) -> Message:
    """Send animated 'thinking' messages to build anticipation."""
    msg = await message.answer(_THINKING_PHASES[0])
    for phase in _THINKING_PHASES[1:]:
        await asyncio.sleep(2)
        await msg.edit_text(phase)
    await asyncio.sleep(1)
    return msg


async def _animate_thinking_in_chat(bot: Bot, chat_id: int) -> Message | None:
    """Same animation but in an arbitrary chat (e.g. the inviter's DM)."""
    try:
        msg = await bot.send_message(chat_id, _THINKING_PHASES[0])
    except Exception:
        logger.warning("Failed to start thinking animation for chat %s", chat_id, exc_info=True)
        return None
    for phase in _THINKING_PHASES[1:]:
        await asyncio.sleep(2)
        try:
            await msg.edit_text(phase)
        except Exception:
            return msg
    await asyncio.sleep(1)
    return msg


# ── /start ─────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if args.startswith("blind_"):
        code = args[len("blind_"):].upper()
        await _handle_blind_join(message, bot, code)
        return

    user = await db.get_or_create_user(message.from_user.id)
    await analytics.track(message.from_user.id, "bot_start")
    text = (
        "🌟 Привет! Я твой персональный таролог.\n\n"
        "🃏 Расклады — карта дня и расклад 3 карты\n"
        "✨ Персональные толкования — расклад по вопросу или теме\n"
        "👥 Парное гадание — по одной карте каждому из двоих\n\n"
        f"🔮 Осталось персональных толкований: {user['ai_requests_remaining']}"
    )
    await message.answer(text, reply_markup=_main_kb(_is_admin(message.from_user.id), user['ai_requests_remaining']))


# ── Menu navigation ───────────────────────────────────

@router.message(F.text == BTN_SPREADS)
async def menu_spreads(message: Message, state: FSMContext) -> None:
    await state.clear()
    await analytics.track(message.from_user.id, "menu_spreads")
    await message.answer("🃏 Выбери тип расклада:", reply_markup=_spreads_kb)


@router.message(F.text.startswith(BTN_PERSONAL_PREFIX))
async def menu_personal(message: Message, state: FSMContext) -> None:
    await state.clear()
    await analytics.track(message.from_user.id, "menu_personal")
    await message.answer("✨ Выбери тип толкования:", reply_markup=_personal_kb)


@router.message(F.text == BTN_PAYMENT)
async def menu_payment(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_or_create_user(message.from_user.id)
    remaining = user["ai_requests_remaining"]
    await analytics.track(message.from_user.id, "menu_payment", balance=remaining)
    await message.answer(
        f"💫 Персональных толкований на балансе: {remaining}\n\n"
        "⬇️ Выбери пакет для пополнения:",
        reply_markup=_payment_kb,
    )


@router.message(F.text == BTN_BACK)
async def menu_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_or_create_user(message.from_user.id)
    await analytics.track(message.from_user.id, "back")
    await message.answer("🏠 Главное меню:",
                         reply_markup=_main_kb(_is_admin(message.from_user.id), user['ai_requests_remaining']))


# ── /day ───────────────────────────────────────────────

@router.message(Command("day"))
@router.message(F.text == BTN_DAY)
async def cmd_day(message: Message, bot: Bot) -> None:
    await _send_day_card(message, bot, message.from_user.id)


async def _send_day_card(message: Message, bot: Bot, user_id: int) -> None:
    await db.get_or_create_user(user_id)
    card = await db.get_random_card()
    await db.log_draw(user_id, card["id"], "day")
    await analytics.track(user_id, "card_day", card_name=card["name"])

    caption = f"🃏 Ваша карта дня — {card['name']}\n\n{card['meaning_short']}"
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
    await analytics.track(user_id, "spread_3", cards=[c["name"] for c in cards])
    await _send_spread_cards(message, cards, user_id)


# ── Расклад с вопросом (AI) ────────────────────────────

@router.message(Command("question"))
@router.message(F.text == BTN_QUESTION)
async def cmd_question_spread(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    if not _is_admin(user_id):
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await analytics.track(user_id, "ai_limit_reached", source="question")
            await message.answer(
                "❌ У тебя закончились персональные толкования.\n"
                "🃏 Обычный расклад доступен всегда!\n"
                "💳 Пополни баланс в разделе «Оплата»"
            )
            return
        await message.answer(f"🔮 Осталось персональных толкований: {remaining}")

    await analytics.track(user_id, "question_start")
    await state.set_state(BotStates.waiting_for_question)
    await message.answer("💬 Задай свой вопрос, и я сделаю расклад с толкованием:")


@router.message(BotStates.waiting_for_question)
async def handle_question(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    question = message.text
    if not question:
        await message.answer("✏️ Пожалуйста, напиши вопрос текстом.")
        return

    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    cards = await db.get_random_cards(3)
    await _send_spread_cards(message, cards, user_id)

    thinking_msg = await _animate_thinking(message)
    ai_text = await interpret_spread(question, cards)
    await thinking_msg.delete()
    if ai_text:
        if not _is_admin(user_id):
            new_remaining = await db.decrement_ai_requests(user_id)
            await analytics.track(user_id, "question_complete", ai_success=True, balance_after=new_remaining)
            await message.answer(
                f"🌙 Толкование расклада:\n\n{ai_text}\n\n"
                f"🔮 Осталось персональных толкований: {new_remaining}",
                reply_markup=_main_kb(False, new_remaining),
            )
        else:
            await analytics.track(user_id, "question_complete", ai_success=True)
            await message.answer(f"🌙 Толкование расклада:\n\n{ai_text}")
    else:
        await analytics.track(user_id, "question_complete", ai_success=False)
        await message.answer("⚠️ Не удалось получить толкование. Попробуйте позже.")


# ── Расклад по теме (AI) ──────────────────────────────

@router.message(F.text == BTN_THEME)
async def cmd_theme_spread(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await db.get_or_create_user(user_id)

    if not _is_admin(user_id):
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await analytics.track(user_id, "ai_limit_reached", source="theme")
            await message.answer(
                "❌ У тебя закончились персональные толкования.\n"
                "🃏 Обычный расклад доступен всегда!\n"
                "💳 Пополни баланс в разделе «Оплата»"
            )
            return
        await message.answer(f"🔮 Осталось персональных толкований: {remaining}")

    await analytics.track(user_id, "theme_start")
    await state.set_state(BotStates.waiting_for_theme_choice)
    await message.answer("🎯 Выбери тему расклада:", reply_markup=_theme_kb)


@router.message(BotStates.waiting_for_theme_choice, F.text.in_({BTN_LOVE, BTN_HEALTH, BTN_CAREER}))
async def handle_theme_choice(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    theme = message.text
    user_id = message.from_user.id
    user = await db.get_or_create_user(user_id)

    cards = await db.get_random_cards(3)
    await analytics.track(user_id, "theme_select", theme=theme)
    await message.answer(f"🎯 Тема: {theme}", reply_markup=_main_kb(_is_admin(user_id), user['ai_requests_remaining']))
    await _send_spread_cards(message, cards, user_id)

    thinking_msg = await _animate_thinking(message)
    ai_text = await interpret_theme(theme, cards)
    await thinking_msg.delete()
    if ai_text:
        if not _is_admin(user_id):
            new_remaining = await db.decrement_ai_requests(user_id)
            await analytics.track(user_id, "theme_complete", ai_success=True, theme=theme, balance_after=new_remaining)
            await message.answer(
                f"🌙 Толкование расклада:\n\n{ai_text}\n\n"
                f"🔮 Осталось персональных толкований: {new_remaining}",
                reply_markup=_main_kb(False, new_remaining),
            )
        else:
            await analytics.track(user_id, "theme_complete", ai_success=True, theme=theme)
            await message.answer(f"🌙 Толкование расклада:\n\n{ai_text}")
    else:
        await analytics.track(user_id, "theme_complete", ai_success=False, theme=theme)
        await message.answer("⚠️ Не удалось получить толкование. Попробуйте позже.")


@router.message(BotStates.waiting_for_theme_choice, F.text == BTN_BACK)
async def handle_theme_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await analytics.track(message.from_user.id, "back", from_screen="theme_choice")
    await message.answer("✨ Выбери тип толкования:", reply_markup=_personal_kb)


# ── Payments (Telegram Stars) ─────────────────────────

@router.message(F.text.in_({BTN_PAY_5, BTN_PAY_10, BTN_PAY_25}))
async def send_payment_invoice(message: Message, bot: Bot) -> None:
    """User tapped a package button → send Stars invoice."""
    package_id = _BTN_TO_PACKAGE[message.text]
    pkg = PAYMENT_PACKAGES[package_id]

    await analytics.track(
        message.from_user.id, "payment_invoice_sent",
        package_id=package_id,
        stars=pkg["stars"],
        readings=pkg["readings"],
    )
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=pkg["title"],
        description=pkg["description"],
        payload=f"{package_id}:{message.from_user.id}",  # package_id:user_id
        currency="XTR",  # Telegram Stars — provider_token не нужен
        prices=[LabeledPrice(label=pkg["title"], amount=pkg["stars"])],
    )


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    """Telegram asks if we're ready to accept payment. Must respond <10 sec."""
    payload = pre_checkout_query.invoice_payload
    parts = payload.split(":")

    # Peek payment: peek:{code}:{user_id}
    if parts[0] == "peek" and len(parts) == 3:
        try:
            user_id = int(parts[2])
        except ValueError:
            await pre_checkout_query.answer(ok=False, error_message="Неверный формат.")
            return
        session = await db.get_blind_session(parts[1])
        if (
            session
            and session["status"] == "completed"
            and user_id in (session["user_a"], session["user_b"])
        ):
            await pre_checkout_query.answer(ok=True)
        else:
            await pre_checkout_query.answer(ok=False, error_message="Сессия недействительна или истекла.")
        return

    # Validate payload format and package existence
    if len(parts) == 2 and parts[0] in PAYMENT_PACKAGES:
        await pre_checkout_query.answer(ok=True)
    else:
        await pre_checkout_query.answer(ok=False, error_message="Неизвестный пакет. Попробуйте снова.")


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    """Payment confirmed by Telegram. Credit AI readings to user."""
    payment = message.successful_payment
    payload = payment.invoice_payload
    parts = payload.split(":")

    # Peek payment: peek:{code}:{user_id}
    if parts[0] == "peek" and len(parts) == 3:
        await _handle_peek_payment(message, payment, parts[1], int(parts[2]))
        return

    if len(parts) != 2 or parts[0] not in PAYMENT_PACKAGES:
        logger.error("Unknown payment payload: %s", payload)
        await message.answer("Оплата получена, но произошла ошибка. Напишите администратору.")
        return

    package_id = parts[0]
    pkg = PAYMENT_PACKAGES[package_id]
    user_id = message.from_user.id
    readings = pkg["readings"]

    # Ensure user exists
    await db.get_or_create_user(user_id)

    # Credit readings to balance
    new_balance = await db.add_ai_requests(user_id, readings)

    # Log payment for accounting
    charge_id = payment.telegram_payment_charge_id or ""
    await db.log_payment(user_id, package_id, pkg["stars"], readings, charge_id)
    await analytics.track(
        user_id, "payment_success",
        package_id=package_id,
        stars=pkg["stars"],
        readings=readings,
        balance_after=new_balance,
    )

    logger.info(
        "Payment OK: user=%s package=%s stars=%s readings=+%s balance=%s charge=%s",
        user_id, package_id, pkg["stars"], readings, new_balance, charge_id,
    )

    await message.answer(
        f"✅ Оплата прошла!\n\n"
        f"🎁 Начислено толкований: +{readings}\n"
        f"🔮 Баланс персональных толкований: {new_balance}",
        reply_markup=_main_kb(_is_admin(user_id), new_balance),
    )


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


# ── Новая анимация для вытягивания карт ──────────────────

async def _animate_drawing(message: Message, card_number: int) -> Message:
    """
    Отправляет сообщение с анимацией вытягивания карты и возвращает объект сообщения.
    card_number: 1, 2 или 3.
    """
    # Словарь с фразами для каждого этапа вытягивания карты
    draw_phrases = {
        1: [
            "🃏 Тасуем колоду...",
            "✨ Концентрируемся на энергии...",
            "🌙 Вытягиваю первую карту...",
            "🔮 Первая карта готова:",
        ],
        2: [
            "🌀 Сдвигаем часть колоды...",
            "🌟 Смотрим вторую карту...",
            "💫 Вторая карта готова:",
        ],
        3: [
            "🌌 Осталась последняя карта...",
            "⭐ Завершаем расклад...",
            "🎴 Третья карта готова:",
        ],
    }

    phrases = draw_phrases.get(card_number, ["🎲 Вытягиваю карту..."])

    # Отправляем первое сообщение из списка фраз
    msg = await message.answer(phrases[0])

    # Проходим по остальным фразам с паузой
    for phrase in phrases[1:]:
        await asyncio.sleep(1.5)  # Пауза между сменой фраз
        await msg.edit_text(phrase)

    await asyncio.sleep(0.8)  # Небольшая пауза перед показом карты
    return msg


async def _send_card_to_chat(bot: Bot, chat_id: int, card: dict, caption: str) -> bool:
    """Same image-cache fallback as _send_card_image, but for arbitrary chat_id."""
    if card.get("file_id"):
        try:
            await bot.send_photo(chat_id=chat_id, photo=card["file_id"], caption=caption)
            return True
        except Exception:
            logger.warning("Stale file_id for card %s, falling back", card["id"])

    image_path = IMAGES_DIR / card["image_url"]
    if image_path.exists():
        try:
            photo = FSInputFile(str(image_path))
            result = await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
            new_file_id = result.photo[-1].file_id
            await db.update_card_file_id(card["id"], new_file_id)
            return True
        except Exception:
            logger.warning("Failed to send image for card %s", card["id"], exc_info=True)

    return False


# ── Blind Pair Tarot ───────────────────────────────────

def _peek_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=f"🔍 Подсмотреть карту партнёра ({PEEK_COST_STARS}⭐)",
                callback_data=f"peek_{code}",
            )
        ]]
    )


def _blind_confirm_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Подтвердить", callback_data=f"blind_confirm_{code}"),
        ]]
    )


def _format_partner_name(chat) -> str:
    if chat is None:
        return "Ваш партнёр"

    parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
    full_name = " ".join(part for part in parts if part).strip()
    if full_name:
        return full_name
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"
    return "Ваш партнёр"


def _blind_confirm_kb_v2(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Подтвердить", callback_data=f"blind_confirm_{code}"),
            InlineKeyboardButton(text="Отклонить", callback_data=f"blind_reject_{code}"),
        ]]
    )


def _blind_result_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Повторить парное гадание",
                callback_data=f"blind_replay_{code}",
            )],
            [InlineKeyboardButton(
                text=f"🔍 Подсмотреть карту партнёра ({PEEK_COST_STARS}⭐)",
                callback_data=f"peek_{code}",
            )],
        ]
    )


async def _send_blind_confirmation_prompt(
    bot: Bot,
    chat_id: int,
    partner_id: int,
    code: str,
    intro_text: str,
) -> None:
    kb = _blind_confirm_kb_v2(code)
    partner_chat = None
    try:
        partner_chat = await bot.get_chat(partner_id)
    except Exception:
        logger.warning("Failed to fetch partner chat %s", partner_id, exc_info=True)

    partner_name = _format_partner_name(partner_chat)
    text = (
        f"{intro_text}\n\n"
        f"Партнёр для парного расклада: {partner_name}\n\n"
        "Нажми «Подтвердить», чтобы подтвердить участие. "
        "Расклад начнётся только после подтверждения обоих участников."
    )

    photo_file_id = None
    try:
        photos = await bot.get_user_profile_photos(partner_id, limit=1)
        if photos.photos:
            photo_file_id = photos.photos[0][-1].file_id
    except Exception:
        logger.warning("Failed to fetch profile photo for partner %s", partner_id, exc_info=True)

    if photo_file_id:
        try:
            await bot.send_photo(chat_id=chat_id, photo=photo_file_id, caption=text, reply_markup=kb)
            return
        except Exception:
            logger.warning("Failed to send confirmation photo to chat %s", chat_id, exc_info=True)

    await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)


async def _start_blind_reading(
    bot: Bot,
    code: str,
    user_a_id: int,
    user_b_id: int,
    trigger_message: Message | None = None,
) -> None:
    cards = await db.get_random_cards(2)
    if len(cards) < 2:
        if trigger_message is not None:
            await trigger_message.answer("Ошибка: недостаточно карт в колоде.")
        else:
            await bot.send_message(user_b_id, "Ошибка: недостаточно карт в колоде.")
        return

    card_a, card_b = cards[0], cards[1]
    started = await db.start_blind_session_if_ready(code, card_a["id"], card_b["id"])
    if not started:
        return

    thinking_a, thinking_b = await asyncio.gather(
        _animate_thinking_in_chat(bot, user_a_id),
        _animate_thinking_in_chat(bot, user_b_id),
    )
    forecast = await generate_pair_forecast(card_a, card_b)
    for item in (thinking_a, thinking_b):
        if item is None:
            continue
        try:
            await item.delete()
        except Exception:
            pass
    if not forecast:
        forecast = "✨ Карты сплетаются в необычный узор — прислушайтесь друг к другу."

    kb = _blind_result_kb(code)

    caption_a = f"🃏 Твоя карта: {card_a['name']}\n\n{card_a['meaning_short']}"
    try:
        sent_a = await _send_card_to_chat(bot, user_a_id, card_a, caption_a)
        if not sent_a:
            await bot.send_message(user_a_id, caption_a)
        await bot.send_message(
            user_a_id,
            f"💞 Общий прогноз для вас двоих:\n\n{forecast}",
            reply_markup=kb,
        )
    except Exception:
        logger.warning("Failed to notify user_a=%s of blind session %s", user_a_id, code, exc_info=True)

    caption_b = f"🃏 Твоя карта: {card_b['name']}\n\n{card_b['meaning_short']}"
    try:
        if trigger_message is not None and trigger_message.chat.id == user_b_id:
            sent_b = await _send_card_image(trigger_message, card_b, caption_b)
            if not sent_b:
                await trigger_message.answer(caption_b)
            await trigger_message.answer(
                f"💞 Общий прогноз для вас двоих:\n\n{forecast}",
                reply_markup=kb,
            )
        else:
            sent_b = await _send_card_to_chat(bot, user_b_id, card_b, caption_b)
            if not sent_b:
                await bot.send_message(user_b_id, caption_b)
            await bot.send_message(
                user_b_id,
                f"💞 Общий прогноз для вас двоих:\n\n{forecast}",
                reply_markup=kb,
            )
    except Exception:
        logger.warning("Failed to notify user_b=%s of blind session %s", user_b_id, code, exc_info=True)

    await db.complete_blind_session(code)


@router.message(F.text == BTN_BLIND)
async def menu_blind(message: Message, state: FSMContext) -> None:
    await state.clear()
    await analytics.track(message.from_user.id, "menu_blind")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🆕 Создать сессию", callback_data="create_blind"),
        ]]
    )
    await message.answer(
        "👥 Парное гадание\n\n"
        "Создай сессию и отправь другу ссылку — каждый вытянет свою карту, "
        "а я дам общий прогноз на ваши отношения.\n\n"
        "💫 Стоимость: 1 персональное толкование.\n"
        "🔍 Карту партнёра можно подсмотреть за ⭐ Stars.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "create_blind")
async def cb_create_blind(callback: CallbackQuery, bot: Bot) -> None:
    user_id = callback.from_user.id
    await db.get_or_create_user(user_id)

    # Gate on AI balance (admin unlimited)
    if not _is_admin(user_id):
        remaining = await db.get_ai_remaining(user_id)
        if remaining <= 0:
            await callback.answer()
            await analytics.track(user_id, "ai_limit_reached", source="blind_create")
            await callback.message.answer(
                "❌ У тебя закончились персональные толкования.\n"
                "🃏 Обычный расклад доступен всегда!\n"
                "💳 Пополни баланс в разделе «Оплата»"
            )
            return

    try:
        code = await db.create_blind_invite(user_id)
    except RuntimeError:
        await callback.answer("Не удалось создать сессию. Попробуй ещё раз.", show_alert=True)
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=blind_{code}"
    await analytics.track(user_id, "blind_create", code=code)
    await callback.answer()
    await callback.message.answer(
        f"Ссылка для парного гадания готова!\n\n"
        f"Отправь другу ссылку:\n{link}\n\n"
        "Эту ссылку можно пересылать нескольким друзьям.\n"
        "Каждый друг создаст с тобой отдельную сессию парного гадания.\n\n"
        "Ссылка действует 24 часа."
    )
    return
    balance_line = f"\n\n🔮 Осталось толкований: {new_balance}" if new_balance is not None else ""
    await callback.message.answer(
        f"✅ Сессия создана!\n\n"
        f"🔗 Отправь другу ссылку:\n{link}\n\n"
        f"⏰ Действует 24 часа.{balance_line}"
    )


async def _handle_blind_join_legacy_v1(message: Message, bot: Bot, code: str) -> None:
    """User B opens the bot via deep-link. Validate, draw cards, notify both."""
    user_b_id = message.from_user.id
    await db.get_or_create_user(user_b_id)

    session = await db.get_blind_session(code)
    if not session:
        await message.answer("⏰ Сессия не найдена или истекла. Попроси друга создать новую.")
        return
    if session["user_a"] == user_b_id:
        await message.answer("❌ Нельзя гадать самому с собой — отправь ссылку другу.")
        return
    if session["user_b"] is not None:
        if session["user_b"] == user_b_id:
            await message.answer("Ты уже присоединился к этой сессии.")
        else:
            await message.answer("К этой сессии уже присоединился другой игрок.")
        return

    cards = await db.get_random_cards(2)
    if len(cards) < 2:
        await message.answer("Ошибка: недостаточно карт в колоде.")
        return
    card_a, card_b = cards[0], cards[1]

    joined = await db.update_blind_session_join(code, user_b_id, card_a["id"], card_b["id"])
    if not joined:
        await message.answer("⏰ Сессия уже занята другим игроком или истекла.")
        return

    user_a_id = session["user_a"]
    await analytics.track(user_b_id, "blind_join", code=code)

    # Animate "thinking" in both chats in parallel
    thinking_b, thinking_a = await asyncio.gather(
        _animate_thinking(message),
        _animate_thinking_in_chat(bot, user_a_id),
    )
    forecast = await generate_pair_forecast(card_a, card_b)
    for m in (thinking_b, thinking_a):
        if m is None:
            continue
        try:
            await m.delete()
        except Exception:
            pass
    if not forecast:
        forecast = "✨ Карты сплетаются в необычный узор — прислушайтесь друг к другу."

    kb = _peek_kb(code)

    # Send to user A
    caption_a = f"🃏 Твоя карта: {card_a['name']}\n\n{card_a['meaning_short']}"
    try:
        sent_a = await _send_card_to_chat(bot, user_a_id, card_a, caption_a)
        if not sent_a:
            await bot.send_message(user_a_id, caption_a)
        await bot.send_message(
            user_a_id,
            f"💞 Общий прогноз для вас двоих:\n\n{forecast}",
            reply_markup=kb,
        )
    except Exception:
        logger.warning("Failed to notify user_a=%s of blind session %s", user_a_id, code, exc_info=True)

    # Send to user B (via message — same chat)
    caption_b = f"🃏 Твоя карта: {card_b['name']}\n\n{card_b['meaning_short']}"
    sent_b = await _send_card_image(message, card_b, caption_b)
    if not sent_b:
        await message.answer(caption_b)
    await message.answer(
        f"💞 Общий прогноз для вас двоих:\n\n{forecast}",
        reply_markup=kb,
    )


async def _handle_blind_join_legacy_v2(message: Message, bot: Bot, code: str) -> None:
    """User B opens the bot via deep-link and both participants confirm before start."""
    user_b_id = message.from_user.id
    await db.get_or_create_user(user_b_id)

    session = await db.get_blind_session(code)
    if not session:
        await message.answer("Сессия не найдена или истекла. Попроси друга создать новую.")
        return
    if session["user_a"] == user_b_id:
        await message.answer("Нельзя гадать самому с собой. Отправь ссылку другу.")
        return
    if session["user_b"] is not None:
        if session["user_b"] == user_b_id:
            if session["status"] == "completed":
                await message.answer("Ты уже присоединился к этой сессии. Расклад уже готов.")
            elif session["status"] == "processing":
                await message.answer("Расклад уже запускается. Подожди ещё немного.")
            else:
                await message.answer(
                    "Ты уже присоединился к этой сессии. Подтверди участие кнопкой ниже, если ещё не подтвердил.",
                    reply_markup=_blind_confirm_kb(code),
                )
        else:
            await message.answer("К этой сессии уже присоединился другой игрок.")
        return

    joined = await db.update_blind_session_join(code, user_b_id)
    if not joined:
        await message.answer("Сессия уже занята другим игроком или истекла.")
        return

    user_a_id = session["user_a"]
    await analytics.track(user_b_id, "blind_join", code=code)
    await _send_blind_confirmation_prompt(
        bot,
        user_a_id,
        user_b_id,
        code,
        "В сессию для парного расклада вошёл второй участник.",
    )
    await _send_blind_confirmation_prompt(
        bot,
        user_b_id,
        user_a_id,
        code,
        "Сессия для парного расклада создана.",
    )


async def _create_blind_session_for_pair(
    bot: Bot,
    initiator_user_id: int,
    partner_user_id: int,
    invite_code: str | None = None,
    analytics_event: str = "blind_join",
) -> str | None:
    if not _is_admin(initiator_user_id):
        initiator_balance = await db.get_ai_remaining(initiator_user_id)
        if initiator_balance <= 0:
            return None

    existing_session = await db.find_incomplete_pair_session(initiator_user_id, partner_user_id)
    if existing_session:
        return ""

    try:
        session_code = await db.create_direct_blind_session(
            initiator_user_id, partner_user_id, invite_code=invite_code
        )
    except RuntimeError:
        return None

    balance_after = None
    if not _is_admin(initiator_user_id):
        balance_after = await db.decrement_ai_requests(initiator_user_id)

    await analytics.track(
        initiator_user_id,
        analytics_event,
        code=session_code,
        invite_code=invite_code,
        partner_user_id=partner_user_id,
    )
    await _send_blind_confirmation_prompt(
        bot,
        initiator_user_id,
        partner_user_id,
        session_code,
        "Сессия для парного расклада создана.",
    )
    await _send_blind_confirmation_prompt(
        bot,
        partner_user_id,
        initiator_user_id,
        session_code,
        "В сессию для парного расклада вошёл второй участник.",
    )

    if balance_after is not None:
        try:
            await bot.send_message(
                initiator_user_id,
                f"🔮 Осталось персональных толкований: {balance_after}",
            )
        except Exception:
            logger.warning(
                "Failed to notify initiator=%s about blind balance",
                initiator_user_id,
                exc_info=True,
            )

    return session_code


async def _handle_blind_join(message: Message, bot: Bot, code: str) -> None:
    """User B opens a reusable invite and creates a dedicated pair session."""
    user_b_id = message.from_user.id
    await db.get_or_create_user(user_b_id)

    invite = await db.get_blind_invite(code)
    if not invite:
        await message.answer("Ссылка для парного гадания не найдена или истекла. Попроси друга создать новую.")
        return

    owner_user_id = invite["owner_user_id"]
    if owner_user_id == user_b_id:
        await message.answer("Нельзя гадать самому с собой. Отправь ссылку другу.")
        return

    existing_session = await db.find_incomplete_pair_session(owner_user_id, user_b_id)
    if existing_session:
        await message.answer("По этой ссылке вы уже создали парное гадание. Повторно присоединиться нельзя.")
        return

    if not _is_admin(owner_user_id):
        owner_balance = await db.get_ai_remaining(owner_user_id)
        if owner_balance <= 0:
            await message.answer("У владельца ссылки закончились персональные толкования. Попроси его пополнить баланс.")
            try:
                await bot.send_message(
                    owner_user_id,
                    "Кто-то открыл твою ссылку на парное гадание, но у тебя закончились персональные толкования.",
                )
            except Exception:
                logger.warning("Failed to notify owner=%s about blind invite balance", owner_user_id, exc_info=True)
            return

    try:
        session_code = await db.create_blind_session_from_invite(code, owner_user_id, user_b_id)
    except RuntimeError:
        await message.answer("Не удалось создать сессию парного гадания. Попробуй ещё раз.")
        return

    balance_after = None
    if not _is_admin(owner_user_id):
        balance_after = await db.decrement_ai_requests(owner_user_id)

    await analytics.track(user_b_id, "blind_join", code=session_code, invite_code=code)
    await _send_blind_confirmation_prompt(
        bot,
        owner_user_id,
        user_b_id,
        session_code,
        "В сессию для парного расклада вошёл второй участник.",
    )
    await _send_blind_confirmation_prompt(
        bot,
        user_b_id,
        owner_user_id,
        session_code,
        "Сессия для парного расклада создана.",
    )

    if balance_after is not None:
        try:
            await bot.send_message(
                owner_user_id,
                f"🔮 Осталось персональных толкований: {balance_after}",
            )
        except Exception:
            logger.warning("Failed to notify owner=%s about blind balance", owner_user_id, exc_info=True)


async def _create_blind_session_for_pair_v2(
    bot: Bot,
    initiator_user_id: int,
    partner_user_id: int,
    invite_code: str | None = None,
    analytics_event: str = "blind_join",
) -> str | None:
    if not _is_admin(initiator_user_id):
        initiator_balance = await db.get_ai_remaining(initiator_user_id)
        if initiator_balance <= 0:
            return None

    existing_session = await db.find_incomplete_pair_session(initiator_user_id, partner_user_id)
    if existing_session:
        return ""

    try:
        session_code = await db.create_direct_blind_session(
            initiator_user_id, partner_user_id, invite_code=invite_code
        )
    except RuntimeError:
        return None

    balance_after = None
    if not _is_admin(initiator_user_id):
        balance_after = await db.decrement_ai_requests(initiator_user_id)

    await analytics.track(
        initiator_user_id,
        analytics_event,
        code=session_code,
        invite_code=invite_code,
        partner_user_id=partner_user_id,
    )
    await _send_blind_confirmation_prompt(
        bot,
        initiator_user_id,
        partner_user_id,
        session_code,
        "Сессия для парного расклада создана.",
    )
    await _send_blind_confirmation_prompt(
        bot,
        partner_user_id,
        initiator_user_id,
        session_code,
        "В сессию для парного расклада вошёл второй участник.",
    )

    if balance_after is not None:
        try:
            await bot.send_message(
                initiator_user_id,
                f"🔮 Осталось персональных толкований: {balance_after}",
            )
        except Exception:
            logger.warning(
                "Failed to notify initiator=%s about blind balance",
                initiator_user_id,
                exc_info=True,
            )

    return session_code


async def _handle_blind_join(message: Message, bot: Bot, code: str) -> None:
    """User B opens a reusable invite and creates a dedicated pair session."""
    user_b_id = message.from_user.id
    await db.get_or_create_user(user_b_id)

    invite = await db.get_blind_invite(code)
    if not invite:
        await message.answer("Ссылка для парного гадания не найдена или истекла. Попроси друга создать новую.")
        return

    owner_user_id = invite["owner_user_id"]
    if owner_user_id == user_b_id:
        await message.answer("Нельзя гадать самому с собой. Отправь ссылку другу.")
        return

    session_code = await _create_blind_session_for_pair_v2(
        bot,
        initiator_user_id=owner_user_id,
        partner_user_id=user_b_id,
        invite_code=code,
        analytics_event="blind_join",
    )
    if session_code == "":
        await message.answer("У вас уже есть незавершённая сессия парного гадания. Сначала завершите её или дождитесь, пока она истечёт.")
        return
    if session_code is None:
        if not _is_admin(owner_user_id):
            owner_balance = await db.get_ai_remaining(owner_user_id)
            if owner_balance <= 0:
                await message.answer("У владельца ссылки закончились персональные толкования. Попроси его пополнить баланс.")
                try:
                    await bot.send_message(
                        owner_user_id,
                        "Кто-то открыл твою ссылку на парное гадание, но у тебя закончились персональные толкования.",
                    )
                except Exception:
                    logger.warning("Failed to notify owner=%s about blind invite balance", owner_user_id, exc_info=True)
                return
        await message.answer("Не удалось создать сессию парного гадания. Попробуй ещё раз.")
        return

    await analytics.track(user_b_id, "blind_join_target", code=session_code, invite_code=code)


@router.callback_query(F.data.startswith("blind_reject_"))
async def cb_blind_reject(callback: CallbackQuery, bot: Bot) -> None:
    code = callback.data[len("blind_reject_"):]
    user_id = callback.from_user.id

    session = await db.get_blind_session(code)
    if not session:
        await callback.answer("Сессия не найдена или истекла.", show_alert=True)
        return
    if user_id not in (session["user_a"], session["user_b"]):
        await callback.answer("Это не ваша сессия.", show_alert=True)
        return
    if session["status"] == "completed":
        await callback.answer("Расклад уже завершён.", show_alert=True)
        return
    if session["status"] == "processing":
        await callback.answer("Расклад уже запускается.", show_alert=True)
        return
    if session["status"] == "rejected":
        await callback.answer("Сессия уже отклонена.", show_alert=True)
        return

    rejected = await db.reject_blind_session(code)
    if not rejected:
        await callback.answer("Не удалось отклонить сессию.", show_alert=True)
        return

    await callback.answer("Сессия отклонена.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    partner_id = rejected["user_b"] if user_id == rejected["user_a"] else rejected["user_a"]
    await callback.message.answer("Ты отклонил(а) сессию парного толкования.")
    try:
        await bot.send_message(partner_id, "Партнёр отклонил сессию парного толкования.")
    except Exception:
        logger.warning("Failed to notify partner=%s about blind rejection", partner_id, exc_info=True)


@router.callback_query(F.data.startswith("blind_replay_"))
async def cb_blind_replay(callback: CallbackQuery, bot: Bot) -> None:
    code = callback.data[len("blind_replay_"):]
    user_id = callback.from_user.id

    session = await db.get_blind_session(code)
    if not session:
        await callback.answer("Сессия не найдена или истекла.", show_alert=True)
        return
    if user_id not in (session["user_a"], session["user_b"]):
        await callback.answer("Это не ваша сессия.", show_alert=True)
        return
    if session["status"] != "completed":
        await callback.answer("Новое толкование можно начать только после завершённой сессии.", show_alert=True)
        return

    partner_id = session["user_b"] if user_id == session["user_a"] else session["user_a"]
    new_session_code = await _create_blind_session_for_pair_v2(
        bot,
        initiator_user_id=user_id,
        partner_user_id=partner_id,
        analytics_event="blind_replay",
    )
    if new_session_code == "":
        await callback.answer("У вас уже есть незавершённая сессия с этим пользователем.", show_alert=True)
        return
    if new_session_code is None:
        if not _is_admin(user_id):
            remaining = await db.get_ai_remaining(user_id)
            if remaining <= 0:
                await callback.answer("У тебя закончились персональные толкования.", show_alert=True)
                return
        await callback.answer("Не удалось создать новую сессию.", show_alert=True)
        return

    await callback.answer("Новая сессия создана.")
    await callback.message.answer("Запросил(а) новое парное толкование с тем же пользователем. Ждём подтверждения обоих.")


@router.callback_query(F.data.startswith("blind_confirm_"))
async def cb_blind_confirm(callback: CallbackQuery, bot: Bot) -> None:
    code = callback.data[len("blind_confirm_"):]
    user_id = callback.from_user.id

    session = await db.get_blind_session(code)
    if not session:
        await callback.answer("Сессия не найдена или истекла.", show_alert=True)
        return
    if user_id not in (session["user_a"], session["user_b"]):
        await callback.answer("Это не ваша сессия.", show_alert=True)
        return
    if session["user_b"] is None:
        await callback.answer("Нужно дождаться второго участника.", show_alert=True)
        return
    if session["status"] == "completed":
        await callback.answer("Расклад уже завершён.", show_alert=True)
        return
    if session["status"] == "processing":
        await callback.answer("Расклад уже запускается.", show_alert=True)
        return

    if session["status"] == "rejected":
        await callback.answer("Сессия была отклонена.", show_alert=True)
        return

    updated = await db.confirm_blind_session_user(code, user_id)
    if not updated:
        await callback.answer("Не удалось подтвердить участие.", show_alert=True)
        return

    is_user_a = user_id == updated["user_a"]
    partner_confirmed = bool(updated["confirmed_b"] if is_user_a else updated["confirmed_a"])

    await callback.answer("Участие подтверждено.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if partner_confirmed:
        await callback.message.answer("Оба участника подтвердили участие. Запускаю парный расклад.")
        await _start_blind_reading(
            bot,
            code,
            updated["user_a"],
            updated["user_b"],
            trigger_message=callback.message if callback.message.chat.id == updated["user_b"] else None,
        )
    else:
        await callback.message.answer("Подтверждение получено. Ждём второго участника.")


@router.callback_query(F.data.startswith("peek_"))
async def cb_peek(callback: CallbackQuery, bot: Bot) -> None:
    code = callback.data[len("peek_"):]
    user_id = callback.from_user.id

    session = await db.get_blind_session(code)
    if not session:
        await callback.answer("⏰ Сессия истекла.", show_alert=True)
        return
    if user_id not in (session["user_a"], session["user_b"]):
        await callback.answer("❌ Эта сессия не твоя.", show_alert=True)
        return
    if session["status"] != "completed":
        await callback.answer("Сессия ещё не завершена.", show_alert=True)
        return

    await callback.answer()
    await analytics.track(user_id, "blind_peek_invoice", code=code)
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Карта партнёра",
        description="Подсмотреть карту, которую вытянул твой партнёр.",
        payload=f"peek:{code}:{user_id}",
        currency="XTR",
        prices=[LabeledPrice(label="Карта партнёра", amount=PEEK_COST_STARS)],
    )


async def _handle_peek_payment(message: Message, payment, code: str, user_id: int) -> None:
    session = await db.get_blind_session(code)
    if not session or user_id not in (session["user_a"], session["user_b"]):
        logger.error("Peek payment for invalid session: code=%s user=%s", code, user_id)
        await message.answer("Оплата получена, но сессия недоступна. Напишите администратору.")
        return

    partner_card_id = session["card_b"] if user_id == session["user_a"] else session["card_a"]
    card = await db.get_card_by_id(partner_card_id)
    if not card:
        await message.answer("Карта не найдена. Напишите администратору.")
        return

    charge_id = payment.telegram_payment_charge_id or ""
    await db.log_payment(user_id, f"peek:{code}", PEEK_COST_STARS, 0, charge_id)
    await analytics.track(
        user_id, "blind_peek_paid",
        code=code, card_name=card["name"], stars=PEEK_COST_STARS,
    )

    caption = f"🔍 Карта партнёра: {card['name']}\n\n{card['meaning_short']}"
    sent = await _send_card_image(message, card, caption)
    if not sent:
        await message.answer(caption)


async def _send_spread_cards(message: Message, cards: list[dict], user_id: int) -> None:
    """
    Отправляет 3 карты с паузой и анимацией вытягивания.
    """
    labels = ["⏳ Прошлое", "🔮 Настоящее", "⭐ Будущее"]

    for idx, (label, card) in enumerate(zip(labels, cards), start=1):
        await db.log_draw(user_id, card["id"], "spread")

        # Показываем анимацию вытягивания карты
        anim_msg = await _animate_drawing(message, idx)

        # Формируем подпись к карте
        caption = f"{label}: {card['name']}\n\n{card['meaning_short']}"

        # Отправляем карту
        sent = await _send_card_image(message, card, caption)

        # Если изображение не отправилось, отправляем текст
        if not sent:
            await message.answer(caption)

        # Удаляем анимационное сообщение, чтобы не засорять чат
        try:
            await anim_msg.delete()
        except Exception:
            pass  # Если сообщение уже удалено или недоступно — игнорируем

        # Пауза между картами (кроме последней)
        if idx < 3:
            await asyncio.sleep(1.0)
