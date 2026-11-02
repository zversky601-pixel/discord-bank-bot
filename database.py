import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = "bank.db"

# ---------- МСК-время ----------
MSK = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    """Текущее время по МСК."""
    return datetime.now(MSK)


def parse_dt(s: str) -> datetime:
    """Парсит ISO-строку в datetime с tzinfo."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ============================================================
#                    ИНИЦИАЛИЗАЦИЯ
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    users_exists = c.fetchone() is not None

    if users_exists:
        c.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in c.fetchall()]

        migrations = {
            "frozen": "ALTER TABLE users ADD COLUMN frozen INTEGER DEFAULT 0",
            "freeze_reason": "ALTER TABLE users ADD COLUMN freeze_reason TEXT DEFAULT NULL",
            "in_jail": "ALTER TABLE users ADD COLUMN in_jail INTEGER DEFAULT 0",
            "jail_until": "ALTER TABLE users ADD COLUMN jail_until TEXT DEFAULT NULL",
            "jail_reason": "ALTER TABLE users ADD COLUMN jail_reason TEXT DEFAULT NULL",
            "negative_since": "ALTER TABLE users ADD COLUMN negative_since TEXT DEFAULT NULL",
            "last_treasury_take": "ALTER TABLE users ADD COLUMN last_treasury_take TEXT DEFAULT NULL",
            "last_steal": "ALTER TABLE users ADD COLUMN last_steal TEXT DEFAULT NULL",
            "last_salary": "ALTER TABLE users ADD COLUMN last_salary TEXT DEFAULT NULL",
            "last_biz_income": "ALTER TABLE users ADD COLUMN last_biz_income TEXT DEFAULT NULL",
        }
        for col, sql in migrations.items():
            if col not in columns:
                c.execute(sql)

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        frozen INTEGER DEFAULT 0,
        freeze_reason TEXT DEFAULT NULL,
        in_jail INTEGER DEFAULT 0,
        jail_until TEXT DEFAULT NULL,
        jail_reason TEXT DEFAULT NULL,
        negative_since TEXT DEFAULT NULL,
        last_treasury_take TEXT DEFAULT NULL,
        last_steal TEXT DEFAULT NULL,
        last_salary TEXT DEFAULT NULL,
        last_biz_income TEXT DEFAULT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS shop_roles (
        role_id INTEGER PRIMARY KEY,
        price INTEGER NOT NULL,
        name TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS auction_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        auction_type TEXT NOT NULL,       -- 'role' или 'biz'
        auction_id INTEGER NOT NULL,
        bidder_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        action TEXT NOT NULL,             -- 'bid', 'refund', 'win', 'cancel'
        details TEXT,
        created_at TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS currencies (
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        amount REAL DEFAULT 0,
        PRIMARY KEY (user_id, currency)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        biz_type TEXT NOT NULL,
        level INTEGER DEFAULT 1,
        last_income TEXT,
        bought_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_points (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS business_taxes (
        biz_type TEXT PRIMARY KEY,
        percent INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS treasury (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        total INTEGER DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO treasury (id, total) VALUES (1, 0)")

    c.execute("""CREATE TABLE IF NOT EXISTS auctions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        biz_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        biz_type TEXT NOT NULL,
        start_price INTEGER NOT NULL,
        current_bid INTEGER DEFAULT 0,
        current_bidder INTEGER DEFAULT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER DEFAULT NULL,
        ends_at TEXT NOT NULL,
        active INTEGER DEFAULT 1
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS role_owners (
        role_id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        bought_at TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lender_id INTEGER NOT NULL,
        borrower_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        debt INTEGER NOT NULL,
        percent INTEGER NOT NULL,
        until TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS role_auctions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        start_price INTEGER NOT NULL,
        current_bid INTEGER DEFAULT 0,
        current_bidder INTEGER DEFAULT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER DEFAULT NULL,
        ends_at TEXT NOT NULL,
        active INTEGER DEFAULT 1
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS role_auction_bids (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        auction_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stocks (
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        amount INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, ticker)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_prices (
        ticker TEXT PRIMARY KEY,
        price REAL NOT NULL,
        last_update TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS btc_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        price REAL DEFAULT 6000000,
        last_update TEXT
    )""")
    c.execute("INSERT OR IGNORE INTO btc_settings (id, price) VALUES (1, 6000000)")

    c.execute("""CREATE TABLE IF NOT EXISTS btc_shop (
        role_id INTEGER PRIMARY KEY,
        price_btc REAL NOT NULL,
        name TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS btc_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        action TEXT NOT NULL,
        target_id INTEGER,
        details TEXT,
        created_at TEXT NOT NULL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS bot_admins (
    user_id INTEGER PRIMARY KEY,
    role TEXT NOT NULL
    )""")

    conn.commit()
    conn.close()


# ============================================================
#                       БАЛАНС
# ============================================================

def get_balance(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
        conn.commit()
        conn.close()
        return 0
    conn.close()
    return row[0]


def set_balance(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO users (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = ?""", (user_id, amount, amount))
    conn.commit()
    conn.close()


def add_balance(user_id: int, amount: int) -> int:
    current = get_balance(user_id)
    new = current + amount
    set_balance(user_id, new)
    return new


def get_all_balances():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, balance FROM users ORDER BY balance DESC")
    rows = c.fetchall()
    conn.close()
    return rows


# ============================================================
#                     ТРАНЗАКЦИИ
# ============================================================

def add_transaction(user_id: int, amount: int, ttype: str, description: str = ""):
    created_at = now_msk().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO transactions (user_id, amount, type, description, created_at)
        VALUES (?, ?, ?, ?, ?)""", (user_id, amount, ttype, description, created_at))
    conn.commit()
    conn.close()


def get_transactions(user_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT amount, type, description, created_at FROM transactions
        WHERE user_id = ? ORDER BY id DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


# ============================================================
#                       МАГАЗИН
# ============================================================

def add_shop_role(role_id: int, price: int, name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO shop_roles (role_id, price, name) VALUES (?, ?, ?)
        ON CONFLICT(role_id) DO UPDATE SET price = ?, name = ?""",
        (role_id, price, name, price, name))
    conn.commit()
    conn.close()


def remove_shop_role(role_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM shop_roles WHERE role_id = ?", (role_id,))
    conn.commit()
    conn.close()


def get_shop_roles():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role_id, price, name FROM shop_roles")
    rows = c.fetchall()
    conn.close()
    return rows


def get_shop_role(role_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role_id, price, name FROM shop_roles WHERE role_id = ?", (role_id,))
    row = c.fetchone()
    conn.close()
    return row


# ============================================================
#                       ЗАМОРОЗКА
# ============================================================

def is_frozen(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT frozen FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row[0]) if row else False


def get_freeze_reason(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT freeze_reason FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_frozen(user_id: int, frozen: bool, reason: str = None):
    get_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET frozen = ?, freeze_reason = ? WHERE user_id = ?",
              (1 if frozen else 0, reason, user_id))
    conn.commit()
    conn.close()


def zero_balance(user_id: int) -> int:
    old = get_balance(user_id)
    set_balance(user_id, 0)
    return old


# ============================================================
#                       ТЮРЬМА
# ============================================================

def is_in_jail(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT in_jail, jail_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    if row[1]:
        until = parse_dt(row[1])
        if now_msk() >= until:
            release_from_jail(user_id)
            return False
    return True


def jail_user(user_id: int, minutes: int, reason: str = "не указана"):
    get_balance(user_id)
    until = (now_msk() + timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET in_jail = 1, jail_until = ?, jail_reason = ? WHERE user_id = ?",
              (until, reason, user_id))
    conn.commit()
    conn.close()


def release_from_jail(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET in_jail = 0, jail_until = NULL, jail_reason = NULL WHERE user_id = ?",
              (user_id,))
    conn.commit()
    conn.close()


def get_jail_info(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT jail_until, jail_reason FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (None, None)


# ============================================================
#                        КАЗНА
# ============================================================

def add_to_treasury(amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE treasury SET total = total + ? WHERE id = 1", (amount,))
    conn.commit()
    conn.close()


def take_from_treasury(amount: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT total FROM treasury WHERE id = 1")
    row = c.fetchone()
    current = row[0] if row else 0
    if current < amount:
        conn.close()
        return False
    c.execute("UPDATE treasury SET total = total - ? WHERE id = 1", (amount,))
    conn.commit()
    conn.close()
    return True


def get_treasury() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT total FROM treasury WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def get_treasury_open() -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'treasury_open'")
    row = c.fetchone()
    conn.close()
    return bool(int(row[0])) if row else False


def set_treasury_open(state: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO settings (key, value) VALUES ('treasury_open', ?)
        ON CONFLICT(key) DO UPDATE SET value = ?""",
        ("1" if state else "0", "1" if state else "0"))
    conn.commit()
    conn.close()


def get_treasury_cooldown(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_treasury_take FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_treasury_cooldown(user_id: int, timestamp: str):
    get_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET last_treasury_take = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()


# ============================================================
#                        КРАЖА
# ============================================================

def get_last_steal(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_steal FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_last_steal(user_id: int, timestamp: str):
    get_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET last_steal = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()


# ============================================================
#                         ЗП
# ============================================================

def get_last_salary(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_salary FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_last_salary(user_id: int, timestamp: str):
    get_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET last_salary = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()


# ============================================================
#                    КД БИЗНЕС-ДОХОД
# ============================================================

def get_last_biz_income(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_biz_income FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_last_biz_income(user_id: int, timestamp: str):
    get_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET last_biz_income = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()


# ============================================================
#                       ВАЛЮТЫ
# ============================================================

def get_currency(user_id: int, currency: str) -> float:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT amount FROM currencies WHERE user_id = ? AND currency = ?", (user_id, currency))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def set_currency(user_id: int, currency: str, amount: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO currencies (user_id, currency, amount) VALUES (?, ?, ?)
        ON CONFLICT(user_id, currency) DO UPDATE SET amount = ?""",
        (user_id, currency, amount, amount))
    conn.commit()
    conn.close()


def add_currency(user_id: int, currency: str, amount: float) -> float:
    cur = get_currency(user_id, currency)
    new = cur + amount
    set_currency(user_id, currency, new)
    return new


def get_all_currencies(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT currency, amount FROM currencies WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows



# ============================================================
#                       КРЕДИТЫ
# ============================================================

def create_credit(lender_id, borrower_id, amount, debt, percent, until) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO credits (lender_id, borrower_id, amount, debt, percent, until, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (lender_id, borrower_id, amount, debt, percent, until, now_msk().isoformat()))
    credit_id = c.lastrowid
    conn.commit()
    conn.close()
    return credit_id


def get_credit(credit_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, lender_id, borrower_id, amount, debt, percent, until, active, created_at
        FROM credits WHERE id = ?""", (credit_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_credits_by_borrower(borrower_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, lender_id, borrower_id, amount, debt, percent, until
        FROM credits WHERE borrower_id = ? AND active = 1""", (borrower_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_credits_by_lender(lender_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, lender_id, borrower_id, amount, debt, percent, until
        FROM credits WHERE lender_id = ? AND active = 1""", (lender_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_credit_debt(credit_id: int, new_debt: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET debt = ? WHERE id = ?", (new_debt, credit_id))
    conn.commit()
    conn.close()


def close_credit(credit_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET active = 0 WHERE id = ?", (credit_id,))
    conn.commit()
    conn.close()


def get_all_overdue_credits():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, lender_id, borrower_id, amount, debt, percent, until
        FROM credits WHERE active = 1""")
    rows = c.fetchall()
    conn.close()
    return rows

 # ============================================================
#                  АУКЦИОНЫ РОЛЕЙ
# ============================================================

def create_role_auction(role_id, seller_id, start_price, channel_id, ends_at) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO role_auctions
        (role_id, seller_id, start_price, current_bid, current_bidder, channel_id, ends_at, active)
        VALUES (?, ?, ?, 0, NULL, ?, ?, 1)""",
        (role_id, seller_id, start_price, channel_id, ends_at))
    aid = c.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_role_auction(aid: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, role_id, seller_id, start_price, current_bid, current_bidder,
                 channel_id, message_id, ends_at, active
                 FROM role_auctions WHERE id = ?""", (aid,))
    row = c.fetchone()
    conn.close()
    return row


def get_active_role_auctions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, role_id, seller_id, start_price, current_bid, current_bidder,
                 channel_id, message_id, ends_at
                 FROM role_auctions WHERE active = 1""")
    rows = c.fetchall()
    conn.close()
    return rows


def update_role_auction_bid(aid: int, bidder_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE role_auctions SET current_bid = ?, current_bidder = ? WHERE id = ?",
              (amount, bidder_id, aid))
    conn.commit()
    conn.close()


def update_role_auction_message(aid: int, message_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE role_auctions SET message_id = ? WHERE id = ?", (message_id, aid))
    conn.commit()
    conn.close()


def close_role_auction(aid: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE role_auctions SET active = 0 WHERE id = ?", (aid,))
    conn.commit()
    conn.close()


def add_role_auction_bid(aid: int, user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO role_auction_bids (auction_id, user_id, amount, created_at)
                 VALUES (?, ?, ?, ?)""", (aid, user_id, amount, now_msk().isoformat()))
    conn.commit()
    conn.close()


def get_top_role_auction_bids(aid: int, limit: int = 2):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT user_id, MAX(amount) AS max_amount
                 FROM role_auction_bids
                 WHERE auction_id = ?
                 GROUP BY user_id
                 ORDER BY max_amount DESC
                 LIMIT ?""", (aid, limit))
    rows = c.fetchall()
    conn.close()
    return rows
    
    
def set_role_owner(role_id: int, owner_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO role_owners (role_id, owner_id, bought_at)
                 VALUES (?, ?, ?)
                 ON CONFLICT(role_id) DO UPDATE SET owner_id = ?, bought_at = ?""",
        (role_id, owner_id, now_msk().isoformat(), owner_id, now_msk().isoformat()))
    conn.commit()
    conn.close()


def get_role_owner(role_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT owner_id FROM role_owners WHERE role_id = ?", (role_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def clear_role_owner(role_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM role_owners WHERE role_id = ?", (role_id,))
    conn.commit()
    conn.close()
    
def count_businesses_by_type(biz_type: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM businesses WHERE biz_type = ?", (biz_type,))
    count = c.fetchone()[0]
    conn.close()
    return count

def add_auction_history(auction_type: str, auction_id: int, bidder_id: int,
                        amount: int, action: str, details: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO auction_history
                 (auction_type, auction_id, bidder_id, amount, action, details, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (auction_type, auction_id, bidder_id, amount, action, details,
               now_msk().isoformat()))
    conn.commit()
    conn.close()


def get_auction_history(auction_type: str, auction_id: int, limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT bidder_id, amount, action, details, created_at
                 FROM auction_history
                 WHERE auction_type = ? AND auction_id = ?
                 ORDER BY id ASC LIMIT ?""",
              (auction_type, auction_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def count_user_businesses_by_type(user_id: int, biz_type: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM businesses WHERE user_id = ? AND biz_type = ?", (user_id, biz_type))
    count = c.fetchone()[0]
    conn.close()
    return count


def set_business_owner_direct(biz_id: int, new_user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE businesses SET user_id = ? WHERE id = ?", (new_user_id, biz_id))
    conn.commit()
    conn.close()


def force_close_credit(credit_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET active = 0 WHERE id = ?", (credit_id,))
    conn.commit()
    conn.close()


def update_credit_until(credit_id: int, new_until: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET until = ? WHERE id = ?", (new_until, credit_id))
    conn.commit()
    conn.close()


def set_business_owner_direct(biz_id: int, new_user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE businesses SET user_id = ? WHERE id = ?", (new_user_id, biz_id))
    conn.commit()
    conn.close()


def force_close_credit(credit_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET active = 0 WHERE id = ?", (credit_id,))
    conn.commit()
    conn.close()


def update_credit_until(credit_id: int, new_until: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credits SET until = ? WHERE id = ?", (new_until, credit_id))
    conn.commit()
    conn.close()


def get_user_points(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points FROM user_points WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_user_points(user_id: int, amount: int) -> int:
    current = get_user_points(user_id)
    new_points = current + amount
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO user_points (user_id, points) VALUES (?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET points = ?""", 
              (user_id, new_points, new_points))
    conn.commit()
    conn.close()
    return new_points

def upgrade_business_level(biz_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE businesses SET level = level + 1 WHERE id = ?", (biz_id,))
    conn.commit()
    conn.close()    
    
    
def get_business_by_id_full(biz_id: int):
    """Возвращает (id, user_id, biz_type, level, last_income)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, biz_type, level, last_income FROM businesses WHERE id = ?", (biz_id,))
    row = c.fetchone()
    conn.close()
    return row
    
    
def set_bot_sleep(state: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO settings (key, value) VALUES ('bot_sleep', ?)
                 ON CONFLICT(key) DO UPDATE SET value = ?""", 
              ("1" if state else "0", "1" if state else "0"))
    conn.commit()
    conn.close()

def get_bot_sleep() -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'bot_sleep'")
    row = c.fetchone()
    conn.close()
    return bool(int(row[0])) if row else False
    
    
def add_blacklist(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO blacklist (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_blacklist(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_blacklisted(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM blacklist WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def get_transactions_period(user_id: int, hours: int = 48):
    """Все транзакции за последние N часов (по умолчанию — 2 дня)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    since = (now_msk() - timedelta(hours=hours)).isoformat()
    c.execute("""
        SELECT amount, type, description, created_at
        FROM transactions
        WHERE user_id = ? AND created_at >= ?
        ORDER BY id DESC
    """, (user_id, since))
    rows = c.fetchall()
    conn.close()
    return rows
   
# И добавь функции в конец файла:
def add_bot_admin(user_id: int, role: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_admins (user_id, role) VALUES (?, ?)", (user_id, role))
    conn.commit()
    conn.close()

def remove_bot_admin(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_bot_admin_role(user_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role FROM bot_admins WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
    
def zero_treasury():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE treasury SET total = 0 WHERE id = 1")
    conn.commit()
    conn.close()
    
def add_pumpkin(user_id: int, amount: int = 1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Создаем таблицу для тыкв, если ее нет
    c.execute("""CREATE TABLE IF NOT EXISTS pumpkins (
        user_id INTEGER PRIMARY KEY,
        amount INTEGER DEFAULT 0
    )""")
    c.execute("""INSERT INTO pumpkins (user_id, amount) VALUES (?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?""", 
              (user_id, amount, amount))
    conn.commit()
    conn.close()

def get_pumpkins(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS pumpkins (
        user_id INTEGER PRIMARY KEY,
        amount INTEGER DEFAULT 0
    )""")
    c.execute("SELECT amount FROM pumpkins WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0