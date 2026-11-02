import os
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1542459952134889522

CURRENCY_NAME = "руб."
CURRENCY_EMOJI = "💵"
START_BALANCE = 1000

ISSUER_ROLE_IDS = []

# ---------- Казино ----------
CASINO_MIN_BET = 1023
CASINO_MAX_BET = 609282096
TABLE_MIN_BET = 10000
TABLE_MAX_BET = 982092822
MAX_PLAYERS_AT_TABLE = 6

# ---------- Слоты ----------
SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "⭐", "7️⃣"]
SLOT_PAYOUTS = {"🍒": 3, "🍋": 4, "🍇": 5, "⭐": 8, "7️⃣": 30}

# ---------- Рулетка ----------
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BLACK = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

BLACKJACK_WIN = 2.0
DICE_MIN = 1
DICE_MAX = 6

FREEZE_EMOJI = "🚫"
STATE_EMOJI = "⚖️"
REPRESSION_EMOJI = "🩸"

# ---------- Авто-арест ФЗ-115 ----------
AUTOFREEZE_STREAK = 5
AUTOFREEZE_DURATION = 420
AUTOFREEZE_REASON = "Федеральный закон № 115-ФЗ"
AUTOFREEZE_MESSAGE = (
    "⚖️ **УВЕДОМЛЕНИЕ ОТ ГОСУДАРСТВЕННОЙ КАЗНЫ**\n\n"
    "**Федеральный закон № 115-ФЗ**\n\n"
    "Ваш счёт **арестован** на **7 минут**."
)

# ---------- Отмывание ----------
LAUNDERING_THRESHOLD = 2000000
LAUNDERING_FREEZE_DURATION = 3600
LAUNDERING_MESSAGE = (
    "⚖️ **ПОДОЗРЕНИЕ В ОТМЫВАНИИ**\n\n"
    "**Федеральный закон № 115-ФЗ**\n\n"
    "Перевод превысил лимит 2 000 000 ₽.\n"
    "**Деньги изъяты в казну.**\n"
    "**Счёт арестован на 1 час.**"
)

# ---------- Обмен валют ----------
CURRENCY_RATES = {"руб": 1.0, "usd": 90.0, "eur": 100.0}
CURRENCY_NAMES = {
    "руб": "🇷🇺 Рубли", "usd": "🇺🇸 Доллары", "eur": "🇪🇺 Евро",
}

# КД на сбор дохода с бизнеса (в секундах)
BUSINESS_INCOME_COOLDOWN = 900  # 15 минут

# ---------- Аукцион ----------
AUCTION_DURATION = 600
AUCTION_MIN_STEP = 1000

# ---------- Банкротство ----------
BANKRUPT_CHECK_INTERVAL = 600
BANKRUPT_JAIL_DURATION = 3600
BANKRUPT_MESSAGE = (
    "⚖️ **ТЫ ПРИЗНАН БАНКРОТОМ**\n\n"
    "Счёт ушёл в минус.\n**Счёт арестован на 1 час.**"
)

# ---------- Казна ----------
TREASURY_WITHDRAW_LIMIT = 200000
TREASURY_COOLDOWN = 21600
TREASURY_FREEZE_DURATION = 3600
TREASURY_ARTICLE_160 = (
    "⚖️ **СТАТЬЯ 160 УК РФ — РАСТРАТА**\n\n"
    "Вы взяли из казны сумму сверх лимита.\n"
    "**Счёт арестован на 1 час.**"
)

# ---------- Кража ----------
STEAL_MAX_AMOUNT = 50000
STEAL_COOLDOWN = 3600
STEAL_FAIL_ARREST = 1200
STEAL_FAIL_FINE_PERCENT = 0.10
STEAL_HIDDEN_CHANCE = 0.10
STEAL_EMOJI = "🥷"
STEAL_SUCCESS_MESSAGE = "🐾 Следы ведут в никуда. Ещё одна кража на счету неизвестного."

# ---------- ЗП ----------
SALARY_AMOUNT = 50000
SALARY_COOLDOWN = 86400

# ---------- Кредиты ----------
CREDIT_MIN_PERCENT = 0
CREDIT_MAX_PERCENT = 200
CREDIT_MIN_HOURS = 1
CREDIT_MAX_HOURS = 168
CREDIT_OVERDUE_FINE = 0.20
CREDIT_OVERDUE_FREEZE = 3600

# ---------- Роль без КД ----------
NO_COOLDOWN_ROLE_ID = 1557432390463266847


STOCK_UPDATE_INTERVAL = 3600
STOCK_VOLATILITY = 0.10
STOCK_MIN_FACTOR = 0.1
STOCK_MAX_FACTOR = 3.0
STOCK_CHANGE_THRESHOLD = 5.0
STOCK_NOTIFY_CHANNEL_ID = 0

# ---------- BTC ----------
BTC_BASE_PRICE = 6000000
BTC_VOLATILITY = 0.05
BTC_UPDATE_INTERVAL = 3600

# ---------- Spy ----------
CASINO_SPY_ID = 825579735282614312# ID роли, которая может использовать /накрутить

# ID роли, которая может использовать /накрутить
NAKRUTKA_ROLE_ID = 1559884149647613972   # SDK

# Кто может выдавать доступ (только этот ID)
OWNER_IDS = [
    825579735282614312,  # Ты
    954697397873819658,  # ID первого друга
]

OWNER_ID = OWNER_IDS[0]  # Берем первого овнера из списка (твой ID)
# ID ролей, которые можно выдавать
# ID ролей, которые можно выдавать
ADMIN_ROLE_ID = 1559678631729692856   # ← ID роли "Админ"
DEV_ROLE_ID   = 1559884149647613972   # ← был SDK_ROLE_ID, теперь Dev

# Лимит мульти-бизнесов НА ОДНОГО ИГРОКА (None = без лимита)

# ---------- Роль "Премия" ----------
PREMIUM_GIVER_ROLE_ID = 1561289186726641684      # ← ВСТАВЬ ID РОЛИ "ПРЕМИЯ"
PREMIUM_AMOUNT = 80000       # 80к
PREMIUM_COOLDOWN = 3 * 3600    # 3 часа (в секундах)

# ---------- РАНГИ БОГАТСТВА ----------
RANKS = [
    {"name": "🪙 Бомж",              "min_bal": 0},
    {"name": "🧹 Уборщик",           "min_bal": 10_000},
    {"name": "🛒 Торгаш",            "min_bal": 50_000},
    {"name": "💼 Клерк",             "min_bal": 200_000},
    {"name": "🏠 Домовладелец",      "min_bal": 500_000},
    {"name": "💵 Буржуй",            "min_bal": 1_000_000},
    {"name": "📈 Инвестор",          "min_bal": 5_000_000},
    {"name": "🏭 Олигарх",           "min_bal": 10_000_000},
    {"name": "👑 Магнат",            "min_bal": 50_000_000},
    {"name": "💎 Миллиардер",        "min_bal": 100_000_000},
    {"name": "🌍 Финансовый Гуру",   "min_bal": 500_000_000},
    {"name": "🏛️ Владыка Банка",     "min_bal": 1_000_000_000},
]
