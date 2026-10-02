import discord

from bot.config import Config
from bot.main import build_bot

CONFIG = Config(
    discord_token="token",
    guild_id=1,
    notion_ejpt_url="https://notion.so/ejpt",
    notion_ecppt_url="https://notion.so/ecppt",
    notion_grupo_url="https://notion.so/grupo",
)


def test_bot_registers_the_three_commands():
    bot = build_bot(CONFIG)
    assert {command.name for command in bot.tree.get_commands()} == {"panel", "ia", "help"}


def test_bot_never_mentions_and_uses_no_privileged_intents():
    bot = build_bot(CONFIG)
    mentions = bot.allowed_mentions
    assert (mentions.everyone, mentions.users, mentions.roles) == (False, False, False)
    assert not bot.intents.message_content
    assert not bot.intents.members
    assert not bot.intents.presences


def test_ia_message_option_is_bounded():
    bot = build_bot(CONFIG)
    option = bot.tree.get_command("ia").parameters[0]
    assert option.name == "mensaje"
    assert option.required
    assert (option.min_value, option.max_value) == (1, 1000)
    assert option.type is discord.AppCommandOptionType.string
