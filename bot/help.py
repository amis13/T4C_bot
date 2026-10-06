import discord
from discord import app_commands

from bot.panel import COLOR

COMMANDS = [
    ("/panel", "Publica el mensaje principal con los Notion y los recursos de competición. Solo administración."),
    ("/ia", "Pregunta al modelo local del grupo. Recuerda la conversación del canal y responde en streaming."),
    ("/ia-reset", "Borra la memoria de /ia en este canal."),
    ("/initai", "Carga Qwythos con contexto 16384, una consulta simultánea y MTP. Solo administración."),
    ("/help", "Muestra esta ayuda."),
]


def build_help() -> discord.Embed:
    embed = discord.Embed(title="Comandos del bot", color=COLOR)
    for name, description in COMMANDS:
        embed.add_field(name=name, value=description, inline=False)
    return embed


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="help", description="Lista los comandos del bot")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_help(), ephemeral=True)
