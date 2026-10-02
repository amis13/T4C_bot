# Talent4Cyber Discord Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot de Discord con un panel de botones a los Notion de eJPT, eCPPT y el grupo, y un comando `/ia` conectado a un modelo local de LM Studio.

**Architecture:** Paquete `bot/` con un módulo por responsabilidad. `config.py`, `lmstudio.py` y las funciones puras de `ia.py` no dependen de un Discord en marcha y se prueban con `pytest`. Cada módulo de comando expone `register(tree, ...)`, y `main.py` es el único punto que los une.

**Tech Stack:** Python 3.12, `discord.py` 2.x, `aiohttp`, `python-dotenv`, `pytest`, `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-10-02-talent4cyber-bot-design.md`

## Global Constraints

- Python 3.12 y `discord.py` 2.x.
- Sin intents privilegiados.
- Los comandos se registran solo en el servidor `GUILD_ID`.
- Todo envío de texto usa `AllowedMentions.none()`.
- Todo texto visible para el usuario va en español.
- El `.env` real nunca se versiona.
- Valores fijos: cooldown de `/ia` 10 s por usuario, timeout de LM Studio 120 s por defecto, límite de mensaje 2000 caracteres, `LMSTUDIO_BASE_URL` por defecto `http://localhost:1234/v1`.
- Cada commit termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Entorno de desarrollo en WSL: `.venv-wsl/`. Los comandos de prueba usan `.venv-wsl/bin/python -m pytest`.

## Review Focus

1. Respuesta del modelo con un bloque de código que cruza el límite de 2000 caracteres: cada mensaje debe seguir mostrándose como código. Test en la Task 3.
2. Modelo de razonamiento que devuelve `<think>…</think>` en el contenido: el usuario solo debe ver la respuesta final. Test en la Task 2.
3. El mismo usuario lanza varios `/ia` mientras el primero sigue en curso: el cooldown debe contar desde la invocación, no desde la respuesta. Test en la Task 3.
4. URL de Notion de más de 512 caracteres (límite de Discord para botones): el bot debe fallar al arrancar nombrando la variable, no al ejecutar `/panel`. Test en la Task 1.
5. `LMSTUDIO_BASE_URL` con barra final o `LMSTUDIO_TIMEOUT` no numérico o no positivo: la barra se normaliza y el timeout inválido da `ConfigError`. Test en la Task 1.

---

### Task 1: Andamiaje y configuración

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.env.example`, `bot/__init__.py`, `bot/config.py`, `tests/__init__.py`
- Modify: `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `bot.config.Config` (dataclass inmutable con `discord_token: str`, `guild_id: int`, `notion_ejpt_url: str`, `notion_ecppt_url: str`, `notion_grupo_url: str`, `lmstudio_base_url: str`, `lmstudio_model: str`, `lmstudio_timeout: float`), `bot.config.ConfigError`, `bot.config.load_config(env: Mapping[str, str]) -> Config`.

- [ ] **Step 1: Crear el andamiaje**

`requirements.txt`:

```
discord.py>=2.4,<3
python-dotenv>=1.0
pytest>=8
pytest-asyncio>=0.23
```

`pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`.env.example`:

```
DISCORD_TOKEN=
GUILD_ID=
NOTION_EJPT_URL=
NOTION_ECPPT_URL=
NOTION_GRUPO_URL=
# Opcionales
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=
LMSTUDIO_TIMEOUT=120
```

`.gitignore`:

```
.env
.venv/
.venv-wsl/
__pycache__/
.pytest_cache/
```

`bot/__init__.py` y `tests/__init__.py` vacíos.

Instalar:

```bash
python3 -m venv .venv-wsl
.venv-wsl/bin/python -m pip install -r requirements.txt
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 3: Ejecutar y comprobar que fallan**

Run: `.venv-wsl/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 4: Implementar**

`bot/config.py`:

```python
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
```

- [ ] **Step 5: Ejecutar y comprobar que pasan**

Run: `.venv-wsl/bin/python -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add project scaffold and config loading"
```

---

### Task 2: Cliente de LM Studio

**Files:**
- Create: `bot/lmstudio.py`
- Test: `tests/test_lmstudio.py`

**Interfaces:**
- Produces: `bot.lmstudio.LMStudioClient(base_url: str, model: str = "", timeout: float = 120.0)` con `async def chat(self, system: str, user: str) -> str`; excepciones `LMStudioError` y sus subclases `LMStudioUnavailable`, `LMStudioTimeout`, `LMStudioBadResponse`, cada una con el atributo de clase `user_message: str`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_lmstudio.py`:

```python
import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, unused_port

from bot.lmstudio import (
    LMStudioBadResponse,
    LMStudioClient,
    LMStudioTimeout,
    LMStudioUnavailable,
)


def ok_body(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
async def serve():
    servers = []

    async def _serve(handler):
        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        server = TestServer(app)
        await server.start_server()
        servers.append(server)
        return str(server.make_url("/v1"))

    yield _serve
    for server in servers:
        await server.close()


async def test_returns_stripped_content_and_sends_messages(serve):
    received = {}

    async def handler(request):
        received.update(await request.json())
        return web.json_response(ok_body("  hola  \n"))

    client = LMStudioClient(await serve(handler))
    assert await client.chat("sistema", "pregunta") == "hola"
    assert received["messages"] == [
        {"role": "system", "content": "sistema"},
        {"role": "user", "content": "pregunta"},
    ]
    assert "model" not in received


async def test_sends_model_when_configured(serve):
    received = {}

    async def handler(request):
        received.update(await request.json())
        return web.json_response(ok_body("ok"))

    client = LMStudioClient(await serve(handler), model="qwen")
    await client.chat("s", "u")
    assert received["model"] == "qwen"


async def test_strips_think_blocks(serve):
    async def handler(request):
        return web.json_response(ok_body("<think>razono\nmucho</think>\n\nrespuesta"))

    client = LMStudioClient(await serve(handler))
    assert await client.chat("s", "u") == "respuesta"


async def test_http_error_is_bad_response(serve):
    async def handler(request):
        return web.Response(status=500, text="boom")

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat("s", "u")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        ok_body(""),
        ok_body("   "),
        ok_body(None),
        ok_body("<think>solo razono</think>"),
    ],
)
async def test_unusable_body_is_bad_response(serve, body):
    async def handler(request):
        return web.json_response(body)

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat("s", "u")


async def test_non_json_body_is_bad_response(serve):
    async def handler(request):
        return web.Response(text="<html>no soy json</html>")

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat("s", "u")


async def test_slow_server_is_timeout(serve):
    async def handler(request):
        await asyncio.sleep(2)
        return web.json_response(ok_body("tarde"))

    client = LMStudioClient(await serve(handler), timeout=0.2)
    with pytest.raises(LMStudioTimeout):
        await client.chat("s", "u")


async def test_closed_port_is_unavailable():
    client = LMStudioClient(f"http://127.0.0.1:{unused_port()}/v1", timeout=2)
    with pytest.raises(LMStudioUnavailable):
        await client.chat("s", "u")
```

- [ ] **Step 2: Ejecutar y comprobar que fallan**

Run: `.venv-wsl/bin/python -m pytest tests/test_lmstudio.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot.lmstudio'`

- [ ] **Step 3: Implementar**

`bot/lmstudio.py`:

```python
import asyncio
import re

import aiohttp

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LMStudioError(Exception):
    user_message = "No he podido consultar el modelo."


class LMStudioUnavailable(LMStudioError):
    user_message = "El modelo no está disponible ahora mismo."


class LMStudioTimeout(LMStudioError):
    user_message = "El modelo ha tardado demasiado en responder."


class LMStudioBadResponse(LMStudioError):
    user_message = "El modelo ha devuelto una respuesta no válida."


class LMStudioClient:
    def __init__(self, base_url: str, model: str = "", timeout: float = 120.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def chat(self, system: str, user: str) -> str:
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        }
        if self._model:
            payload["model"] = self._model
        data = await self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LMStudioBadResponse("respuesta sin choices") from exc
        if not isinstance(content, str):
            raise LMStudioBadResponse("contenido no textual")
        content = _THINK.sub("", content).strip()
        if not content:
            raise LMStudioBadResponse("contenido vacío")
        return content

    async def _post(self, payload: dict):
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(self._url, json=payload) as response:
                    if response.status != 200:
                        raise LMStudioBadResponse(f"HTTP {response.status}")
                    return await response.json(content_type=None)
        # asyncio.TimeoutError va primero: ServerTimeoutError también es ClientConnectionError
        except asyncio.TimeoutError as exc:
            raise LMStudioTimeout(str(exc)) from exc
        except aiohttp.ClientConnectionError as exc:
            raise LMStudioUnavailable(str(exc)) from exc
        except (aiohttp.ClientError, ValueError) as exc:
            raise LMStudioBadResponse(str(exc)) from exc
```

- [ ] **Step 4: Ejecutar y comprobar que pasan**

Run: `.venv-wsl/bin/python -m pytest tests/test_lmstudio.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add LM Studio chat client"
```

---

### Task 3: Piezas puras de `/ia`: troceado, cita y cooldown

**Files:**
- Create: `bot/ia.py`
- Test: `tests/test_chunking.py`, `tests/test_cooldown.py`

**Interfaces:**
- Produces: `bot.ia.chunk_text(text: str, limit: int = 2000) -> list[str]`, `bot.ia.format_reply(question: str, answer: str) -> str`, `bot.ia.Cooldown(seconds: float, clock: Callable[[], float] = time.monotonic)` con `remaining(user_id: int) -> float`, `touch(user_id: int) -> None` y `reset(user_id: int) -> None`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_chunking.py`:

```python
from bot.ia import chunk_text, format_reply


def test_short_text_is_a_single_chunk():
    assert chunk_text("hola") == ["hola"]


def test_text_at_the_limit_is_not_split():
    text = "a" * 48
    assert chunk_text(text, limit=48) == [text]


def test_empty_or_blank_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n ") == []


def test_cuts_on_newline():
    text = "a" * 30 + "\n" + "b" * 30
    assert chunk_text(text, limit=48) == ["a" * 30, "b" * 30]


def test_cuts_on_space_when_there_is_no_newline():
    text = "a" * 30 + " " + "b" * 30
    assert chunk_text(text, limit=48) == ["a" * 30, "b" * 30]


def test_word_longer_than_limit_is_hard_split():
    text = "a" * 100
    chunks = chunk_text(text, limit=48)
    assert all(0 < len(chunk) <= 48 for chunk in chunks)
    assert "".join(chunks) == text


def test_code_block_stays_fenced_in_every_chunk():
    lines = [f"linea {i:02d}" for i in range(20)]
    text = "```\n" + "\n".join(lines) + "\n```"
    chunks = chunk_text(text, limit=48)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 48
        assert chunk.startswith("```")
        assert chunk.endswith("```")
        assert chunk.count("```") == 2
        assert chunk != "```\n```"
    body = "\n".join(chunk[4:-4] for chunk in chunks)
    assert body == "\n".join(lines)


def test_text_after_a_code_block_is_not_fenced():
    text = "```\n" + "x" * 30 + "\n```\n" + "y" * 30
    chunks = chunk_text(text, limit=48)
    assert chunks[-1] == "y" * 30


def test_format_reply_quotes_the_question():
    assert format_reply("¿qué es nmap?", "Un escáner.") == "> ¿qué es nmap?\n\nUn escáner."


def test_format_reply_flattens_and_truncates_long_questions():
    reply = format_reply("uno\ndos " + "x" * 300, "ok")
    quote = reply.split("\n\n")[0]
    assert "\n" not in quote
    assert quote.startswith("> uno dos ")
    assert len(quote) == 202
    assert quote.endswith("…")
```

`tests/test_cooldown.py`:

```python
from bot.ia import Cooldown


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_unknown_user_has_no_cooldown():
    assert Cooldown(10, clock=FakeClock()).remaining(1) == 0


def test_cooldown_counts_from_the_invocation():
    clock = FakeClock()
    cooldown = Cooldown(10, clock=clock)
    cooldown.touch(1)
    assert cooldown.remaining(1) == 10
    clock.now += 4
    assert cooldown.remaining(1) == 6


def test_cooldown_expires():
    clock = FakeClock()
    cooldown = Cooldown(10, clock=clock)
    cooldown.touch(1)
    clock.now += 10
    assert cooldown.remaining(1) == 0


def test_cooldown_is_per_user():
    cooldown = Cooldown(10, clock=FakeClock())
    cooldown.touch(1)
    assert cooldown.remaining(2) == 0


def test_reset_clears_the_cooldown():
    cooldown = Cooldown(10, clock=FakeClock())
    cooldown.touch(1)
    cooldown.reset(1)
    assert cooldown.remaining(1) == 0
    cooldown.reset(1)
```

- [ ] **Step 2: Ejecutar y comprobar que fallan**

Run: `.venv-wsl/bin/python -m pytest tests/test_chunking.py tests/test_cooldown.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot.ia'`

- [ ] **Step 3: Implementar**

`bot/ia.py`:

```python
import time
from typing import Callable

MESSAGE_LIMIT = 2000
QUOTE_LIMIT = 200
FENCE = "```"
# Hueco para cerrar un bloque de código al final de un trozo y reabrirlo en el siguiente
_FENCE_ROOM = 2 * (len(FENCE) + 1)


def _split(text: str, limit: int) -> list[str]:
    pieces = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def chunk_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks = []
    in_code = False
    for piece in _split(text, limit - _FENCE_ROOM):
        if in_code:
            if piece == FENCE:
                in_code = False
                continue
            piece = FENCE + "\n" + piece
        in_code = piece.count(FENCE) % 2 == 1
        if in_code:
            piece += "\n" + FENCE
        chunks.append(piece)
    return chunks


def format_reply(question: str, answer: str) -> str:
    quote = " ".join(question.split())
    if len(quote) > QUOTE_LIMIT:
        quote = quote[: QUOTE_LIMIT - 1] + "…"
    return f"> {quote}\n\n{answer}"


class Cooldown:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def remaining(self, user_id: int) -> float:
        last = self._last.get(user_id)
        if last is None:
            return 0
        return max(0, self._seconds - (self._clock() - last))

    def touch(self, user_id: int) -> None:
        self._last[user_id] = self._clock()

    def reset(self, user_id: int) -> None:
        self._last.pop(user_id, None)
```

- [ ] **Step 4: Ejecutar y comprobar que pasan**

Run: `.venv-wsl/bin/python -m pytest tests/test_chunking.py tests/test_cooldown.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add reply chunking, quoting and cooldown for /ia"
```

---

### Task 4: Panel y ayuda

**Files:**
- Create: `bot/panel.py`, `bot/help.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- Consumes: `bot.config.Config`.
- Produces: `bot.panel.build_panel(config: Config) -> tuple[discord.Embed, discord.ui.View]`, `bot.panel.register(tree: app_commands.CommandTree, config: Config) -> None`, `bot.help.build_help() -> discord.Embed`, `bot.help.register(tree: app_commands.CommandTree) -> None`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_panel.py`:

```python
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
```

- [ ] **Step 2: Ejecutar y comprobar que fallan**

Run: `.venv-wsl/bin/python -m pytest tests/test_panel.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot.help'`

- [ ] **Step 3: Implementar**

`bot/panel.py`:

```python
import discord
from discord import app_commands

from bot.config import Config

COLOR = 0x00B894


def build_panel(config: Config) -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="Talent4Cyber · Recursos del grupo",
        description=(
            "Todo lo que usamos para preparar el evento, a un clic.\n\n"
            "📘 **eJPT**: apuntes y laboratorios\n"
            "📕 **eCPPT**: apuntes y laboratorios\n"
            "👥 **Grupo**: organización, tareas y notas comunes\n\n"
            "¿Dudas? Pregunta al modelo del grupo con `/ia`."
        ),
        color=COLOR,
    )
    # Botones de enlace: no generan interacciones, siguen funcionando con el bot apagado
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="eJPT", emoji="📘", url=config.notion_ejpt_url))
    view.add_item(discord.ui.Button(label="eCPPT", emoji="📕", url=config.notion_ecppt_url))
    view.add_item(discord.ui.Button(label="Grupo", emoji="👥", url=config.notion_grupo_url))
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
```

`bot/help.py`:

```python
import discord
from discord import app_commands

from bot.panel import COLOR

COMMANDS = [
    ("/panel", "Publica el mensaje principal con los enlaces a los Notion. Solo administración."),
    ("/ia", "Pregunta al modelo local del grupo. Cada pregunta es independiente."),
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
```

- [ ] **Step 4: Ejecutar y comprobar que pasan**

Run: `.venv-wsl/bin/python -m pytest tests/test_panel.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add panel and help commands"
```

---

### Task 5: Comando `/ia`, arranque y README

**Files:**
- Modify: `bot/ia.py` (añadir imports, constantes y `register` al final)
- Create: `bot/main.py`, `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `bot.config.Config`, `ConfigError`, `load_config`; `bot.lmstudio.LMStudioClient`, `LMStudioError` (con `user_message`); `bot.ia.chunk_text`, `format_reply`, `Cooldown`; `bot.panel.register(tree, config)`; `bot.help.register(tree)`.
- Produces: `bot.ia.register(tree: app_commands.CommandTree, client: LMStudioClient) -> None`, `bot.main.build_bot(config: Config) -> Bot` (subclase de `discord.Client` con atributo `tree`), `bot.main.main() -> int`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_main.py`:

```python
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
```

- [ ] **Step 2: Ejecutar y comprobar que falla**

Run: `.venv-wsl/bin/python -m pytest tests/test_main.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot.main'`

- [ ] **Step 3: Añadir el comando a `bot/ia.py`**

Sustituir los imports del principio del fichero por:

```python
import asyncio
import logging
import math
import time
from typing import Callable

import discord
from discord import app_commands

from bot.lmstudio import LMStudioClient, LMStudioError

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 10
QUESTION_LIMIT = 1000
SYSTEM_PROMPT = (
    "Eres el asistente de un grupo que prepara las certificaciones eJPT y eCPPT "
    "para el evento Talent4Cyber. Ayudas con pentesting, redes, sistemas y "
    "ciberseguridad en entornos de laboratorio y con autorización. "
    "Responde siempre en español, de forma concisa y práctica, y usa bloques de "
    "código para los comandos."
)
```

Añadir al final del fichero:

```python
def register(tree: app_commands.CommandTree, client: LMStudioClient) -> None:
    cooldown = Cooldown(COOLDOWN_SECONDS)
    lock = asyncio.Lock()
    no_mentions = discord.AllowedMentions.none()

    @tree.command(name="ia", description="Pregunta al modelo local del grupo")
    @app_commands.describe(mensaje="Lo que quieres preguntar")
    async def ia(
        interaction: discord.Interaction,
        mensaje: app_commands.Range[str, 1, QUESTION_LIMIT],
    ):
        user_id = interaction.user.id
        remaining = cooldown.remaining(user_id)
        if remaining > 0:
            await interaction.response.send_message(
                f"Espera {math.ceil(remaining)} s antes de volver a preguntar.",
                ephemeral=True,
            )
            return
        # El cooldown cuenta desde la invocación para que no se encolen varias preguntas
        cooldown.touch(user_id)
        await interaction.response.defer(thinking=True)
        try:
            async with lock:
                answer = await client.chat(SYSTEM_PROMPT, mensaje)
        except LMStudioError as exc:
            cooldown.reset(user_id)
            log.warning("Fallo de LM Studio: %s: %s", type(exc).__name__, exc)
            # Se borra el "pensando…" público para que el aviso solo lo vea quien preguntó
            await interaction.delete_original_response()
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        for chunk in chunk_text(format_reply(mensaje, answer)):
            await interaction.followup.send(chunk, allowed_mentions=no_mentions)
```

- [ ] **Step 4: Crear `bot/main.py`**

```python
import logging
import os
import sys

import discord
from discord import app_commands
from dotenv import load_dotenv

from bot import help as help_command
from bot import ia, panel
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
        config.lmstudio_base_url, config.lmstudio_model, config.lmstudio_timeout
    )
    panel.register(bot.tree, config)
    ia.register(bot.tree, client)
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
```

- [ ] **Step 5: Ejecutar toda la suite**

Run: `.venv-wsl/bin/python -m pytest -q`
Expected: PASS en todos los tests

- [ ] **Step 6: Comprobar el arranque sin configuración**

Run: `env -i PATH="$PATH" .venv-wsl/bin/python -m bot.main; echo "exit=$?"`
Expected: `Error de configuración: Falta la variable DISCORD_TOKEN en el .env` y `exit=1`

- [ ] **Step 7: Escribir `README.md`**

````markdown
# Bot de Discord · Talent4Cyber

Bot del grupo para Talent4Cyber: un panel con botones a los Notion de eJPT, eCPPT
y el grupo, y un comando `/ia` conectado a un modelo local en LM Studio.

## Comandos

| Comando | Qué hace |
|---|---|
| `/panel` | Publica el mensaje principal con los tres botones. Requiere "Gestionar servidor". |
| `/ia mensaje:<texto>` | Pregunta al modelo de LM Studio. Sin memoria, 10 s de espera por usuario. |
| `/help` | Lista los comandos. |

## 1. Crear el bot en Discord

1. En <https://discord.com/developers/applications>, crea una aplicación.
2. En **Bot**, pulsa **Reset Token** y copia el token. No hace falta activar
   ningún intent privilegiado.
3. En **OAuth2 → URL Generator**, marca los scopes `bot` y
   `applications.commands`, y los permisos **Send Messages** y **Embed Links**.
   Abre la URL generada e invita el bot a tu servidor.
4. En Discord, activa **Ajustes → Avanzado → Modo desarrollador**, haz clic
   derecho en el servidor y pulsa **Copiar ID del servidor**.

## 2. Configurar

Copia `.env.example` a `.env` y rellénalo:

| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot. |
| `GUILD_ID` | ID del servidor. |
| `NOTION_EJPT_URL` | Enlace al Notion de eJPT. |
| `NOTION_ECPPT_URL` | Enlace al Notion de eCPPT. |
| `NOTION_GRUPO_URL` | Enlace al Notion del grupo. |
| `LMSTUDIO_BASE_URL` | Opcional. Por defecto `http://localhost:1234/v1`. |
| `LMSTUDIO_MODEL` | Opcional. Vacío usa el modelo cargado en LM Studio. |
| `LMSTUDIO_TIMEOUT` | Opcional. Segundos de espera, por defecto `120`. |

## 3. Arrancar LM Studio

En LM Studio, carga un modelo y arranca el servidor en la pestaña **Developer**
(puerto 1234).

## 4. Ejecutar el bot

En Windows (PowerShell), que es lo más simple porque LM Studio queda en
`localhost`:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bot.main
```

En WSL, LM Studio no está en `localhost`. Activa **Serve on Local Network** en
LM Studio y pon en el `.env` la IP de Windows:

```bash
python3 -m venv .venv-wsl
.venv-wsl/bin/python -m pip install -r requirements.txt
echo "LMSTUDIO_BASE_URL=http://$(ip route show default | awk '{print $3}'):1234/v1"
.venv-wsl/bin/python -m bot.main
```

## 5. Probar en Discord

1. `/help` muestra los tres comandos.
2. `/panel` publica el mensaje y los tres botones abren su Notion.
3. `/ia mensaje:¿qué es nmap?` responde con el modelo.
4. Con el servidor de LM Studio parado, `/ia` avisa de que el modelo no está
   disponible.

## Tests

```bash
.venv-wsl/bin/python -m pytest -q
```
````

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: wire /ia command, bot entry point and README"
```
