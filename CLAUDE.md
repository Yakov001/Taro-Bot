# BotTaro

Telegram tarot bot MVP. Validate the hypothesis: users want quick Tarot spreads in Telegram without registration.

## Team
- Two developers collaborating on the same repo, both using Claude Code locally.

## Dev environment
- IDE: PyCharm
- OS: Windows
- Run locally with `python main.py` (polling mode), using a single bot token in `.env`
- Secrets (BOT_TOKEN, ADMIN_USER_ID, YANDEX_API_KEY, YANDEX_FOLDER_ID) must never be committed — use `.env`

## Stack
- Python 3.11 + aiogram 3.x
- YandexGPT via OpenAI-compatible API for AI interpretations
- SQLite (up to 10,000 users; design for possible PostgreSQL migration)
- No Redis, no queues, no external cache
- Spam blocking via in-memory dict
- Telegram images: PNG files bundled in bot, cache `file_id` after first send
- Only inline buttons, no WebApp

## Project structure
- `main.py` — entry point (currently a placeholder)

## Database schema (3 tables)

### users
```sql
user_id INTEGER PRIMARY KEY,
spreads_remaining INTEGER DEFAULT 5,
ai_requests_remaining INTEGER DEFAULT 3,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

### tarot_cards (static, populated once)
```sql
id INTEGER PRIMARY KEY,
name TEXT,
image_url TEXT,
meaning_short TEXT,
file_id TEXT DEFAULT NULL
```

### draw_log (for /stats top-3 cards and spread counts)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
card_id INTEGER,
draw_type TEXT CHECK(draw_type IN ('day', 'spread')),
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

## Bot commands

### P0 (must have)
| Command | Description |
|---------|-------------|
| `/start` | Welcome message, short instructions, inline buttons |
| `/day` | Random card from 78: name + image + short meaning (2-3 sentences). Unlimited. |
| `/spread` | Past-present-future, 3 random cards (no duplicates), brief meanings. Limited to 5 per user lifetime. |
| `/question` | Spread with AI interpretation (YandexGPT). User asks a question, gets 3 cards + AI reading. Limited to 3 per user lifetime ("персональные толкования"). Admin has unlimited. |

### P1 (should have)
| Command | Description |
|---------|-------------|
| `/reset user_id` | Admin only (ADMIN_USER_ID in .env). Resets spread counter for a user. |
| `/stats` | Admin only. Total users, today's spreads, top-3 cards of the day. |
| Spam block | >10 requests/min = 5 min temp ban (in-memory dict) |

## Explicitly excluded from MVP
- Payments / subscriptions
- Spread history
- GPT / AI integration
- Admin panel UI
- Registration / profiles
- Voice messages
- WebApp / animations
- Multiple decks
- Free-text messages (bot responds to commands only)

## Non-functional requirements
- Response time: < 1.5 seconds per command
- Concurrent users: up to 100
- Store only user_id and counters — no personal data
- All commands duplicated with inline buttons
- Manual DB backup once per day

## UX examples

### /start
```
Привет! Я простой таролог-бот.
Карта дня — /day
Расклад на прошлое-настоящее-будущее — /spread
У тебя осталось 5 бесплатных раскладов.

[Кнопки: Карта дня | Расклад 3 карты]
```

### /day
```
Ваша карта дня — Влюблённые
[Изображение]
Это карта выбора и гармонии. Сегодня важно прислушаться к сердцу.
```

### /spread
```
Прошлое: Отшельник — время поиска себя.
Настоящее: Колесо Фортуны — перемены уже идут.
Будущее: Звезда — надежда и новые возможности.
```

### Limit reached
```
У тебя закончились бесплатные расклады.
Карта дня (/day) доступна всегда. Полная версия бота — скоро!
```

## Acceptance criteria
- `/start` shows welcome + buttons
- `/day` returns random card with image
- `/spread` returns 3 different cards
- Counter decrements from 5 to 0 after 5 spreads
- 6th spread shows "limit reached" message
- `/reset user_id` (admin) resets counter
- `/stats` shows user count, today's spreads, top card
- 50 concurrent `/day` requests: avg < 1 sec, no errors

## Risks
- Bot doesn't attract users → launch in 5 themed chats, collect feedback
- SQLite slows at 1000 users → design schema for PostgreSQL migration
- Users confuse /spread and /day → label buttons "1 карта" and "3 карты"

## Infrastructure
- Hosting: VPS $5-10 (DigitalOcean, Timeweb). PythonAnywhere free tier does NOT support long-polling.
- Deploy: manual `git pull` + `systemctl restart`
- Monitoring: console logs only
