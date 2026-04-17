import asyncio
import logging
import random
import unicodedata
import re

import openai

from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL

logger = logging.getLogger(__name__)

_client: openai.OpenAI | None = None


def _get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=YANDEX_API_KEY,
            project=YANDEX_FOLDER_ID,
            base_url="https://ai.api.cloud.yandex.net/v1",
        )
    return _client


# Белый список эмодзи, которые рендерятся во всех клиентах Telegram.
# Запросы GPT ограничены этим списком; всё остальное режется санитайзером.
ALLOWED_EMOJIS = "🌟✨🔮🌙💫🃏⭐❤🍀💪🌈🦋🔥💎💰💼👥💕💞⚡🤝🎭"

_EMOJI_INSTRUCTION = (
    f"Разрешено использовать ТОЛЬКО эмодзи из этого списка: {ALLOWED_EMOJIS}. "
    "Никаких других эмодзи или специальных символов."
)


SYSTEM_PROMPT = (
    "Ты — мудрый и тёплый таролог. Человек задал личный вопрос и вытянул три карты: "
    "прошлое, настоящее, будущее. Твоя задача — дать толкование, которое напрямую отвечает на суть вопроса. "
    "Не уходи в абстрактные рассуждения — говори конкретно по теме, которую человек обозначил. "
    "Обращайся на «ты», с душой и живыми образами. "
    "Не используй «вы». Не говори, что ты ИИ. Ответ — 4-6 предложений. "
    + _EMOJI_INSTRUCTION
)


THEME_SYSTEM_PROMPT = (
    "Ты — мудрый и тёплый таролог. Человек выбрал тему «{theme}» и вытянул три карты: "
    "прошлое, настоящее, будущее. Дай толкование на «ты», связывая карты с темой. "
    "Не используй «вы». Не говори, что ты ИИ. Ответ — 4-6 предложений. "
    + _EMOJI_INSTRUCTION
)


PAIR_SYSTEM_PROMPT = (
    "Ты — проницательный таролог. Двое вытянули по карте вслепую. "
    "Дай прогноз для их пары. Обращайся: «в вашей паре», «между вами», «вы оба». "
    "Не перечисляй названия карт. Не говори, что ты ИИ. "
    "Ответ — ровно 4-6 предложения. "
    + _EMOJI_INSTRUCTION
)


_ALLOWED_EMOJI_SET = set(ALLOWED_EMOJIS)
# Необходимые join-символы для составных эмодзи (VS-16, ZWJ).
_EMOJI_JOINERS = {"\uFE0F", "\u200D"}
# Диапазоны блоков Юникода, где живут эмодзи. Внутри них всё, что не в белом
# списке или не JOINER, выкидываем — это и есть частый источник «tofu» в Telegram.
_EMOJI_RANGES = (
    (0x2300, 0x23FF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0x1F000, 0x1FFFF),
)


def _is_in_emoji_range(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _sanitize(text: str) -> str:
    """Удаляет проблемные символы и дублирующиеся фрагменты."""
    if not text:
        return ""

    banned_categories = {"Co", "Cn"}  # Private Use, Unassigned

    result = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in banned_categories:
            continue
        if cat == "Cc" and ch not in ("\t", "\n", "\r"):
            continue
        cp = ord(ch)
        # Фильтруем неразрешённые эмодзи, чтобы в чат не летели квадратики.
        if _is_in_emoji_range(cp):
            if ch not in _ALLOWED_EMOJI_SET and ch not in _EMOJI_JOINERS:
                continue
        result.append(ch)

    cleaned = "".join(result)

    # Удаляем строки вида "Общий прогноз для вас двоих:" и подобные заголовки
    cleaned = re.sub(r"^(Общий прогноз для вас двоих|Прогноз для пары|Расклад для пары)[:\-–—]\s*", "", cleaned, flags=re.IGNORECASE)

    # Убираем повторяющиеся фрагменты (если нейросеть задвоила ответ)
    # Ищем точное повторение первой половины во второй
    half = len(cleaned) // 2
    if half > 30 and cleaned[:half] == cleaned[half:half * 2]:
        cleaned = cleaned[:half]

    # Убираем дублирующиеся предложения
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    seen = set()
    unique_sentences = []
    for s in sentences:
        normalized = s.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_sentences.append(s)
    cleaned = " ".join(unique_sentences)

    # Чистим множественные пробелы и переводы строк
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)

    return cleaned.strip()


async def _call_yandex(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str | None:
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _get_client().responses.create(
                model=f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.65,  # Чуть ниже для стабильности
                max_output_tokens=max_tokens,
            ),
        )
        raw = response.output[0].content[0].text
        return _sanitize(raw)
    except Exception:
        logger.error("YandexGPT request failed", exc_info=True)
        return None


def _format_cards(cards: list[dict]) -> str:
    labels = ["Прошлое", "Настоящее", "Будущее"]
    return "\n".join(
        f"{label}: {card['name']} — {card['meaning_short']}"
        for label, card in zip(labels, cards)
    )


async def interpret_spread(question: str, cards: list[dict]) -> str | None:
    user_prompt = f"Вопрос: {question}\n\nКарты:\n{_format_cards(cards)}"
    return await _call_yandex(SYSTEM_PROMPT, user_prompt, max_tokens=600)


async def interpret_theme(theme: str, cards: list[dict]) -> str | None:
    system = THEME_SYSTEM_PROMPT.format(theme=theme)
    user_prompt = f"Тема: {theme}\n\nКарты:\n{_format_cards(cards)}"
    return await _call_yandex(system, user_prompt, max_tokens=600)


async def generate_pair_forecast(card_a: dict, card_b: dict) -> str | None:
    """Общий прогноз по двум картам с рандомной позицией каждой."""
    pos_a = "прямая" if random.random() < 0.7 else "перевёрнутая"
    pos_b = "прямая" if random.random() < 0.7 else "перевёрнутая"
    user_prompt = (
        f"Карта 1: {card_a['name']} ({pos_a}) — {card_a['meaning_short']}\n"
        f"Карта 2: {card_b['name']} ({pos_b}) — {card_b['meaning_short']}\n\n"
        "Дай прогноз для этой пары."
    )
    return await _call_yandex(PAIR_SYSTEM_PROMPT, user_prompt, max_tokens=400)