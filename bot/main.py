import logging
import os
import sys

import discord
from discord import app_commands
from dotenv import load_dotenv

from bot import help as help_command
from bot import aiinit, ia, panel
from bot.config import Config, ConfigError, load_config
from bot.lmstudio import LMStudioClient

log = logging.getLogger(__name__)


class Bot(discord.Client):
    def __init__(self, config: Config):
        super().__init__(
            intents=discord.Intents.default(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.config = config
        self.initializer = None
        self.tree = app_commands.CommandTree(self)
        self.tree.error(self.on_command_error)

    async def setup_hook(self) -> None:
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.Forbidden:
            log.error(
                "No puedo registrar los comandos en el servidor %s. Comprueba GUILD_ID "
                "y que el bot se invitó con el scope applications.commands.",
                self.config.guild_id,
            )
            raise
        log.info("Comandos registrados: %s", ", ".join(command.name for command in synced))
        if self.config.lmstudio_auto_init and self.initializer is not None:
            try:
                log.info("Inicialización de LM Studio: %s", await self.initializer.initialize())
            except aiinit.InitializationError as exc:
                log.warning("No se pudo inicializar LM Studio al arrancar: %s", exc)

    async def on_ready(self) -> None:
        log.info("Conectado como %s", self.user)

    async def on_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "No tienes permiso para usar este comando."
        else:
            log.error("Error en un comando", exc_info=error)
            message = "Ha ocurrido un error inesperado."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def build_bot(config: Config) -> Bot:
    bot = Bot(config)
    client = LMStudioClient(
        config.lmstudio_base_url, config.lmstudio_model, config.lmstudio_timeout,
        max_tokens=config.lmstudio_max_tokens,
    )
    panel.register(bot.tree, config)
    bot.initializer = aiinit.ModelInitializer(client, config.lmstudio_base_url, config.lmstudio_model)
    ia.register(bot.tree, client, bot.initializer.lock)
    aiinit.register(bot.tree, bot.initializer)
    help_command.register(bot.tree)
    return bot


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 1
    bot = build_bot(config)
    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.LoginFailure:
        print("Error de configuración: DISCORD_TOKEN no es válido", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
