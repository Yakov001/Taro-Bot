import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "bot.db")
IMAGES_DIR = BASE_DIR / "images"

FLOOD_RATE_LIMIT = 10
FLOOD_WINDOW_SECONDS = 60
FLOOD_BAN_SECONDS = 300

DEFAULT_SPREADS = 5
