import discord

from bot.config import Config
from bot.help import build_help
from bot.panel import RESOURCES, build_panel

CONFIG = Config(
    discord_token="token",
    guild_id=1,
    notion_ejpt_url="https://notion.so/ejpt",
    notion_ecppt_url="https://notion.so/ecppt",
    notion_grupo_url="https://notion.so/grupo",
)


async def test_first_row_has_the_three_notion_buttons_in_order():
    embed, view = build_panel(CONFIG)
    assert embed.title
    assert embed.description
    notion = [button for button in view.children if button.row == 0]
    assert [(button.label, button.url) for button in notion] == [
        ("eJPT", "https://notion.so/ejpt"),
        ("eCPPT", "https://notion.so/ecppt"),
        ("Grupo", "https://notion.so/grupo"),
    ]


async def test_resource_buttons_follow_the_notion_row():
    _, view = build_panel(CONFIG)
    resources = [button for button in view.children if button.row != 0]
    assert [(button.label, button.url) for button in resources] == [
        (label, url) for label, _, url in RESOURCES
    ]
    assert dict(
        (button.label, button.url) for button in resources
    )["Exploit-DB"] == "https://www.exploit-db.com/"


async def test_every_button_is_a_valid_link_and_rows_fit_discord_limits():
    _, view = build_panel(CONFIG)
    rows = {}
    for button in view.children:
        assert button.style is discord.ButtonStyle.link
        assert button.url.startswith("https://")
        assert len(button.url) <= 512
        rows[button.row] = rows.get(button.row, 0) + 1
    assert len(rows) <= 5
    assert all(count <= 5 for count in rows.values())


def test_help_lists_every_command():
    embed = build_help()
    names = [field.name for field in embed.fields]
    assert names == ["/panel", "/ia", "/initai", "/help"]
    assert all(field.value for field in embed.fields)
