import discord

from bot.config import Config
from bot.help import build_help
from bot.panel import build_panel

CONFIG = Config(
    discord_token="token",
    guild_id=1,
    notion_ejpt_url="https://notion.so/ejpt",
    notion_ecppt_url="https://notion.so/ecppt",
    notion_grupo_url="https://notion.so/grupo",
)


async def test_panel_has_three_link_buttons_in_order():
    embed, view = build_panel(CONFIG)
    assert embed.title
    assert embed.description
    assert [(button.label, button.url) for button in view.children] == [
        ("eJPT", "https://notion.so/ejpt"),
        ("eCPPT", "https://notion.so/ecppt"),
        ("Grupo", "https://notion.so/grupo"),
    ]
    assert all(button.style is discord.ButtonStyle.link for button in view.children)


def test_help_lists_every_command():
    embed = build_help()
    names = [field.name for field in embed.fields]
    assert names == ["/panel", "/ia", "/help"]
    assert all(field.value for field in embed.fields)
