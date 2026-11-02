import discord
from discord.ext import commands
import config
import asyncio

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    print("⏳ Удаляем все старые команды...")
    if config.GUILD_ID:
        guild = discord.Object(id=config.GUILD_ID)
        # Жестко очищаем глобальные и серверные команды
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    else:
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    
    print("✅ Команды полностью удалены!")
    await bot.close()

bot.run(config.TOKEN)