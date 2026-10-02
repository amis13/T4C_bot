from dataclasses import dataclass
from typing import Mapping

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_TIMEOUT = 120.0
BUTTON_URL_LIMIT = 512


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int
    notion_ejpt_url: str
    notion_ecppt_url: str
    notion_grupo_url: str
    lmstudio_base_url: str = DEFAULT_BASE_URL
    lmstudio_model: str = ""
    lmstudio_timeout: float = DEFAULT_TIMEOUT


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Falta la variable {name} en el .env")
    return value


def _check_http(name: str, value: str) -> str:
    if not value.startswith(("http://", "https://")):
        raise ConfigError(f"{name} debe empezar por http:// o https://")
    return value


def _notion_url(env: Mapping[str, str], name: str) -> str:
    value = _check_http(name, _required(env, name))
    if len(value) > BUTTON_URL_LIMIT:
        raise ConfigError(
            f"{name} supera los {BUTTON_URL_LIMIT} caracteres que admite un botón de Discord"
        )
    return value


def _guild_id(env: Mapping[str, str]) -> int:
    value = _required(env, "GUILD_ID")
    try:
        return int(value)
    except ValueError:
        raise ConfigError("GUILD_ID debe ser el ID numérico del servidor") from None


def _timeout(env: Mapping[str, str]) -> float:
    raw = env.get("LMSTUDIO_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0:
        raise ConfigError("LMSTUDIO_TIMEOUT debe ser un número de segundos mayor que 0")
    return value


def load_config(env: Mapping[str, str]) -> Config:
    base_url = env.get("LMSTUDIO_BASE_URL", "").strip() or DEFAULT_BASE_URL
    return Config(
        discord_token=_required(env, "DISCORD_TOKEN"),
        guild_id=_guild_id(env),
        notion_ejpt_url=_notion_url(env, "NOTION_EJPT_URL"),
        notion_ecppt_url=_notion_url(env, "NOTION_ECPPT_URL"),
        notion_grupo_url=_notion_url(env, "NOTION_GRUPO_URL"),
        lmstudio_base_url=_check_http("LMSTUDIO_BASE_URL", base_url).rstrip("/"),
        lmstudio_model=env.get("LMSTUDIO_MODEL", "").strip(),
        lmstudio_timeout=_timeout(env),
    )
