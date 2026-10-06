import discord
import pytest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.aiinit import InitializationError
from bot.config import Config
from bot.main import build_bot

CONFIG = Config(
    discord_token="token",
    guild_id=1,
    notion_ejpt_url="https://notion.so/ejpt",
    notion_ecppt_url="https://notion.so/ecppt",
    notion_grupo_url="https://notion.so/grupo",
)


def db_config(tmp_path, **changes):
    return replace(CONFIG, ia_db_path=str(tmp_path / "ia.db"), **changes)


def test_bot_registers_all_commands(tmp_path):
    bot = build_bot(db_config(tmp_path))
    assert {command.name for command in bot.tree.get_commands()} == {
        "panel", "ia", "ia-reset", "initai", "help",
    }


def test_bot_never_mentions_and_uses_no_privileged_intents(tmp_path):
    bot = build_bot(db_config(tmp_path))
    mentions = bot.allowed_mentions
    assert (mentions.everyone, mentions.users, mentions.roles) == (False, False, False)
    assert not bot.intents.message_content
    assert not bot.intents.members
    assert not bot.intents.presences


def test_ia_message_option_is_bounded(tmp_path):
    bot = build_bot(db_config(tmp_path))
    option = bot.tree.get_command("ia").parameters[0]
    assert option.name == "mensaje"
    assert option.required
    assert (option.min_value, option.max_value) == (1, 4000)
    assert option.type is discord.AppCommandOptionType.string


@pytest.mark.parametrize("fails", [False, True])
async def test_startup_runs_auto_init_and_survives_model_failure(fails, tmp_path):
    bot = build_bot(db_config(tmp_path, lmstudio_auto_init=True))
    initialize = AsyncMock(return_value="correcto")
    if fails:
        initialize.side_effect = InitializationError("apagado")
    bot.initializer = SimpleNamespace(initialize=initialize)
    bot.tree.sync = AsyncMock(return_value=[])
    await bot.setup_hook()
    initialize.assert_awaited_once()


def test_build_bot_registers_reset_command(tmp_path):
    bot = build_bot(db_config(tmp_path))
    names = {c.name for c in bot.tree.get_commands()}
    assert {"ia", "ia-reset", "panel", "help", "initai"} <= names
