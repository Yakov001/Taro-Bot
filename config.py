import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
AMPLITUDE_API_KEY = os.getenv("AMPLITUDE_API_KEY", "")

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "yandexgpt")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "bot.db")
IMAGES_DIR = BASE_DIR / "images"

FLOOD_RATE_LIMIT = 60
FLOOD_WINDOW_SECONDS = 20
FLOOD_BAN_SECONDS = 300

DEFAULT_AI_REQUESTS = 3

# ── Blind Pair Tarot ─────────────────────────────────
PEEK_COST_STARS = 10  # Telegram Stars to reveal partner's card

# ── Telegram Stars payment packages ──────────────────
# payload_id → (stars_price, readings_granted, title, description)
PAYMENT_PACKAGES = {
    "pack_5": {
        "stars": 25,
        "readings": 5,
        "title": "5 толкований",
        "description": "Мини-пакет: 5 персональных толкований",
    },
    "pack_10": {
        "stars": 50,
        "readings": 10,
        "title": "10 толкований",
        "description": "Пакет: 10 персональных толкований",
    },
    "pack_25": {
        "stars": 100,
        "readings": 25,
        "title": "25 толкований",
        "description": "Премиум-пакет: 25 персональных толкований",
    },
}
