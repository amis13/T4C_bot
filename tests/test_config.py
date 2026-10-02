import pytest

from bot.config import ConfigError, load_config

BASE = {
    "DISCORD_TOKEN": "token",
    "GUILD_ID": "123",
    "NOTION_EJPT_URL": "https://notion.so/ejpt",
    "NOTION_ECPPT_URL": "https://notion.so/ecppt",
    "NOTION_GRUPO_URL": "https://notion.so/grupo",
}


def test_loads_required_values_and_defaults():
    config = load_config(BASE)
    assert config.discord_token == "token"
    assert config.guild_id == 123
    assert config.notion_ejpt_url == "https://notion.so/ejpt"
    assert config.notion_ecppt_url == "https://notion.so/ecppt"
    assert config.notion_grupo_url == "https://notion.so/grupo"
    assert config.lmstudio_base_url == "http://localhost:1234/v1"
    assert config.lmstudio_model == ""
    assert config.lmstudio_timeout == 120.0


@pytest.mark.parametrize("name", list(BASE))
def test_missing_required_variable_names_it(name):
    env = {k: v for k, v in BASE.items() if k != name}
    with pytest.raises(ConfigError, match=name):
        load_config(env)


def test_blank_required_variable_is_missing():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config({**BASE, "DISCORD_TOKEN": "   "})


def test_guild_id_must_be_integer():
    with pytest.raises(ConfigError, match="GUILD_ID"):
        load_config({**BASE, "GUILD_ID": "abc"})


def test_notion_url_must_be_http():
    with pytest.raises(ConfigError, match="NOTION_ECPPT_URL"):
        load_config({**BASE, "NOTION_ECPPT_URL": "notion.so/ecppt"})


def test_notion_url_over_512_chars_is_rejected():
    url = "https://notion.so/" + "a" * 500
    with pytest.raises(ConfigError, match="NOTION_GRUPO_URL"):
        load_config({**BASE, "NOTION_GRUPO_URL": url})


def test_optional_values_are_read():
    config = load_config(
        {
            **BASE,
            "LMSTUDIO_BASE_URL": "http://192.168.1.10:1234/v1/",
            "LMSTUDIO_MODEL": "qwen",
            "LMSTUDIO_TIMEOUT": "30",
        }
    )
    assert config.lmstudio_base_url == "http://192.168.1.10:1234/v1"
    assert config.lmstudio_model == "qwen"
    assert config.lmstudio_timeout == 30.0


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_timeout_is_rejected(value):
    with pytest.raises(ConfigError, match="LMSTUDIO_TIMEOUT"):
        load_config({**BASE, "LMSTUDIO_TIMEOUT": value})


def test_base_url_must_be_http():
    with pytest.raises(ConfigError, match="LMSTUDIO_BASE_URL"):
        load_config({**BASE, "LMSTUDIO_BASE_URL": "localhost:1234"})
