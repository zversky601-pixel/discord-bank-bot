import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import asyncio
import random

import config
import database as db

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
db.init_db()


# ============================================================
#                       УТИЛИТЫ
# ============================================================

MSK = timezone(timedelta(hours=3))


def fmt(amount) -> str:
    if isinstance(amount, float):
        return f"{amount:,.2f}".replace(",", " ")
    return f"{amount:,}".replace(",", " ")


def fmt_btc(amount: float) -> str:
    return f"{amount:.8f}"


def now_msk() -> datetime:
    return datetime.now(MSK)


def time_left(until_str: str) -> str:
    try:
        until = db.parse_dt(until_str)
    except Exception:
        return "—"
    delta = until - now_msk()
    sec = int(delta.total_seconds())
    if sec < 0:
        return "⚠️ **ПРОСРОЧЕН**"
    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d} д")
    if h:
        parts.append(f"{h} ч")
    if m and not d:
        parts.append(f"{m} мин")
    return "через " + " ".join(parts) if parts else "меньше минуты"


def has_no_cooldown(member: discord.Member) -> bool:
    if not config.NO_COOLDOWN_ROLE_ID:
        return False
    return any(r.id == config.NO_COOLDOWN_ROLE_ID for r in member.roles)
    

def get_user_tag(member: discord.Member) -> str:      # ← ВСТАВЬ ЭТО
    """Тег для отображения: Админ / Dev / оба."""
    tags = []
    role_ids = {r.id for r in member.roles}
    if config.ADMIN_ROLE_ID in role_ids:
        tags.append("👑 Админ")
    if config.DEV_ROLE_ID in role_ids:
        tags.append("💎 Dev")
    return " • ".join(tags)
    
    
def get_rank_info(bal):
    current_rank = config.RANKS[0]
    next_rank = None
    
    for i, rank in enumerate(config.RANKS):
        if bal >= rank["min_bal"]:
            current_rank = rank
            if i + 1 < len(config.RANKS):
                next_rank = config.RANKS[i + 1]
        else:
            break

    if not next_rank:
        return current_rank["name"], "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 (MAX)", "Максимальный ранг!"

    current_bal = bal - current_rank["min_bal"]
    need_bal = next_rank["min_bal"] - current_rank["min_bal"]
    progress = min(1.0, max(0.0, current_bal / need_bal))
    
    filled = int(progress * 10)
    bar = "🟩" * filled + "⬛" * (10 - filled)
    
    left = next_rank["min_bal"] - bal
    text = f"До **{next_rank['name']}** осталось: **{fmt(left)}** {config.CURRENCY_EMOJI}"
    
    return current_rank["name"], f"{bar} ({int(progress*100)}%)", text
    
    
def get_rank_info(bal):
    current_rank = config.RANKS[0]
    next_rank = None
    
    # Ищем текущий и следующий ранг
    for i, rank in enumerate(config.RANKS):
        if bal >= rank["min_bal"]:
            current_rank = rank
            if i + 1 < len(config.RANKS):
                next_rank = config.RANKS[i + 1]
        else:
            break

    # Если это максимальный ранг
    if not next_rank:
        return current_rank["name"], "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 (MAX)", "Максимальный ранг!"

    # Считаем прогресс
    current_bal = bal - current_rank["min_bal"]
    need_bal = next_rank["min_bal"] - current_rank["min_bal"]
    progress = min(1.0, max(0.0, current_bal / need_bal))
    
    # Рисуем полоску (10 квадратиков)
    filled = int(progress * 10)
    bar = "🟩" * filled + "⬛" * (10 - filled)
    
    # Текст до следующего ранга
    left = next_rank["min_bal"] - bal
    text = f"До **{next_rank['name']}** осталось: **{fmt(left)}** {config.CURRENCY_EMOJI}"
    
    return current_rank["name"], f"{bar} ({int(progress*100)}%)", text
    
def actor_label(member: discord.Member) -> str:
    """Метка автора действия: '👑 Админ' / '💎 Dev' / иначе — упоминание."""
    if not isinstance(member, discord.Member):
        return f"@{member.name}"
    tag = get_user_tag(member)
    return tag if tag else member.mention
    
    
def log_admin(actor, category: str, action: str, target_id: int = None, details: str = ""):
    try:
        uid = actor.id if isinstance(actor, (discord.Member, discord.User)) else None
        db.add_admin_log(uid, category, action, target_id, details)
    except Exception as e:
        print(f"⚠️ log_admin: {e}")    


def _make_chart(prices, width=20):
    if len(prices) < 2:
        return "— нет данных —"
    mn, mx = min(prices), max(prices)
    if mx == mn:
        return "▬" * width
    rows = []
    for level in range(5, -1, -1):
        threshold = mn + (mx - mn) * level / 5
        line = ""
        for p in prices[-width:]:
            line += "█" if p >= threshold else " "
        rows.append(line)
    return "\n".join(rows)


# ============================================================
#                    ФОНОВЫЕ ЗАДАЧИ
# ============================================================

async def auction_checker():
    while True:
        await asyncio.sleep(30)
        try:
            for a in db.get_active_auctions():
                aid = a[0]
                ends_at = db.parse_dt(a[9])
                if now_msk() >= ends_at:
                    await finish_auction(aid)
        except Exception as e:
            print(f"⚠️ auction_checker: {e}")


async def bankrupt_checker():
    while True:
        await asyncio.sleep(60)
        try:
            now = now_msk()
            for user_id, balance, neg_since in db.get_all_negative():
                if not neg_since:
                    db.set_negative_since(user_id, now.isoformat())
                    continue
                if (now - db.parse_dt(neg_since)).total_seconds() >= config.BANKRUPT_CHECK_INTERVAL:
                    if not db.is_frozen(user_id):
                        db.set_frozen(user_id, True, "Банкротство")
                        db.set_negative_since(user_id, None)
                        try:
                            user = await bot.fetch_user(user_id)
                            await user.send(config.BANKRUPT_MESSAGE)
                        except Exception:
                            pass
                        asyncio.create_task(unfreeze_after(user_id, config.BANKRUPT_JAIL_DURATION))
        except Exception as e:
            print(f"⚠️ bankrupt_checker: {e}")


async def credit_checker():
    while True:
        await asyncio.sleep(300)
        try:
            now = now_msk()
            for credit in db.get_all_overdue_credits():
                cid, lender, borrower, amount, debt, percent, until = credit
                if now >= db.parse_dt(until):
                    if not db.is_frozen(borrower):
                        fine = int(debt * config.CREDIT_OVERDUE_FINE)
                        new_debt = debt + fine
                        db.update_credit_debt(cid, new_debt)
                        db.set_frozen(borrower, True, f"Просрочен кредит #{cid}")
                        try:
                            u = await bot.fetch_user(borrower)
                            await u.send(f"⚖️ **КРЕДИТ ПРОСРОЧЕН**\nДолг: **{fmt(new_debt)}** 💵")
                        except Exception:
                            pass
                        asyncio.create_task(unfreeze_after(borrower, config.CREDIT_OVERDUE_FREEZE))
        except Exception as e:
            print(f"⚠️ credit_checker: {e}")


async def stock_updater():
    while True:
        await asyncio.sleep(config.STOCK_UPDATE_INTERVAL)
        try:
            changes = []
            for ticker, info in config.STOCKS.items():
                current = db.get_stock_price(ticker) or info["base_price"]
                change = random.uniform(-config.STOCK_VOLATILITY, config.STOCK_VOLATILITY)
                new_price = current * (1 + change)
                min_p = info["base_price"] * config.STOCK_MIN_FACTOR
                max_p = info["base_price"] * config.STOCK_MAX_FACTOR
                new_price = max(min_p, min(new_price, max_p))
                db.set_stock_price(ticker, round(new_price, 2))

                percent = ((new_price - current) / current) * 100
                if abs(percent) >= config.STOCK_CHANGE_THRESHOLD:
                    changes.append((ticker, info["name"], current, new_price, percent))

            print("📈 Цены акций обновлены")

            if config.STOCK_NOTIFY_CHANNEL_ID and changes:
                channel = bot.get_channel(config.STOCK_NOTIFY_CHANNEL_ID)
                if channel:
                    for ticker, name, old, new, percent in changes:
                        arrow = "📈" if percent > 0 else "📉"
                        sign = "+" if percent > 0 else ""
                        embed = discord.Embed(
                            title=f"{arrow} {name} ({ticker})",
                            description=(
                                f"**Было:** {fmt(old)} 💵\n"
                                f"**Стало:** {fmt(new)} 💵\n"
                                f"**Изменение:** **{sign}{percent:.2f}%**"
                            ),
                            color=discord.Color.green() if percent > 0 else discord.Color.red()
                        )
                        await channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ stock_updater: {e}")


async def btc_updater():
    while True:
        await asyncio.sleep(config.BTC_UPDATE_INTERVAL)
        try:
            current = db.get_btc_price()
            change = random.uniform(-config.BTC_VOLATILITY, config.BTC_VOLATILITY)
            new_price = current * (1 + change)
            db.set_btc_price(round(new_price, 2))
            print(f"₿ BTC: {fmt(int(current))} → {fmt(int(new_price))}")
        except Exception as e:
            print(f"⚠️ btc_updater: {e}")


async def unfreeze_after(user_id: int, seconds: int):
    await asyncio.sleep(seconds)
    if db.is_frozen(user_id):
        db.set_frozen(user_id, False, None)
        try:
            user = await bot.fetch_user(user_id)
            await user.send("✅ **Счёт разморожен.**")
        except Exception:
            pass


async def finish_auction(auction_id: int):
    auction = db.get_auction(auction_id)
    if not auction or not auction[10]:
        return
    aid, biz_id, seller_id, biz_type, start_price, current_bid, current_bidder, ch_id, msg_id, ends_at, active = auction
    info = config.BUSINESS_TYPES.get(biz_type, {})
    channel = bot.get_channel(ch_id)

    if current_bidder and current_bid:
        db.add_balance(seller_id, current_bid)
        db.transfer_business(biz_id, current_bidder)
        if channel:
            embed = discord.Embed(
                title=f"🏛️ АУКЦИОН #{aid} ЗАВЕРШЁН",
                description=f"**Победитель:** <@{current_bidder}>\n**Ставка:** **{fmt(current_bid)}** {config.CURRENCY_EMOJI}",
                color=discord.Color.green()
            )
            embed.set_footer(text="Государственная казна")
            await channel.send(embed=embed)
    else:
        if channel:
            await channel.send(f"🏛️ Аукцион #{aid} закрыт — нет ставок.")
    db.close_auction(auction_id)


@bot.event
async def on_ready():
    print(f"✅ Бот {bot.user} подключился!")
    try:
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
        else:
            synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

    bot.loop.create_task(role_auction_checker())
    bot.loop.create_task(bankrupt_checker())
    bot.loop.create_task(credit_checker())
    bot.loop.create_task(stock_updater())
    bot.loop.create_task(btc_updater())


# ============================================================
#                    ГЛАВНОЕ МЕНЮ /БАНК
# ============================================================


class BankView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💼 Баланс", style=discord.ButtonStyle.primary, row=0)
    async def balance(self, interaction, button):
        await show_balance(interaction, interaction.user)

    @discord.ui.button(label="📜 История", style=discord.ButtonStyle.secondary, row=0)
    async def history(self, interaction, button):
        await show_history(interaction, interaction.user)

    @discord.ui.button(label="🏆 Топ", style=discord.ButtonStyle.success, row=0)
    async def top(self, interaction, button):
        await show_top(interaction)

    @discord.ui.button(label="💱 Валюты", style=discord.ButtonStyle.primary, row=1)
    async def currencies(self, interaction, button):
        await show_currencies(interaction, interaction.user)

    @discord.ui.button(label="🏭 Бизнесы", style=discord.ButtonStyle.success, row=1)
    async def businesses(self, interaction, button):
        await interaction.response.send_message("🏭 Используй `/бизнес`", ephemeral=True)

    @discord.ui.button(label="📈 Акции", style=discord.ButtonStyle.danger, row=1)
    async def stocks(self, interaction, button):
        await interaction.response.send_message("📈 Используй `/акции`", ephemeral=True)

    @discord.ui.button(label="₿ BTC", style=discord.ButtonStyle.success, row=2)
    async def btc(self, interaction, button):
        await interaction.response.send_message("₿ Используй `/btc`", ephemeral=True)

    @discord.ui.button(label="💳 Кредиты", style=discord.ButtonStyle.primary, row=2)
    async def credits(self, interaction, button):
        await show_credits(interaction, interaction.user)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction, button):
        await interaction.response.defer()
        bal = db.get_balance(interaction.user.id)
        btc = db.get_currency(interaction.user.id, "btc")
        frozen = db.is_frozen(interaction.user.id)
        jail = db.is_in_jail(interaction.user.id)

        status_line = ""
        if frozen:
            status_line = f"\n{config.FREEZE_EMOJI} **СЧЁТ ЗАБЛОКИРОВАН**"
        elif jail:
            status_line = "\n🚔 **Ты в тюрьме**"

        embed = discord.Embed(
            title="🏦 БАНК",
            description=(
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💼 **Баланс:** {fmt(bal)} {config.CURRENCY_EMOJI}\n"
                f"₿ **BTC:** {fmt_btc(btc)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━{status_line}"
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Банк • {interaction.user.name}")
        await interaction.edit_original_response(embed=embed, view=self)


# ============================================================
#                    БАЗОВЫЕ (внутренние)
# ============================================================

async def show_balance(interaction, user):
    bal = db.get_balance(user.id)
    frozen = db.is_frozen(user.id)
    reason = db.get_freeze_reason(user.id)
    jail = db.is_in_jail(user.id)
    
    btc = db.get_currency(user.id, "btc")
    usd = db.get_currency(user.id, "usd")
    eur = db.get_currency(user.id, "eur")

    # Определяем роль
    is_owner = user.id == config.OWNER_ID
    is_dev = False
    is_admin = False
    
    if isinstance(user, discord.Member):
        role_ids = {r.id for r in user.roles}
        is_dev = config.DEV_ROLE_ID in role_ids
        is_admin = config.ADMIN_ROLE_ID in role_ids

    # Задаем стиль в зависимости от роли
    if is_owner:
        color = discord.Color.from_rgb(255, 215, 0) # Золотой
        title = "👑 VIP-СЧЁТ ОСНОВАТЕЛЯ"
        footer_text = "Государственный Банк • Высшая лига"
        status_text = "👑 **Основатель Банка**"
    elif is_dev:
        color = discord.Color.from_rgb(30, 30, 30) # Почти черный
        title = "🖤 СЧЁТ РАЗРАБОТЧИКА"
        footer_text = "Государственный Банк • Секретный отдел"
        status_text = "🖤 **Разработчик (Тень)**"
    elif is_admin:
        color = discord.Color.from_rgb(220, 20, 60) # Ярко-красный
        title = "👑 СЧЁТ АДМИНИСТРАТОРА"
        footer_text = "Государственный Банк • Управление"
        status_text = "👑 **Администратор**"
    else:
        color = discord.Color.red() if frozen else discord.Color.dark_green()
        title = "🏦 Банковский счёт"
        footer_text = "Безопасность и надежность • МСК"
        status_text = "✅ **Активен**"
        
        # Считаем ранг для обычного игрока
        rank_name, progress_bar, next_text = get_rank_info(bal)
        rank_text = f"**{rank_name}**\n{progress_bar}\n*{next_text}*"
        
        if frozen:
            status_text = f"🚫 **Заморожен**\n*Причина: {reason or '—'}*"
        elif jail:
            until, reason_jail = db.get_jail_info(user.id)
            status_text = f"🚔 **В тюрьме**\n*Освобождение: {time_left(until) if until else '—'}*"

        # Вычисляем ранг (если функции get_rank_info еще нет, она упадет, но мы её добавим)
        rank_name, progress_bar, next_text = get_rank_info(bal)
        rank_text = f"**{rank_name}**\n{progress_bar}\n*{next_text}*"

    # Формируем описание
    desc = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Клиент:** {user.mention}\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Основной баланс:**\n"
        f"# {fmt(bal)} {config.CURRENCY_EMOJI}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    embed = discord.Embed(title=title, description=desc, color=color)

    # Блок валют
    currencies_text = ""
    if usd > 0: currencies_text += f"💵 **USD:** {fmt(usd)} $\n"
    if eur > 0: currencies_text += f"💶 **EUR:** {fmt(eur)} €\n"
    if btc > 0: currencies_text += f"₿ **BTC:** {fmt_btc(btc)}\n"
    
    if currencies_text:
        embed.add_field(name="💱 Валютные счета", value=currencies_text, inline=True)
    else:
        embed.add_field(name="💱 Валютные счета", value="*Пусто*", inline=True)

       # Блок статуса
    embed.add_field(name="📌 Статус", value=status_text, inline=True)

    # Дополнительная плашка для персонала
    if is_owner:
        embed.add_field(name="🏆 Прогресс", value="👑 **VIP-доступ (Владелец)**\n*У вас не активен прогресс-бар*", inline=False)
    elif is_dev:
        embed.add_field(name="🏆 Прогресс", value="💎 **Доступ = Dev**\n*У вас не активен прогресс-бар*", inline=False)
    elif is_admin:
        embed.add_field(name="🏆 Прогресс", value="👑 **Доступ = Админ**\n*У вас не активен прогресс-бар*", inline=False)
    else:
        embed.add_field(name="🏆 Твой ранг", value=rank_text, inline=False)

    # Футер и аватарка
    embed.set_footer(text=footer_text)
    embed.set_thumbnail(url=user.display_avatar.url)

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.send_message(embed=embed)

async def show_history(interaction, user):
    txs = db.get_transactions(user.id, limit=15)
    if not txs:
        await interaction.response.send_message("📜 История пуста.", ephemeral=True)
        return

    type_emoji = {"transfer": "💸", "shop": "🛒", "admin": "⚖️", "casino": "🎰",
                  "issue": "💵", "biz": "🏭", "exchange": "💱", "steal": "🥷", "stock": "📈"}

    lines = []
    for amount, ttype, desc, created in txs:
        emoji = type_emoji.get(ttype, "💼")
        sign = "+" if amount > 0 else ""
        try:
            dt = db.parse_dt(created)
            date = dt.strftime("%d.%m %H:%M")
        except Exception:
            date = created[5:16].replace("T", " ")
        desc_text = f" — {desc}" if desc else ""
        lines.append(f"{emoji} `{date}` {sign}**{fmt(amount)}**{desc_text}")

    embed = discord.Embed(
        title="📜 История транзакций",
        description="━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) + "\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Последние {len(txs)} операций")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log_admin(interaction.user, "people", "Обыск", user.id, "")


async def show_currencies(interaction, user):
    rows = db.get_all_currencies(user.id)
    rub = db.get_balance(user.id)

    embed = discord.Embed(title="💱 Валютные счета", color=discord.Color.green())
    embed.add_field(name="🇷🇺 Рубли", value=f"**{fmt(rub)}**", inline=True)
    for cur, amount in rows:
        if amount > 0:
            if cur == "btc":
                embed.add_field(name="₿ BTC", value=f"**{fmt_btc(amount)}**", inline=True)
            else:
                embed.add_field(name=config.CURRENCY_NAMES.get(cur, cur), value=f"**{fmt(amount)}**", inline=True)
    embed.set_footer(text=f"Владелец: {user.name}")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def show_top(interaction):
    balances = db.get_all_balances()
    if not balances:
        await interaction.response.send_message("🏆 База данных пуста.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🏆 ЗАЛ СЛАВЫ БАНКА",
        description="Самые состоятельные клиенты нашего банка:\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.gold()
    )
    
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    
    # Считаем общую массу денег в экономике
    total_economy = sum(bal for _, bal in balances)

    for i, (user_id, bal) in enumerate(balances[:10]):
        prefix = medals[i] if i < 3 else f"**{i + 1}.**"
        
        # Если счет заморожен, добавляем метку
        status = ""
        if db.is_frozen(user_id):
            status = " 🚫"
            
        lines.append(f"{prefix} <@{user_id}> — **{fmt(bal)}** {config.CURRENCY_EMOJI}{status}")
        
    embed.add_field(
        name="👑 Топ-10 богачей", 
        value="\n".join(lines), 
        inline=False
    )
    
    embed.set_footer(text=f"💵 Всего денег в экономике: {fmt(total_economy)} {config.CURRENCY_EMOJI}")
    
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def show_credits(interaction, user):
    rows_debts = db.get_credits_by_borrower(user.id)
    rows_lent = db.get_credits_by_lender(user.id)

    embed = discord.Embed(title="💳 Кредиты", color=discord.Color.green())
    if rows_debts:
        lines = []
        for cid, lender, borrower, amount, debt, percent, until in rows_debts:
            lines.append(f"**#{cid}** → <@{lender}> • **{fmt(debt)}** 💵 • {time_left(until)}")
        embed.add_field(name="📥 Я должен", value="\n".join(lines), inline=False)
    if rows_lent:
        lines = []
        for cid, lender, borrower, amount, debt, percent, until in rows_lent:
            lines.append(f"**#{cid}** ← <@{borrower}> • **{fmt(debt)}** 💵 • {time_left(until)}")
        embed.add_field(name="📤 Мне должны", value="\n".join(lines), inline=False)
    if not rows_debts and not rows_lent:
        embed.description = "Нет активных кредитов."
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#                    КОМАНДЫ (ключевые)
# ============================================================

@bot.tree.command(name="balance", description="💼 Показать свой баланс")
async def balance(interaction: discord.Interaction):
    await show_balance(interaction, interaction.user)


@bot.tree.command(name="кошелёк", description="👛 Подсмотреть чужой кошелёк")
@app_commands.describe(user="Чей кошелёк")
async def wallet(interaction: discord.Interaction, user: discord.Member):
    if user.bot:
        await interaction.response.send_message("❌ У ботов нет кошелька.", ephemeral=True)
        return
    await show_balance(interaction, user)


@bot.tree.command(name="transfer", description="💸 Перевести рубли")
@app_commands.describe(user="Кому", amount="Сколько")
async def transfer(interaction: discord.Interaction, user: discord.Member, amount: int):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!** Переводы недоступны.", ephemeral=True)
        return
    if db.is_frozen(interaction.user.id):
        await interaction.response.send_message("🚫 Счёт заблокирован!", ephemeral=True)
        return
    if user.id == interaction.user.id or user.bot or amount <= 0:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    if db.get_balance(interaction.user.id) < amount:
        await interaction.response.send_message("❌ Недостаточно.", ephemeral=True)
        return

        # --- ОБХОД ДЛЯ DEV ---
    if interaction.user.id in config.OWNER_IDS or _is_dev_or_owner(interaction.user):
        # Если это Dev или Owner, просто переводим деньги без лимитов
        db.add_balance(interaction.user.id, -amount)
        db.add_balance(user.id, amount)
        db.add_transaction(interaction.user.id, -amount, "transfer", f"→ {user.name} (Обход by Dev)")
        db.add_transaction(user.id, amount, "transfer", f"← {interaction.user.name}")
        
        embed = discord.Embed(title="💸 Перевод (Обход by Dev)", color=discord.Color.purple())
        embed.add_field(name="Отправитель", value=interaction.user.mention, inline=True)
        embed.add_field(name="Получатель", value=user.mention, inline=True)
        embed.add_field(name="Сумма", value=f"**{fmt(amount)}** {config.CURRENCY_EMOJI}", inline=False)
        await interaction.response.send_message(embed=embed)
        return

    if amount >= config.LAUNDERING_THRESHOLD:
        # ... (дальше твой старый код с заморозкой)
        db.add_balance(interaction.user.id, -amount)
        db.add_to_treasury(amount)
        db.add_transaction(interaction.user.id, -amount, "admin", f"Изъято в казну (отмывание): {amount}")
        db.set_frozen(interaction.user.id, True, "Отмывание (ФЗ-115)")
        db.set_frozen(user.id, True, "Отмывание (ФЗ-115)")
        embed = discord.Embed(
            title="🚨 ПОДОЗРЕНИЕ В ОТМЫВАНИИ",
            description=(
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Перевод **{fmt(amount)}** превысил лимит **{fmt(config.LAUNDERING_THRESHOLD)}** {config.CURRENCY_EMOJI}.\n\n"
                f"**Деньги изъяты в казну.**\n"
                f"**Оба счёта заморожены на 1 час.**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        for u in (interaction.user, user):
            try:
                await u.send(config.LAUNDERING_MESSAGE)
            except Exception:
                pass
        asyncio.create_task(unfreeze_after(interaction.user.id, config.LAUNDERING_FREEZE_DURATION))
        asyncio.create_task(unfreeze_after(user.id, config.LAUNDERING_FREEZE_DURATION))
        return

    db.add_balance(interaction.user.id, -amount)
    db.add_balance(user.id, amount)
    db.add_transaction(interaction.user.id, -amount, "transfer", f"→ {user.name}")
    db.add_transaction(user.id, amount, "transfer", f"← {actor_label(interaction.user)}")

    embed = discord.Embed(title="💸 Перевод выполнен", color=discord.Color.green())
    embed.add_field(name="Отправитель", value=interaction.user.mention, inline=True)
    embed.add_field(name="Получатель", value=user.mention, inline=True)
    embed.add_field(name="Сумма", value=f"**{fmt(amount)}** {config.CURRENCY_EMOJI}", inline=False)
    embed.set_footer(text=f"Банк • {interaction.user.name}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="transfer_usd", description="💵 Перевести доллары")
@app_commands.describe(user="Кому", amount="Сколько $")
async def transfer_usd(interaction: discord.Interaction, user: discord.Member, amount: float):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
        return
    if db.is_frozen(interaction.user.id):
        await interaction.response.send_message("🚫 Счёт заблокирован!", ephemeral=True)
        return
    if user.id == interaction.user.id or user.bot or amount <= 0:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    have = db.get_currency(interaction.user.id, "usd")
    if amount > have + 1e-9:
        await interaction.response.send_message(f"❌ У тебя только **{fmt(have)}** $.", ephemeral=True)
        return
    db.add_currency(interaction.user.id, "usd", -amount)
    db.add_currency(user.id, "usd", amount)
    embed = discord.Embed(title="💵 Перевод USD", color=discord.Color.green())
    embed.add_field(name="Отправитель", value=interaction.user.mention, inline=True)
    embed.add_field(name="Получатель", value=user.mention, inline=True)
    embed.add_field(name="Сумма", value=f"**{fmt(amount)}** $", inline=False)
    await interaction.response.send_message(embed=embed)
    try:
        await user.send(f"💵 **Ты получил {fmt(amount)} $ от {interaction.user.name}**")
    except Exception:
        pass


@bot.tree.command(name="transfer_eur", description="💶 Перевести евро")
@app_commands.describe(user="Кому", amount="Сколько €")
async def transfer_eur(interaction: discord.Interaction, user: discord.Member, amount: float):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
        return
    if db.is_frozen(interaction.user.id):
        await interaction.response.send_message("🚫 Счёт заблокирован!", ephemeral=True)
        return
    if user.id == interaction.user.id or user.bot or amount <= 0:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    have = db.get_currency(interaction.user.id, "eur")
    if amount > have + 1e-9:
        await interaction.response.send_message(f"❌ У тебя только **{fmt(have)}** €.", ephemeral=True)
        return
    db.add_currency(interaction.user.id, "eur", -amount)
    db.add_currency(user.id, "eur", amount)
    embed = discord.Embed(title="💶 Перевод EUR", color=discord.Color.green())
    embed.add_field(name="Отправитель", value=interaction.user.mention, inline=True)
    embed.add_field(name="Получатель", value=user.mention, inline=True)
    embed.add_field(name="Сумма", value=f"**{fmt(amount)}** €", inline=False)
    await interaction.response.send_message(embed=embed)
    try:
        await user.send(f"💶 **Ты получил {fmt(amount)} € от {interaction.user.name}**")
    except Exception:
        pass


@bot.tree.command(name="топ", description="🏆 Топ-10 богачей")
async def top(interaction: discord.Interaction):
    await show_top(interaction)


@bot.tree.command(name="история", description="📜 Последние транзакции")
async def history(interaction: discord.Interaction):
    await show_history(interaction, interaction.user)


@bot.tree.command(name="обменять", description="💱 Обменять валюту")
@app_commands.describe(amount="Сколько", from_cur="Из валюты", to_cur="В валюту")
@app_commands.choices(from_cur=[
    app_commands.Choice(name="Рубли 🇷🇺", value="руб"),
    app_commands.Choice(name="Доллары 🇺🇸", value="usd"),
    app_commands.Choice(name="Евро 🇪🇺", value="eur"),
])
@app_commands.choices(to_cur=[
    app_commands.Choice(name="Рубли 🇷🇺", value="руб"),
    app_commands.Choice(name="Доллары 🇺🇸", value="usd"),
    app_commands.Choice(name="Евро 🇪🇺", value="eur"),
])
async def exchange(interaction: discord.Interaction, amount: float,
                   from_cur: app_commands.Choice[str], to_cur: app_commands.Choice[str]):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
        return
    if db.is_frozen(interaction.user.id):
        await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
        return
    if amount <= 0 or from_cur.value == to_cur.value:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    if from_cur.value == "руб":
        if db.get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("❌ Недостаточно рублей.", ephemeral=True)
            return
        db.add_balance(interaction.user.id, -int(amount))
    else:
        if db.get_currency(interaction.user.id, from_cur.value) < amount:
            await interaction.response.send_message("❌ Недостаточно.", ephemeral=True)
            return
        db.add_currency(interaction.user.id, from_cur.value, -amount)
    rub_amount = amount * config.CURRENCY_RATES[from_cur.value]
    result = rub_amount / config.CURRENCY_RATES[to_cur.value]
    if to_cur.value == "руб":
        db.add_balance(interaction.user.id, int(result))
    else:
        db.add_currency(interaction.user.id, to_cur.value, result)
    db.add_transaction(interaction.user.id, 0, "exchange",
                       f"{fmt(amount)} {from_cur.value} → {fmt(result)} {to_cur.value}")
    embed = discord.Embed(title="💱 Обмен выполнен", color=discord.Color.green())
    embed.add_field(name="Отдал", value=f"**{fmt(amount)}** {from_cur.name}", inline=True)
    embed.add_field(name="Получил", value=f"**{fmt(result)}** {to_cur.name}", inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="валюты", description="💰 Мои валютные счета")
async def currencies(interaction: discord.Interaction):
    await show_currencies(interaction, interaction.user)


# ============================================================
#                       МАГАЗИН
# ============================================================

shop_group = app_commands.Group(name="shop", description="🛒 Магазин ролей")


@shop_group.command(name="list", description="🛒 Роли")
async def shop_list(interaction: discord.Interaction):
    roles = db.get_shop_roles()
    if not roles:
        await interaction.response.send_message("🛒 Пусто.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🛒 Магазин ролей",
        description="━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green()
    )
    for role_id, price, name in roles:
        role = interaction.guild.get_role(role_id)
        embed.add_field(
            name=f"🎭 {name}",
            value=f"{role.mention if role else role_id} • **{fmt(price)}** {config.CURRENCY_EMOJI}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)


@shop_group.command(name="buy", description="💳 Купить роль")
async def shop_buy(interaction: discord.Interaction, role: discord.Role):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
        return
    if db.is_frozen(interaction.user.id):
        await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
        return
    shop_role = db.get_shop_role(role.id)
    if not shop_role:
        await interaction.response.send_message("❌ Нет в магазине.", ephemeral=True)
        return
    _, price, name = shop_role
    if db.get_balance(interaction.user.id) < price:
        await interaction.response.send_message("❌ Недостаточно.", ephemeral=True)
        return
    bot_member = interaction.guild.get_member(bot.user.id)
    if role >= bot_member.top_role:
        await interaction.response.send_message("❌ Роль выше моей.", ephemeral=True)
        return
    try:
        await interaction.user.add_roles(role, reason="Покупка")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
        return
    db.add_balance(interaction.user.id, -price)
    db.add_transaction(interaction.user.id, -price, "shop", f"Куплена роль {name}")
    embed = discord.Embed(
        title="✅ Покупка успешна",
        description=f"Ты купил {role.mention} за **{fmt(price)}** {config.CURRENCY_EMOJI}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)


bot.tree.add_command(shop_group)



# ============================================================
#                       АУКЦИОН
# ============================================================

auction_group = app_commands.Group(name="аукцион", description="🏛️ Аукцион")


@auction_group.command(name="выставить", description="🏛️ [АДМИН] Выставить бизнес")
@app_commands.describe(seller="Владелец", biz_id="ID", start_price="Старт", bypass="Обход (Dev)")
@app_commands.default_permissions(administrator=True)
async def auction_create(interaction: discord.Interaction, seller: discord.Member, biz_id: int, start_price: int, bypass: bool = False):
    if start_price <= 0:
        await interaction.response.send_message("❌ Цена > 0.", ephemeral=True)
        return
    biz = db.get_user_business(biz_id)
    if not biz:
        await interaction.response.send_message("❌ Не найден.", ephemeral=True)
        return
    owner_id, biz_type = biz
    owner_id, biz_type = biz
    is_dev = _is_dev_or_owner(interaction.user)
    bypass_allowed = bypass and is_dev
    note = " — **обход by Dev**" if bypass_allowed else ""

    if owner_id != seller.id and not bypass_allowed:
        await interaction.response.send_message(f"❌ Принадлежит <@{owner_id}>.", ephemeral=True)
        return
    ends_at = (now_msk() + timedelta(seconds=config.AUCTION_DURATION)).isoformat()
    auction_id = db.create_auction(biz_id, seller.id, biz_type, start_price, interaction.channel_id, ends_at)
    info = config.BUSINESS_TYPES.get(biz_type, {})
    embed = discord.Embed(
        title=f"🏛️ АУКЦИОН #{auction_id}",
        description=(
            f"**Лот:** {info.get('name', biz_type)}\n"
            f"**Продавец:** {seller.mention}\n"
            f"**Старт:** **{fmt(start_price)}** {config.CURRENCY_EMOJI}\n"
            f"⏰ До конца: <t:{int((now_msk() + timedelta(seconds=config.AUCTION_DURATION)).timestamp())}:R>"
        ),
        color=discord.Color.green()
    )
    msg = await interaction.channel.send(embed=embed, view=AuctionView(auction_id))
    db.update_auction_message(auction_id, msg.id)
    db.add_auction_history("biz", auction_id, interaction.user.id, start_price,
                           "start", f"Бизнес: {info.get('name', biz_type)}")
    log_admin(interaction.user, "biz", f"Аукцион бизнеса: старт{note}", None, biz_type)
    await interaction.response.send_message(f"✅ Лот #{auction_id} выставлен.", ephemeral=True)


@auction_group.command(name="список", description="🏛️ Активные аукционы")
async def auction_list(interaction: discord.Interaction):
    auctions = db.get_active_auctions()
    if not auctions:
        await interaction.response.send_message("🏛️ Нет аукционов.", ephemeral=True)
        return
    embed = discord.Embed(title="🏛️ Активные аукционы", color=discord.Color.green())
    for a in auctions:
        aid, biz_id, seller_id, biz_type, start_price, current_bid, current_bidder, ch_id, msg_id, ends_at = a
        info = config.BUSINESS_TYPES.get(biz_type, {})
        bid_text = f"**{fmt(current_bid)}** {config.CURRENCY_EMOJI}" if current_bid else "нет ставок"
        embed.add_field(
            name=f"#{aid}: {info.get('name', biz_type)}",
            value=f"Старт: **{fmt(start_price)}**\nСтавка: {bid_text}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)
    log_admin(interaction.user, "biz", "Забрать бизнес", user.id, info.get("name", biz_type))


class AuctionView(discord.ui.View):
    def __init__(self, auction_id: int):
        super().__init__(timeout=None)
        self.auction_id = auction_id

    @discord.ui.button(label="💰 Ставка", style=discord.ButtonStyle.success, custom_id="auction_bid")
    async def bid(self, interaction, button):
        auction = db.get_auction(self.auction_id)
        if not auction or not auction[10]:
            await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
            return
        if interaction.user.id == auction[2]:
            await interaction.response.send_message("❌ Свой лот.", ephemeral=True)
            return
        min_bid = auction[5] + config.AUCTION_MIN_STEP if auction[5] else auction[4]
        await interaction.response.send_modal(AuctionBidModal(self.auction_id, min_bid))


class AuctionBidModal(discord.ui.Modal):
    def __init__(self, auction_id: int, min_bid: int):
        super().__init__(title="Ставка")
        self.auction_id = auction_id
        self.min_bid = min_bid
        self.bid_input = discord.ui.TextInput(label=f"Мин. {min_bid}", min_length=1, max_length=15)
        self.add_item(self.bid_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.bid_input.value)
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if amount < self.min_bid:
            await interaction.response.send_message(f"❌ Мин. **{fmt(self.min_bid)}**.", ephemeral=True)
            return
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        if db.get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("❌ Недостаточно.", ephemeral=True)
            return
        auction = db.get_auction(self.auction_id)
        if not auction or not auction[10]:
            await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
            return
        if auction[6]:
            db.add_balance(auction[6], auction[5])
        db.add_balance(interaction.user.id, -amount)
        db.update_auction_bid(self.auction_id, interaction.user.id, amount)
        db.add_auction_history("biz", self.auction_id, interaction.user.id, amount, "bid")
        if auction[6]:
            db.add_auction_history("biz", self.auction_id, auction[6], auction[5], "refund",
                                   f"Возврат при перебитии от <@{interaction.user.id}>")
        await interaction.response.send_message(f"✅ Ставка **{fmt(amount)}** принята!", ephemeral=True)


bot.tree.add_command(auction_group)


# ============================================================
#                  КАЗНА
# ============================================================

@bot.tree.command(name="казн", description="⚖️ Государственная казна")
async def treasury_cmd(interaction: discord.Interaction):
    total = db.get_treasury()
    status = "🔓 Открыта" if db.get_treasury_open() else "🔒 Закрыта"
    embed = discord.Embed(
        title="⚖️ Государственная казна",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 **В казне:** {fmt(total)} {config.CURRENCY_EMOJI}\n"
            f"🚪 **Статус:** {status}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="Государственная казна")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="казна_панель", description="⚖️ [АДМИН] Панель казны")
@app_commands.default_permissions(administrator=True)
async def kazna_panel(interaction: discord.Interaction):
    await interaction.response.send_message(embed=make_treasury_embed(), view=TreasuryView())


def make_treasury_embed() -> discord.Embed:
    is_open = db.get_treasury_open()
    status = "🔓 ОТКРЫТА" if is_open else "🔒 ЗАКРЫТА"
    color = discord.Color.green() if is_open else discord.Color.red()
    embed = discord.Embed(
        title=f"⚖️ Государственная казна — {status}",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 **В казне:** {fmt(db.get_treasury())} {config.CURRENCY_EMOJI}\n"
            f"⏰ **КД:** 6 часов\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=color
    )
    embed.set_footer(text="Управление казной")
    return embed


class TreasuryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔓 Открыть", style=discord.ButtonStyle.success, row=0)
    async def open_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Только админы.", ephemeral=True)
            return
        if db.get_treasury_open():
            await interaction.response.send_message("❌ Уже открыта.", ephemeral=True)
            return
        db.set_treasury_open(True)
        await interaction.response.edit_message(embed=make_treasury_embed(), view=self)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger, row=0)
    async def close_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Только админы.", ephemeral=True)
            return
        if not db.get_treasury_open():
            await interaction.response.send_message("❌ Уже закрыта.", ephemeral=True)
            return
        db.set_treasury_open(False)
        await interaction.response.edit_message(embed=make_treasury_embed(), view=self)

    @discord.ui.button(label="💰 Взять", style=discord.ButtonStyle.primary, row=1)
    async def take_btn(self, interaction, button):
        if not db.get_treasury_open():
            await interaction.response.send_message("🔒 Казна закрыта.", ephemeral=True)
            return
        await interaction.response.send_modal(TreasuryTakeModal())

    @discord.ui.button(label="📊 Обновить", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction, button):
        await interaction.response.edit_message(embed=make_treasury_embed(), view=self)


class TreasuryTakeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Взять из казны")
        self.amount_input = discord.ui.TextInput(label="Сумма", min_length=1, max_length=15)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount_input.value)
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
            return
        if not has_no_cooldown(interaction.user):
            last = db.get_treasury_cooldown(interaction.user.id)
            if last:
                elapsed = (now_msk() - db.parse_dt(last)).total_seconds()
                if elapsed < config.TREASURY_COOLDOWN:
                    remaining = int(config.TREASURY_COOLDOWN - elapsed)
                    await interaction.response.send_message(
                        f"⏳ КД. Подожди **{remaining // 3600} ч {(remaining % 3600) // 60} мин**.",
                        ephemeral=True
                    )
                    return
        if db.get_treasury() < amount:
            await interaction.response.send_message(f"❌ В казне только **{fmt(db.get_treasury())}** {config.CURRENCY_EMOJI}.", ephemeral=True)
            return
        db.take_from_treasury(amount)
        db.add_balance(interaction.user.id, amount)
        db.add_transaction(interaction.user.id, amount, "admin", "Взято из казны")
        db.set_treasury_cooldown(interaction.user.id, now_msk().isoformat())
        if amount > config.TREASURY_WITHDRAW_LIMIT:
            db.set_frozen(interaction.user.id, True, "Ст. 160 УК РФ — растрата")
            embed = discord.Embed(
                title="🚨 СТАТЬЯ 160 УК РФ",
                description=f"Взято **{fmt(amount)}** сверх лимита.\n**Счёт арестован.**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            asyncio.create_task(unfreeze_after(interaction.user.id, config.TREASURY_FREEZE_DURATION))
            return
        embed = discord.Embed(
            title="⚖️ Взято из казны",
            description=f"**+{fmt(amount)}** {config.CURRENCY_EMOJI}\nОстаток: **{fmt(db.get_treasury())}**",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)


# ============================================================
#                  ГОСУДАРСТВО
# ============================================================

@bot.tree.command(name="снять_деньги", description="⚖️ [АДМИН] Списать деньги")
@app_commands.describe(user="С кого", amount="Сколько", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def snyat(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = None):
    if amount <= 0 or user.bot:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    real = min(amount, db.get_balance(user.id))
    db.add_balance(user.id, -real)
    db.add_to_treasury(real)
    db.add_transaction(user.id, -real, "admin", f"Списание: {reason or '—'}")
    log_admin(interaction.user, "economy", "Списание", user.id, f"{real} — {reason or '—'}")
    embed = discord.Embed(title="⚖️ Списание", color=discord.Color.red())
    embed.add_field(name="Кому", value=user.mention)
    embed.add_field(name="Списано", value=f"**-{fmt(real)}** {config.CURRENCY_EMOJI}")
    embed.add_field(name="Причина", value=reason or "—")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="конфисковать", description="⚖️ [АДМИН] Конфисковать ВСЁ")
@app_commands.describe(user="У кого", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def confiscate(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return
    old = db.zero_balance(user.id)
    db.add_to_treasury(old)
    db.add_transaction(user.id, -old, "admin", f"Конфискация: {reason or '—'}")
    log_admin(interaction.user, "economy", "Конфискация", user.id, str(old))
    await interaction.response.send_message(f"⚖️ **{user.mention}** — изъято **{fmt(old)}** {config.CURRENCY_EMOJI}")


@bot.tree.command(name="налог", description="⚖️ [АДМИН] Налог %")
@app_commands.describe(user="С кого", percent="Процент")
@app_commands.default_permissions(administrator=True)
async def nalog(interaction: discord.Interaction, user: discord.Member, percent: int):
    if percent <= 0 or percent > 100:
        await interaction.response.send_message("❌ 1-100.", ephemeral=True)
        return
    tax = int(db.get_balance(user.id) * percent / 100)
    db.add_balance(user.id, -tax)
    db.add_to_treasury(tax)
    db.add_transaction(user.id, -tax, "admin", f"Налог {percent}%")
    log_admin(interaction.user, "economy", "Налог", user.id, f"{percent}%={tax}")
    await interaction.response.send_message(f"⚖️ Налог **{fmt(tax)}** {config.CURRENCY_EMOJI} с {user.mention}")


@bot.tree.command(name="налог_все", description="⚖️ [АДМИН] Налог со ВСЕХ")
@app_commands.describe(percent="Процент (1-100)")
@app_commands.default_permissions(administrator=True)
async def nalog_all(interaction: discord.Interaction, percent: int):
    if percent <= 0 or percent > 100:
        await interaction.response.send_message("❌ 1-100.", ephemeral=True)
        return
    balances = db.get_all_balances()
    total_taken = 0
    count = 0
    for user_id, bal in balances:
        if bal <= 0:
            continue
        tax = int(bal * percent / 100)
        db.add_balance(user_id, -tax)
        db.add_transaction(user_id, -tax, "admin", f"Массовый налог {percent}%")
        total_taken += tax
        count += 1
    db.add_to_treasury(total_taken)
    log_admin(interaction.user, "economy", "Массовый налог", None, f"{percent}%={total_taken}")
    embed = discord.Embed(
        title="⚖️ МАССОВЫЙ НАЛОГ",
        description=(
            f"**Ставка:** {percent}%\n"
            f"**Обложено:** {count} игроков\n"
            f"**Собрано:** **{fmt(total_taken)}** {config.CURRENCY_EMOJI}\n"
            f"**В казне:** {fmt(db.get_treasury())} {config.CURRENCY_EMOJI}"
        ),
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="штраф", description="⚖️ [АДМИН] Штраф")
@app_commands.describe(user="Кого", amount="Сумма", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def shtraf(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = None):
    if amount <= 0 or user.bot:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    db.add_balance(user.id, -amount)
    db.add_to_treasury(amount)
    db.add_transaction(user.id, -amount, "admin", f"Штраф: {reason or '—'}")
    log_admin(interaction.user, "economy", "Штраф", user.id, str(amount))
    await interaction.response.send_message(f"⚖️ Штраф **{fmt(amount)}** {config.CURRENCY_EMOJI} на {user.mention}")


@bot.tree.command(name="обыск", description="⚖️ [АДМИН] Обыск")
@app_commands.describe(user="Кого")
@app_commands.default_permissions(administrator=True)
async def obysk(interaction: discord.Interaction, user: discord.Member):
    bal = db.get_balance(user.id)
    frozen = db.is_frozen(user.id)
    reason = db.get_freeze_reason(user.id)
    txs = db.get_transactions(user.id, limit=5)
    embed = discord.Embed(title=f"🔍 Обыск: {user.name}", color=discord.Color.red())
    embed.add_field(name="Баланс", value=f"**{fmt(bal)}** {config.CURRENCY_EMOJI}")
    embed.add_field(name="Статус", value="🚫 Арестован" if frozen else "✅ Активен")
    if frozen:
        embed.add_field(name="Причина", value=reason or "—")
    if txs:
        lines = []
        for a, t, d, c in txs:
            sign = "+" if a > 0 else ""
            lines.append(f"{sign}**{fmt(a)}** — {d or t}")
        embed.add_field(name="Последнее", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="розыск", description="🚨 [АДМИН] Розыск")
@app_commands.describe(user="Кого", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def розыск(interaction: discord.Interaction, user: discord.Member, reason: str = "не указана"):
    embed = discord.Embed(
        title="🚨 ВНИМАНИЕ! РОЗЫСК",
        description=f"**Гражданин:** {user.mention}\n**Причина:** {reason}",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"Государственная служба безопасности • {actor_label(interaction.user)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="арестовать", description="🚫 [АДМИН] Арест")
@app_commands.describe(user="Кого", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def arest(interaction: discord.Interaction, user: discord.Member, reason: str = "не указана"):
    if user.bot or db.is_frozen(user.id):
        await interaction.response.send_message("❌ Нельзя.", ephemeral=True)
        return
    db.set_frozen(user.id, True, reason)
    log_admin(interaction.user, "people", "Арест", user.id, reason)
    db.add_transaction(user.id, 0, "admin", f"Арест: {reason}")
    embed = discord.Embed(
        title=f"{config.FREEZE_EMOJI} СЧЁТ ЗАБЛОКИРОВАН",
        description=f"**{user.mention}**\n**Причина:** {reason}",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="разморозить", description="✅ [АДМИН] Разморозить")
@app_commands.describe(user="Кого")
@app_commands.default_permissions(administrator=True)
async def razmoroz(interaction: discord.Interaction, user: discord.Member):
    if not db.is_frozen(user.id):
        await interaction.response.send_message("❌ Не заморожен.", ephemeral=True)
        return
    db.set_frozen(user.id, False, None)
    log_admin(interaction.user, "people", "Разморозка", user.id, "")
    await interaction.response.send_message(f"✅ {user.mention} разморожен.")


@bot.tree.command(name="амнистия", description="⚖️ [АДМИН] Разморозить всех")
@app_commands.default_permissions(administrator=True)
async def amnistiya(interaction: discord.Interaction):
    count = 0
    for user_id, _ in db.get_all_balances():
        if db.is_frozen(user_id):
            db.set_frozen(user_id, False, None)
            count += 1
    await interaction.response.send_message(f"⚖️ Разморожено: **{count}**")
    log_admin(interaction.user, "people", "Амнистия", None, f"count={count}")


@bot.tree.command(name="аннулировать", description="⚖️ [АДМИН] Аннулировать")
@app_commands.describe(user="Кого", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def annul(interaction: discord.Interaction, user: discord.Member, reason: str = "не указана"):
    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return
    old = db.zero_balance(user.id)
    db.add_to_treasury(old)
    db.add_transaction(user.id, -old, "admin", f"Аннулирование: {reason}")
    await interaction.response.send_message(f"⚖️ **{user.mention}** — изъято **{fmt(old)}**")


@bot.tree.command(name="репрессия", description="🩸 [АДМИН] Уничтожить деньги")
@app_commands.describe(amount="Сколько", user="У кого (пусто = казна)")
@app_commands.default_permissions(administrator=True)
async def repression(interaction: discord.Interaction, amount: int, user: discord.Member = None):
    if amount <= 0:
        await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
        return
    if user is None:
        if db.get_treasury() < amount:
            await interaction.response.send_message("❌ В казне мало.", ephemeral=True)
            return
        db.take_from_treasury(amount)
        await interaction.response.send_message(f"🩸 Из казны уничтожено **{fmt(amount)}**")
        return
    real = min(amount, db.get_balance(user.id))
    if real <= 0:
        await interaction.response.send_message("❌ У него нет денег.", ephemeral=True)
        return
    db.add_balance(user.id, -real)
    db.add_transaction(user.id, -real, "admin", f"Репрессия: {actor_label(interaction.user)}")
    await interaction.response.send_message(f"🩸 **{user.mention}** — уничтожено **{fmt(real)}**")


@bot.tree.command(name="накрутить", description="🖨️ Накрутить рубли")
@app_commands.describe(amount="Сколько", user="Кому (по умолчанию себе)")
async def nakrutit(interaction: discord.Interaction, amount: int, user: discord.Member = None):
    if not any(r.id == config.NAKRUTKA_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message(
            "❌ У тебя нет прав на эту команду.",
            ephemeral=True
        )
        return

    target = user or interaction.user
    if amount <= 0:
        await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
        return

    new = db.add_balance(target.id, amount)
    db.add_transaction(target.id, amount, "admin", f"Накрутка от {actor_label(interaction.user)}")
    log_admin(interaction.user, "economy", "Накрутка", target.id, str(amount))
    await interaction.response.send_message(
        f"🖨️ {target.mention}: **+{fmt(amount)}** (баланс: **{fmt(new)}**)",
        ephemeral=True
    )


@bot.tree.command(name="выдать", description="💵 Выдать (банкиры)")
@app_commands.describe(user="Кому", amount="Сколько")
async def vydat(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not any(r.id in config.ISSUER_ROLE_IDS for r in interaction.user.roles):
        await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
        return
    if amount <= 0 or user.bot:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    new = db.add_balance(user.id, amount)
    db.add_transaction(user.id, amount, "issue", f"Выдал {actor_label(interaction.user)}")
    log_admin(interaction.user, "economy", "Выдача", user.id, str(amount))
    await interaction.response.send_message(f"💵 {user.mention}: **+{fmt(amount)}** (баланс: **{fmt(new)}**)")


@bot.tree.command(name="зп", description="💰 Выдать зарплату")
@app_commands.describe(user="Кому")
@app_commands.default_permissions(administrator=True)
async def salary(interaction: discord.Interaction, user: discord.Member):
    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return
    if not has_no_cooldown(interaction.user):
        last = db.get_last_salary(user.id)
        if last:
            elapsed = (now_msk() - db.parse_dt(last)).total_seconds()
            if elapsed < config.SALARY_COOLDOWN:
                remaining = int(config.SALARY_COOLDOWN - elapsed)
                await interaction.response.send_message(
                    f"⏳ {user.mention} уже получал ЗП. Жди **{remaining // 3600} ч {(remaining % 3600) // 60} мин**.",
                    ephemeral=True
                )
                return
    amount = config.SALARY_AMOUNT
    db.add_balance(user.id, amount)
    db.set_last_salary(user.id, now_msk().isoformat())
    log_admin(interaction.user, "economy", "ЗП", user.id, str(config.SALARY_AMOUNT))
    db.add_transaction(user.id, amount, "admin", f"ЗП от {actor_label(interaction.user)}")
    embed = discord.Embed(
        title="💵 РАСЧЕТНЫЙ ЛИСТ",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 **Банк:** Государственный\n"
            f"👤 **Получатель:** {user.mention}\n"
            f"📅 **Дата:** {now_msk().strftime('%d.%m.%Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Начислено:** {fmt(amount)} {config.CURRENCY_EMOJI}\n"
            f"✅ **Статус:** Исполнено"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="Подпись: Главный бухгалтер")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="премия", description="🎁 Выдать премию")
@app_commands.describe(user="Кому", amount="Сумма", reason="Причина")
@app_commands.default_permissions(administrator=True)
async def bonus(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "не указана"):
    if user.bot or amount <= 0:
        await interaction.response.send_message("❌ Некорректно.", ephemeral=True)
        return
    db.add_balance(user.id, amount)
    db.add_transaction(user.id, amount, "admin", f"Премия от {actor_label(interaction.user)}: {reason}")
    log_admin(interaction.user, "economy", "Премия", user.id, f"{amount} — {reason}")
    embed = discord.Embed(title="🎁 Премия", color=discord.Color.green())
    embed.add_field(name="Кому", value=user.mention)
    embed.add_field(name="Сумма", value=f"**+{fmt(amount)}** {config.CURRENCY_EMOJI}")
    embed.add_field(name="Причина", value=reason)
    await interaction.response.send_message(embed=embed)
    log_admin(interaction.user, "people", "Амнистия", None, f"count={count}")


@bot.tree.command(name="add_shop_role", description="🎭 [АДМИН] Роль в магазин")
@app_commands.default_permissions(administrator=True)
async def add_shop(interaction: discord.Interaction, role: discord.Role, price: int, name: str):
    if price <= 0:
        await interaction.response.send_message("❌ Цена > 0.", ephemeral=True)
        return
    db.add_shop_role(role.id, price, name)
    await interaction.response.send_message(f"✅ {role.mention} за **{fmt(price)}**", ephemeral=True)


@bot.tree.command(name="remove_shop_role", description="🗑️ [АДМИН] Убрать роль")
@app_commands.default_permissions(administrator=True)
async def rem_shop(interaction: discord.Interaction, role: discord.Role):
    db.remove_shop_role(role.id)
    await interaction.response.send_message(f"✅ {role.mention} убрана.", ephemeral=True)







# ============================================================
#                       АКЦИИ
# ============================================================

@bot.tree.command(name="акции", description="📈 Фондовый рынок")
async def stocks_menu(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📈 ФОНДОВЫЙ РЫНОК",
        description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери действие:",
        color=discord.Color.green()
    )
    embed.set_footer(text="Биржа • МСК")
    await interaction.response.send_message(embed=embed, view=StocksView(interaction.user.id))


class StocksView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📊 Рынок", style=discord.ButtonStyle.primary, row=0)
    async def market(self, interaction, button):
        embed = discord.Embed(
            title="📈 ФОНДОВЫЙ РЫНОК",
            description="━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green()
        )
        for ticker, info in config.STOCKS.items():
            price = db.get_stock_price(ticker)
            if price is None:
                price = info["base_price"]
                db.set_stock_price(ticker, price)
            diff = ((price - info["base_price"]) / info["base_price"]) * 100
            arrow = "🟢" if diff >= 0 else "🔴"
            embed.add_field(
                name=f"{info['name']} ({ticker})",
                value=f"{arrow} **{fmt(price)}** {config.CURRENCY_EMOJI} ({diff:+.1f}%)",
                inline=False
            )
        embed.set_footer(text="МСК • Обновление раз в час")
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="💼 Портфель", style=discord.ButtonStyle.success, row=0)
    async def portfolio(self, interaction, button):
        rows = db.get_user_stocks(interaction.user.id)
        if not rows:
            await interaction.response.send_message("📈 Портфель пуст.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📈 Мой портфель",
            description="━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green()
        )
        total = 0
        for ticker, amount in rows:
            price = db.get_stock_price(ticker) or config.STOCKS[ticker]["base_price"]
            value = int(price * amount)
            total += value
            embed.add_field(
                name=config.STOCKS[ticker]["name"],
                value=f"{amount} шт. × **{fmt(price)}** = **{fmt(value)}** 💵",
                inline=False
            )
        embed.set_footer(text=f"💼 Общая стоимость: {fmt(total)} 💵")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💰 Купить", style=discord.ButtonStyle.success, row=1)
    async def buy(self, interaction, button):
        await interaction.response.send_modal(StockBuyModal())

    @discord.ui.button(label="💸 Продать", style=discord.ButtonStyle.danger, row=1)
    async def sell(self, interaction, button):
        await interaction.response.send_modal(StockSellModal())

    @discord.ui.button(label="📊 График", style=discord.ButtonStyle.secondary, row=1)
    async def chart(self, interaction, button):
        await interaction.response.send_modal(StockChartModal())


class StockBuyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Купить акции")
        self.ticker = discord.ui.TextInput(label="Тикер (GAZP, SBER, ...)", min_length=1, max_length=10)
        self.amount = discord.ui.TextInput(label="Количество", min_length=1, max_length=10)
        self.add_item(self.ticker)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        ticker = self.ticker.value.upper()
        if ticker not in config.STOCKS:
            await interaction.response.send_message("❌ Нет такого тикера.", ephemeral=True)
            return
        try:
            amount = int(self.amount.value)
        except ValueError:
            await interaction.response.send_message("❌ Кол-во — число.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("❌ Кол-во > 0.", ephemeral=True)
            return
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        price = db.get_stock_price(ticker) or config.STOCKS[ticker]["base_price"]
        total = int(price * amount)
        if db.get_balance(interaction.user.id) < total:
            await interaction.response.send_message(f"❌ Нужно **{fmt(total)}** 💵.", ephemeral=True)
            return
        db.add_balance(interaction.user.id, -total)
        db.set_user_stock(interaction.user.id, ticker, db.get_user_stock(interaction.user.id, ticker) + amount)
        db.add_transaction(interaction.user.id, -total, "stock", f"Куплено {amount} {ticker}")
        embed = discord.Embed(
            title="✅ Куплено",
            description=f"**{amount}** {config.STOCKS[ticker]['name']} за **{fmt(total)}** 💵",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)


class StockSellModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Продать акции")
        self.ticker = discord.ui.TextInput(label="Тикер", min_length=1, max_length=10)
        self.amount = discord.ui.TextInput(label="Количество", min_length=1, max_length=10)
        self.add_item(self.ticker)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        ticker = self.ticker.value.upper()
        if ticker not in config.STOCKS:
            await interaction.response.send_message("❌ Нет тикера.", ephemeral=True)
            return
        try:
            amount = int(self.amount.value)
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        have = db.get_user_stock(interaction.user.id, ticker)
        if have < amount or amount <= 0:
            await interaction.response.send_message(f"❌ У тебя только **{have}** шт.", ephemeral=True)
            return
        price = db.get_stock_price(ticker) or config.STOCKS[ticker]["base_price"]
        total = int(price * amount)
        db.set_user_stock(interaction.user.id, ticker, have - amount)
        db.add_balance(interaction.user.id, total)
        db.add_transaction(interaction.user.id, total, "stock", f"Продано {amount} {ticker}")
        embed = discord.Embed(
            title="✅ Продано",
            description=f"**{amount}** {ticker} за **{fmt(total)}** 💵",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)


class StockChartModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="График акции")
        self.ticker = discord.ui.TextInput(label="Тикер", min_length=1, max_length=10)
        self.add_item(self.ticker)

    async def on_submit(self, interaction):
        ticker = self.ticker.value.upper()
        if ticker not in config.STOCKS:
            await interaction.response.send_message("❌ Нет тикера.", ephemeral=True)
            return
        history = db.get_stock_history(ticker, limit=24)
        if len(history) < 2:
            await interaction.response.send_message("📊 Мало данных. Подожди час.", ephemeral=True)
            return
        prices = [p for p, _ in history]
        chart = _make_chart(prices)
        info = config.STOCKS[ticker]
        current = prices[-1]
        diff = ((current - info["base_price"]) / info["base_price"]) * 100
        embed = discord.Embed(
            title=f"📊 {info['name']} ({ticker})",
            description=f"```\n{chart}\n```",
            color=discord.Color.green() if diff >= 0 else discord.Color.red()
        )
        embed.add_field(name="Цена", value=f"**{fmt(current)}** 💵 ({diff:+.1f}%)")
        embed.add_field(name="Мин/Макс", value=f"{fmt(min(prices))} / {fmt(max(prices))}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#                       BTC
# ============================================================

@bot.tree.command(name="btc", description="₿ Биткоин-кошелёк")
async def btc_menu(interaction: discord.Interaction):
    if db.is_in_jail(interaction.user.id):
        await interaction.response.send_message("🚔 **Ты в тюрьме!** BTC недоступен.", ephemeral=True)
        return
    price = db.get_btc_price()
    user_btc = db.get_currency(interaction.user.id, "btc")
    rub_value = user_btc * price

    embed = discord.Embed(
        title="₿ БИТКОИН",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **Курс:** 1 BTC = **{fmt(int(price))}** {config.CURRENCY_EMOJI}\n"
            f"💼 **У тебя:** **{fmt_btc(user_btc)}** BTC\n"
            f"💵 **В рублях:** {fmt(int(rub_value))}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="BTC • МСК")
    await interaction.response.send_message(embed=embed, view=BTCView(interaction.user.id))


class BTCView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💰 Купить", style=discord.ButtonStyle.success, row=0)
    async def buy(self, interaction, button):
        await interaction.response.send_modal(BTCBuyModal())

    @discord.ui.button(label="💸 Продать", style=discord.ButtonStyle.danger, row=0)
    async def sell(self, interaction, button):
        await interaction.response.send_modal(BTCSellModal())

    @discord.ui.button(label="📤 Перевести", style=discord.ButtonStyle.primary, row=0)
    async def transfer(self, interaction, button):
        await interaction.response.send_modal(BTCTransferModal())

    @discord.ui.button(label="📊 Курс", style=discord.ButtonStyle.secondary, row=1)
    async def price(self, interaction, button):
        price = db.get_btc_price()
        history = db.get_btc_history(limit=24)
        chart = _make_chart([p for p, _ in history]) if len(history) >= 2 else "— мало данных —"
        embed = discord.Embed(
            title="📊 Курс BTC",
            description=f"**Текущий:** 1 BTC = **{fmt(int(price))}** {config.CURRENCY_EMOJI}\n```\n{chart}\n```",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🛒 BTC-магазин", style=discord.ButtonStyle.primary, row=1)
    async def shop(self, interaction, button):
        roles = db.get_btc_shop_roles()
        if not roles:
            await interaction.response.send_message("🛒 BTC-магазин пуст.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🛒 BTC-магазин",
            description="━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.green()
        )
        for role_id, price_btc, name in roles:
            role = interaction.guild.get_role(role_id)
            role_mention = role.mention if role else f"`{role_id}`"
            embed.add_field(
                name=f"🎭 {name}",
                value=f"{role_mention} • **{fmt_btc(price_btc)}** BTC",
                inline=False
            )
        await interaction.response.send_message(embed=embed, view=BTCShopView(self.owner_id), ephemeral=True)


class BTCBuyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Купить BTC")
        self.amount = discord.ui.TextInput(label="Сколько рублей потратить", min_length=1, max_length=15)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        try:
            rub = int(self.amount.value)
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if rub <= 0:
            await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
            return
        if db.get_balance(interaction.user.id) < rub:
            await interaction.response.send_message("❌ Недостаточно рублей.", ephemeral=True)
            return
        price = db.get_btc_price()
        btc_amount = rub / price
        db.add_balance(interaction.user.id, -rub)
        db.add_currency(interaction.user.id, "btc", btc_amount)
        db.add_transaction(interaction.user.id, -rub, "exchange", f"Куплено {fmt_btc(btc_amount)} BTC")
        embed = discord.Embed(
            title="✅ Куплено BTC",
            description=f"Потрачено: **{fmt(rub)}** 💵\nПолучено: **{fmt_btc(btc_amount)}** ₿",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)


class BTCSellModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Продать BTC")
        self.amount = discord.ui.TextInput(label="Сколько BTC продать", min_length=1, max_length=20)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        try:
            btc = float(self.amount.value.replace(",", "."))
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if btc <= 0:
            await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
            return
        have = db.get_currency(interaction.user.id, "btc")
        if btc > have + 1e-9:
            await interaction.response.send_message(f"❌ У тебя только **{fmt_btc(have)}** BTC.", ephemeral=True)
            return
        price = db.get_btc_price()
        rub = int(btc * price)
        db.add_currency(interaction.user.id, "btc", -btc)
        db.add_balance(interaction.user.id, rub)
        db.add_transaction(interaction.user.id, rub, "exchange", f"Продано {fmt_btc(btc)} BTC")
        embed = discord.Embed(
            title="✅ Продано BTC",
            description=f"Продано: **{fmt_btc(btc)}** ₿\nПолучено: **{fmt(rub)}** 💵",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)


class BTCTransferModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Перевести BTC")
        self.user_id = discord.ui.TextInput(label="ID получателя (или @mention)", min_length=1, max_length=30)
        self.amount = discord.ui.TextInput(label="Сколько BTC", min_length=1, max_length=20)
        self.add_item(self.user_id)
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        if db.is_in_jail(interaction.user.id):
            await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
            return
        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return
        target_str = self.user_id.value.strip().replace("<@", "").replace(">", "").replace("!", "")
        try:
            target_id = int(target_str)
        except ValueError:
            await interaction.response.send_message("❌ Укажи ID или @mention.", ephemeral=True)
            return
        if target_id == interaction.user.id:
            await interaction.response.send_message("❌ Себе нельзя.", ephemeral=True)
            return
        try:
            btc = float(self.amount.value.replace(",", "."))
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return
        if btc <= 0:
            await interaction.response.send_message("❌ Сумма > 0.", ephemeral=True)
            return
        have = db.get_currency(interaction.user.id, "btc")
        if btc > have + 1e-9:
            await interaction.response.send_message(f"❌ У тебя только **{fmt_btc(have)}** BTC.", ephemeral=True)
            return
        db.add_currency(interaction.user.id, "btc", -btc)
        db.add_currency(target_id, "btc", btc)
        db.add_transaction(interaction.user.id, 0, "transfer", f"BTC → <@{target_id}>: {fmt_btc(btc)}")
        db.add_transaction(target_id, 0, "transfer", f"BTC ← {interaction.user.name}: {fmt_btc(btc)}")
        embed = discord.Embed(
            title="📤 BTC переведено",
            description=f"Получатель: <@{target_id}>\nСумма: **{fmt_btc(btc)}** ₿",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
        try:
            user = await bot.fetch_user(target_id)
            await user.send(f"📥 **Ты получил {fmt_btc(btc)} BTC от {interaction.user.name}**")
        except Exception:
            pass


class BTCShopView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💳 Купить роль", style=discord.ButtonStyle.success)
    async def buy_role(self, interaction, button):
        roles = db.get_btc_shop_roles()
        if not roles:
            await interaction.response.send_message("❌ Магазин пуст.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=name, value=str(role_id), description=f"{fmt_btc(price_btc)} BTC")
            for role_id, price_btc, name in roles[:25]
        ]
        select = discord.ui.Select(placeholder="Выбери роль", options=options)
        view = discord.ui.View(timeout=60)

        async def callback(inter):
            role_id = int(select.values[0])
            shop_role = db.get_btc_shop_role(role_id)
            if not shop_role:
                await inter.response.send_message("❌ Не найдено.", ephemeral=True)
                return
            _, price_btc, name = shop_role
            have = db.get_currency(inter.user.id, "btc")
            if price_btc > have + 1e-9:
                await inter.response.send_message(f"❌ Нужно **{fmt_btc(price_btc)}** BTC, у тебя **{fmt_btc(have)}**.", ephemeral=True)
                return
            role = inter.guild.get_role(role_id)
            if not role:
                await inter.response.send_message("❌ Роль удалена.", ephemeral=True)
                return
            bot_member = inter.guild.get_member(bot.user.id)
            if role >= bot_member.top_role:
                await inter.response.send_message("❌ Роль выше моей.", ephemeral=True)
                return
            try:
                await inter.user.add_roles(role, reason="Покупка за BTC")
            except discord.Forbidden:
                await inter.response.send_message("❌ Нет прав.", ephemeral=True)
                return
            db.add_currency(inter.user.id, "btc", -price_btc)
            db.add_transaction(inter.user.id, 0, "shop", f"Куплено за {fmt_btc(price_btc)} BTC: {name}")
            await inter.response.send_message(f"✅ Куплено {role.mention} за **{fmt_btc(price_btc)}** BTC")

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message("Выбери роль:", view=view, ephemeral=True)


# ---------- BTC-админ ----------

@bot.tree.command(name="btc_add_role", description="₿ [АДМИН] Роль в BTC-магазин")
@app_commands.describe(role="Роль", price_btc="Цена в BTC", name="Название")
@app_commands.default_permissions(administrator=True)
async def btc_add_role(interaction: discord.Interaction, role: discord.Role, price_btc: float, name: str):
    if price_btc <= 0:
        await interaction.response.send_message("❌ Цена > 0.", ephemeral=True)
        return
    db.add_btc_shop_role(role.id, price_btc, name)
    await interaction.response.send_message(f"✅ {role.mention} за **{fmt_btc(price_btc)}** BTC", ephemeral=True)


@bot.tree.command(name="btc_remove_role", description="₿ [АДМИН] Убрать из BTC-магазина")
@app_commands.describe(role="Роль")
@app_commands.default_permissions(administrator=True)
async def btc_remove_role(interaction: discord.Interaction, role: discord.Role):
    db.remove_btc_shop_role(role.id)
    await interaction.response.send_message(f"✅ {role.mention} убрана.", ephemeral=True)


@bot.tree.command(name="btc_set_price", description="₿ [АДМИН] Установить курс BTC")
@app_commands.describe(price="Цена в рублях за 1 BTC")
@app_commands.default_permissions(administrator=True)
async def btc_set_price(interaction: discord.Interaction, price: float):
    if price <= 0:
        await interaction.response.send_message("❌ Цена > 0.", ephemeral=True)
        return
    db.set_btc_price(price)
    await interaction.response.send_message(f"₿ Курс BTC: **{fmt(int(price))}** 💵", ephemeral=True)
    log_admin(interaction.user, "rates", "Курс BTC", None, str(price))
    
    # ============================================================
#                    ВЫДАЧА ДОСТУПА
# ============================================================

@bot.tree.command(name="выдать_доступ", description="🔑 Выдать роль Админ или Dev")
@app_commands.describe(
    user="Кому выдать",
    role="Какую роль выдать"
)
@app_commands.choices(role=[
    app_commands.Choice(name="👑 Админ", value="admin"),
    app_commands.Choice(name="💎 Dev", value="dev"),
])
async def give_access(interaction: discord.Interaction, user: discord.Member, role: app_commands.Choice[str]):
    # Проверка: только OWNER_ID
    if interaction.user.id != config.OWNER_ID:
        await interaction.response.send_message(
            "❌ Только владелец может использовать эту команду.",
            ephemeral=True
        )
        return

    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return

    # Выбор роли
    if role.value == "admin":
        role_id = config.ADMIN_ROLE_ID
        role_name = "👑 Админ"
    else:
        role_id = config.DEV_ROLE_ID
        role_name = "💎 Dev"

    target_role = interaction.guild.get_role(role_id)
    if not target_role:
        await interaction.response.send_message(
            f"❌ Роль `{role_name}` не найдена (ID: `{role_id}`).",
            ephemeral=True
        )
        return

    # Проверка иерархии: роль бота должна быть выше
    bot_member = interaction.guild.get_member(bot.user.id)
    if target_role >= bot_member.top_role:
        await interaction.response.send_message(
            f"❌ Роль `{role_name}` **выше** моей. Подними мою роль в настройках сервера.",
            ephemeral=True
        )
        return

    # Проверка: есть ли уже эта роль
    if target_role in user.roles:
        await interaction.response.send_message(
            f"❌ У {user.mention} уже есть роль **{role_name}**.",
            ephemeral=True
        )
        return

    # Выдаём
    try:
        await user.add_roles(target_role, reason=f"Выдача доступа от {interaction.user.name}")
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ У меня нет прав выдать эту роль.",
            ephemeral=True
        )
        return
    db.add_bot_admin(user.id, role.value)
    
    embed = discord.Embed(
        title="🔑 Доступ выдан",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Кому:** {user.mention}\n"
            f"🎭 **Роль:** {target_role.mention}\n"
            f"👑 **Выдал:** {interaction.user.mention}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="Доступ выдан • МСК")
    await interaction.response.send_message(embed=embed)
    log_admin(interaction.user, "people", "Выдать доступ", user.id, role_name)

    # ЛС пользователю
    try:
        await user.send(
            f"🔑 **Тебе выдали доступ**\n"
            f"Роль: **{role_name}**\n"
            f"Выдал: {actor_label(interaction.user)}"
        )
    except Exception:
        pass
        
@bot.tree.command(name="транзакции", description="📊 Выписка по счету за 2 дня")
@app_commands.describe(user="Чей счет (по умолчанию — свой)")
async def transactions_2d(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    txs = db.get_transactions_period(target.id, hours=48)
    
    embed = discord.Embed(
        title=f"📜 ВЫПИСКА ПО СЧЕТУ",
        description=(
            f"👤 **Клиент:** {target.mention}\n"
            f"📅 **Период:** последние 48 часов\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.blue()
    )

    if not txs:
        embed.description += "\n_Операций за этот период не найдено._"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    lines = []
    total_plus = 0
    total_minus = 0

    # Собираем строки (показываем последние 20 операций)
    for amount, ttype, desc, created in txs[:20]:
        try:
            date = db.parse_dt(created).strftime("%d.%m %H:%M")
        except Exception:
            date = created[5:16].replace("T", " ")

        sign = "🟢 +" if amount > 0 else "🔴 "
        desc_text = f" — {desc}" if desc else ""
        
        lines.append(f"`{date}` {sign}**{fmt(amount)}**{desc_text}")
        
        if amount > 0:
            total_plus += amount
        else:
            total_minus += amount

    # Если транзакций больше 20, пишем сколько скрыто
    if len(txs) > 20:
        lines.append(f"... и ещё **{len(txs) - 20}** операций")

    embed.add_field(name="📋 Операции", value="\n".join(lines), inline=False)
    
    # Итоги
    embed.add_field(name="📥 Приход", value=f"**+{fmt(total_plus)}** {config.CURRENCY_EMOJI}", inline=True)
    embed.add_field(name="📤 Расход", value=f"**{fmt(total_minus)}** {config.CURRENCY_EMOJI}", inline=True)
    embed.add_field(name="💼 Итог", value=f"**{fmt(total_plus + total_minus)}** {config.CURRENCY_EMOJI}", inline=False)
    
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text=f"Всего операций: {len(txs)} • МСК")

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
# ============================================================
#                       HELP
# ============================================================

@bot.tree.command(name="help", description="📖 Все команды")
async def help_cmd(interaction: discord.Interaction):
    is_admin = interaction.user.guild_permissions.administrator
    is_issuer = any(r.id in config.ISSUER_ROLE_IDS for r in interaction.user.roles)

    embed = discord.Embed(
        title="📖 БАНК — КОМАНДЫ",
        description=f"Валюта: {config.CURRENCY_EMOJI} {config.CURRENCY_NAME} • МСК",
        color=discord.Color.green()
    )

    embed.add_field(name="🏦 Главное меню", value="`/банк` — все действия кнопками", inline=False)

    embed.add_field(name="👤 Для всех", value=(
        "`/balance` `/кошелёк` — баланс\n"
        "`/transfer` `/transfer_usd` `/transfer_eur` — переводы\n"
        "`/топ` `/история` — рейтинг и транзакции\n"
        "`/обменять` `/валюты` — валюты\n"
        "`/бизнес` `/акции` `/btc` — бизнесы, акции, BTC\n"
        "`/украсть` `/кредит` — кража и кредиты\n"
        "`/казн` — государственная казна"
        "`/аукцион_роль` — аукцион на роль\n"
        "`/аукцион_роли_список` — список аукционов ролей\n"
    ), inline=False)

    if is_issuer:
        embed.add_field(name="🏦 Банкиры", value="`/выдать`", inline=False)

    if is_admin:
        embed.add_field(name="🛠 Админ", value=(
            "🛠 **/админ_панель** — управление людьми по кнопкам\n"
            "`/накрутить` `/снять_деньги` `/конфисковать`\n"
            "`/налог` `/налог_все` `/штраф`\n"
            "`/обыск` `/розыск`\n"
            "`/арестовать` `/разморозить` `/амнистия` `/аннулировать`\n"
            "`/репрессия` `/зп` `/премия`\n"
            "`/казна_панель` `/аукцион выставить`\n"
            "`/бизнес_налог` `/бизнес_налоги`\n"
            "`/конфисковать_бизнес` `/выдать_бизнес`\n"
            "`/btc_add_role` `/btc_remove_role` `/btc_set_price`"
        ), inline=False)

    embed.set_footer(text="Банк • МСК | По вопросам и багам: @rui")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    
# ============================================================
#                    АДМИН-ПАНЕЛЬ
# ============================================================

def _is_staff(member: discord.Member) -> bool:
    if member.id == config.OWNER_ID:
        return True
    if member.guild_permissions.administrator:
        return True
    role_ids = {r.id for r in member.roles}
    return config.ADMIN_ROLE_ID in role_ids or config.DEV_ROLE_ID in role_ids
    
    
def _is_dev_or_owner(member: discord.Member) -> bool:
    if member.id == config.OWNER_ID:
        return True
    if member.guild_permissions.administrator:
        return True
    return config.DEV_ROLE_ID in {r.id for r in member.roles}


# ---------- Главное меню ----------

def make_panel_main() -> discord.Embed:
    return discord.Embed(
        title="🛠 АДМИН-ПАНЕЛЬ",
        description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери раздел:",
        color=discord.Color.dark_red()
    ).set_footer(text="Банк • панель управления | По вопросам: @rui")


class AdminMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True
    
    @discord.ui.button(label="🕵️ Чёрный ящик", style=discord.ButtonStyle.danger, row=1)
    async def blackbox(self, interaction, button):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message("❌ Только для Dev/Owner.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🕵️ Чёрный ящик",
            description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери категорию:",
            color=discord.Color.dark_gray()
        )
        await interaction.response.edit_message(embed=embed, view=BlackBoxCategoryView())


    @discord.ui.button(label="👥 Люди", style=discord.ButtonStyle.primary, row=0)
    async def people(self, interaction, button):
        await interaction.response.send_modal(FindUserModal())

    @discord.ui.button(label="📜 Лог", style=discord.ButtonStyle.primary, row=0)
    async def log(self, interaction, button):
        await interaction.response.send_modal(LogFilterModal())

    @discord.ui.button(label="🧰 Утилиты", style=discord.ButtonStyle.success, row=0)
    async def utils(self, interaction, button):
        embed = discord.Embed(
            title="🧰 Утилиты",
            description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери действие:",
            color=discord.Color.dark_red()
        )
        await interaction.response.edit_message(embed=embed, view=UtilitiesView())

    @discord.ui.button(label="🛠 Сервис", style=discord.ButtonStyle.danger, row=1)
    async def service(self, interaction, button):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message(
                "❌ Раздел «Сервис» — только для Dev/Owner.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🛠 Сервис",
            description="━━━━━━━━━━━━━━━━━━━━━━\nТолько Dev/Owner:",
            color=discord.Color.dark_red()
        )
        await interaction.response.edit_message(embed=embed, view=ServiceView())

# ---------- Поиск юзера ----------

class FindUserModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Найти юзера")
        self.user_input = discord.ui.TextInput(
            label="ID юзера (или @mention)", max_length=30
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction):
        raw = self.user_input.value.strip().replace("<@", "").replace(">", "").replace("!", "")
        try:
            uid = int(raw)
        except ValueError:
            await interaction.response.send_message("❌ ID — число.", ephemeral=True)
            return

        member = interaction.guild.get_member(uid)
        user = member or await bot.fetch_user(uid)
        if not user:
            await interaction.response.send_message("❌ Юзер не найден.", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=make_user_card(uid, user, member),
            view=UserCardView(uid),
            ephemeral=True
        )


# ---------- Карточка юзера ----------

def make_user_card(uid: int, user, member) -> discord.Embed:
    bal = db.get_balance(uid)
    frozen = db.is_frozen(uid)
    reason = db.get_freeze_reason(uid)
    jail = db.is_in_jail(uid)
    biz = db.get_businesses(uid)
    tag = get_user_tag(member) if member else ""

    embed = discord.Embed(
        title=f"👤 {user.name}",
        color=discord.Color.red() if frozen else discord.Color.green()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="💼 Баланс", value=f"**{fmt(bal)}** {config.CURRENCY_EMOJI}", inline=True)
    embed.add_field(name="🏭 Бизнесы", value=f"**{len(biz)}**", inline=True)
    embed.add_field(name="🎭 Роль", value=tag or "—", inline=True)

    status = "✅ Активен"
    if frozen:
        status = f"🚫 Заморожен — {reason or '—'}"
    elif jail:
        status = "🚔 В тюрьме"
    embed.add_field(name="📌 Статус", value=status, inline=False)
    embed.set_footer(text=f"ID: {uid}")
    return embed


class UserCardView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=600)
        self.uid = uid

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💼 Баланс", style=discord.ButtonStyle.success, row=0)
    async def balance(self, interaction, button):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message(
                "❌ Изменение баланса — только для Dev/Owner.",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(BalanceActionModal(self.uid))

    @discord.ui.button(label="🎭 Роли", style=discord.ButtonStyle.primary, row=0)
    async def roles(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎭 Управление ролями",
                description=f"<@{self.uid}> — выбери действие:",
                color=discord.Color.blue()
            ),
            view=RoleActionView(self.uid)
        )

    @discord.ui.button(label="🏭 Бизнесы", style=discord.ButtonStyle.primary, row=0)
    async def businesses(self, interaction, button):
        await interaction.response.edit_message(
            embed=make_biz_list_embed(self.uid),
            view=BizActionView(self.uid)
        )

    @discord.ui.button(label="🚫 Статус", style=discord.ButtonStyle.danger, row=0)
    async def status(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🚫 Управление статусом",
                description=f"<@{self.uid}> — выбери действие:",
                color=discord.Color.red()
            ),
            view=StatusActionView(self.uid)
        )

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=make_panel_main(), view=AdminMainView())


# ---------- Баланс ----------

class BalanceActionModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Изменить баланс")
        self.uid = uid
        self.amount_input = discord.ui.TextInput(
            label="Сумма (можно с минусом)", max_length=20
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Число.", ephemeral=True)
            return
        new = db.add_balance(self.uid, amount)
        db.add_transaction(self.uid, amount, "admin", f"Правка баланса ({actor_label(interaction.user)})")
        await interaction.response.send_message(
            f"✅ <@{self.uid}>: **{'+' if amount >= 0 else ''}{fmt(amount)}** → баланс **{fmt(new)}**",
            ephemeral=True
        )


# ---------- Роли ----------

class RoleActionView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=300)
        self.uid = uid

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction, role_id, role_name):
        member = interaction.guild.get_member(self.uid)
        if not member:
            await interaction.response.send_message("❌ Юзер не на сервере.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("❌ Роль не найдена.", ephemeral=True)
            return
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"Снятие от {interaction.user.name}")
                msg = f"🔒 Снята **{role_name}** у {member.mention}"
            else:
                await member.add_roles(role, reason=f"Выдача от {interaction.user.name}")
                msg = f"✅ Выдана **{role_name}** {member.mention}"
        except discord.Forbidden:
            await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
            return
        if role in member.roles:
            db.remove_bot_admin(self.uid)
        else:
            db.add_bot_admin(self.uid, "admin" if role_id == config.ADMIN_ROLE_ID else "dev")
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="👑 Админ", style=discord.ButtonStyle.primary)
    async def admin(self, interaction, button):
        await self._toggle(interaction, config.ADMIN_ROLE_ID, "👑 Админ")

    @discord.ui.button(label="💎 Dev", style=discord.ButtonStyle.primary)
    async def dev(self, interaction, button):
        await self._toggle(interaction, config.DEV_ROLE_ID, "💎 Dev")

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        member = interaction.guild.get_member(self.uid)
        user = member or await bot.fetch_user(self.uid)
        await interaction.response.edit_message(
            embed=make_user_card(self.uid, user, member),
            view=UserCardView(self.uid)
        )


# ---------- Бизнесы ----------

def make_biz_list_embed(uid: int) -> discord.Embed:
    rows = db.get_user_businesses_full(uid)
    embed = discord.Embed(
        title=f"🏭 Бизнесы <@{uid}>",
        color=discord.Color.green()
    )
    if not rows:
        embed.description = "Нет бизнесов."
        return embed
    lines = []
    for biz_id, biz_type, level, _ in rows:
        info = config.BUSINESS_TYPES.get(biz_type, {})
        lines.append(f"`#{biz_id}` — **{info.get('name', biz_type)}** (ур. {level})")
    embed.description = "━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines)
    return embed


class BizActionView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=300)
        self.uid = uid

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="➕ Выдать", style=discord.ButtonStyle.success)
    async def give(self, interaction, button):
        await interaction.response.send_modal(GiveBizModal(self.uid))

    @discord.ui.button(label="➖ Забрать", style=discord.ButtonStyle.danger)
    async def take(self, interaction, button):
        await interaction.response.send_modal(TakeBizModal(self.uid))

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction, button):
        await interaction.response.edit_message(
            embed=make_biz_list_embed(self.uid),
            view=self
        )

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        member = interaction.guild.get_member(self.uid)
        user = member or await bot.fetch_user(self.uid)
        await interaction.response.edit_message(
            embed=make_user_card(self.uid, user, member),
            view=UserCardView(self.uid)
        )


class GiveBizModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Выдать бизнес")
        self.uid = uid
        self.biz_input = discord.ui.TextInput(
            label="Тип (kiosk/cafe/shop/factory/bank/oil)", max_length=20
        )
        self.add_item(self.biz_input)

    async def on_submit(self, interaction):
        biz_type = self.biz_input.value.strip().lower()
        if biz_type not in config.BUSINESS_TYPES:
            await interaction.response.send_message("❌ Нет такого типа.", ephemeral=True)
            return
        db.buy_business(self.uid, biz_type)
        info = config.BUSINESS_TYPES[biz_type]
        db.add_transaction(self.uid, 0, "admin", f"Выдан {info['name']} ({actor_label(interaction.user)})")
        await interaction.response.send_message(
            f"✅ <@{self.uid}> выдан **{info['name']}**",
            ephemeral=True
        )


class TakeBizModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Забрать бизнес")
        self.uid = uid
        self.biz_id_input = discord.ui.TextInput(label="ID бизнеса (см. список)", max_length=15)
        self.add_item(self.biz_id_input)

    async def on_submit(self, interaction):
        try:
            biz_id = int(self.biz_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID — число.", ephemeral=True)
            return
        biz = db.get_user_business(biz_id)
        if not biz or biz[0] != self.uid:
            await interaction.response.send_message("❌ Бизнес не найден у этого юзера.", ephemeral=True)
            return
        info = config.BUSINESS_TYPES.get(biz[1], {})
        db.delete_business(biz_id)
        db.add_transaction(self.uid, 0, "admin", f"Изъят {info.get('name', biz[1])} ({actor_label(interaction.user)})")
        await interaction.response.send_message(
            f"➖ У <@{self.uid}> изъят **{info.get('name', biz[1])}**",
            ephemeral=True
        )


# ---------- Статус ----------

class StatusActionView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=300)
        self.uid = uid

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🚫 Заморозить", style=discord.ButtonStyle.danger)
    async def freeze(self, interaction, button):
        await interaction.response.send_modal(FreezeModal(self.uid))

    @discord.ui.button(label="✅ Разморозить", style=discord.ButtonStyle.success)
    async def unfreeze(self, interaction, button):
        if not db.is_frozen(self.uid):
            await interaction.response.send_message("❌ Не заморожен.", ephemeral=True)
            return
        db.set_frozen(self.uid, False, None)
        await interaction.response.send_message(f"✅ <@{self.uid}> разморожен.", ephemeral=True)

    @discord.ui.button(label="🚔 В тюрьму", style=discord.ButtonStyle.danger)
    async def jail(self, interaction, button):
        await interaction.response.send_modal(JailModal(self.uid))

    @discord.ui.button(label="🔓 Освободить", style=discord.ButtonStyle.success)
    async def release(self, interaction, button):
        if not db.is_in_jail(self.uid):
            await interaction.response.send_message("❌ Не в тюрьме.", ephemeral=True)
            return
        db.release_from_jail(self.uid)
        await interaction.response.send_message(f"✅ <@{self.uid}> освобождён.", ephemeral=True)

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        member = interaction.guild.get_member(self.uid)
        user = member or await bot.fetch_user(self.uid)
        await interaction.response.edit_message(
            embed=make_user_card(self.uid, user, member),
            view=UserCardView(self.uid)
        )


class FreezeModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Заморозить счёт")
        self.uid = uid
        self.reason = discord.ui.TextInput(label="Причина", max_length=200)
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        db.set_frozen(self.uid, True, self.reason.value)
        db.add_transaction(self.uid, 0, "admin", f"Заморозка: {self.reason.value}")
        await interaction.response.send_message(
            f"🚫 <@{self.uid}> заморожен: {self.reason.value}",
            ephemeral=True
        )


class JailModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Отправить в тюрьму")
        self.uid = uid
        self.minutes = discord.ui.TextInput(label="Минут", default="60", max_length=6)
        self.reason = discord.ui.TextInput(label="Причина", max_length=200)
        self.add_item(self.minutes)
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        try:
            minutes = int(self.minutes.value)
        except ValueError:
            await interaction.response.send_message("❌ Минуты — число.", ephemeral=True)
            return
        db.jail_user(self.uid, minutes, self.reason.value)
        db.add_transaction(self.uid, 0, "admin", f"Тюрьма на {minutes} мин: {self.reason.value}")
        await interaction.response.send_message(
            f"🚔 <@{self.uid}> в тюрьме на {minutes} мин: {self.reason.value}",
            ephemeral=True
        )


# ---------- Команда ----------


    
    
class BlackBoxCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    async def interaction_check(self, interaction):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message("❌ Только Dev/Owner.", ephemeral=True)
            return False
        return True

    async def _show(self, interaction, category):
        await interaction.response.send_modal(BlackBoxPeriodModal(category))

    @discord.ui.button(label="💰 Экономика", style=discord.ButtonStyle.success)
    async def economy(self, i, b): await self._show(i, "economy")

    @discord.ui.button(label="👥 Люди", style=discord.ButtonStyle.primary)
    async def people(self, i, b): await self._show(i, "people")

    @discord.ui.button(label="🏭 Бизнесы", style=discord.ButtonStyle.primary)
    async def biz(self, i, b): await self._show(i, "biz")

    @discord.ui.button(label="💱 Курсы", style=discord.ButtonStyle.primary)
    async def rates(self, i, b): await self._show(i, "rates")

    @discord.ui.button(label="🧰 Прочее", style=discord.ButtonStyle.secondary)
    async def other(self, i, b): await self._show(i, "panel")

    @discord.ui.button(label="📋 Всё", style=discord.ButtonStyle.danger)
    async def allcat(self, i, b): await self._show(i, None)


class BlackBoxPeriodModal(discord.ui.Modal):
    def __init__(self, category):
        titles = {
            "economy": "Чёрный ящик — Экономика",
            "people":  "Чёрный ящик — Люди",
            "biz":     "Чёрный ящик — Бизнесы",
            "rates":   "Чёрный ящик — Курсы",
            "panel":   "Чёрный ящик — Прочее",
            None:      "Чёрный ящик — Всё",
        }
        super().__init__(title=titles.get(category, "Чёрный ящик"))
        self.category = category
        self.hours_input = discord.ui.TextInput(label="За сколько часов (1-720)", default="48", max_length=4)
        self.limit_input = discord.ui.TextInput(label="Количество (5-50)", default="25", max_length=2)
        self.add_item(self.hours_input)
        self.add_item(self.limit_input)

    async def on_submit(self, interaction):
        try:
            hours = max(1, min(int(self.hours_input.value or "48"), 720))
            limit = max(5, min(int(self.limit_input.value or "25"), 50))
        except ValueError:
            await interaction.response.send_message("❌ Неверные числа.", ephemeral=True)
            return

        logs = db.get_admin_logs(category=self.category, hours=hours, limit=limit)
        if not logs:
            await interaction.response.send_message("🕵️ Пусто.", ephemeral=True)
            return

        cat_emoji = {"economy": "💰", "people": "👥", "biz": "🏭", "rates": "💱", "panel": "🧰", None: "📋"}
        lines = []
        for actor, cat, action, target, details, created in logs:
            try:
                dt = db.parse_dt(created)
                date = dt.strftime("%d.%m %H:%M")
            except Exception:
                date = created[5:16].replace("T", " ")
            e = cat_emoji.get(cat, "•")
            target_str = f" → <@{target}>" if target else ""
            details_str = f" • {details}" if details else ""
            lines.append(f"{e} `{date}` <@{actor}> **{action}**{target_str}{details_str}")

        embed = discord.Embed(
            title="🕵️ ЧЁРНЫЙ ЯЩИК",
            description="━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) + "\n━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.dark_gray()
        )
        embed.set_footer(text=f"Категория: {self.category or 'всё'} • период: до {hours} ч • записей: {len(logs)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        
        
# ============================================================
#                  АУКЦИОН РОЛЕЙ
# ============================================================

ROLE_AUCTION_MIN_STEP = 1000


def make_role_auction_embed(aid: int, guild: discord.Guild) -> discord.Embed:
    auc = db.get_role_auction(aid)
    if not auc or not auc[9]:
        return discord.Embed(title="🎭 Аукцион закрыт", color=discord.Color.red())

    (_, role_id, seller_id, start_price, current_bid,
     current_bidder, ch_id, msg_id, ends_at, active) = auc

    role = guild.get_role(role_id) if guild else None
    role_str = role.mention if role else f"`{role_id}`"

    top = db.get_top_role_auction_bids(aid, limit=2)
    if top:
        medals = ["🥇", "🥈"]
        lines = []
        for i, (uid, amt) in enumerate(top):
            prefix = medals[i] if i < len(medals) else f"**{i+1}.**"
            lines.append(f"{prefix} <@{uid}> — **{fmt(amt)}** {config.CURRENCY_EMOJI}")
        bids_block = "\n".join(lines)
    else:
        bids_block = "_пока нет ставок_"

    embed = discord.Embed(
        title=f"🎭 АУКЦИОН РОЛИ #{aid}",
        description=(
            f"**Роль:** {role_str}\n"
            f"**Старт:** **{fmt(start_price)}** {config.CURRENCY_EMOJI}\n"
            f"**Шаг:** **{fmt(ROLE_AUCTION_MIN_STEP)}** {config.CURRENCY_EMOJI}\n"
            f"⏰ До конца: <t:{int(db.parse_dt(ends_at).timestamp())}:R>\n\n"
            f"**Топ ставок:**\n{bids_block}"
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Аукцион #{aid}")
    return embed


class RoleAuctionBidModal(discord.ui.Modal):
    def __init__(self, aid: int, min_bid: int):
        super().__init__(title="Ставка на роль")
        self.aid = aid
        self.min_bid = min_bid
        self.bid_input = discord.ui.TextInput(
            label=f"Минимум: {min_bid}", min_length=1, max_length=15
        )
        self.add_item(self.bid_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.bid_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Не число.", ephemeral=True)
            return

        if amount < self.min_bid:
            await interaction.response.send_message(
                f"❌ Минимум: **{fmt(self.min_bid)}** {config.CURRENCY_EMOJI}",
                ephemeral=True
            )
            return

        if db.is_frozen(interaction.user.id):
            await interaction.response.send_message("🚫 Счёт заблокирован.", ephemeral=True)
            return

        if db.is_in_jail(interaction.user.id):
            await interaction.response.send_message("🚔 Ты в тюрьме.", ephemeral=True)
            return

        if db.get_balance(interaction.user.id) < amount:
            await interaction.response.send_message("❌ Недостаточно денег.", ephemeral=True)
            return

        auc = db.get_role_auction(self.aid)
        if not auc or not auc[9]:
            await interaction.response.send_message("❌ Аукцион закрыт.", ephemeral=True)
            return

        # Вернуть предыдущую ставку
        if auc[5]:
            db.add_balance(auc[5], auc[4])

        # Списать у нового
        db.add_balance(interaction.user.id, -amount)
        db.update_role_auction_bid(self.aid, interaction.user.id, amount)
        db.add_role_auction_bid(self.aid, interaction.user.id, amount)
        db.add_auction_history("role", self.aid, interaction.user.id, amount, "bid")
        if auc[5]:
            db.add_auction_history("role", self.aid, auc[5], auc[4], "refund",
                                   f"Возврат при перебитии от <@{interaction.user.id}>")
        log_admin(interaction.user, "panel", "Аукцион роли: ставка", self.aid, str(amount))

        # Обновить сообщение с новым топ-2
        auc_full = db.get_role_auction(self.aid)
        if auc_full and auc_full[7]:
            try:
                channel = interaction.client.get_channel(auc_full[6])
                msg = await channel.fetch_message(auc_full[7])
                await msg.edit(
                    embed=make_role_auction_embed(self.aid, channel.guild),
                    view=RoleAuctionView(self.aid)
                )
            except Exception as e:
                print(f"⚠️ не обновил сообщение аукциона: {e}")

        await interaction.response.send_message(
            f"✅ Ставка **{fmt(amount)}** {config.CURRENCY_EMOJI} принята!",
            ephemeral=True
        )


class RoleAuctionView(discord.ui.View):
    def __init__(self, aid: int):
        super().__init__(timeout=None)
        self.aid = aid

    @discord.ui.button(label="💰 Ставка", style=discord.ButtonStyle.success,
                       custom_id="role_auction_bid")
    async def bid(self, interaction, button):
        auc = db.get_role_auction(self.aid)
        if not auc or not auc[9]:
            await interaction.response.send_message("❌ Аукцион закрыт.", ephemeral=True)
            return
        if interaction.user.id == auc[2]:
            await interaction.response.send_message("❌ Нельзя ставить на свой лот.", ephemeral=True)
            return
        min_bid = auc[4] + ROLE_AUCTION_MIN_STEP if auc[4] else auc[3]
        await interaction.response.send_modal(RoleAuctionBidModal(self.aid, min_bid))


@bot.tree.command(name="аукцион_роль", description="🎭 [АДМИН] Аукцион на роль")
@app_commands.describe(role="Роль", start_price="Стартовая цена", minutes="Минут (5-1440)")
@app_commands.default_permissions(administrator=True)
async def role_auction(interaction: discord.Interaction, role: discord.Role,
                       start_price: int, minutes: int = 10):
    if start_price <= 0:
        await interaction.response.send_message("❌ Старт > 0.", ephemeral=True)
        return
    if minutes < 5 or minutes > 1440:
        await interaction.response.send_message("❌ Минуты: 5-1440.", ephemeral=True)
        return

    bot_member = interaction.guild.get_member(bot.user.id)
    if role >= bot_member.top_role:
        await interaction.response.send_message("❌ Роль выше моей.", ephemeral=True)
        return

    ends_at = (now_msk() + timedelta(minutes=minutes)).isoformat()
    aid = db.create_role_auction(role.id, interaction.user.id, start_price,
                                 interaction.channel_id, ends_at)

    msg = await interaction.channel.send(
        embed=make_role_auction_embed(aid, interaction.guild),
        view=RoleAuctionView(aid)
    )
    db.update_role_auction_message(aid, msg.id)
    db.add_auction_history("role", aid, interaction.user.id, start_price,
                           "start", f"Роль: {role.name}")
    await interaction.response.send_message(f"✅ Аукцион #{aid} запущен.", ephemeral=True)
    log_admin(interaction.user, "panel", "Аукцион роли: старт", None,
              f"{role.name} от {start_price}")


@bot.tree.command(name="аукцион_роли_список", description="🎭 Активные аукционы ролей")
async def role_auction_list(interaction: discord.Interaction):
    rows = db.get_active_role_auctions()
    if not rows:
        await interaction.response.send_message("🎭 Нет аукционов.", ephemeral=True)
        return
    embed = discord.Embed(title="🎭 Активные аукционы ролей", color=discord.Color.gold())
    for a in rows:
        aid, role_id, seller_id, start_price, current_bid, current_bidder, ch_id, msg_id, ends_at = a
        role = interaction.guild.get_role(role_id)
        top = db.get_top_role_auction_bids(aid, limit=2)
        if top:
            medals = ["🥇", "🥈"]
            lines = [f"{medals[i] if i < len(medals) else '•'} <@{uid}> — **{fmt(amt)}**"
                     for i, (uid, amt) in enumerate(top)]
            bids_block = "\n".join(lines)
        else:
            bids_block = "_нет ставок_"
        embed.add_field(
            name=f"#{aid}: {role.name if role else role_id}",
            value=f"Старт: **{fmt(start_price)}**\n{bids_block}\n{time_left(ends_at)}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)


async def finish_role_auction(aid: int):
    auc = db.get_role_auction(aid)
    if not auc or not auc[9]:
        return
    (_, role_id, seller_id, start_price, current_bid,
     current_bidder, ch_id, msg_id, ends_at, active) = auc

    channel = bot.get_channel(ch_id)
    guild = channel.guild if channel else None
    role = guild.get_role(role_id) if guild else None

    if not role or not guild:
        db.close_role_auction(aid)
        return

    if current_bidder and current_bid:
        # Деньги победителя → продавцу
        db.add_balance(seller_id, current_bid)
        db.add_auction_history("biz", aid, current_bidder, current_bid, "win",
                               f"Победитель, деньги → продавцу <@{seller_id}>")
        db.add_auction_history("role", aid, current_bidder, current_bid, "win",
                               f"Победитель, деньги → продавцу <@{seller_id}>")

        # Снять роль со старого владельца (продавца)
        seller_member = guild.get_member(seller_id)
        if seller_member and role in seller_member.roles:
            try:
                await seller_member.remove_roles(role, reason=f"Аукцион роли #{aid}")
            except discord.Forbidden:
                pass

        # Выдать роль победителю
        winner = guild.get_member(current_bidder)
        if winner:
            try:
                await winner.add_roles(role, reason=f"Аукцион роли #{aid}")
            except discord.Forbidden:
                pass

        # Обновить владельца в БД
        db.set_role_owner(role_id, current_bidder)

        if channel:
            embed = discord.Embed(
                title=f"🎭 АУКЦИОН РОЛИ #{aid} ЗАВЕРШЁН",
                description=(
                    f"**Победитель:** <@{current_bidder}>\n"
                    f"**Роль:** {role.mention}\n"
                    f"**Ставка:** **{fmt(current_bid)}** {config.CURRENCY_EMOJI}\n"
                    f"**Продавец:** <@{seller_id}> получил деньги"
                ),
                color=discord.Color.green()
            )
            await channel.send(embed=embed)
    else:
        if channel:
            await channel.send(f"🎭 Аукцион роли #{aid} закрыт — нет ставок.")
            db.add_auction_history("role", aid, 0, 0, "no_bids", "Ставок не было")

    db.close_role_auction(aid)


async def role_auction_checker():
    while True:
        await asyncio.sleep(30)
        try:
            for a in db.get_active_role_auctions():
                aid = a[0]
                ends_at = db.parse_dt(a[8])
                if now_msk() >= ends_at:
                    await finish_role_auction(aid)
        except Exception as e:
            print(f"⚠️ role_auction_checker: {e}")
            
            
@bot.tree.command(name="роль_аукцион_выставить", description="🎭 Выставить роль на аукцион")
@app_commands.describe(role="Какую роль", start_price="Стартовая цена", minutes="Минут (5-1440)", bypass="Обход (Dev)")
async def role_auction_create_player(interaction: discord.Interaction, role: discord.Role, start_price: int, minutes: int = 10, bypass: bool = False):
    if start_price <= 0:
        await interaction.response.send_message("❌ Старт > 0.", ephemeral=True)
        return
    if minutes < 5 or minutes > 1440:
        await interaction.response.send_message("❌ Минуты: 5-1440.", ephemeral=True)
        return

    # Роль должна быть у игрока
    is_admin = _is_staff(interaction.user)
    is_dev = _is_dev_or_owner(interaction.user)
    bypass_allowed = bypass and is_dev
    note = " — **обход by Dev**" if bypass_allowed else ""

    if role not in interaction.user.roles and not bypass_allowed:
        await interaction.response.send_message("❌ У тебя нет этой роли.", ephemeral=True)
        return

    owner_id = db.get_role_owner(role.id)

    if owner_id != interaction.user.id and not is_admin and not bypass_allowed:
        await interaction.response.send_message("❌ Ты не владелец этой роли.", ephemeral=True)
        return

    if bypass_allowed:
        seller_id = owner_id if owner_id else interaction.user.id
    else:
        seller_id = interaction.user.id

    # Роль ниже роли бота?
    bot_member = interaction.guild.get_member(bot.user.id)
    if role >= bot_member.top_role:
        await interaction.response.send_message("❌ Роль выше моей.", ephemeral=True)
        return

    # Нет ли уже активного аукциона на эту роль
    for a in db.get_active_role_auctions():
        if a[1] == role.id:
            await interaction.response.send_message(
                f"❌ На эту роль уже идёт аукцион #{a[0]}.", ephemeral=True
            )
            return

    ends_at = (now_msk() + timedelta(minutes=minutes)).isoformat()
    aid = db.create_role_auction(role.id, interaction.user.id, start_price,
                                 interaction.channel_id, ends_at)

    msg = await interaction.channel.send(
        embed=make_role_auction_embed(aid, interaction.guild),
        view=RoleAuctionView(aid)
    )
    db.update_role_auction_message(aid, msg.id)
    await interaction.response.send_message(f"✅ Аукцион #{aid} запущен.", ephemeral=True)
    log_admin(interaction.user, "panel", "Аукцион роли: старт (игрок)", None,
              f"{role.name} от {start_price}")
              
              
@bot.tree.command(name="аукцион_отмена", description="🎭 Отменить аукцион (роль или бизнес)")
@app_commands.describe(aid="ID аукциона", kind="Что отменяем")
@app_commands.choices(kind=[
    app_commands.Choice(name="🎭 Роль", value="role"),
    app_commands.Choice(name="🏛️ Бизнес", value="biz"),
])
async def auction_cancel(interaction: discord.Interaction, aid: int, kind: app_commands.Choice[str]):
    is_admin = _is_staff(interaction.user)

    # ============ РОЛЬ ============
    if kind.value == "role":
        auc = db.get_role_auction(aid)
        if not auc or not auc[9]:
            await interaction.response.send_message("❌ Аукцион роли не найден или закрыт.", ephemeral=True)
            return

        (_, role_id, seller_id, start_price, current_bid,
         current_bidder, ch_id, msg_id, ends_at, active) = auc

        if interaction.user.id not in (seller_id,) and not is_admin:
            await interaction.response.send_message("❌ Только владелец или админ.", ephemeral=True)
            return

        # Вернуть ставку последнему, если была
        if current_bidder and current_bid:
            db.add_balance(current_bidder, current_bid)

        db.close_role_auction(aid)
        if current_bidder and current_bid:
            db.add_auction_history("role", aid, current_bidder, current_bid,
                                   "refund", "Отмена аукциона, возврат")
        db.add_auction_history("role", aid, interaction.user.id, 0, "cancel",
                               f"Отменил {interaction.user.name}")

        # Редактировать сообщение
        if msg_id:
            try:
                channel = bot.get_channel(ch_id)
                msg = await channel.fetch_message(msg_id)
                embed = discord.Embed(
                    title=f"🎭 АУКЦИОН РОЛИ #{aid} ОТМЕНЁН",
                    description=f"Отменил: {actor_label(interaction.user)}",
                    color=discord.Color.dark_gray()
                )
                await msg.edit(embed=embed, view=None)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ Аукцион роли #{aid} отменён.", ephemeral=True)
        log_admin(interaction.user, "panel", "Аукцион роли: отмена", aid, "")

    # ============ БИЗНЕС ============
    else:
        auc = db.get_auction(aid)
        if not auc or not auc[10]:
            await interaction.response.send_message("❌ Аукцион бизнеса не найден или закрыт.", ephemeral=True)
            return

        (_, biz_id, seller_id, biz_type, start_price, current_bid,
         current_bidder, ch_id, msg_id, ends_at, active) = auc

        if interaction.user.id not in (seller_id,) and not is_admin:
            await interaction.response.send_message("❌ Только владелец или админ.", ephemeral=True)
            return

        # Вернуть ставку последнему
        if current_bidder and current_bid:
            db.add_balance(current_bidder, current_bid)

        db.close_auction(aid)

        # Редактировать сообщение
        if msg_id:
            try:
                channel = bot.get_channel(ch_id)
                msg = await channel.fetch_message(msg_id)
                embed = discord.Embed(
                    title=f"🏛️ АУКЦИОН #{aid} ОТМЕНЁН",
                    description=f"Отменил: {actor_label(interaction.user)}",
                    color=discord.Color.dark_gray()
                )
                await msg.edit(embed=embed, view=None)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ Аукцион бизнеса #{aid} отменён.", ephemeral=True)
        log_admin(interaction.user, "panel", "Аукцион бизнеса: отмена", aid, "") 



@bot.tree.command(name="аукцион_лог", description="📜 История ставок по аукциону")
@app_commands.describe(aid="ID аукциона", kind="Тип")
@app_commands.choices(kind=[
    app_commands.Choice(name="🎭 Роль", value="role"),
    app_commands.Choice(name="🏛️ Бизнес", value="biz"),
])
async def auction_log(interaction: discord.Interaction, aid: int, kind: app_commands.Choice[str]):
    rows = db.get_auction_history(kind.value, aid, limit=50)
    if not rows:
        await interaction.response.send_message(
            f"📜 История аукциона #{aid} пуста.", ephemeral=True
        )
        return

    action_emoji = {
        "start": "🚀", "bid": "💰", "refund": "↩️",
        "win": "🏆", "cancel": "❌", "no_bids": "😴",
    }

    lines = []
    for bidder_id, amount, action, details, created in rows:
        e = action_emoji.get(action, "•")
        try:
            dt = db.parse_dt(created)
            date = dt.strftime("%d.%m %H:%M:%S")
        except Exception:
            date = created[5:19].replace("T", " ")
        who = f"<@{bidder_id}>" if bidder_id else "—"
        amt = f"**{fmt(amount)}** {config.CURRENCY_EMOJI}" if amount else ""
        det = f" • {details}" if details else ""
        lines.append(f"{e} `{date}` {who} {amt}{det}")

    kind_name = "🎭 Роль" if kind.value == "role" else "🏛️ Бизнес"
    embed = discord.Embed(
        title=f"📜 Лог аукциона #{aid} ({kind_name})",
        description="━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) + "\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Всего записей: {len(rows)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(name="аукцион_завершить", description="⚡ [АДМИН] Принудительно завершить аукцион")
@app_commands.describe(aid="ID аукциона", kind="Тип")
@app_commands.choices(kind=[
    app_commands.Choice(name="🎭 Роль", value="role"),
    app_commands.Choice(name="🏛️ Бизнес", value="biz"),
])
@app_commands.default_permissions(administrator=True)
async def auction_force_finish(interaction: discord.Interaction, aid: int, kind: app_commands.Choice[str]):
    if kind.value == "role":
        await finish_role_auction(aid)
    else:
        await finish_auction(aid)

    await interaction.response.send_message(f"✅ Аукцион #{aid} завершён.", ephemeral=True)
    log_admin(interaction.user, "panel", "Принудительное завершение аукциона", aid, kind.value)
    
    
    
@bot.tree.command(name="кредит_аннулировать", description="💳 [DEV] Аннулировать кредит (без возврата)")
@app_commands.describe(credit_id="ID кредита")
async def credit_annul(interaction: discord.Interaction, credit_id: int):
    if not _is_dev_or_owner(interaction.user):
        await interaction.response.send_message("❌ Только Dev/Owner.", ephemeral=True)
        return

    credit = db.get_credit(credit_id)
    if not credit or not credit[7]:
        await interaction.response.send_message("❌ Кредит не найден или закрыт.", ephemeral=True)
        return

    cid, lender, borrower, amount, debt, percent, until, active, created = credit
    db.force_close_credit(credit_id)

    db.add_transaction(borrower, 0, "admin", f"Кредит #{cid} аннулирован (обход by Dev)")
    db.add_transaction(lender, 0, "admin", f"Кредит #{cid} аннулирован (обход by Dev)")
    log_admin(interaction.user, "economy", "Аннулирование кредита (обход by Dev)",
              borrower, f"#{cid} долг {debt}")

    await interaction.response.send_message(
        f"✅ Кредит #{cid} аннулирован **обход by Dev**.\n"
        f"<@{borrower}> больше не должен, <@{lender}> не получит возврат.",
        ephemeral=True
    )


@bot.tree.command(name="кредит_продлить", description="💳 [DEV] Продлить кредит (сверх лимита)")
@app_commands.describe(credit_id="ID кредита", hours="На сколько часов")
async def credit_extend(interaction: discord.Interaction, credit_id: int, hours: int):
    if not _is_dev_or_owner(interaction.user):
        await interaction.response.send_message("❌ Только Dev/Owner.", ephemeral=True)
        return
    if hours <= 0:
        await interaction.response.send_message("❌ Часы > 0.", ephemeral=True)
        return

    credit = db.get_credit(credit_id)
    if not credit or not credit[7]:
        await interaction.response.send_message("❌ Кредит не найден или закрыт.", ephemeral=True)
        return

    old_until = credit[6]
    new_until = (db.parse_dt(old_until) + timedelta(hours=hours)).isoformat()
    db.update_credit_until(credit_id, new_until)

    db.add_transaction(credit[2], 0, "admin", f"Кредит #{credit_id} продлён на {hours}ч (обход by Dev)")
    log_admin(interaction.user, "economy", "Продление кредита (обход by Dev)",
              credit[2], f"#{credit_id} +{hours}ч")

    await interaction.response.send_message(
        f"✅ Кредит #{credit_id} продлён на **{hours} ч** **обход by Dev**.",
        ephemeral=True
    )



 # ============================================================
#                  РОЛЬ ПРЕМИЯ
# ============================================================

@bot.tree.command(name="премия_выдать", description="🎁 Выдать премию 80к (роль «Премия», КД 3 часа)")
@app_commands.describe(user="Кому")
async def premium_give(interaction: discord.Interaction, user: discord.Member):
    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return
        
    if not any(r.id == config.PREMIUM_GIVER_ROLE_ID for r in interaction.user.roles):
        await interaction.response.send_message(
            "❌ Только для роли «Премия».", ephemeral=True
        )
        return

    if not has_no_cooldown(interaction.user):
        last = db.get_last_salary(interaction.user.id)
        if last:
            elapsed = (now_msk() - db.parse_dt(last)).total_seconds()
            if elapsed < config.PREMIUM_COOLDOWN:
                remaining = int(config.PREMIUM_COOLDOWN - elapsed)
                await interaction.response.send_message(
                    f"⏳ КД. Подожди **{remaining // 3600} ч {(remaining % 3600) // 60} мин**.",
                    ephemeral=True
                )
                return

    db.add_balance(user.id, config.PREMIUM_AMOUNT)
    db.set_last_salary(interaction.user.id, now_msk().isoformat())
    db.add_transaction(user.id, config.PREMIUM_AMOUNT, "admin",
                       f"Премия от {actor_label(interaction.user)}")
    log_admin(interaction.user, "economy", "Премия (роль)", user.id,
              str(config.PREMIUM_AMOUNT))

    await interaction.response.send_message(
        f"🎁 {user.mention} получил **+{fmt(config.PREMIUM_AMOUNT)}** {config.CURRENCY_EMOJI}"
    )


@bot.tree.command(name="сброс_кд_премия", description="🎁 [DEV] Сбросить КД премии у игрока")
@app_commands.describe(user="Кому сбросить")
async def reset_premium_cd(interaction: discord.Interaction, user: discord.Member):
    if not _is_dev_or_owner(interaction.user):
        await interaction.response.send_message("❌ Только Dev/Owner.", ephemeral=True)
        return

    db.set_last_salary(user.id, None)
    log_admin(interaction.user, "panel", "Сброс КД премии (обход by Dev)", user.id, "")
    
    await interaction.response.send_message(
        f"✅ КД премии сброшено для {user.mention} **обход by Dev**.",
        ephemeral=True
    )
    
 

    # Формула цены: 1=1млн, 2=3млн, 3=6млн (сумма арифметической прогрессии)
    # Цена = (amount * (1_000_000 + amount * 1_000_000)) // 2 
    # Упростим: 1-е очко 1кк, каждое следующее +1кк к цене.
    # 1 -> 1кк, 2 -> 3кк, 3 -> 6кк, 4 -> 10кк
    cost = 0
    for i in range(1, amount + 1):
        cost += i * 1_000_000

    if db.get_balance(interaction.user.id) < cost:
        await interaction.response.send_message(
            f"❌ Нужно **{fmt(cost)}** {config.CURRENCY_EMOJI} (у тебя {fmt(db.get_balance(interaction.user.id))}).", 
            ephemeral=True
        )
        return

    db.add_balance(interaction.user.id, -cost)
    new_pts = db.add_user_points(interaction.user.id, amount)
    db.add_transaction(interaction.user.id, -cost, "admin", f"Куплено {amount} очков бизнеса")
    
    embed = discord.Embed(
        title="💎 Очки куплены!",
        description=f"Ты купил **{amount}** очков за **{fmt(cost)}** {config.CURRENCY_EMOJI}.\nВсего очков: **{new_pts}**",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)
   
# ============================================================
#                  ЕДИНАЯ ПАНЕЛЬ БИЗНЕСОВ
# ============================================================

def make_level_bar(level: int) -> str:
    if level >= 5:
        return "🟩🟩🟩🟩🟩 **(MAX)**"
    return "🟩" * level + "⬛" * (5 - level) + f" ({level}/5)"


def make_biz_embed(user_id: int) -> discord.Embed:
    rows = db.get_businesses(user_id)
    pts = db.get_user_points(user_id)
    
    embed = discord.Embed(
        title="🏭 Мои бизнесы",
        description=f"💎 Твои очки: **{pts}**\n━━━━━━━━━━━━━━━━━━━━━━\n",
        color=discord.Color.green()
    )
    
    if not rows:
        embed.description += "\n_У тебя нет бизнесов._"
        return embed

    total_income = 0
    for biz_id, biz_type, level, last_income in rows:
        info = config.BUSINESS_TYPES.get(biz_type, {})
        income = info.get("income", 0) * level
        total_income += income
        
        pending = 0
        if last_income:
            try:
                hours = (now_msk() - db.parse_dt(last_income)).total_seconds() / 3600
                pending = int(income * hours)
            except Exception:
                pass

        bar = make_level_bar(level)
        embed.add_field(
            name=f"`#{biz_id}` {info.get('name', biz_type)}",
            value=(
                f"📊 Уровень: {bar}\n"
                f"📈 Доход: **{fmt(income)}** {config.CURRENCY_EMOJI}/час\n"
                f"💰 Накоплено: **{fmt(pending)}** {config.CURRENCY_EMOJI}"
            ),
            inline=False
        )
    
    embed.set_footer(text=f"💼 Общий доход: {fmt(total_income)} {config.CURRENCY_EMOJI}/час")
    return embed


class BizPanelView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.update_select()

    def update_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
                
        rows = db.get_businesses(self.user_id)
        if not rows:
            return

        options = []
        for biz_id, biz_type, level, _ in rows:
            info = config.BUSINESS_TYPES.get(biz_type, {})
            is_max = level >= 5
            options.append(discord.SelectOption(
                label=f"#{biz_id} {info.get('name', biz_type)} (Ур. {level})",
                value=str(biz_id),
                description="Максимальный уровень" if is_max else f"Улучшить за {level} очков",
                emoji="🛑" if is_max else "⬆️"
            ))
        
        if options:
            select = discord.ui.Select(placeholder="Выбери бизнес...", options=options, row=0)
            select.callback = self.select_callback
            self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction):
        biz_id = int(interaction.data["values"][0])
        biz = db.get_business_by_id_full(biz_id)
        
        if not biz or biz[1] != self.user_id:
            await interaction.response.send_message("❌ Бизнес не найден.", ephemeral=True)
            return
            
        level = biz[3]
        if level >= 5:
            await interaction.response.send_message("❌ Максимальный уровень (5).", ephemeral=True)
            return

        cost_pts = level
        user_pts = db.get_user_points(self.user_id)

        if user_pts < cost_pts:
            await interaction.response.send_message(f"❌ Нужно **{cost_pts}** 💎 (у тебя {user_pts}).", ephemeral=True)
            return

        db.add_user_points(self.user_id, -cost_pts)
        db.upgrade_business_level(biz_id)
        
        info = config.BUSINESS_TYPES.get(biz[2], {})
        new_level = level + 1
        new_income = info.get("income", 0) * new_level
        
        db.add_transaction(self.user_id, 0, "biz", f"Улучшение {info.get('name')} до {new_level} ур.")
        
        self.update_select()
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=self)
        
        await interaction.followup.send(
            f"🎉 **{info.get('name')}** улучшен до **{new_level} ур.** (списано {cost_pts} 💎).",
            ephemeral=True
        )

    @discord.ui.button(label="🎁 Собрать доход", style=discord.ButtonStyle.success, row=1)
    async def collect(self, interaction, button):
        if db.is_in_jail(self.user_id) or db.is_frozen(self.user_id):
            await interaction.response.send_message("🚔 Ты в тюрьме / счёт заблокирован.", ephemeral=True)
            return
            
        if not has_no_cooldown(interaction.user):
            last = db.get_last_biz_income(self.user_id)
            if last:
                elapsed = (now_msk() - db.parse_dt(last)).total_seconds()
                if elapsed < config.BUSINESS_INCOME_COOLDOWN:
                    remaining = int(config.BUSINESS_INCOME_COOLDOWN - elapsed)
                    await interaction.response.send_message(f"⏳ КД. Подожди **{remaining // 60} мин**.", ephemeral=True)
                    return

        rows = db.get_businesses(self.user_id)
        total_gross = 0
        for biz_id, biz_type, level, last_income in rows:
            info = config.BUSINESS_TYPES.get(biz_type, {})
            income = info.get("income", 0) * level
            pending = 0
            if last_income:
                try:
                    hours = (now_msk() - db.parse_dt(last_income)).total_seconds() / 3600
                    pending = int(income * hours)
                except Exception:
                    pass
            if pending > 0:
                total_gross += pending
                db.update_business_income(biz_id, now_msk().isoformat())

        if total_gross == 0:
            await interaction.response.send_message("💰 Пока нечего собирать.", ephemeral=True)
            return

        db.add_balance(self.user_id, total_gross)
        db.add_transaction(self.user_id, total_gross, "biz", "Сбор дохода")
        db.set_last_biz_income(self.user_id, now_msk().isoformat())
        
        self.update_select()
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=self)
        await interaction.followup.send(f"💰 Ты собрал **{fmt(total_gross)}** {config.CURRENCY_EMOJI}!", ephemeral=True)

    @discord.ui.button(label="💎 Магазин очков", style=discord.ButtonStyle.primary, row=1)
    async def shop(self, interaction, button):
        await interaction.response.edit_message(embed=make_shop_embed(self.user_id), view=PointShopView(self.user_id))


def make_shop_embed(user_id: int) -> discord.Embed:
    pts = db.get_user_points(user_id)
    return discord.Embed(
        title="💎 Магазин очков бизнеса",
        description=f"У тебя **{pts}** очков.\n━━━━━━━━━━━━━━━━━━━━━━\nВыбери пакет для покупки:",
        color=discord.Color.blue()
    )


class PointShopView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    async def _buy(self, interaction, amount):
        cost = sum(i * 1_000_000 for i in range(1, amount + 1))
        current_pts = db.get_user_points(self.user_id)
        
        # Защита от обхода
        if amount == 1 and current_pts >= 2:
            await interaction.response.send_message(
                "❌ Вы уже купили 2 очка. Чтобы купить ещё, используйте пакеты (2, 3 или 4 очка), иначе цена будет невыгодной!", 
                ephemeral=True
            )
            return

        # Проверка баланса
        if db.get_balance(self.user_id) < cost:
            await interaction.response.send_message(f"❌ Нужно **{fmt(cost)}** {config.CURRENCY_EMOJI}.", ephemeral=True)
            return
            
        # Покупка
        db.add_balance(self.user_id, -cost)
        db.add_user_points(self.user_id, amount)
        db.add_transaction(self.user_id, -cost, "admin", f"Куплено {amount} очков")
        
        # Обновление панели
        await interaction.response.edit_message(embed=make_shop_embed(self.user_id), view=self)
        await interaction.followup.send(f"✅ Куплено **{amount}** очков за **{fmt(cost)}** {config.CURRENCY_EMOJI}.", ephemeral=True)

    @discord.ui.button(label="1 очко (1 млн)", style=discord.ButtonStyle.success, row=0)
    async def b1(self, i, b): await self._buy(i, 1)
    
    @discord.ui.button(label="2 очка (3 млн)", style=discord.ButtonStyle.success, row=0)
    async def b2(self, i, b): await self._buy(i, 2)
    
    @discord.ui.button(label="3 очка (6 млн)", style=discord.ButtonStyle.primary, row=0)
    async def b3(self, i, b): await self._buy(i, 3)
    
    @discord.ui.button(label="4 очка (10 млн)", style=discord.ButtonStyle.primary, row=1)
    async def b4(self, i, b): await self._buy(i, 4)
    
    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=BizPanelView(self.user_id))

    
# ============================================================
#                  СИСТЕМА ОЧКОВ И УЛУЧШЕНИЙ
# ============================================================

def make_level_bar(level: int) -> str:
    """Красивая полоска уровня."""
    if level >= 5:
        return "🟩🟩🟩🟩🟩 **(MAX)**"
    bar = "🟩" * level + "⬛" * (5 - level)
    return f"{bar} ({level}/5)"

class BusinessUpgradeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="⬆️ Улучшить бизнес", style=discord.ButtonStyle.success)
    async def upgrade_btn(self, interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return
        await interaction.response.send_modal(UpgradeBusinessModal(self.user_id))

class UpgradeBusinessModal(discord.ui.Modal):
    def __init__(self, user_id: int):
        super().__init__(title="Улучшение бизнеса")
        self.user_id = user_id
        self.biz_id_input = discord.ui.TextInput(
            label="ID бизнеса (например, #25)", 
            placeholder="Введи только цифры (25)",
            min_length=1, max_length=10
        )
        self.add_item(self.biz_id_input)

    async def on_submit(self, interaction):
        try:
            biz_id = int(self.biz_id_input.value.replace("#", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ ID — это число.", ephemeral=True)
            return

        # Ищем бизнес юзера
        rows = db.get_businesses(self.user_id)
        biz = next((r for r in rows if r[0] == biz_id), None)
        
        if not biz:
            await interaction.response.send_message("❌ У тебя нет бизнеса с таким ID.", ephemeral=True)
            return

        biz_type, current_level = biz[1], biz[2]
        
        if current_level >= 5:
            await interaction.response.send_message("❌ Этот бизнес уже максимального уровня (5).", ephemeral=True)
            return

        cost_pts = current_level # 1->2 стоит 1 очко, 2->3 стоит 2 очка...
        user_pts = db.get_user_points(self.user_id)

        if user_pts < cost_pts:
            await interaction.response.send_message(
                f"❌ Нужно **{cost_pts}** 💎 очков (у тебя {user_pts}).", 
                ephemeral=True
            )
            return

        # Улучшаем
        db.add_user_points(self.user_id, -cost_pts)
        db.upgrade_business_level(biz_id)
        
        info = config.BUSINESS_TYPES.get(biz_type, {})
        new_level = current_level + 1
        new_income = info.get("income", 0) * new_level
        
        db.add_transaction(self.user_id, 0, "biz", f"Улучшение {info.get('name')} до {new_level} ур.")
        log_admin(interaction.user, "biz", "Улучшение бизнеса", self.user_id, f"#{biz_id} до {new_level}")

        embed = discord.Embed(
            title="🎉 Бизнес успешно улучшен!",
            description=(
                f"**{info.get('name', 'Бизнес')}** повышен до **{new_level} уровня**!\n\n"
                f"📈 Новый доход: **{fmt(new_income)}** {config.CURRENCY_EMOJI}/час\n"
                f"💎 Потрачено: **{cost_pts}** очков"
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="очки", description="💎 Твои очки бизнеса")
async def my_points(interaction: discord.Interaction):
    pts = db.get_user_points(interaction.user.id)
    embed = discord.Embed(
        title="💎 Очки бизнеса",
        description=f"У тебя на счету: **{pts}** очков.\n\n"
                    f"Купить очки можно командой `/очки_купить`.\n"
                    f"Потратить их можно в `/бизнес мои`.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
 
 # ============================================================
#                  ЕДИНАЯ ПАНЕЛЬ БИЗНЕСОВ
# ============================================================

def make_level_bar(level: int) -> str:
    if level >= 5:
        return "🟩🟩🟩🟩🟩 **(MAX)**"
    return "🟩" * level + "⬛" * (5 - level) + f" ({level}/5)"


def make_biz_embed(user_id: int) -> discord.Embed:
    rows = db.get_businesses(user_id)
    pts = db.get_user_points(user_id)
    
    embed = discord.Embed(
        title="🏭 Мои бизнесы",
        description=f"💎 Твои очки: **{pts}**\n━━━━━━━━━━━━━━━━━━━━━━\n",
        color=discord.Color.green()
    )
    
    if not rows:
        embed.description += "\n_У тебя нет бизнесов._"
        return embed

    total_income = 0
    for biz_id, biz_type, level, last_income in rows:
        info = config.BUSINESS_TYPES.get(biz_type, {})
        income = info.get("income", 0) * level
        total_income += income
        
        pending = 0
        if last_income:
            try:
                hours = (now_msk() - db.parse_dt(last_income)).total_seconds() / 3600
                pending = int(income * hours)
            except Exception:
                pass

        bar = make_level_bar(level)
        embed.add_field(
            name=f"`#{biz_id}` {info.get('name', biz_type)}",
            value=(
                f"📊 Уровень: {bar}\n"
                f"📈 Доход: **{fmt(income)}** {config.CURRENCY_EMOJI}/час\n"
                f"💰 Накоплено: **{fmt(pending)}** {config.CURRENCY_EMOJI}"
            ),
            inline=False
        )
    
    embed.set_footer(text=f"💼 Общий доход: {fmt(total_income)} {config.CURRENCY_EMOJI}/час")
    return embed


class BizPanelView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.update_select()

    def update_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
                
        rows = db.get_businesses(self.user_id)
        if not rows:
            return

        options = []
        for biz_id, biz_type, level, _ in rows:
            info = config.BUSINESS_TYPES.get(biz_type, {})
            is_max = level >= 5
            options.append(discord.SelectOption(
                label=f"#{biz_id} {info.get('name', biz_type)} (Ур. {level})",
                value=str(biz_id),
                description="Максимальный уровень" if is_max else f"Улучшить за {level} очков",
                emoji="🛑" if is_max else "⬆️"
            ))
        
        if options:
            select = discord.ui.Select(placeholder="Выбери бизнес для улучшения...", options=options, row=0)
            select.callback = self.select_callback
            self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction):
        biz_id = int(interaction.data["values"][0])
        biz = db.get_business_by_id_full(biz_id)
        
        if not biz or biz[1] != self.user_id:
            await interaction.response.send_message("❌ Бизнес не найден.", ephemeral=True)
            return
            
        level = biz[3]
        if level >= 5:
            await interaction.response.send_message("❌ Максимальный уровень (5).", ephemeral=True)
            return

        cost_pts = level
        user_pts = db.get_user_points(self.user_id)

        if user_pts < cost_pts:
            await interaction.response.send_message(f"❌ Нужно **{cost_pts}** 💎 (у тебя {user_pts}).", ephemeral=True)
            return

        db.add_user_points(self.user_id, -cost_pts)
        db.upgrade_business_level(biz_id)
        
        info = config.BUSINESS_TYPES.get(biz[2], {})
        new_level = level + 1
        new_income = info.get("income", 0) * new_level
        
        db.add_transaction(self.user_id, 0, "biz", f"Улучшение {info.get('name')} до {new_level} ур.")
        
        self.update_select()
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=self)
        
        await interaction.followup.send(
            f"🎉 **{info.get('name')}** улучшен до **{new_level} ур.** (списано {cost_pts} 💎).",
            ephemeral=True
        )

    @discord.ui.button(label="🎁 Собрать доход", style=discord.ButtonStyle.success, row=1)
    async def collect(self, interaction, button):
        if db.is_in_jail(self.user_id) or db.is_frozen(self.user_id):
            await interaction.response.send_message("🚔 Ты в тюрьме / счёт заблокирован.", ephemeral=True)
            return
            
        if not has_no_cooldown(interaction.user):
            last = db.get_last_biz_income(self.user_id)
            if last:
                elapsed = (now_msk() - db.parse_dt(last)).total_seconds()
                if elapsed < config.BUSINESS_INCOME_COOLDOWN:
                    remaining = int(config.BUSINESS_INCOME_COOLDOWN - elapsed)
                    await interaction.response.send_message(f"⏳ КД. Подожди **{remaining // 60} мин**.", ephemeral=True)
                    return

        rows = db.get_businesses(self.user_id)
        total_gross = 0
        for biz_id, biz_type, level, last_income in rows:
            info = config.BUSINESS_TYPES.get(biz_type, {})
            income = info.get("income", 0) * level
            pending = 0
            if last_income:
                try:
                    hours = (now_msk() - db.parse_dt(last_income)).total_seconds() / 3600
                    pending = int(income * hours)
                except Exception:
                    pass
            if pending > 0:
                total_gross += pending
                db.update_business_income(biz_id, now_msk().isoformat())

        if total_gross == 0:
            await interaction.response.send_message("💰 Пока нечего собирать.", ephemeral=True)
            return

        db.add_balance(self.user_id, total_gross)
        db.add_transaction(self.user_id, total_gross, "biz", "Сбор дохода")
        db.set_last_biz_income(self.user_id, now_msk().isoformat())
        
        self.update_select()
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=self)
        await interaction.followup.send(f"💰 Ты собрал **{fmt(total_gross)}** {config.CURRENCY_EMOJI}!", ephemeral=True)

    @discord.ui.button(label="💎 Магазин очков", style=discord.ButtonStyle.primary, row=1)
    async def shop(self, interaction, button):
        await interaction.response.edit_message(embed=make_shop_embed(self.user_id), view=PointShopView(self.user_id))


def make_shop_embed(user_id: int) -> discord.Embed:
    pts = db.get_user_points(user_id)
    return discord.Embed(
        title="💎 Магазин очков бизнеса",
        description=f"У тебя **{pts}** очков.\n━━━━━━━━━━━━━━━━━━━━━━\nВыбери пакет для покупки:",
        color=discord.Color.blue()
    )


class PointShopView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    async def _buy(self, interaction, amount):
        cost = sum(i * 1_000_000 for i in range(1, amount + 1))
        if db.get_balance(self.user_id) < cost:
            await interaction.response.send_message(f"❌ Нужно **{fmt(cost)}** {config.CURRENCY_EMOJI}.", ephemeral=True)
            return
        db.add_balance(self.user_id, -cost)
        db.add_user_points(self.user_id, amount)
        db.add_transaction(self.user_id, -cost, "admin", f"Куплено {amount} очков")
        
        await interaction.response.edit_message(embed=make_shop_embed(self.user_id), view=self)
        await interaction.followup.send(f"✅ Куплено **{amount}** очков за **{fmt(cost)}** {config.CURRENCY_EMOJI}.", ephemeral=True)

    @discord.ui.button(label="1 очко (1 млн)", style=discord.ButtonStyle.success, row=0)
    async def b1(self, interaction, button):
        current_pts = db.get_user_points(self.user_id)
        if current_pts >= 1:
            await interaction.response.send_message(
                "❌ Первое очко уже куплено. Дальше покупайте пакетами (2, 3 или 4 очка)!", 
                ephemeral=True
            )
            return
        await self._buy(interaction, 1)
    
    @discord.ui.button(label="2 очка (3 млн)", style=discord.ButtonStyle.success, row=0)
    async def b2(self, i, b): await self._buy(i, 2)
    
    @discord.ui.button(label="3 очка (6 млн)", style=discord.ButtonStyle.primary, row=0)
    async def b3(self, i, b): await self._buy(i, 3)
    
    @discord.ui.button(label="4 очка (10 млн)", style=discord.ButtonStyle.primary, row=1)
    async def b4(self, i, b): await self._buy(i, 4)
    
    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=make_biz_embed(self.user_id), view=BizPanelView(self.user_id))



    
# ============================================================
#                  DEV-ПАНЕЛЬ УПРАВЛЕНИЯ ОЧКАМИ
# ============================================================

class DevPointsManageView(discord.ui.View):
    def __init__(self, target_user: discord.Member, author: discord.Member):
        super().__init__(timeout=300)
        self.target_user = target_user
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Это меню не для тебя.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="➕ Добавить", style=discord.ButtonStyle.success, row=0)
    async def add_btn(self, interaction, button):
        await interaction.response.send_modal(ChangePointsModal(self.target_user, "add"))

    @discord.ui.button(label="➖ Забрать", style=discord.ButtonStyle.danger, row=0)
    async def remove_btn(self, interaction, button):
        await interaction.response.send_modal(ChangePointsModal(self.target_user, "remove"))

    @discord.ui.button(label="🔄 Установить", style=discord.ButtonStyle.primary, row=0)
    async def set_btn(self, interaction, button):
        await interaction.response.send_modal(ChangePointsModal(self.target_user, "set"))

    @discord.ui.button(label="🗑️ Обнулить", style=discord.ButtonStyle.secondary, row=1)
    async def zero_btn(self, interaction, button):
        current = db.get_user_points(self.target_user.id)
        db.add_user_points(self.target_user.id, -current)
        log_admin(interaction.user, "people", "Dev: очки обнулены", self.target_user.id, f"Было: {current}")
        
        embed = make_dev_points_embed(self.target_user)
        await interaction.response.edit_message(embed=embed, view=self)


class ChangePointsModal(discord.ui.Modal):
    def __init__(self, target_user: discord.Member, action: str):
        self.target_user = target_user
        self.action = action
        
        titles = {"add": "Добавить очки", "remove": "Забрать очки", "set": "Установить очки"}
        super().__init__(title=titles.get(action, "Изменить очки"))
        
        self.amount_input = discord.ui.TextInput(
            label="Количество очков", 
            placeholder="Введи число (например, 5)",
            min_length=1, max_length=10
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Это должно быть число.", ephemeral=True)
            return

        if amount < 0:
            await interaction.response.send_message("❌ Число должно быть положительным.", ephemeral=True)
            return

        current = db.get_user_points(self.target_user.id)
        
        if self.action == "add":
            db.add_user_points(self.target_user.id, amount)
            action_text = f"Добавлено **{amount}** очков"
        elif self.action == "remove":
            db.add_user_points(self.target_user.id, -amount)
            action_text = f"Забрано **{amount}** очков"
        else:
            diff = amount - current
            db.add_user_points(self.target_user.id, diff)
            action_text = f"Установлено **{amount}** очков"

        log_admin(interaction.user, "people", f"Dev: {action_text}", self.target_user.id, "")
        
        embed = make_dev_points_embed(self.target_user)
        view = DevPointsManageView(self.target_user, interaction.user)
        
        # Обновляем сообщение (если это модалка от кнопки)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            pass # Если модалка была вызвана извне


class DevUserSelect(discord.ui.UserSelect):
    def __init__(self, author: discord.Member):
        super().__init__(placeholder="Выбери игрока для управления очками...", min_values=1, max_values=1)
        self.author = author

    async def callback(self, interaction: discord.Interaction):
        target_user = self.values[0]
        embed = make_dev_points_embed(target_user)
        view = DevPointsManageView(target_user, self.author)
        await interaction.response.edit_message(embed=embed, view=view)


def make_dev_points_embed(target_user: discord.Member) -> discord.Embed:
    pts = db.get_user_points(target_user.id)
    embed = discord.Embed(
        title=f"💎 Управление очками: {target_user.name}",
        description=(
            f"👤 **Игрок:** {target_user.mention}\n"
            f"💎 **Текущие очки:** **{pts}**\n\n"
            f"Выбери действие на кнопках ниже:"
        ),
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    return embed


@bot.tree.command(name="очки_dev", description="💎 [DEV] Управление очками игроков")
async def dev_points_cmd(interaction: discord.Interaction):
    if not _is_dev_or_owner(interaction.user):
        await interaction.response.send_message("❌ Только Dev/Owner.", ephemeral=True)
        return

    view = discord.ui.View(timeout=180)
    view.add_item(DevUserSelect(interaction.user))
    
    embed = discord.Embed(
        title="💎 Dev-панель очков",
        description="Выбери игрока из списка ниже, чтобы управлять его очками.",
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed, view=view)
    
    
    
@bot.tree.command(name="owner_sleep", description="💤 [OWNER] Включить/выключить режим тех. работ")
async def owner_sleep(interaction: discord.Interaction):
    if interaction.user.id != config.OWNER_ID:
        await interaction.response.send_message("❌ Только создатель бота может это делать.", ephemeral=True)
        return

    current = db.get_bot_sleep()
    db.set_bot_sleep(not current)
    
    if not current:
        await interaction.response.send_message("💤 Бот переведен в **режим тех. работ**. Команды работают только у тебя.")
    else:
        await interaction.response.send_message("✅ Режим тех. работ **отключен**. Бот снова доступен всем.")
    

@bot.tree.command(name="вайп_всех", description="🛑 [OWNER] Обнулить балансы у ВСЕХ игроков")
async def wipe_all_balances(interaction: discord.Interaction):
    # Проверка на овнера (или админа)
    if interaction.user.id != config.OWNER_ID:
        await interaction.response.send_message("❌ Только владелец.", ephemeral=True)
        return

    balances = db.get_all_balances()
    total_wiped = 0
    count = 0

    for user_id, bal in balances:
        if bal > 0:
            db.set_balance(user_id, 0)
            total_wiped += bal
            count += 1

    db.add_to_treasury(total_wiped)
    
    await interaction.response.send_message(
        f"💀 **ГЛОБАЛЬНЫЙ ВАЙП**\n"
        f"Обнулено счетов: **{count}**\n"
        f"Изъято в казну: **{fmt(total_wiped)}** {config.CURRENCY_EMOJI}",
        ephemeral=False
    )



@bot.tree.command(name="банк", description="🏦 Главное меню банка")
async def bank_menu(interaction: discord.Interaction):
    bal = db.get_balance(interaction.user.id)
    frozen = db.is_frozen(interaction.user.id)
    jail = db.is_in_jail(interaction.user.id)

    status_line = ""
    if frozen:
        status_line = f"\n{config.FREEZE_EMOJI} **СЧЁТ ЗАБЛОКИРОВАН**"
    elif jail:
        status_line = "\n🚔 **В ТЮРЬМЕ**"

    embed = discord.Embed(
        title="🏦 ГОСУДАРСТВЕННЫЙ БАНК",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Клиент:** {interaction.user.mention}\n"
            f"💼 **Баланс:** {fmt(bal)} {config.CURRENCY_EMOJI}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━{status_line}"
        ),
        color=discord.Color.green() if not frozen else discord.Color.red()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="Безопасность и надежность • МСК")
    await interaction.response.send_message(embed=embed, view=BankView(interaction.user.id))


class BankView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это меню не для тебя.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💼 Мой кошелёк", style=discord.ButtonStyle.primary, row=0)
    async def balance(self, interaction, button):
        await show_balance(interaction, interaction.user)

    @discord.ui.button(label="📜 История", style=discord.ButtonStyle.secondary, row=0)
    async def history(self, interaction, button):
        await show_history(interaction, interaction.user)

    @discord.ui.button(label="💳 Кредиты", style=discord.ButtonStyle.success, row=1)
    async def credits_btn(self, interaction, button):
        await show_credits(interaction, interaction.user)

    @discord.ui.button(label="⚖️ Казна", style=discord.ButtonStyle.danger, row=1)
    async def treasury(self, interaction, button):
        total = db.get_treasury()
        status = "🔓 Открыта" if db.get_treasury_open() else "🔒 Закрыта"
        embed = discord.Embed(
            title="⚖️ Государственная казна",
            description=f"💵 **В казне:** {fmt(total)} {config.CURRENCY_EMOJI}\n🚪 **Статус:** {status}",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction, button):
        bal = db.get_balance(interaction.user.id)
        frozen = db.is_frozen(interaction.user.id)
        
        status_line = ""
        if frozen:
            status_line = f"\n{config.FREEZE_EMOJI} **СЧЁТ ЗАБЛОКИРОВАН**"

        embed = discord.Embed(
            title="🏦 ГОСУДАРСТВЕННЫЙ БАНК",
            description=(
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **Клиент:** {interaction.user.mention}\n"
                f"💼 **Баланс:** {fmt(bal)} {config.CURRENCY_EMOJI}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━{status_line}"
            ),
            color=discord.Color.green() if not frozen else discord.Color.red()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)
        

@bot.tree.command(name="кредит_мои", description="💳 Мои кредиты и долги")
async def credit_menu(interaction: discord.Interaction):
    await show_credits(interaction, interaction.user)        
    
    
# ============================================================
#                    КРЕДИТЫ (КРАСИВОЕ МЕНЮ)
# ============================================================

class CreditUserSelect(discord.ui.UserSelect):
    def __init__(self, author: discord.Member):
        super().__init__(placeholder="Кому выдать кредит?", min_values=1, max_values=1)
        self.author = author

    async def callback(self, interaction: discord.Interaction):
        target_user = self.values[0]
        
        # Открываем модалку для ввода суммы и процентов
        await interaction.response.send_modal(CreditOfferModal(self.author, target_user))


class CreditPanelView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🤝 Предложить кредит", style=discord.ButtonStyle.success, row=0)
    async def offer_btn(self, interaction, button):
        # Проверка на права (если нужно оставить только для 2-х лиц, раскомментируй)
        # if interaction.user.id not in config.CREDIT_ISSUER_IDS:
        #     await interaction.response.send_message("❌ Вы не можете выдавать кредиты.", ephemeral=True)
        #     return
            
        view = discord.ui.View(timeout=180)
        view.add_item(CreditUserSelect(interaction.user))
        
        embed = discord.Embed(
            title="🤝 Выдача кредита",
            description="Выбери игрока из списка ниже, чтобы предложить ему кредит:",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="📜 Мои кредиты", style=discord.ButtonStyle.primary, row=0)
    async def my_credits(self, interaction, button):
        # Вызываем нашу старую функцию show_credits
        await show_credits(interaction, interaction.user)


class CreditOfferModal(discord.ui.Modal):
    def __init__(self, author, target_user):
        super().__init__(title=f"Кредит для {target_user.name}")
        self.author = author
        self.target_user = target_user
        
        self.amount_input = discord.ui.TextInput(
            label="Сумма кредита", 
            placeholder="Сколько денег выдать?",
            min_length=1, max_length=15
        )
        self.percent_input = discord.ui.TextInput(
            label="Процент (%)", 
            placeholder="Например: 10",
            min_length=1, max_length=3
        )
        self.hours_input = discord.ui.TextInput(
            label="Срок (в часах)", 
            placeholder="Например: 24",
            min_length=1, max_length=3
        )
        self.add_item(self.amount_input)
        self.add_item(self.percent_input)
        self.add_item(self.hours_input)

    async def on_submit(self, interaction):
        try:
            amount = int(self.amount_input.value)
            percent = int(self.percent_input.value)
            hours = int(self.hours_input.value)
        except ValueError:
            await interaction.response.send_message("❌ Все поля должны быть числами.", ephemeral=True)
            return

        if amount <= 0 or percent < 0 or hours <= 0:
            await interaction.response.send_message("❌ Сумма и срок должны быть больше 0.", ephemeral=True)
            return

        if db.get_balance(self.author.id) < amount:
            await interaction.response.send_message("❌ У вас недостаточно средств для выдачи такого кредита.", ephemeral=True)
            return

        debt = int(amount * (1 + percent / 100))
        until = (now_msk() + timedelta(hours=hours)).isoformat()
        
        # Создаем кредит в базе
        cid = db.create_credit(self.author.id, self.target_user.id, amount, debt, percent, until)
        
        # Списываем деньги у кредитора
        #db.add_balance(self.author.id, -amount)
        #db.add_transaction(self.author.id, -amount, "admin", f"Выдан кредит #{cid} для {self.target_user.name}")
        
        # Отправляем красивое уведомление в канал
        embed = discord.Embed(
            title=f"💳 КРЕДИТНЫЙ ДОГОВОР #{cid}",
            description=(
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏦 **Кредитор:** {self.author.mention}\n"
                f"👤 **Заемщик:** {self.target_user.mention}\n"
                f"💰 **Сумма:** {fmt(amount)} {config.CURRENCY_EMOJI}\n"
                f"📈 **К возврату:** {fmt(debt)} {config.CURRENCY_EMOJI} ({percent}%)\n"
                f"⏳ **Срок:** {hours} ч.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)
        try:
            await self.target_user.send(
                f"💳 **Вам предложен кредит!**\n"
                f"Кредитор: {self.author.name}\n"
                f"Сумма к получению: **{fmt(amount)}** {config.CURRENCY_EMOJI}\n"
                f"Долг: **{fmt(debt)}** {config.CURRENCY_EMOJI}\n"
                f"Срок: {hours} ч.\n\n"
                f"Жмите кнопку ниже, чтобы принять.",
                view=CreditAcceptView(cid, self.author, self.target_user, amount, debt, percent, hours)
            )
        except Exception:
            pass
        
        # Пытаемся отправить в ЛС заемщику
        

@bot.tree.command(name="кредит", description="💳 Кредитный отдел (выдача и управление)")
async def credit_menu_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💳 КРЕДИТНЫЙ ОТДЕЛ БАНКА",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Добро пожаловать в кредитный отдел.\n"
            f"Здесь вы можете выдать кредит или посмотреть свои долги.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Клиент:** {interaction.user.mention}"
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, view=CreditPanelView(interaction.user.id))
   
   
@bot.tree.command(name="забрать_доступ", description="🔒 Забрать роль Админ или Dev")
@app_commands.describe(user="У кого забрать", role="Какую роль забрать")
@app_commands.choices(role=[
    app_commands.Choice(name="👑 Админ", value="admin"),
    app_commands.Choice(name="💎 Dev",   value="dev"),
])
async def revoke_access(interaction: discord.Interaction, user: discord.Member, role: app_commands.Choice[str]):
    if interaction.user.id not in config.OWNER_IDS:
        await interaction.response.send_message("❌ Только владелец может использовать эту команду.", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("❌ Ботам нельзя.", ephemeral=True)
        return

    if role.value == "admin":
        role_id = config.ADMIN_ROLE_ID
        role_name = "👑 Админ"
    else:
        role_id = config.DEV_ROLE_ID
        role_name = "💎 Dev"

    target_role = interaction.guild.get_role(role_id)
    if not target_role:
        await interaction.response.send_message(f"❌ Роль `{role_name}` не найдена.", ephemeral=True)
        return

    if target_role not in user.roles:
        await interaction.response.send_message(f"❌ У {user.mention} нет роли **{role_name}**.", ephemeral=True)
        return

    try:
        await user.remove_roles(target_role, reason=f"Снятие доступа от {interaction.user.name}")
        db.remove_bot_admin(user.id)
    except discord.Forbidden:
        await interaction.response.send_message("❌ У меня нет прав снять эту роль.", ephemeral=True)
        return

    await interaction.response.send_message(f"🔒 У {user.mention} забрана роль **{role_name}**.")
    
    
@bot.tree.command(name="обнулить_казну", description="⚖️ [ADMIN] Полностью обнулить казну")
@app_commands.default_permissions(administrator=True)
async def wipe_treasury(interaction: discord.Interaction):
    if not _is_staff(interaction.user):
        await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
        return

    # Забираем текущую сумму для отчета
    old_total = db.get_treasury()
    
    # Обнуляем в базе
    db.zero_treasury()
    
    # Отправляем красивый отчет
    embed = discord.Embed(
        title="⚖️ КАЗНА ОБНУЛЕНА",
        description=(
            f"Из казны изъято и сожжено: **{fmt(old_total)}** {config.CURRENCY_EMOJI}\n"
            f"Текущий баланс казны: **0** {config.CURRENCY_EMOJI}"
        ),
        color=discord.Color.dark_red()
    )
    embed.set_footer(text=f"Обнулил: {interaction.user.name}")
    
    await interaction.response.send_message(embed=embed)
    
# ============================================================
#                       ЗАПУСК
# ============================================================

if __name__ == "__main__":
    from casino import setup_casino
    from admin_panel import setup_admin_panel

    @bot.event
    async def on_ready():
        print(f"✅ Бот {bot.user} подключился!")
        
        try:
            if config.GUILD_ID:
                guild = discord.Object(id=config.GUILD_ID)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
            else:
                synced = await bot.tree.sync()
            print(f"✅ Синхронизировано {len(synced)} команд")
        except Exception as e:
            print(f"❌ Ошибка синхронизации: {e}")

        # Запуск фоновых задач (кредиты, казна)
        bot.loop.create_task(bankrupt_checker())
        bot.loop.create_task(credit_checker())

    setup_casino(bot)
    setup_admin_panel(bot)
    bot.run(config.TOKEN)