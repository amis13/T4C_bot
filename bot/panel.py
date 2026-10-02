import discord
from discord import app_commands

from bot.config import Config

COLOR = 0x00B894
ROW_SIZE = 5

# (etiqueta, emoji, url). Se reparten en filas de 5 debajo de los Notion.
RESOURCES = [
    ("Exploit-DB", "💥", "https://www.exploit-db.com/"),
    ("GTFOBins", "🐧", "https://gtfobins.github.io/"),
    ("LOLBAS", "🪟", "https://lolbas-project.github.io/"),
    ("HackTricks", "📖", "https://book.hacktricks.wiki/"),
    ("PayloadsAllTheThings", "🧨", "https://swisskyrepo.github.io/PayloadsAllTheThings/"),
    ("RevShells", "🐚", "https://www.revshells.com/"),
    ("CyberChef", "🍳", "https://gchq.github.io/CyberChef/"),
    ("CrackStation", "🔓", "https://crackstation.net/"),
    ("WADComs", "🏰", "https://wadcoms.github.io/"),
]


def build_panel(config: Config) -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="Talent4Cyber · Recursos del grupo",
        description=(
            "Todo lo que usamos para preparar el evento, a un clic.\n\n"
            "📘 **eJPT**: apuntes y laboratorios\n"
            "📕 **eCPPT**: apuntes y laboratorios\n"
            "👥 **Grupo**: organización, tareas y notas comunes\n\n"
            "🛠️ **Para la competición**: exploits, escalada de privilegios, "
            "payloads, reverse shells y hashes\n\n"
            "¿Dudas? Pregunta al modelo del grupo con `/ia`."
        ),
        color=COLOR,
    )
    # Botones de enlace: no generan interacciones, siguen funcionando con el bot apagado
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="eJPT", row=0, emoji="📘", url=config.notion_ejpt_url))
    view.add_item(discord.ui.Button(label="eCPPT", row=0, emoji="📕", url=config.notion_ecppt_url))
    view.add_item(discord.ui.Button(label="Grupo", row=0, emoji="👥", url=config.notion_grupo_url))
    for index, (label, emoji, url) in enumerate(RESOURCES):
        row = 1 + index // ROW_SIZE
        view.add_item(discord.ui.Button(label=label, emoji=emoji, url=url, row=row))
    return embed, view


def register(tree: app_commands.CommandTree, config: Config) -> None:
    @tree.command(name="panel", description="Publica el mensaje principal con los enlaces del grupo")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(interaction: discord.Interaction):
        embed, view = build_panel(config)
        try:
            await interaction.channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.response.send_message(
                "No tengo permiso para enviar mensajes o insertar enlaces en este canal.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("Panel publicado.", ephemeral=True)
