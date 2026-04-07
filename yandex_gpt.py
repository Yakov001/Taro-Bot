import asyncio
import logging

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


SYSTEM_PROMPT = (
    "Ты — мудрый и чуткий таролог. Пользователь задал вопрос и вытянул три карты Таро "
    "(прошлое, настоящее, будущее). Твоя задача — дать связное, тёплое и вдохновляющее "
    "толкование расклада, привязав каждую карту к вопросу пользователя. "
    "Ответ должен быть на русском языке, 4-6 предложений. Не повторяй вопрос дословно. "
    "Не упоминай, что ты ИИ."
)


async def interpret_spread(
    question: str,
    cards: list[dict],
) -> str | None:
    labels = ["Прошлое", "Настоящее", "Будущее"]
    cards_text = "\n".join(
        f"{label}: {card['name']} — {card['meaning_short']}"
        for label, card in zip(labels, cards)
    )

    user_prompt = f"Вопрос: {question}\n\nКарты:\n{cards_text}"

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _get_client().responses.create(
                model=f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_output_tokens=1000,
            ),
        )
        return response.output[0].content[0].text
    except Exception:
        logger.error("YandexGPT request failed", exc_info=True)
        return None
