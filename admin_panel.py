import discord
from discord import app_commands

import config
import database as db


def fmt(amount) -> str:
    if isinstance(amount, float):
        return f"{amount:,.2f}".replace(",", " ")
    return f"{amount:,}".replace(",", " ")


def fmt_btc(amount: float) -> str:
    return f"{amount:.8f}"


def get_user_tag(member: discord.Member) -> str:
    if not isinstance(member, discord.Member):
        return ""
    tags = []
    ids = {r.id for r in member.roles}
    if config.ADMIN_ROLE_ID in ids:
        tags.append("👑 Админ")
    if config.DEV_ROLE_ID in ids:
        tags.append("💎 Dev")
    return " • ".join(tags)


def actor_label(member) -> str:
    if not isinstance(member, discord.Member):
        return f"@{getattr(member, 'name', '?')}"
    tag = get_user_tag(member)
    return tag if tag else member.mention


def log_admin(actor, category: str, action: str, target_id: int = None, details: str = ""):
    try:
        uid = actor.id if isinstance(actor, (discord.Member, discord.User)) else None
        db.add_admin_log(uid, category, action, target_id, details)
    except Exception as e:
        print(f"⚠️ log_admin: {e}")


def _is_staff(member: discord.Member) -> bool:
    if member.id in config.OWNER_IDS:
        return True
    # Проверяем базу данных бота
    db_role = db.get_bot_admin_role(member.id)
    return db_role in ("admin", "dev")


def _is_dev_or_owner(member: discord.Member) -> bool:
    if member.id in config.OWNER_IDS:
        return True
    # Только те, кому бот выдал Dev
    return db.get_bot_admin_role(member.id) == "dev"


def make_panel_main() -> discord.Embed:
    return discord.Embed(
        title="🛠 АДМИН-ПАНЕЛЬ",
        description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери раздел:",
        color=discord.Color.dark_red()
    ).set_footer(text="Банк • панель управления")


# ============================================================
#                    ГЛАВНОЕ МЕНЮ
# ============================================================

class AdminMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

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
                "❌ Только Dev/Owner.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🛠 Сервис",
            description="━━━━━━━━━━━━━━━━━━━━━━\nТолько Dev/Owner:",
            color=discord.Color.dark_red()
        )
        await interaction.response.edit_message(embed=embed, view=ServiceView())

    @discord.ui.button(label="🕵️ Чёрный ящик", style=discord.ButtonStyle.danger, row=1)
    async def blackbox(self, interaction, button):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message(
                "❌ Только Dev/Owner.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🕵️ Чёрный ящик",
            description="━━━━━━━━━━━━━━━━━━━━━━\nВыбери категорию:",
            color=discord.Color.dark_gray()
        )
        await interaction.response.edit_message(embed=embed, view=BlackBoxCategoryView())


# ============================================================
#                    ПОИСК ЮЗЕРА
# ============================================================

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
        user = member or await interaction.client.fetch_user(uid)
        if not user:
            await interaction.response.send_message("❌ Юзер не найден.", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=make_user_card(uid, user, member),
            view=UserCardView(uid),
            ephemeral=True
        )


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
                "❌ Изменение баланса — только для Dev/Owner.", ephemeral=True
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
        log_admin(interaction.user, "economy", "Панель: баланс", self.uid, str(amount))
        await interaction.response.send_message(
            f"✅ <@{self.uid}>: **{'+' if amount >= 0 else ''}{fmt(amount)}** → баланс **{fmt(new)}**",
            ephemeral=True
        )


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
        log_admin(interaction.user, "people", f"Панель: роль {role_name}", self.uid, "")
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
        user = member or await interaction.client.fetch_user(self.uid)
        await interaction.response.edit_message(
            embed=make_user_card(self.uid, user, member),
            view=(self.uid)
        )


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
        user = member or await interaction.client.fetch_user(self.uid)
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
        log_admin(interaction.user, "biz", "Панель: выдать бизнес", self.uid, biz_type)
        await interaction.response.send_message(
            f"✅ <@{self.uid}> выдан **{info['name']}**",
            ephemeral=True
        )


class TakeBizModal(discord.ui.Modal):
    def __init__(self, uid: int):
        super().__init__(title="Забрать бизнес")
        self.uid = uid
        self.biz_id_input = discord.ui.TextInput(label="ID бизнеса", max_length=15)
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
        log_admin(interaction.user, "biz", "Панель: забрать бизнес", self.uid, biz[1])
        await interaction.response.send_message(
            f"➖ У <@{self.uid}> изъят **{info.get('name', biz[1])}**",
            ephemeral=True
        )


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
        log_admin(interaction.user, "people", "Панель: разморозка", self.uid, "")
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
        log_admin(interaction.user, "people", "Панель: освобождение", self.uid, "")
        await interaction.response.send_message(f"✅ <@{self.uid}> освобождён.", ephemeral=True)

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        member = interaction.guild.get_member(self.uid)
        user = member or await interaction.client.fetch_user(self.uid)
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
        log_admin(interaction.user, "people", "Панель: заморозка", self.uid, self.reason.value)
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
        log_admin(interaction.user, "people", "Панель: тюрьма", self.uid, f"{minutes}м {self.reason.value}")
        await interaction.response.send_message(
            f"🚔 <@{self.uid}> в тюрьме на {minutes} мин: {self.reason.value}",
            ephemeral=True
        )


# ============================================================
#                    ЛОГ
# ============================================================

class LogFilterModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Лог транзакций")
        self.user_input = discord.ui.TextInput(
            label="ID юзера (пусто = по всем)", required=False, max_length=25
        )
        self.limit_input = discord.ui.TextInput(
            label="Количество (5-50)", default="20", max_length=2
        )
        self.hours_input = discord.ui.TextInput(
            label="За сколько часов", default="48", max_length=4
        )
        self.add_item(self.user_input)
        self.add_item(self.limit_input)
        self.add_item(self.hours_input)

    async def on_submit(self, interaction):
        try:
            limit = max(5, min(int(self.limit_input.value or "20"), 50))
            hours = max(1, min(int(self.hours_input.value or "48"), 720))
        except ValueError:
            await interaction.response.send_message("❌ Неверные числа.", ephemeral=True)
            return

        user_id = None
        if self.user_input.value.strip():
            try:
                user_id = int(self.user_input.value.strip())
            except ValueError:
                await interaction.response.send_message("❌ ID — число.", ephemeral=True)
                return

        txs = db.get_all_transactions(limit=limit, user_id=user_id)
        if not txs:
            await interaction.response.send_message("📜 Пусто.", ephemeral=True)
            return

        emoji_map = {
            "transfer": "💸", "shop": "🛒", "admin": "⚖️", "casino": "🎰",
            "issue": "💵", "biz": "🏭", "exchange": "💱", "steal": "🥷", "stock": "📈"
        }
        lines = []
        for uid, amount, ttype, desc, created in txs:
            e = emoji_map.get(ttype, "💼")
            sign = "+" if amount > 0 else ""
            try:
                dt = db.parse_dt(created)
                date = dt.strftime("%d.%m %H:%M")
            except Exception:
                date = created[5:16].replace("T", " ")
            lines.append(f"{e} `{date}` <@{uid}> {sign}**{fmt(amount)}** — {desc or ttype}")

        if len(lines) > 30:
            lines = lines[:30] + [f"... ещё {len(txs) - 30}"]

        embed = discord.Embed(
            title="📜 Лог транзакций",
            description="━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) + "\n━━━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.dark_red()
        )
        embed.set_footer(text=f"Всего: {len(txs)} • период: до {hours} ч")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#                    УТИЛИТЫ
# ============================================================

class UtilitiesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🧹 Очистить транзакции", style=discord.ButtonStyle.danger)
    async def clear_tx(self, interaction, button):
        await interaction.response.send_modal(ClearTxModal())

    @discord.ui.button(label="⏱ Сброс КД", style=discord.ButtonStyle.primary)
    async def reset_cd(self, interaction, button):
        await interaction.response.send_modal(ResetCdModal())

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=make_panel_main(), view=AdminMainView())


class ClearTxModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Очистить транзакции")
        self.user_input = discord.ui.TextInput(label="ID юзера", max_length=25)
        self.mode_input = discord.ui.TextInput(
            label="Режим: 48 / all", default="48", max_length=5
        )
        self.add_item(self.user_input)
        self.add_item(self.mode_input)

    async def on_submit(self, interaction):
        try:
            uid = int(self.user_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID — число.", ephemeral=True)
            return
        mode = self.mode_input.value.strip().lower()
        if mode == "all":
            deleted = db.clear_all_transactions(uid)
        else:
            deleted = db.clear_transactions(uid, hours=48)
        log_admin(interaction.user, "panel", "Очистка tx", uid, f"{deleted}")
        await interaction.response.send_message(
            f"🧹 Удалено **{deleted}** транзакций у <@{uid}>.", ephemeral=True
        )


class ResetCdModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Сбросить кулдауны")
        self.user_input = discord.ui.TextInput(label="ID юзера", max_length=25)
        self.add_item(self.user_input)

    async def on_submit(self, interaction):
        try:
            uid = int(self.user_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID — число.", ephemeral=True)
            return
        db.set_last_steal(uid, None)
        db.set_last_salary(uid, None)
        db.set_treasury_cooldown(uid, None)
        db.set_last_biz_income(uid, None)
        log_admin(interaction.user, "panel", "Сброс КД", uid, "")
        await interaction.response.send_message(f"⏱ КД сброшены для <@{uid}>.", ephemeral=True)


# ============================================================
#                    СЕРВИС
# ============================================================

class ServiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not _is_dev_or_owner(interaction.user):
            await interaction.response.send_message(
                "❌ Только Dev/Owner.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🔁 Синхронизировать команды", style=discord.ButtonStyle.success)
    async def sync_cmds(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            if config.GUILD_ID:
                guild = discord.Object(id=config.GUILD_ID)
                interaction.client.tree.copy_global_to(guild=guild)
                synced = await interaction.client.tree.sync(guild=guild)
            else:
                synced = await interaction.client.tree.sync()
            await interaction.followup.send(
                f"✅ Синхронизировано **{len(synced)}** команд.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=make_panel_main(), view=AdminMainView())


# ============================================================
#                    ЧЁРНЫЙ ЯЩИК
# ============================================================

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
#                    РЕГИСТРАЦИЯ
# ============================================================

def setup_admin_panel(bot):
    @bot.tree.command(name="админ_панель", description="🛠 Админ-панель банка")
    async def admin_panel(interaction: discord.Interaction):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ Только для Админ/Dev.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=make_panel_main(),
            view=AdminMainView(),
            ephemeral=True
        )