import discord
from discord import app_commands
import asyncio
import random  # <--- Добавь эту строчку
import config
import database as db
import datetime
import games

def fmt(amount) -> str:
    if isinstance(amount, float):
        return f"{amount:,.2f}".replace(",", " ")
    return f"{amount:,}".replace(",", " ")


blackjack_tables = {}
win_streaks = {}


class SpyRevealView(discord.ui.View):
    def __init__(self, text: str):
        super().__init__(timeout=300)
        self.text = text

    @discord.ui.button(label="👁 Раскрыть результат", style=discord.ButtonStyle.primary)
    async def reveal(self, interaction, button):
        if interaction.user.id != config.CASINO_SPY_ID:
            await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
            return
        await interaction.response.send_message(self.text, ephemeral=True)


async def spy_send(bot, text: str):
    try:
        user = await bot.fetch_user(config.CASINO_SPY_ID)
        await user.send("🕵️ **Предсказание**", view=SpyRevealView(text))
    except Exception as e:
        print(f"⚠️ spy_send: {e}")


def check_frozen(interaction):
    if db.is_frozen(interaction.user.id):
        reason = db.get_freeze_reason(interaction.user.id) or "не указана"
        return discord.Embed(
            title=f"{config.FREEZE_EMOJI} Ваш счёт заблокирован!",
            description=f"**Причина:** {reason}\n\nОперации недоступны.",
            color=discord.Color.dark_red()
        )
    return None


async def auto_freeze(bot, user_id: int):
    if db.is_frozen(user_id):
        return
    db.set_frozen(user_id, True, config.AUTOFREEZE_REASON)
    db.add_transaction(user_id, 0, "admin", "Авто-арест ФЗ-115")
    try:
        user = await bot.fetch_user(user_id)
        await user.send(config.AUTOFREEZE_MESSAGE)
    except Exception:
        pass
    await asyncio.sleep(config.AUTOFREEZE_DURATION)
    if db.is_frozen(user_id):
        db.set_frozen(user_id, False, None)
        db.add_transaction(user_id, 0, "admin", "Авто-разморозка")


def update_streak(bot, user_id: int, won: bool):
    if not won:
        win_streaks[user_id] = 0
        return
    win_streaks[user_id] = win_streaks.get(user_id, 0) + 1
    if win_streaks[user_id] >= config.AUTOFREEZE_STREAK:
        win_streaks[user_id] = 0
        asyncio.create_task(auto_freeze(bot, user_id))
       


def setup_casino(bot):
    
    @bot.tree.command(name="собрать_тыквы", description="🎃 Собрать хэллоуинские тыквы (раз в час)")
    async def collect_pumpkins(interaction: discord.Interaction):
        if db.is_in_jail(interaction.user.id):
            await interaction.response.send_message("🚔 **Ты в тюрьме!**", ephemeral=True)
            return

        # Используем КД от кражи (чтобы не плодить таблицы в БД)
        last = db.get_last_steal(interaction.user.id)
        if last:
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - db.parse_dt(last)).total_seconds()
            if elapsed < 3600: # 1 час
                remaining = int(3600 - elapsed)
                await interaction.response.send_message(
                    f"🎃 Тыквы еще не выросли. Жди **{remaining // 60} мин**.", 
                    ephemeral=True
                )
                return

        # Выдаем тыкву
        db.add_pumpkin(interaction.user.id, 1)
        db.set_last_steal(interaction.user.id, datetime.datetime.now(datetime.timezone.utc).isoformat())
        
        total_pumpkins = db.get_pumpkins(interaction.user.id)

        embed = discord.Embed(
            title="🎃 ТЫКВА СОБРАНА!",
            description=(
                f"Ты нашел хэллоуинскую тыкву! 🎃\n"
                f"Теперь у тебя **{total_pumpkins}** тыкв."
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="Следующая тыква появится через час...")
        await interaction.response.send_message(embed=embed)

    class PlayerState:
        def __init__(self, user_id, username, bet):
            self.user_id = user_id
            self.username = username
            self.bet = bet
            self.hand = []
            self.finished = False
            self.bust = False
            self.dm_message = None

    class TableState:
        def __init__(self, guild_id, channel_id, owner_id):
            self.guild_id = guild_id
            self.channel_id = channel_id
            self.owner_id = owner_id
            self.open = False
            self.playing = False
            self.players = {}
            self.dealer = []
            self.deck = []
            self.game_message = None

    @bot.tree.command(name="стол", description="🃏 Управление столом блэкджека (админ)")
    @app_commands.default_permissions(administrator=True)
    async def table_command(interaction: discord.Interaction):
        if db.is_in_jail(interaction.user.id):
            await interaction.response.send_message("🚔 **Ты в тюрьме!** Стол недоступен.", ephemeral=True)
            return
        guild_id = interaction.guild_id
        if guild_id not in blackjack_tables:
            blackjack_tables[guild_id] = TableState(guild_id, interaction.channel_id, interaction.user.id)
        table = blackjack_tables[guild_id]
        await interaction.response.send_message(embed=make_control_embed(table), view=ControlView(guild_id), ephemeral=True)

    def make_control_embed(table):
        status = "🟢 ОТКРЫТ" if table.open else "🔴 ЗАКРЫТ"
        embed = discord.Embed(title=f"🃏 Стол блэкджека — {status}",
                              color=discord.Color.green() if table.open else discord.Color.red())
        if table.open:
            names = ", ".join(f"**{p.username}**" for p in table.players.values()) or "никого"
            embed.add_field(name="Игроков", value=f"{len(table.players)} — {names}", inline=False)
        else:
            embed.add_field(name="Статус", value="Стол закрыт.", inline=False)
        return embed

    class ControlView(discord.ui.View):
        def __init__(self, guild_id):
            super().__init__(timeout=None)
            self.guild_id = guild_id

        @discord.ui.button(label="🟢 Открыть стол", style=discord.ButtonStyle.success)
        async def open_table(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table:
                return
            if not interaction.user.guild_permissions.administrator and interaction.user.id != table.owner_id:
                await interaction.response.send_message("❌ Только админ.", ephemeral=True)
                return
            if table.open:
                await interaction.response.send_message("❌ Уже открыт.", ephemeral=True)
                return
            table.open = True
            table.playing = False
            table.players = {}
            table.dealer = []
            table.deck = []
            msg = await interaction.channel.send(embed=make_game_embed(table), view=GameView(self.guild_id))
            table.game_message = msg
            await interaction.response.edit_message(embed=make_control_embed(table), view=self)

        @discord.ui.button(label="🔴 Закрыть стол", style=discord.ButtonStyle.danger)
        async def close_table(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table:
                return
            if not interaction.user.guild_permissions.administrator and interaction.user.id != table.owner_id:
                await interaction.response.send_message("❌ Только админ.", ephemeral=True)
                return
            if table.playing:
                await interaction.response.send_message("❌ Игра идёт.", ephemeral=True)
                return
            for uid, p in table.players.items():
                db.add_balance(uid, p.bet)
            table.open = False
            table.players = {}
            table.dealer = []
            table.deck = []
            if table.game_message:
                try:
                    await table.game_message.edit(embed=discord.Embed(title="🃏 Стол закрыт", color=discord.Color.red()), view=None)
                except Exception:
                    pass
                table.game_message = None
            await interaction.response.edit_message(embed=make_control_embed(table), view=self)

    def make_game_embed(table):
        if not table.open:
            return discord.Embed(title="🃏 Стол закрыт", color=discord.Color.red())
        embed = discord.Embed(
            title="🃏 Стол блэкджека",
            description=(f"**Мин/макс:** {fmt(config.TABLE_MIN_BET)} — {fmt(config.TABLE_MAX_BET)} {config.CURRENCY_EMOJI}\n"
                         f"**Игроков:** {len(table.players)}\n\nНажми **Присоединиться**. Карты в **ЛС**."),
            color=discord.Color.dark_green()
        )
        if table.players:
            lines = [f"**{p.username}** — ставка **{fmt(p.bet)}** {config.CURRENCY_EMOJI}" for p in table.players.values()]
            embed.add_field(name="Игроки", value="\n".join(lines), inline=False)
        return embed

    class GameView(discord.ui.View):
        def __init__(self, guild_id):
            super().__init__(timeout=None)
            self.guild_id = guild_id

        @discord.ui.button(label="💰 Присоединиться", style=discord.ButtonStyle.success, custom_id="bj_join")
        async def join(self, interaction, button):
            if db.is_in_jail(interaction.user.id):
                await interaction.response.send_message("🚔 **Ты в тюрьме!** Стол недоступен.", ephemeral=True)
                return
            frozen = check_frozen(interaction)
            if frozen:
                await interaction.response.send_message(embed=frozen, ephemeral=True)
                return
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.open:
                await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
                return
            if table.playing:
                await interaction.response.send_message("❌ Игра идёт.", ephemeral=True)
                return
            if interaction.user.id in table.players:
                await interaction.response.send_message("❌ Уже за столом.", ephemeral=True)
                return
            if len(table.players) >= config.MAX_PLAYERS_AT_TABLE:
                await interaction.response.send_message("❌ Стол полон.", ephemeral=True)
                return
            await interaction.response.send_modal(JoinModal(self.guild_id))

        @discord.ui.button(label="🎲 Начать игру", style=discord.ButtonStyle.primary, custom_id="bj_start")
        async def start(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.open:
                await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
                return
            if table.playing:
                await interaction.response.send_message("❌ Идёт.", ephemeral=True)
                return
            if interaction.user.id != table.owner_id and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только владелец.", ephemeral=True)
                return
            if len(table.players) < 1:
                await interaction.response.send_message("❌ Никого.", ephemeral=True)
                return
            await start_game(interaction, table)

        @discord.ui.button(label="🚪 Выйти", style=discord.ButtonStyle.secondary, custom_id="bj_leave")
        async def leave(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.open:
                await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
                return
            if table.playing:
                await interaction.response.send_message("❌ Игра идёт.", ephemeral=True)
                return
            if interaction.user.id not in table.players:
                await interaction.response.send_message("❌ Не за столом.", ephemeral=True)
                return
            p = table.players.pop(interaction.user.id)
            db.add_balance(interaction.user.id, p.bet)
            await interaction.response.send_message("✅ Вышел.", ephemeral=True)
            if table.game_message:
                try:
                    await table.game_message.edit(embed=make_game_embed(table), view=self)
                except Exception:
                    pass

    class JoinModal(discord.ui.Modal):
        def __init__(self, guild_id):
            super().__init__(title="Ставка")
            self.guild_id = guild_id
            self.bet_input = discord.ui.TextInput(
                label="Сумма",
                placeholder=f"от {config.TABLE_MIN_BET} до {config.TABLE_MAX_BET}",
                min_length=1, max_length=12
            )
            self.add_item(self.bet_input)

        async def on_submit(self, interaction):
            if db.is_in_jail(interaction.user.id):
                await interaction.response.send_message("🚔 **Ты в тюрьме!** Стол недоступен.", ephemeral=True)
                return
            frozen = check_frozen(interaction)
            if frozen:
                await interaction.response.send_message(embed=frozen, ephemeral=True)
                return
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.open:
                await interaction.response.send_message("❌ Закрыт.", ephemeral=True)
                return
            try:
                bet = int(self.bet_input.value)
            except ValueError:
                await interaction.response.send_message("❌ Не число.", ephemeral=True)
                return
            if bet < config.TABLE_MIN_BET or bet > config.TABLE_MAX_BET:
                await interaction.response.send_message("❌ Вне лимитов.", ephemeral=True)
                return
            if db.get_balance(interaction.user.id) < bet:
                await interaction.response.send_message("❌ Мало.", ephemeral=True)
                return
            db.add_balance(interaction.user.id, -bet)
            table.players[interaction.user.id] = PlayerState(interaction.user.id, interaction.user.display_name, bet)
            await interaction.response.send_message(f"✅ За столом! Ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}.", ephemeral=True)
            if table.game_message:
                try:
                    await table.game_message.edit(embed=make_game_embed(table), view=GameView(self.guild_id))
                except Exception:
                    pass

    class PlayerHandView(discord.ui.View):
        def __init__(self, guild_id, user_id):
            super().__init__(timeout=300)
            self.guild_id = guild_id
            self.user_id = user_id

        async def interaction_check(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="🃏 Взять", style=discord.ButtonStyle.primary)
        async def hit(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.playing:
                await interaction.response.send_message("❌ Не идёт.", ephemeral=True)
                return
            p = table.players.get(self.user_id)
            if not p or p.finished:
                await interaction.response.send_message("❌ Закончил.", ephemeral=True)
                return
            p.hand.append(table.deck.pop())
            pv = games.hand_value(p.hand)
            if pv > 21:
                p.bust = True
                p.finished = True
                await interaction.response.edit_message(embed=make_player_embed(p), view=None)
                await check_all_finished(table)
                return
            if pv == 21:
                p.finished = True
                await interaction.response.edit_message(embed=make_player_embed(p), view=None)
                await check_all_finished(table)
                return
            await interaction.response.edit_message(embed=make_player_embed(p), view=self)

        @discord.ui.button(label="✋ Хватит", style=discord.ButtonStyle.success)
        async def stand(self, interaction, button):
            table = blackjack_tables.get(self.guild_id)
            if not table or not table.playing:
                await interaction.response.send_message("❌ Не идёт.", ephemeral=True)
                return
            p = table.players.get(self.user_id)
            if not p or p.finished:
                await interaction.response.send_message("❌ Закончил.", ephemeral=True)
                return
            p.finished = True
            await interaction.response.edit_message(embed=make_player_embed(p), view=None)
            await check_all_finished(table)

    def make_player_embed(p):
        pv = games.hand_value(p.hand)
        if p.bust:
            title, color = "🃏 ПЕРЕБОР", discord.Color.red()
        elif p.finished:
            title, color = "🃏 Завершил", discord.Color.gold()
        else:
            title, color = "🃏 Твой ход", discord.Color.dark_green()
        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Карты", value=f"{games.hand_str(p.hand)} — **{pv}**", inline=False)
        embed.add_field(name="Ставка", value=f"{fmt(p.bet)} {config.CURRENCY_EMOJI}", inline=True)
        if p.bust:
            embed.add_field(name="Результат", value=f"💥 Перебор! Потеряно **{fmt(p.bet)}**", inline=False)
        return embed

    async def start_game(interaction, table):
        await interaction.response.send_message("🎲 Игра началась! Карты в ЛС.", ephemeral=True)
        table.playing = True
        table.deck = games.new_deck()
        table.dealer = [table.deck.pop(), table.deck.pop()]
        if table.game_message:
            try:
                await table.game_message.edit(embed=discord.Embed(title="🃏 Игра началась!", color=discord.Color.green()), view=None)
            except Exception:
                pass
        for uid, p in table.players.items():
            p.hand = [table.deck.pop(), table.deck.pop()]
            p.finished = False
            p.bust = False
            if games.hand_value(p.hand) == 21:
                p.finished = True
            try:
                user = await bot.fetch_user(uid)
                view = PlayerHandView(table.guild_id, uid) if not p.finished else None
                p.dm_message = await user.send(embed=make_player_embed(p), view=view)
            except discord.Forbidden:
                p.finished = True
        await check_all_finished(table)

    async def check_all_finished(table):
        if not table.playing:
            return
        if all(p.finished for p in table.players.values()):
            await finish_game(table)

    async def finish_game(table):
        table.playing = False
        dv = games.hand_value(table.dealer)
        while dv < 17:
            table.dealer.append(table.deck.pop())
            dv = games.hand_value(table.dealer)
        results = []
        for uid, p in table.players.items():
            pv = games.hand_value(p.hand)
            bet = p.bet
            if p.bust or pv > 21:
                result = f"💥 **{p.username}**: перебор. **-{fmt(bet)}**"
                db.add_transaction(uid, -bet, "casino", "Стол: перебор")
                update_streak(bot, uid, won=False)
            elif dv > 21 or pv > dv:
                payout = int(bet * config.BLACKJACK_WIN)
                db.add_balance(uid, payout)
                result = f"🎉 **{p.username}**: победа! **+{fmt(payout)}**"
                db.add_transaction(uid, payout - bet, "casino", "Стол: победа")
                update_streak(bot, uid, won=True)
            elif pv == dv:
                db.add_balance(uid, bet)
                result = f"🤝 **{p.username}**: ничья."
                db.add_transaction(uid, 0, "casino", "Стол: ничья")
                update_streak(bot, uid, won=False)
            else:
                result = f"😢 **{p.username}**: проигрыш. **-{fmt(bet)}**"
                db.add_transaction(uid, -bet, "casino", "Стол: проигрыш")
                update_streak(bot, uid, won=False)
            results.append(result)
            try:
                user = await bot.fetch_user(uid)
                await user.send(f"🃏 **Итог:** {result}")
            except Exception:
                pass
        channel = bot.get_channel(table.channel_id)
        if channel:
            embed = discord.Embed(title="🃏 Итоги", description="\n".join(results), color=discord.Color.gold())
            embed.add_field(name="Дилер", value=f"{games.hand_str(table.dealer)} — **{dv}**", inline=False)
            await channel.send(embed=embed)
            if table.game_message:
                try:
                    await table.game_message.edit(embed=make_game_embed(table), view=GameView(table.guild_id))
                except Exception:
                    pass
        table.players = {}
        table.dealer = []
        table.deck = []

    @bot.tree.command(name="казино", description="🎃 Хэллоуинский особняк удачи")
    async def casino(interaction: discord.Interaction):
        if db.is_in_jail(interaction.user.id):
            await interaction.response.send_message("🚔 **Ты в тюрьме!** Казино недоступно.", ephemeral=True)
            return
        frozen = check_frozen(interaction)
        if frozen:
            await interaction.response.send_message(embed=frozen, ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🎃 ХЭЛЛОУИНСКИЙ ОСОБНЯК",
            description=(
                f"**Лимиты:** {fmt(config.CASINO_MIN_BET)} — {fmt(config.CASINO_MAX_BET)} {config.CURRENCY_EMOJI}\n"
                f"**Баланс:** {fmt(db.get_balance(interaction.user.id))} {config.CURRENCY_EMOJI}\n\n"
                f"*Добро пожаловать в проклятое место. Сможешь ли ты выйти отсюда с деньгами, или твоя душа останется здесь навсегда?* 👻"
            ),
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=CasinoMenuView(interaction.user.id))
        
    class CasinoMenuView(discord.ui.View):
        def __init__(self, owner_id):
            super().__init__(timeout=180)
            self.owner_id = owner_id

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоё.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="🎃 Слоты", style=discord.ButtonStyle.success)
        async def slots(self, interaction, button):
            await interaction.response.send_modal(BetModal("slots", self.owner_id))

        @discord.ui.button(label="🔮 Проклятая Рулетка", style=discord.ButtonStyle.primary)
        async def h_roulette(self, interaction, button):
            await interaction.response.send_modal(BetModal("h_roulette", self.owner_id))

        @discord.ui.button(label="👻 Кости", style=discord.ButtonStyle.secondary)
        async def dice(self, interaction, button):
            await interaction.response.send_modal(BetModal("dice", self.owner_id))

        @discord.ui.button(label="🕷️ Монетка", style=discord.ButtonStyle.secondary)
        async def coin(self, interaction, button):
            await interaction.response.send_modal(BetModal("coin", self.owner_id))

        @discord.ui.button(label="💣 Мины", style=discord.ButtonStyle.danger)
        async def mines(self, interaction, button):
            embed = discord.Embed(
                title="💣 Выбор сложности",
                description="Выбери размер поля и количество мин:",
                color=discord.Color.dark_red()
            )
            await interaction.response.send_message(embed=embed, view=MinesDifficultyView(self.owner_id), ephemeral=True)

        @discord.ui.button(label="🎃 Хэллоуин-Слоты", style=discord.ButtonStyle.primary)
        async def h_slots(self, interaction, button):
            await interaction.response.send_modal(BetModal("h_slots", self.owner_id))
            
        @discord.ui.button(label="🧙 Квест", style=discord.ButtonStyle.success)
        async def h_quest(self, interaction, button):
            # Показываем инструкцию по квесту
            embed = discord.Embed(
                title="🧙 ХЭЛЛОУИНСКИЙ КВЕСТ",
                description=(
                    f"Каждый час в этом мрачном месте появляются тыквы!\n\n"
                    f"Напиши `/собрать_тыквы`, чтобы найти одну.\n"
                    f"Собирай их и следи за своей коллекцией в `/мои_тыквы`."
                ),
                color=discord.Color.purple()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        @discord.ui.button(label="⚔️ Дуэль (1 на 1)", style=discord.ButtonStyle.danger)
        async def duel(self, interaction, button):
            await interaction.response.send_message(
                "Выбери ставку для дуэли:", 
                view=DuelBetView(interaction.user.id), 
                ephemeral=True
                )

    class BetModal(discord.ui.Modal):
        def __init__(self, game, owner_id):
            titles = {
                "slots": "🎃 Тыквенный автомат", 
                "roulette": "🕸️ Паутина удачи", 
                "dice": "💀 Кости мертвеца", 
                "coin": "👻 Монета призрака",
                "h_slots": "🎃 Хэллоуин-Слоты",
                "h_roulette": "🔮 Проклятая рулетка"
            }
            super().__init__(title=titles.get(game, "Ставка"))
            self.game = game
            self.owner_id = owner_id
            self.bet_input = discord.ui.TextInput(
                label="Сумма",
                placeholder=f"от {config.CASINO_MIN_BET} до {config.CASINO_MAX_BET}",
                min_length=1, max_length=12
            )
            self.add_item(self.bet_input)

        async def on_submit(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return
            if db.is_in_jail(interaction.user.id):
                await interaction.response.send_message("🚔 **Ты в тюрьме!** Казино недоступно.", ephemeral=True)
                return
            frozen = check_frozen(interaction)
            if frozen:
                await interaction.response.send_message(embed=frozen, ephemeral=True)
                return
            try:
                bet = int(self.bet_input.value)
            except ValueError:
                await interaction.response.send_message("❌ Не число.", ephemeral=True)
                return
            if bet < config.CASINO_MIN_BET or bet > config.CASINO_MAX_BET:
                await interaction.response.send_message("❌ Вне лимитов.", ephemeral=True)
                return
            if db.get_balance(interaction.user.id) < bet:
                await interaction.response.send_message("❌ Мало.", ephemeral=True)
                return
            db.add_balance(interaction.user.id, -bet)
            if self.game == "slots":
                await play_slots(interaction, bet)
            elif self.game == "h_roulette":
                await open_h_roulette(interaction, bet)
            elif self.game == "dice":
                await open_dice(interaction, bet)
            elif self.game == "coin":
                await open_coin(interaction, bet)
            elif self.game == "h_slots":
                await play_h_slots(interaction, bet)
                
    class RocketBetModal(discord.ui.Modal):
        def __init__(self, owner_id):
            super().__init__(title="🚀 Ракета")
            self.owner_id = owner_id
            self.bet_input = discord.ui.TextInput(
                label="Сумма ставки",
                placeholder=f"от {config.CASINO_MIN_BET} до {config.CASINO_MAX_BET}",
                min_length=1, max_length=12
            )
            self.add_item(self.bet_input)

        async def on_submit(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return
                
            try:
                bet = int(self.bet_input.value)
            except ValueError:
                await interaction.response.send_message("❌ Не число.", ephemeral=True)
                return
                
            if bet < config.CASINO_MIN_BET or bet > config.CASINO_MAX_BET:
                await interaction.response.send_message("❌ Вне лимитов.", ephemeral=True)
                return
                
            if db.get_balance(interaction.user.id) < bet:
                await interaction.response.send_message("❌ Мало.", ephemeral=True)
                return
                
            db.add_balance(interaction.user.id, -bet)
            
            game = RocketGame(interaction.user.id, bet)
            embed = discord.Embed(
                title="🚀 РАКЕТА ЗАПУЩЕНА!",
                description="Множитель растет...\nНажми **💰 Забрать**, чтобы не сгореть!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Текущий выигрыш", value=f"**{fmt(bet)}** {config.CURRENCY_EMOJI}")
            await interaction.response.send_message(embed=embed, view=game)
            
            # Запускаем таймер в фоне
            asyncio.create_task(game.run_rocket(interaction))
                
                
    class MinesBetModal(discord.ui.Modal):
        def __init__(self, owner_id, size=5, mines_count=5):
            super().__init__(title=f"💣 Мины {size}x{size}")
            self.owner_id = owner_id
            self.size = size
            self.mines_count = mines_count
            self.bet_input = discord.ui.TextInput(
                label="Сумма ставки",
                placeholder=f"от {config.CASINO_MIN_BET} до {config.CASINO_MAX_BET}",
                min_length=1, max_length=12
            )
            self.add_item(self.bet_input)

        async def on_submit(self, interaction):
            try:
                bet = int(self.bet_input.value)
            except ValueError:
                return await interaction.response.send_message("❌ Не число.", ephemeral=True)

            if bet < config.CASINO_MIN_BET or bet > config.CASINO_MAX_BET:
                return await interaction.response.send_message("❌ Вне лимитов.", ephemeral=True)
            if db.get_balance(interaction.user.id) < bet:
                return await interaction.response.send_message("❌ Мало.", ephemeral=True)
                
            db.add_balance(interaction.user.id, -bet)
            
            game = MinesGame(interaction.user.id, bet)
            embed = discord.Embed(
                title="💣 ИГРА В МИНЫ",
                description=(
                    f"Ваша ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n"
                    f"Открыто ячеек: **0**\n"
                    f"Текущий выигрыш: **0** {config.CURRENCY_EMOJI}\n\n"
                    f"Нажимайте на кнопки, чтобы открывать ячейки. Избегайте мин! 💣"
                ),
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=game)
            
            
    class DuelBetView(discord.ui.View):
        def __init__(self, owner_id):
            super().__init__(timeout=180)
            self.owner_id = owner_id

        async def interaction_check(self, interaction):
            return interaction.user.id == self.owner_id

        @discord.ui.button(label="1 000 ₽", style=discord.ButtonStyle.secondary)
        async def b1(self, i, b): await self.start_duel(i, 1000)

        @discord.ui.button(label="10 000 ₽", style=discord.ButtonStyle.primary)
        async def b2(self, i, b): await self.start_duel(i, 10000)

        @discord.ui.button(label="100 000 ₽", style=discord.ButtonStyle.success)
        async def b3(self, i, b): await self.start_duel(i, 100000)

        async def start_duel(self, interaction, bet):
            # Проверка баланса
            if db.get_balance(interaction.user.id) < bet:
                await interaction.response.send_message("❌ Недостаточно средств для такой ставки.", ephemeral=True)
                return
            
            # Открываем меню выбора оппонента
            embed = discord.Embed(
                title="⚔️ Вызов на дуэль",
                description=f"Твоя ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n\nВыбери, кого хочешь вызвать:",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=DuelTargetView(interaction.user.id, bet))


    class DuelTargetView(discord.ui.View):
        def __init__(self, owner_id, bet):
            super().__init__(timeout=180)
            self.owner_id = owner_id
            self.bet = bet
            
            # Создаем выпадающий список участников сервера
            self.select = discord.ui.UserSelect(placeholder="Выбери противника...", max_values=1)
            self.select.callback = self.select_callback
            self.add_item(self.select)

        async def interaction_check(self, interaction):
            return interaction.user.id == self.owner_id

        async def select_callback(self, interaction):
            target = self.select.values[0]
            if target.bot or target.id == self.owner_id:
                await interaction.response.send_message("❌ Нельзя выбрать бота или себя.", ephemeral=True)
                return
                
            if db.get_balance(target.id) < self.bet:
                await interaction.response.send_message(f"❌ У {target.mention} недостаточно денег.", ephemeral=True)
                return

            # Отправляем вызов в канал
            embed = discord.Embed(
                title="⚔️ ВЫЗОВ НА ДУЭЛЬ!",
                description=(
                    f"{interaction.user.mention} вызывает {target.mention} на дуэль!\n\n"
                    f"**Ставка:** {fmt(self.bet)} {config.CURRENCY_EMOJI} с каждого\n"
                    f"**Победитель забирает:** {fmt(self.bet * 2)} {config.CURRENCY_EMOJI}\n\n"
                    f"{target.mention}, ты принимаешь вызов?"
                ),
                color=discord.Color.gold()
            )
            # Создаем View для принятия/отклонения
            view = DuelAcceptView(interaction.user.id, target.id, self.bet)
            await interaction.response.edit_message(content="Вызов отправлен!", embed=None, view=None)
            await interaction.channel.send(embed=embed, view=view)


    class DuelAcceptView(discord.ui.View):
        def __init__(self, host_id, target_id, bet):
            super().__init__(timeout=120)
            self.host_id = host_id
            self.target_id = target_id
            self.bet = bet

        @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success)
        async def accept(self, interaction, button):
            if interaction.user.id != self.target_id:
                await interaction.response.send_message("❌ Это не твой вызов.", ephemeral=True)
                return

            # Списываем ставки
            db.add_balance(self.host_id, -self.bet)
            db.add_balance(self.target_id, -self.bet)

            # Отправляем сообщение о начале
            embed = discord.Embed(
                title="⚔️ ДУЭЛЬ НАЧАЛАСЬ!",
                description=f"Оба игрока скинули по **{fmt(self.bet)}** {config.CURRENCY_EMOJI}.\nНажмите кнопку, чтобы бросить кубик!",
                color=discord.Color.red()
            )
            # Обновляем сообщение и убираем кнопку "Принять"
            await interaction.response.edit_message(embed=embed, view=DuelPlayView(self.host_id, self.target_id, self.bet))

        @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
        async def decline(self, interaction, button):
            if interaction.user.id != self.target_id:
                await interaction.response.send_message("❌ Это не твой вызов.", ephemeral=True)
                return
            await interaction.response.edit_message(content="❌ Вызов отклонен.", embed=None, view=None)
            
            
    class MinesDifficultyView(discord.ui.View):
        def __init__(self, owner_id):
            super().__init__(timeout=180)
            self.owner_id = owner_id

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id == self.owner_id

        async def start_game(self, interaction, size, mines_count):
            await interaction.response.send_modal(MinesBetModal(self.owner_id, size, mines_count))

        @discord.ui.button(label="🟢 3x3 (Легко)", style=discord.ButtonStyle.success)
        async def easy(self, i, b): await self.start_game(i, 3, 2)

        @discord.ui.button(label="🟡 5x5 (Средне)", style=discord.ButtonStyle.primary)
        async def medium(self, i, b): await self.start_game(i, 5, 5)



    class MinesGame(discord.ui.View):
        def __init__(self, user_id: int, bet: int, size: int, mines_count: int):
            super().__init__(timeout=300)
            self.user_id = user_id
            self.bet = bet
            self.size = size
            self.total_cells = size * size
            self.mines_count = mines_count
            self.mines_positions = random.sample(range(self.total_cells), mines_count)
            self.revealed = []
            self.safe_revealed = 0

            # Создаем кнопки
            for i in range(self.total_cells):
                btn = discord.ui.Button(label="❓", style=discord.ButtonStyle.secondary, custom_id=f"mine_{i}")
                btn.callback = self.create_callback(i)
                self.add_item(btn)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Не твоя игра.", ephemeral=True)
                return False
            return True

        def get_multiplier(self):
            # На 3x3 множитель растет быстрее (+0.5), на 8x8 медленнее (+0.1)
            if self.size == 3: step = 0.5
            elif self.size == 8: step = 0.1
            else: step = 0.2
            return 1 + (self.safe_revealed * step)

        def create_callback(self, index):
            async def callback(interaction: discord.Interaction):
                if index in self.revealed:
                    return await interaction.response.send_message("❌ Уже открыто.", ephemeral=True)

                self.revealed.append(index)
                btn = self.children[index]
                
                if index in self.mines_positions:
                    btn.label = "💣"
                    btn.style = discord.ButtonStyle.danger
                    for i in self.mines_positions:
                        self.children[i].label = "💣"
                        self.children[i].style = discord.ButtonStyle.danger
                        self.children[i].disabled = True
                    for child in self.children:
                        child.disabled = True
                    
                    embed = discord.Embed(
                        title="💥 ВЗРЫВ! ВЫ ПРОИГРАЛИ!",
                        description=f"Ставка **{fmt(self.bet)}** {config.CURRENCY_EMOJI} сгорела.",
                        color=discord.Color.red()
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    db.add_transaction(self.user_id, -self.bet, "casino", "Мины: проигрыш")
                    return

                btn.label = "💎"
                btn.style = discord.ButtonStyle.success
                btn.disabled = True
                self.safe_revealed += 1

                mult = self.get_multiplier()
                win = int(self.bet * mult)
                safe_cells = self.total_cells - self.mines_count

                # Победа
                if self.safe_revealed == safe_cells:
                    for child in self.children:
                        child.disabled = True
                    db.add_balance(self.user_id, win)
                    db.add_transaction(self.user_id, win - self.bet, "casino", "Мины: победа (все открыты)")
                    embed = discord.Embed(
                        title="🎉 ПОБЕДА! ВЫ ОТКРЫЛИ ВСЕ ЯЧЕЙКИ!",
                        description=f"Выигрыш: **{fmt(win)}** {config.CURRENCY_EMOJI} (x{mult:.1f})",
                        color=discord.Color.gold()
                    )
                    return await interaction.response.edit_message(embed=embed, view=self)

                embed = discord.Embed(
                    title=f"💣 ИГРА В МИНЫ {self.size}x{self.size}",
                    description=(
                        f"Ставка: **{fmt(self.bet)}** {config.CURRENCY_EMOJI}\n"
                        f"Открыто: **{self.safe_revealed}** / {safe_cells}\n"
                        f"Текущий выигрыш: **{fmt(win)}** {config.CURRENCY_EMOJI} (x{mult:.1f})\n\n"
                        f"Забрать или продолжить?"
                    ),
                    color=discord.Color.blue()
                )
                
                                # Проверяем, что кнопок меньше 25, чтобы не превысить лимит Discord
                if len(self.children) < 25:
                    if not any(isinstance(item, discord.ui.Button) and item.label == "💰 Забрать" for item in self.children):
                        cashout_btn = discord.ui.Button(label="💰 Забрать", style=discord.ButtonStyle.primary, row=4)
                        cashout_btn.callback = self.cashout
                        self.add_item(cashout_btn)
                
                await interaction.response.edit_message(embed=embed, view=self)
            return callback

        async def cashout(self, interaction: discord.Interaction):
            for child in self.children:
                child.disabled = True
                
            mult = self.get_multiplier()
            win = int(self.bet * mult)
            
            db.add_balance(self.user_id, win)
            db.add_transaction(self.user_id, win - self.bet, "casino", "Мины: забрал выигрыш")
            
            embed = discord.Embed(
                title="💰 ВЫ ЗАБРАЛИ ВЫИГРЫШ!",
                description=f"Выигрыш: **{fmt(win)}** {config.CURRENCY_EMOJI} (x{mult:.1f})",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=self)
    async def play_h_slots(interaction, bet):
        # Символы: 🎃, 👻, 🕷️, 💀, 🧙
        reels = [random.choice(["🎃", "👻", "🕷️", "💀", "🧙"]) for _ in range(3)]
        
        win = 0
        if reels[0] == reels[1] == reels[2]:
            if reels[0] == "🎃": win = bet * 10
            elif reels[0] == "👻": win = bet * 15
            elif reels[0] == "🕷️": win = bet * 20
            elif reels[0] == "💀": win = bet * 30
            elif reels[0] == "🧙": win = bet * 50
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            win = bet * 2

        if win > 0:
            db.add_balance(interaction.user.id, win)
            db.add_transaction(interaction.user.id, win - bet, "casino", f"Хэллоуин слоты: {''.join(reels)}")
        else:
            db.add_transaction(interaction.user.id, -bet, "casino", f"Хэллоуин слоты: {''.join(reels)}")

        color = discord.Color.purple() if win > 0 else discord.Color.dark_red()
        result = f"**+{fmt(win)}** {config.CURRENCY_EMOJI}" if win > 0 else f"**-{fmt(bet)}** {config.CURRENCY_EMOJI}"
        
        embed = discord.Embed(title="🎃 ХЭЛЛОУИН-СЛОТЫ", color=color)
        embed.add_field(name="Барабаны", value=f"**{reels[0]} | {reels[1]} | {reels[2]}**", inline=False)
        embed.add_field(name="Ставка", value=f"{fmt(bet)}", inline=True)
        embed.add_field(name="Результат", value=result, inline=True)
        embed.set_footer(text="Духи казино наблюдают за тобой...")
        
        await interaction.response.send_message(embed=embed)

    async def open_h_roulette(interaction, bet):
        embed = discord.Embed(
            title="🔮 ПРОКЛЯТАЯ РУЛЕТКА", 
            description=f"Ставка: **{fmt(bet)}**\n\nНа что ставим, смельчак? 🔥 Огонь, 🌑 Тьма или 🟢 Духи?", 
            color=discord.Color.dark_purple()
        )
        await interaction.response.send_message(embed=embed, view=HRouletteView(bet, interaction.user.id))

    class HRouletteView(discord.ui.View):
        def __init__(self, bet, owner_id):
            super().__init__(timeout=60)
            self.bet = bet
            self.owner_id = owner_id
            # 0 - Духи (зеленый), 1-18 - Тьма, 19-36 - Огонь
            self.number = random.randint(0, 36)
            if self.number == 0:
                self.color = "spirits"
            elif self.number % 2 == 0:
                self.color = "fire"
            else:
                self.color = "dark"

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return False
            return True

        async def spin(self, interaction, choice, label):
            bet = self.bet
            uid = interaction.user.id
            await interaction.response.defer()
            for c in self.children:
                c.disabled = True
            
            win = 0
            if choice == "fire" and self.color == "fire": win = bet * 2
            elif choice == "dark" and self.color == "dark": win = bet * 2
            elif choice == "spirits" and self.color == "spirits": win = bet * 14

            if win > 0:
                db.add_balance(uid, win)
                db.add_transaction(uid, win - bet, "casino", f"Проклятая рулетка {label}: {self.number}")
            else:
                db.add_transaction(uid, -bet, "casino", f"Проклятая рулетка {label}: {self.number}")

            emoji = {"fire": "🔥", "dark": "🌑", "spirits": "🟢"}[self.color]
            color = discord.Color.green() if win > 0 else discord.Color.red()
            
            embed = discord.Embed(
                title="🔮 ПРОКЛЯТАЯ РУЛЕТКА", 
                description=f"Выпало число: **{self.number}** {emoji} ({label})",
                color=color
            )
            embed.add_field(name="Ставка", value=f"{fmt(bet)} на {label}")
            embed.add_field(name="Результат", value=f"**+{fmt(win)}**" if win > 0 else f"**-{fmt(bet)}**")
            embed.set_footer(text=f"Баланс: {fmt(db.get_balance(uid))}")
            await interaction.edit_original_response(embed=embed, view=None)

        @discord.ui.button(label="🔥 Огонь (x2)", style=discord.ButtonStyle.danger, row=0)
        async def fire(self, i, b): await self.spin(i, "fire", "🔥 Огонь")

        @discord.ui.button(label="🌑 Тьма (x2)", style=discord.ButtonStyle.secondary, row=0)
        async def dark(self, i, b): await self.spin(i, "dark", "🌑 Тьма")

        @discord.ui.button(label="🟢 Духи (x14)", style=discord.ButtonStyle.success, row=0)
        async def spirits(self, i, b): await self.spin(i, "spirits", "🟢 Духи")
            

        
    class RocketGame(discord.ui.View):
        def __init__(self, user_id, bet):
            super().__init__(timeout=30)
            self.user_id = user_id
            self.bet = bet
            self.multiplier = 1.0
            self.playing = True
            self.message = None
            # Ракета взорвется через случайное время от 2 до 15 секунд
            self.crash_time = random.uniform(2.0, 15.0) 
            self.start_time = 0
            self.crashed = False # Флаг для защиты от двойных нажатий

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Не твоя игра.", ephemeral=True)
                return False
            return True

        async def run_rocket(self, interaction: discord.Interaction):
            # Ждем, пока сообщение появится в канале
            await asyncio.sleep(0.5)
            self.message = interaction.channel.last_message
            if not self.message:
                return

            # --- ОБРАТНЫЙ ОТСЧЕТ ---
            for i in range(3, 0, -1):
                embed = discord.Embed(title="🚀 ПОДГОТОВКА...", description=f"**{i}**...", color=discord.Color.gold())
                try:
                    await self.message.edit(embed=embed, view=self)
                except:
                    pass
                await asyncio.sleep(1)

            embed = discord.Embed(
                title="🚀 ПОЛЕТЕЛИ!",
                description="Множитель растет...\nНажми **💰 Забрать**, чтобы не сгореть!",
                color=discord.Color.green()
            )
            try:
                await self.message.edit(embed=embed, view=self)
            except:
                pass
            
            # Запоминаем время старта
            self.start_time = asyncio.get_event_loop().time()

            # Фоновый цикл обновления экрана
            while self.playing:
                await asyncio.sleep(0.6) # Обновляем экран раз в 0.6 сек
                
                if not self.playing:
                    break

                elapsed = asyncio.get_event_loop().time() - self.start_time
                
                # Взрыв
                if elapsed >= self.crash_time:
                    self.playing = False
                    self.crashed = True
                    for child in self.children:
                        child.disabled = True
                    
                    embed = discord.Embed(
                        title="💥 РАКЕТА ВЗОРВАЛАСЬ!",
                        description=f"Ставка **{fmt(self.bet)}** {config.CURRENCY_EMOJI} сгорела на **x{self.multiplier:.2f}**",
                        color=discord.Color.red()
                    )
                    db.add_transaction(self.user_id, -self.bet, "casino", "Ракета: проигрыш")
                    try:
                        await self.message.edit(embed=embed, view=self)
                    except:
                        pass
                    break

                # Обновление множителя
                self.multiplier = 1.0 + (elapsed * random.uniform(0.3, 0.5))
                win = int(self.bet * self.multiplier)

                embed = discord.Embed(
                    title="🚀 РАКЕТА ЛЕТИТ...",
                    description=f"Множитель: **x{self.multiplier:.2f}**\n\nНажми **💰 Забрать**, чтобы забрать **{fmt(win)}** {config.CURRENCY_EMOJI}!",
                    color=discord.Color.blue()
                )
                try:
                    await self.message.edit(embed=embed, view=self)
                except:
                    pass

        @discord.ui.button(label="💰 Забрать", style=discord.ButtonStyle.success)
        async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
            # 1. Мгновенный ответ, чтобы Discord не ругался на "Ошибку взаимодействия"
            await interaction.response.defer()

            # 2. Защита от нажатия после взрыва
            if not self.playing or self.crashed:
                return

            self.playing = False
            self.crashed = True
            
            for child in self.children:
                child.disabled = True

            # Считаем точное время на момент клика
            elapsed = asyncio.get_event_loop().time() - self.start_time
            self.multiplier = 1.0 + (elapsed * random.uniform(0.3, 0.5))
            
            win = int(self.bet * self.multiplier)
            db.add_balance(self.user_id, win)
            db.add_transaction(self.user_id, win - self.bet, "casino", f"Ракета: победа x{self.multiplier:.2f}")

            embed = discord.Embed(
                title="💰 УСПЕЛ ЗАБРАТЬ!",
                description=f"Ты забрал **{fmt(win)}** {config.CURRENCY_EMOJI} на множителе **x{self.multiplier:.2f}**!",
                color=discord.Color.green()
            )
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except:
                pass

    class RouletteView(discord.ui.View):
        def __init__(self, bet, owner_id):
            super().__init__(timeout=60)
            self.bet = bet
            self.owner_id = owner_id
            self.number, self.color = games.spin_roulette()
            emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[self.color]
            asyncio.create_task(spy_send(
                bot,
                f"🎡 **Рулетка**\n"
                f"Игрок: <@{owner_id}>\n"
                f"Ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n"
                f"Выпадет: **{self.number}** {emoji} ({self.color})"
            ))

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return False
            return True

        async def spin(self, interaction, choice, label):
            bet = self.bet
            uid = interaction.user.id
            await interaction.response.defer()
            for c in self.children:
                c.disabled = True
            number, color = self.number, self.color
            emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]
            win = 0
            if choice == "red" and color == "red": win = bet * 2
            elif choice == "black" and color == "black": win = bet * 2
            elif choice == "green" and color == "green": win = bet * 14
            elif choice == "even" and number != 0 and number % 2 == 0: win = bet * 2
            elif choice == "odd" and number != 0 and number % 2 == 1: win = bet * 2
            elif choice == "low" and 1 <= number <= 18: win = bet * 2
            elif choice == "high" and 19 <= number <= 36: win = bet * 2
            if win > 0:
                db.add_balance(uid, win)
                db.add_transaction(uid, win - bet, "casino", f"Рулетка {label}: {number} {color}")
            else:
                db.add_transaction(uid, -bet, "casino", f"Рулетка {label}: {number} {color}")
            update_streak(bot, uid, won=(win > 0))
            new_bal = db.get_balance(uid)
            embed = discord.Embed(title="🎡 Рулетка",
                                  description=f"Выпало: **{number}** {emoji} ({color})",
                                  color=discord.Color.green() if win > 0 else discord.Color.red())
            embed.add_field(name="Ставка", value=f"{fmt(bet)} на **{label}**")
            embed.add_field(name="Результат", value=f"**+{fmt(win)}**" if win > 0 else f"**-{fmt(bet)}**")
            embed.set_footer(text=f"Баланс: {fmt(new_bal)}")
            await interaction.edit_original_response(embed=embed, view=None)

        @discord.ui.button(label="🔴 Красное", style=discord.ButtonStyle.danger, row=0)
        async def red(self, i, b): await self.spin(i, "red", "Красное")

        @discord.ui.button(label="⚫ Чёрное", style=discord.ButtonStyle.secondary, row=0)
        async def black(self, i, b): await self.spin(i, "black", "Чёрное")

        @discord.ui.button(label="🟢 Зелёное", style=discord.ButtonStyle.success, row=0)
        async def green(self, i, b): await self.spin(i, "green", "Зелёное")

        @discord.ui.button(label="Чёт", style=discord.ButtonStyle.primary, row=1)
        async def even(self, i, b): await self.spin(i, "even", "Чёт")

        @discord.ui.button(label="Нечет", style=discord.ButtonStyle.primary, row=1)
        async def odd(self, i, b): await self.spin(i, "odd", "Нечет")

        @discord.ui.button(label="1-18", style=discord.ButtonStyle.secondary, row=1)
        async def low(self, i, b): await self.spin(i, "low", "1-18")

        @discord.ui.button(label="19-36", style=discord.ButtonStyle.secondary, row=1)
        async def high(self, i, b): await self.spin(i, "high", "19-36")

    async def open_dice(interaction, bet):
        embed = discord.Embed(title="🎲 Кости", description=f"Ставка: **{fmt(bet)}**\n\nНа что?", color=discord.Color.dark_purple())
        await interaction.response.send_message(embed=embed, view=DiceView(bet, interaction.user.id))

    class DiceView(discord.ui.View):
        def __init__(self, bet, owner_id):
            super().__init__(timeout=60)
            self.bet = bet
            self.owner_id = owner_id
            self.dice = games.roll_dice(2)
            total = self.dice[0] + self.dice[1]
            asyncio.create_task(spy_send(
                bot,
                f"🎲 **Кости**\n"
                f"Игрок: <@{owner_id}>\n"
                f"Ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n"
                f"Выпадет: **{self.dice[0]}** и **{self.dice[1]}** = **{total}**"
            ))

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return False
            return True

        async def roll(self, interaction, choice, label):
            bet = self.bet
            uid = interaction.user.id
            await interaction.response.defer()
            for c in self.children:
                c.disabled = True
            d1, d2 = self.dice
            total = d1 + d2
            win = 0
            if choice == "high" and 8 <= total <= 12: win = bet * 2
            elif choice == "low" and 2 <= total <= 6: win = bet * 2
            elif choice == "seven" and total == 7: win = bet * 5
            if win > 0:
                db.add_balance(uid, win)
                db.add_transaction(uid, win - bet, "casino", f"Кости {label}: {d1}+{d2}={total}")
            else:
                db.add_transaction(uid, -bet, "casino", f"Кости {label}: {d1}+{d2}={total}")
            update_streak(bot, uid, won=(win > 0))
            new_bal = db.get_balance(uid)
            embed = discord.Embed(title="🎲 Кости",
                                  description=f"Выпало: **{d1}** и **{d2}** = **{total}**",
                                  color=discord.Color.green() if win > 0 else discord.Color.red())
            embed.add_field(name="Ставка", value=f"{fmt(bet)} на **{label}**")
            embed.add_field(name="Результат", value=f"**+{fmt(win)}**" if win > 0 else f"**-{fmt(bet)}**")
            embed.set_footer(text=f"Баланс: {fmt(new_bal)}")
            await interaction.edit_original_response(embed=embed, view=None)

        @discord.ui.button(label="Больше (8-12)", style=discord.ButtonStyle.success)
        async def high(self, i, b): await self.roll(i, "high", "Больше")

        @discord.ui.button(label="Меньше (2-6)", style=discord.ButtonStyle.danger)
        async def low(self, i, b): await self.roll(i, "low", "Меньше")

        @discord.ui.button(label="Ровно 7", style=discord.ButtonStyle.primary)
        async def seven(self, i, b): await self.roll(i, "seven", "Семёрка")

    async def open_coin(interaction, bet):
        embed = discord.Embed(title="🪙 Монетка", description=f"Ставка: **{fmt(bet)}**\n\nОрёл или решка?", color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, view=CoinView(bet, interaction.user.id))

    class CoinView(discord.ui.View):
        def __init__(self, bet, owner_id):
            super().__init__(timeout=60)
            self.bet = bet
            self.owner_id = owner_id
            self.result = games.flip_coin()
            asyncio.create_task(spy_send(
                bot,
                f"🪙 **Монетка**\n"
                f"Игрок: <@{owner_id}>\n"
                f"Ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n"
                f"Выпадет: **{'🦅 Орёл' if self.result == 'heads' else '🪙 Решка'}**"
            ))

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ Не твоя.", ephemeral=True)
                return False
            return True

        async def flip(self, interaction, choice, label):
            bet = self.bet
            uid = interaction.user.id
            await interaction.response.defer()
            for c in self.children:
                c.disabled = True
            result = self.result
            win = bet * 2 if result == choice else 0
            if win > 0:
                db.add_balance(uid, win)
                db.add_transaction(uid, win - bet, "casino", f"Монетка: {label}")
            else:
                db.add_transaction(uid, -bet, "casino", f"Монетка: {label}")
            update_streak(bot, uid, won=(win > 0))
            new_bal = db.get_balance(uid)
            result_emoji = "🦅 Орёл" if result == "heads" else "🪙 Решка"
            embed = discord.Embed(title="🪙 Монетка",
                                  description=f"Выпало: **{result_emoji}**",
                                  color=discord.Color.green() if win > 0 else discord.Color.red())
            embed.add_field(name="Ставка", value=f"{fmt(bet)} на **{label}**")
            embed.add_field(name="Результат", value=f"**+{fmt(win)}**" if win > 0 else f"**-{fmt(bet)}**")
            embed.set_footer(text=f"Баланс: {fmt(new_bal)}")
            await interaction.edit_original_response(embed=embed, view=None)

        @discord.ui.button(label="🦅 Орёл", style=discord.ButtonStyle.primary)
        async def heads(self, i, b): await self.flip(i, "heads", "Орёл")

        @discord.ui.button(label="🪙 Решка", style=discord.ButtonStyle.secondary)
        async def tails(self, i, b): await self.flip(i, "tails", "Решка")
        
        
    @bot.tree.command(name="мины", description="💣 Игра Мины (5x5)")
    @app_commands.describe(bet="Ставка")
    async def mines_game(interaction: discord.Interaction, bet: int):
        if bet < config.CASINO_MIN_BET or bet > config.CASINO_MAX_BET:
            await interaction.response.send_message(f"❌ Ставка от {fmt(config.CASINO_MIN_BET)} до {fmt(config.CASINO_MAX_BET)}.", ephemeral=True)
            return
            
        if db.get_balance(interaction.user.id) < bet:
            await interaction.response.send_message("❌ Недостаточно средств.", ephemeral=True)
            return

        # Списание ставки
        db.add_balance(interaction.user.id, -bet)
        
        # Создаем новую игру
        game = MinesGame(interaction.user.id, bet)
        
        embed = discord.Embed(
            title="💣 ИГРА В МИНЫ",
            description=(
                f"Ваша ставка: **{fmt(bet)}** {config.CURRENCY_EMOJI}\n"
                f"Открыто ячеек: **0**\n"
                f"Текущий выигрыш: **0** {config.CURRENCY_EMOJI}\n\n"
                f"Нажимайте на кнопки, чтобы открывать ячейки. Избегайте мин! 💣"
            ),
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed, view=game)


    class MinesGame(discord.ui.View):
        def __init__(self, user_id: int, bet: int):
            super().__init__(timeout=300)
            self.user_id = user_id
            self.bet = bet
            self.mines_positions = random.sample(range(25), 5) # 5 мин на 25 ячеек
            self.revealed = []
            self.safe_revealed = 0

            # Создаем 25 кнопок (5х5)
            for i in range(25):
                btn = discord.ui.Button(label="❓", style=discord.ButtonStyle.secondary, custom_id=f"mine_{i}")
                btn.callback = self.create_callback(i)
                self.add_item(btn)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Это не твоя игра.", ephemeral=True)
                return False
            return True

        def create_callback(self, index):
            async def callback(interaction: discord.Interaction):
                # Если уже нажато
                if index in self.revealed:
                    await interaction.response.send_message("❌ Эта ячейка уже открыта.", ephemeral=True)
                    return

                self.revealed.append(index)
                btn = self.children[index]
                
                # Если попали на мину
                if index in self.mines_positions:
                    btn.label = "💣"
                    btn.style = discord.ButtonStyle.danger
                    
                    # Открываем все мины
                    for i in self.mines_positions:
                        self.children[i].label = "💣"
                        self.children[i].style = discord.ButtonStyle.danger
                        self.children[i].disabled = True
                    
                    # Отключаем все кнопки
                    for child in self.children:
                        child.disabled = True
                    
                    embed = discord.Embed(
                        title="💥 ВЗРЫВ! ВЫ ПРОИГРАЛИ!",
                        description=f"Ваша ставка **{fmt(self.bet)}** {config.CURRENCY_EMOJI} сгорела.",
                        color=discord.Color.red()
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    
                    db.add_transaction(self.user_id, -self.bet, "casino", "Мины: проигрыш")
                    return

                # Если безопасно
                btn.label = "💎"
                btn.style = discord.ButtonStyle.success
                btn.disabled = True
                self.safe_revealed += 1

                # Коэффициент (растет с каждой открытой ячейкой)
                multiplier = 1 + (self.safe_revealed * 0.2)
                win = int(self.bet * multiplier)

                # Проверка на победу (открыли все безопасные ячейки - 20 из 25)
                if self.safe_revealed == 20:
                    for child in self.children:
                        child.disabled = True
                    
                    db.add_balance(self.user_id, win)
                    db.add_transaction(self.user_id, win - self.bet, "casino", "Мины: победа (все открыты)")
                    
                    embed = discord.Embed(
                        title="🎉 ПОБЕДА! ВЫ ОТКРЫЛИ ВСЕ ЯЧЕЙКИ!",
                        description=f"Вы выиграли **{fmt(win)}** {config.CURRENCY_EMOJI} (x{multiplier:.1f})",
                        color=discord.Color.gold()
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    return

                # Обновляем интерфейс (кнопку "Забрать")
                embed = discord.Embed(
                    title="💣 ИГРА В МИНЫ",
                    description=(
                        f"Ваша ставка: **{fmt(self.bet)}** {config.CURRENCY_EMOJI}\n"
                        f"Открыто ячеек: **{self.safe_revealed}**\n"
                        f"Текущий выигрыш: **{fmt(win)}** {config.CURRENCY_EMOJI} (x{multiplier:.1f})\n\n"
                        f"Продолжайте открывать или заберите выигрыш! 💰"
                    ),
                    color=discord.Color.blue()
                )
                
                # Превращаем последнюю кнопку в "Забрать", чтобы не превысить лимит в 25 кнопок
                if not any(isinstance(item, discord.ui.Button) and item.label == "💰 Забрать" for item in self.children):
                    cashout_btn = self.children[-1]
                    cashout_btn.label = "💰 Забрать"
                    cashout_btn.style = discord.ButtonStyle.primary
                    cashout_btn.disabled = False
                    cashout_btn.callback = self.cashout
                
                await interaction.response.edit_message(embed=embed, view=self)
            return callback

        async def cashout(self, interaction: discord.Interaction):
            # Отключаем все кнопки
            for child in self.children:
                child.disabled = True
                
            multiplier = 1 + (self.safe_revealed * 0.2)
            win = int(self.bet * multiplier)
            
            db.add_balance(self.user_id, win)
            db.add_transaction(self.user_id, win - self.bet, "casino", "Мины: забрал выигрыш")
            
            embed = discord.Embed(
                title="💰 ВЫ ЗАБРАЛИ ВЫИГРЫШ!",
                description=(
                    f"Вы выиграли **{fmt(win)}** {config.CURRENCY_EMOJI} (x{multiplier:.1f})\n"
                    f"Открыто ячеек: **{self.safe_revealed}**"
                ),
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=self)
            
            
    @bot.tree.command(name="мои_тыквы", description="🎃 Твоя коллекция тыкв")
    async def my_pumpkins(interaction: discord.Interaction):
            count = db.get_pumpkins(interaction.user.id)
            
            embed = discord.Embed(
                title="🎃 Твоя коллекция",
                description=f"Ты собрал **{count}** хэллоуинских тыкв!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        
    class DuelPlayView(discord.ui.View):
        def __init__(self, host_id, target_id, bet):
            super().__init__(timeout=120)
            self.host_id = host_id
            self.target_id = target_id
            self.bet = bet
            self.host_roll = None
            self.target_roll = None

        @discord.ui.button(label="🎲 Бросить кубик (Хост)", style=discord.ButtonStyle.primary)
        async def host_roll_btn(self, interaction, button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Не твоя кнопка.", ephemeral=True)
                return
            self.host_roll = random.randint(1, 6)
            await interaction.response.send_message(f"🎲 Ты выбросил: **{self.host_roll}**", ephemeral=True)
            await self.check_finish(interaction)

        @discord.ui.button(label="🎲 Бросить кубик (Цель)", style=discord.ButtonStyle.primary)
        async def target_roll_btn(self, interaction, button):
            if interaction.user.id != self.target_id:
                await interaction.response.send_message("❌ Не твоя кнопка.", ephemeral=True)
                return
            self.target_roll = random.randint(1, 6)
            await interaction.response.send_message(f"🎲 Ты выбросил: **{self.target_roll}**", ephemeral=True)
            await self.check_finish(interaction)

        async def check_finish(self, interaction):
            if self.host_roll is not None and self.target_roll is not None:
                # Отключаем кнопки
                for child in self.children:
                    child.disabled = True
                
                # Определяем победителя
                if self.host_roll > self.target_roll:
                    winner_id = self.host_id
                    text = f"🏆 Победил {interaction.guild.get_member(self.host_id).mention}!"
                elif self.target_roll > self.host_roll:
                    winner_id = self.target_id
                    text = f"🏆 Победил {interaction.guild.get_member(self.target_id).mention}!"
                else:
                    # Ничья, возвращаем деньги
                    db.add_balance(self.host_id, self.bet)
                    db.add_balance(self.target_id, self.bet)
                    text = "🤝 Ничья! Ставки возвращены."
                    embed = discord.Embed(title="⚔️ РЕЗУЛЬТАТ", description=text, color=discord.Color.greyple())
                    await interaction.response.edit_message(embed=embed, view=self)
                    return

                # Начисляем выигрыш победителю
                win_amount = self.bet * 2
                db.add_balance(winner_id, win_amount)
                db.add_transaction(winner_id, self.bet, "casino", f"Дуэль: победа")

                embed = discord.Embed(title="⚔️ РЕЗУЛЬТАТ", description=f"{text}\n\nВыигрыш: **{fmt(win_amount)}** {config.CURRENCY_EMOJI}", color=discord.Color.green())
                await interaction.response.edit_message(embed=embed, view=self)