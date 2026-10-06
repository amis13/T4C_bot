# Memoria y streaming para `/ia` — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar a `/ia` memoria de conversación por canal (persistente) y respuesta en streaming con preview en vivo, más un `/ia-reset`.

**Architecture:** La memoria vive en SQLite (`bot/memory.py`), se guarda entera y se envía al modelo solo una ventana recortada por tokens. `bot/lmstudio.py` pasa a hablar con listas de `messages` y gana un `stream_chat` que parsea SSE. `bot/ia.py` arma `[system] + ventana + pregunta`, muestra un preview editando la respuesta diferida mientras streamea, y al terminar reutiliza intacta la lógica de troceado/adjunto actual, guardando el turno solo si hubo éxito.

**Tech Stack:** Python 3.12, discord.py 2.x, aiohttp, sqlite3 (stdlib), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-06-ia-memory-streaming-design.md`

## Global Constraints

- Python 3.12; sin dependencias nuevas (SQLite es stdlib).
- Mensajes de cara a Discord en español.
- Interacciones y HTTP asíncronos; SQLite (bloqueante) va en `asyncio.to_thread`.
- Respuestas de error privadas (`ephemeral=True`) y `allowed_mentions=none()` en envíos con contenido del modelo, como hoy.
- Seguir el patrón `register(...)` por módulo.
- `IA_HISTORY_TOKENS` por defecto `3000`; `IA_DB_PATH` por defecto `ia_history.db`.
- El fichero SQLite no se versiona (`.gitignore`).
- Actualizar `.env.example` y `README.md` cuando cambie configuración.

## Review Focus

- **Un turno previo más grande que todo el presupuesto:** `window` va del más reciente al más viejo y para al primer desbordamiento; si el turno previo más reciente ya no cabe, devuelve `[]` (no se arrastra un pegote que reventaría el contexto). → Task 2.
- **Fallo de SQLite al leer la ventana:** la respuesta no se interrumpe; se degrada a conversación sin historial y se registra en log. → Task 4.
- **`finish_reason == "length"` en el stream:** se trata como truncado, no se publica lo parcial como definitivo ni se guarda en memoria. → Task 4.
- **Escrituras concurrentes de dos usuarios en el mismo canal:** el orden del historial es estable (por `id` autoincremental). → Task 2.
- **Líneas SSE vacías, comentarios o `data:` partidas:** el parser las ignora con robustez y solo corta en `[DONE]`. → Task 3.

---

## File Structure

- `bot/memory.py` (nuevo): `ConversationStore` sobre SQLite. Única responsabilidad: persistir y recortar el historial por canal.
- `bot/lmstudio.py` (modificar): `chat(messages)` y `stream_chat(messages)`; expone `strip_reasoning`.
- `bot/ia.py` (modificar): `register(tree, client, store, operation_lock=None, clock=...)`; añade `/ia` con streaming+memoria y `/ia-reset`.
- `bot/config.py` (modificar): `ia_history_tokens`, `ia_db_path`.
- `bot/main.py` (modificar): instancia el store y lo cablea.
- `.gitignore`, `.env.example`, `README.md` (modificar).
- Tests: `tests/test_memory.py` (nuevo), y ampliaciones en `tests/test_lmstudio.py`, `tests/test_ia_command.py`, `tests/test_config.py`.

---

### Task 1: Configuración (`IA_HISTORY_TOKENS`, `IA_DB_PATH`)

**Files:**
- Modify: `bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.ia_history_tokens: int` (def. 3000), `Config.ia_db_path: str` (def. `"ia_history.db"`).

- [ ] **Step 1: Write the failing tests**

En `tests/test_config.py`, añade (reutiliza el helper de entorno que ya use el fichero; si construye un dict mínimo, parte de él):

```python
def test_history_defaults_when_absent(valid_env):
    config = load_config(valid_env)
    assert config.ia_history_tokens == 3000
    assert config.ia_db_path == "ia_history.db"


def test_history_tokens_must_be_positive_int(valid_env):
    import pytest
    from bot.config import ConfigError
    valid_env["IA_HISTORY_TOKENS"] = "0"
    with pytest.raises(ConfigError):
        load_config(valid_env)


def test_history_values_are_read_from_env(valid_env):
    valid_env["IA_HISTORY_TOKENS"] = "1500"
    valid_env["IA_DB_PATH"] = "/data/ia.db"
    config = load_config(valid_env)
    assert config.ia_history_tokens == 1500
    assert config.ia_db_path == "/data/ia.db"
```

Si no existe un fixture `valid_env`, crea uno que devuelva un dict con las variables requeridas (`DISCORD_TOKEN`, `GUILD_ID`, las tres `NOTION_*_URL`) ya válidas, copiando los valores que usan los tests existentes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-wsl/bin/python -m pytest tests/test_config.py -k history -v`
Expected: FAIL (`AttributeError: ... ia_history_tokens` o `TypeError`).

- [ ] **Step 3: Implement**

En `bot/config.py` añade la constante y el parser, y los campos al dataclass:

```python
DEFAULT_HISTORY_TOKENS = 3000
DEFAULT_DB_PATH = "ia_history.db"
```

En `Config` (tras `lmstudio_auto_init`):

```python
    ia_history_tokens: int = DEFAULT_HISTORY_TOKENS
    ia_db_path: str = DEFAULT_DB_PATH
```

Parser (junto a `_max_tokens`):

```python
def _history_tokens(env: Mapping[str, str]) -> int:
    raw = env.get("IA_HISTORY_TOKENS", "").strip()
    if not raw:
        return DEFAULT_HISTORY_TOKENS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError("IA_HISTORY_TOKENS debe ser un entero mayor que 0")
    return value
```

En `load_config(...)`, añade a la construcción de `Config`:

```python
        ia_history_tokens=_history_tokens(env),
        ia_db_path=env.get("IA_DB_PATH", "").strip() or DEFAULT_DB_PATH,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-wsl/bin/python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat: add IA_HISTORY_TOKENS and IA_DB_PATH config"
```

---

### Task 2: `ConversationStore` (memoria SQLite)

**Files:**
- Create: `bot/memory.py`
- Test: `tests/test_memory.py`

**Interfaces:**
- Produces:
  - `estimate_tokens(text: str) -> int`
  - `class ConversationStore:`
    - `__init__(self, path: str)`
    - `append(self, channel_id: int, role: str, content: str) -> None`
    - `window(self, channel_id: int, budget_tokens: int) -> list[dict]` → `[{"role": str, "content": str}, ...]` en orden cronológico
    - `reset(self, channel_id: int) -> None`
- Consumes: nada.

Nota: los métodos son **síncronos** (SQLite). `ia.py` los llamará con `asyncio.to_thread`. La conexión se abre en `__init__` con `check_same_thread=False` y cada operación se protege con un `threading.Lock`.

- [ ] **Step 1: Write the failing tests**

```python
from bot.memory import ConversationStore, estimate_tokens


def make_store(tmp_path):
    return ConversationStore(str(tmp_path / "ia.db"))


def test_estimate_tokens_grows_with_length():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("x" * 400) > estimate_tokens("x" * 40)


def test_window_returns_turns_in_chronological_order(tmp_path):
    store = make_store(tmp_path)
    store.append(10, "user", "uno")
    store.append(10, "assistant", "dos")
    store.append(10, "user", "tres")
    assert store.window(10, budget_tokens=1000) == [
        {"role": "user", "content": "uno"},
        {"role": "assistant", "content": "dos"},
        {"role": "user", "content": "tres"},
    ]


def test_window_is_isolated_per_channel(tmp_path):
    store = make_store(tmp_path)
    store.append(1, "user", "canal uno")
    store.append(2, "user", "canal dos")
    assert store.window(1, 1000) == [{"role": "user", "content": "canal uno"}]


def test_window_drops_oldest_turns_beyond_budget(tmp_path):
    store = make_store(tmp_path)
    for i in range(10):
        store.append(5, "user", "x" * 400)  # ~100 tokens cada uno
    result = store.window(5, budget_tokens=250)
    assert 1 <= len(result) < 10
    # conserva los más recientes: todos son iguales aquí, basta comprobar el recorte


def test_window_drops_a_single_oversized_recent_turn(tmp_path):
    store = make_store(tmp_path)
    store.append(5, "user", "contexto previo corto")
    store.append(5, "user", "y" * 100000)  # el más reciente no cabe
    assert store.window(5, budget_tokens=100) == []


def test_reset_clears_only_that_channel(tmp_path):
    store = make_store(tmp_path)
    store.append(1, "user", "a")
    store.append(2, "user", "b")
    store.reset(1)
    assert store.window(1, 1000) == []
    assert store.window(2, 1000) == [{"role": "user", "content": "b"}]


def test_history_survives_reopening_the_store(tmp_path):
    path = str(tmp_path / "ia.db")
    first = ConversationStore(path)
    first.append(7, "user", "persistente")
    second = ConversationStore(path)
    assert second.window(7, 1000) == [{"role": "user", "content": "persistente"}]


def test_ordering_is_stable_for_same_channel(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.append(3, "user", str(i))
    assert [m["content"] for m in store.window(3, 10000)] == ["0", "1", "2", "3", "4"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-wsl/bin/python -m pytest tests/test_memory.py -v`
Expected: FAIL (`ModuleNotFoundError: bot.memory`).

- [ ] **Step 3: Implement**

```python
import sqlite3
import threading
import time

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


class ConversationStore:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "channel_id INTEGER NOT NULL, ts REAL NOT NULL, "
            "role TEXT NOT NULL, content TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id, id)"
        )
        self._db.commit()

    def append(self, channel_id: int, role: str, content: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO messages(channel_id, ts, role, content) VALUES (?, ?, ?, ?)",
                (channel_id, time.time(), role, content),
            )
            self._db.commit()

    def window(self, channel_id: int, budget_tokens: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM messages WHERE channel_id = ? ORDER BY id DESC",
                (channel_id,),
            ).fetchall()
        selected = []
        used = 0
        for role, content in rows:
            used += estimate_tokens(content)
            if used > budget_tokens:
                break
            selected.append({"role": role, "content": content})
        selected.reverse()
        return selected

    def reset(self, channel_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
            self._db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-wsl/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/memory.py tests/test_memory.py
git commit -m "feat: add per-channel conversation store"
```

---

### Task 3: `lmstudio.py` — mensajes + streaming

**Files:**
- Modify: `bot/lmstudio.py`
- Test: `tests/test_lmstudio.py`

**Interfaces:**
- Produces:
  - `strip_reasoning(content: str) -> str` (renombrado de `_strip_reasoning`, público).
  - `class StreamEvent` (dataclass): `text: str`, `reasoning: str`, `finish_reason: str | None`.
  - `LMStudioClient.chat(self, messages: list[dict]) -> str` (ya **no** `(system, user)`).
  - `LMStudioClient.stream_chat(self, messages: list[dict]) -> AsyncIterator[StreamEvent]`.
- Consumes: nada nuevo.

- [ ] **Step 1: Write the failing tests**

En `tests/test_lmstudio.py`, primero un helper y la migración de la firma. Añade arriba:

```python
def msgs(system, user):
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

Y **cambia todas** las llamadas existentes `client.chat("s", "u")` / `client.chat("sistema", "pregunta")` por `client.chat(msgs("s", "u"))` / `client.chat(msgs("sistema", "pregunta"))`. En `test_returns_stripped_content_and_sends_messages`, la aserción `received["messages"] == [...]` ya coincide con `msgs("sistema", "pregunta")`, déjala igual.

Añade tests nuevos de streaming (SSE). Reutiliza el fixture `serve`, pero registra un handler que emita eventos:

```python
import json
from bot.lmstudio import StreamEvent, strip_reasoning


def sse(events):
    async def handler(request):
        resp = web.StreamResponse()
        resp.headers["Content-Type"] = "text/event-stream"
        await resp.prepare(request)
        for line in events:
            await resp.write(line.encode("utf-8"))
        await resp.write_eof()
        return resp
    return handler


def delta(content=None, reasoning=None, finish=None):
    choice = {"delta": {}}
    if content is not None:
        choice["delta"]["content"] = content
    if reasoning is not None:
        choice["delta"]["reasoning_content"] = reasoning
    if finish is not None:
        choice["finish_reason"] = finish
    return "data: " + json.dumps({"choices": [choice]}) + "\n\n"


async def collect(client, messages):
    return [event async for event in client.stream_chat(messages)]


async def test_stream_yields_text_deltas_and_stops_at_done(serve):
    events = [delta("ho"), delta("la"), "data: [DONE]\n\n", delta("IGNORA")]
    client = LMStudioClient(await serve(sse(events)))
    out = await collect(client, msgs("s", "u"))
    assert "".join(e.text for e in out) == "hola"


async def test_stream_ignores_blank_and_non_data_lines(serve):
    events = ["\n", ": comentario\n", delta("ok"), "\n"]
    client = LMStudioClient(await serve(sse(events)))
    out = await collect(client, msgs("s", "u"))
    assert "".join(e.text for e in out) == "ok"


async def test_stream_separates_reasoning_from_text(serve):
    events = [delta(reasoning="pienso"), delta("respuesta")]
    client = LMStudioClient(await serve(sse(events)))
    out = await collect(client, msgs("s", "u"))
    assert "".join(e.text for e in out) == "respuesta"
    assert any(e.reasoning == "pienso" for e in out)


async def test_stream_exposes_finish_reason(serve):
    events = [delta("parcial", finish="length")]
    client = LMStudioClient(await serve(sse(events)))
    out = await collect(client, msgs("s", "u"))
    assert out[-1].finish_reason == "length"


async def test_stream_enables_streaming_in_payload(serve):
    received = {}

    async def handler(request):
        received.update(await request.json())
        resp = web.StreamResponse()
        await resp.prepare(request)
        await resp.write(delta("x").encode("utf-8"))
        await resp.write_eof()
        return resp

    client = LMStudioClient(await serve(handler))
    await collect(client, msgs("s", "u"))
    assert received["stream"] is True
```

(Opcional: añade `strip_reasoning("<think>a</think>b") == "b"` para fijar el renombrado.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-wsl/bin/python -m pytest tests/test_lmstudio.py -v`
Expected: FAIL (`ImportError: strip_reasoning/StreamEvent`, y `chat()` recibe lista donde esperaba dos args).

- [ ] **Step 3: Implement**

En `bot/lmstudio.py`:

1. Añade `import json` y `from dataclasses import dataclass`, `from typing import AsyncIterator`.
2. Renombra `_strip_reasoning` a `strip_reasoning` (público) y actualiza su uso interno.
3. Añade el dataclass de evento:

```python
@dataclass
class StreamEvent:
    text: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
```

4. Extrae el payload y reescribe `chat` para aceptar `messages`:

```python
    def _payload(self, messages: list[dict], stream: bool) -> dict:
        payload = {
            "temperature": 0.6, "top_p": 0.95, "top_k": 20,
            "max_tokens": self._max_tokens, "stream": stream,
            "messages": messages,
        }
        if self._model:
            payload["model"] = self._model
        return payload

    async def chat(self, messages: list[dict]) -> str:
        data = await self._post(self._payload(messages, stream=False))
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LMStudioBadResponse("respuesta sin choices") from exc
        if not isinstance(content, str):
            if choice.get("finish_reason") == "length":
                raise LMStudioTruncated("límite de generación sin respuesta textual")
            raise LMStudioBadResponse("contenido no textual")
        content = strip_reasoning(content)
        if choice.get("finish_reason") == "length":
            raise LMStudioTruncated("límite de generación alcanzado")
        if not content:
            raise LMStudioBadResponse("contenido vacío")
        return content
```

5. Añade `stream_chat`:

```python
    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[StreamEvent]:
        payload = self._payload(messages, stream=True)
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(self._url, json=payload) as response:
                    if response.status != 200:
                        raise LMStudioBadResponse(f"HTTP {response.status}")
                    async for raw in response.content:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            return
                        try:
                            choice = json.loads(data)["choices"][0]
                        except (ValueError, KeyError, IndexError, TypeError) as exc:
                            raise LMStudioBadResponse("evento SSE no válido") from exc
                        delta = choice.get("delta") or {}
                        yield StreamEvent(
                            text=delta.get("content") or "",
                            reasoning=delta.get("reasoning_content") or "",
                            finish_reason=choice.get("finish_reason"),
                        )
        except asyncio.TimeoutError as exc:
            raise LMStudioTimeout(str(exc)) from exc
        except aiohttp.ClientConnectionError as exc:
            raise LMStudioUnavailable(str(exc)) from exc
        except (aiohttp.ClientError, ValueError) as exc:
            raise LMStudioBadResponse(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-wsl/bin/python -m pytest tests/test_lmstudio.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/lmstudio.py tests/test_lmstudio.py
git commit -m "feat: add message-list chat and SSE streaming to LM Studio client"
```

---

### Task 4: `ia.py` — streaming con preview y memoria

**Files:**
- Modify: `bot/ia.py`
- Test: `tests/test_ia_command.py`

**Interfaces:**
- Consumes: `client.stream_chat(messages)`, `strip_reasoning` (de `bot.lmstudio`); `store.window`, `store.append` (de `bot.memory.ConversationStore`).
- Produces: `register(tree, client, store, operation_lock=None, clock=time.monotonic)`. Constantes `PREVIEW_INTERVAL = 1.0`, `PREVIEW_LIMIT = 1900`.

Comportamiento de publicación (enfoque A):
- `defer(thinking=True)` crea la respuesta diferida.
- Durante el stream: se acumula `raw`; `visible = strip_reasoning(raw)`. Si `visible` está vacío → preview `🤔 pensando…`; si no → `format_reply(mensaje, visible)` recortado a `PREVIEW_LIMIT`. Se edita con `interaction.edit_original_response(content=...)` como mucho una vez por `PREVIEW_INTERVAL` (throttle con `clock`).
- Al terminar con éxito: `answer = strip_reasoning(raw)`; si `finish_reason == "length"` → `LMStudioTruncated`; si `answer` vacío → `LMStudioBadResponse`. Luego:
  - `chunks = chunk_text(format_reply(mensaje, answer))`.
  - Si **un solo chunk y sin adjunto**: `interaction.edit_original_response(content=chunks[0])` (sustituye el preview en el sitio).
  - Si **varios chunks o adjunto**: `interaction.delete_original_response()` y después la **lógica actual de followups + `.md` sin cambios**.
  - Guardar en memoria: `await to_thread(store.append, channel_id, "user", mensaje)` y `"assistant", answer`.
- En timeout / error / truncado: `delete_original_response()` + followup ephemeral (como hoy); **no** se guarda nada.
- La ventana se lee con `await to_thread(store.window, channel_id, IA_HISTORY_TOKENS)`; si lanza excepción, se registra en log y se sigue con `[]`.

Añade `IA_HISTORY_TOKENS` leído de módulo: pásalo por `register` o como parámetro. Para mantenerlo simple, `register` recibe `history_tokens: int` (lo cablea `main.py` desde `config.ia_history_tokens`).

> Firma final: `register(tree, client, store, history_tokens, operation_lock=None, clock=time.monotonic)`.

- [ ] **Step 1: Write the failing tests**

Reescribe el `FakeModel` y amplía `FakeInteraction` en `tests/test_ia_command.py`:

```python
class FakeModel:
    def __init__(self, deltas=None, error=None, gate=None, finish=None):
        self.deltas = deltas if deltas is not None else ["respuesta"]
        self.error = error
        self.gate = gate
        self.finish = finish
        self.calls = 0
        self.messages = None

    async def stream_chat(self, messages):
        self.calls += 1
        self.messages = messages
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        from bot.lmstudio import StreamEvent
        for i, text in enumerate(self.deltas):
            finish = self.finish if i == len(self.deltas) - 1 else None
            yield StreamEvent(text=text, finish_reason=finish)


class FakeStore:
    def __init__(self, history=None):
        self.history = history or []
        self.appended = []
        self.reset_channels = []

    def window(self, channel_id, budget_tokens):
        return list(self.history)

    def append(self, channel_id, role, content):
        self.appended.append((channel_id, role, content))

    def reset(self, channel_id):
        self.reset_channels.append(channel_id)
```

Amplía `FakeInteraction` con `channel_id` y `edit_original_response`:

```python
    def __init__(self, user_id=1, channel_id=100):
        self.user = SimpleNamespace(id=user_id)
        self.channel_id = channel_id
        self.log = []
        self.response = SimpleNamespace(send_message=self._send_message, defer=self._defer)
        self.followup = SimpleNamespace(send=self._followup)

    async def edit_original_response(self, content=None, **kwargs):
        self.log.append(("edit", content))
```

`make_command` pasa a crear store y clock parado (para que no salten previews intermedios en los tests de logs exactos):

```python
def make_command(model, store=None, history_tokens=3000):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    store = store or FakeStore()
    ia.register(tree, model, store, history_tokens, clock=lambda: 0.0)
    return tree.get_command("ia").callback, store
```

Tests (adapta los existentes a la nueva tupla de `make_command` y a `edit` para el caso de un solo mensaje):

```python
async def test_single_chunk_answer_replaces_the_preview_in_place():
    command, store = make_command(FakeModel(deltas=["respuesta"]))
    interaction = FakeInteraction()
    await command(interaction, "hola")
    assert interaction.log[0] == ("defer",)
    assert interaction.log[-1] == ("edit", "> hola\n\nrespuesta")


async def test_history_window_is_prepended_to_the_prompt():
    history = [{"role": "user", "content": "antes"},
               {"role": "assistant", "content": "vale"}]
    model = FakeModel()
    command, store = make_command(model, store=FakeStore(history=history))
    await command(FakeInteraction(), "ahora")
    roles = [m["role"] for m in model.messages]
    assert roles[0] == "system"
    assert model.messages[1:3] == history
    assert model.messages[-1]["role"] == "user" and "ahora" in model.messages[-1]["content"]


async def test_successful_turn_is_stored():
    command, store = make_command(FakeModel(deltas=["resp"]))
    await command(FakeInteraction(channel_id=42), "preg")
    assert (42, "user", "preg") in store.appended
    assert (42, "assistant", "resp") in store.appended


async def test_failed_turn_is_not_stored():
    command, store = make_command(FakeModel(error=LMStudioUnavailable("x")))
    interaction = FakeInteraction()
    await command(interaction, "preg")
    assert store.appended == []
    assert interaction.log[-1][0] == "followup" and interaction.log[-1][2] is True


async def test_truncated_stream_is_reported_and_not_stored():
    command, store = make_command(FakeModel(deltas=["a medias"], finish="length"))
    interaction = FakeInteraction()
    await command(interaction, "preg")
    assert store.appended == []
    assert interaction.log[-2] == ("delete",)
    assert interaction.log[-1][2] is True  # ephemeral


async def test_reset_command_clears_the_channel():
    store = FakeStore()
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    ia.register(tree, FakeModel(), store, 3000, clock=lambda: 0.0)
    reset = tree.get_command("ia-reset").callback
    interaction = FakeInteraction(channel_id=77)
    await reset(interaction)
    assert store.reset_channels == [77]
    assert interaction.log[-1][0] == "send_message" and interaction.log[-1][2] is True


async def test_window_read_failure_degrades_to_no_history():
    class Boom(FakeStore):
        def window(self, channel_id, budget_tokens):
            raise RuntimeError("db caída")
    model = FakeModel()
    command, store = make_command(model, store=Boom())
    await command(FakeInteraction(), "preg")
    # responde igualmente; sin turnos de historial, solo system + user
    assert [m["role"] for m in model.messages] == ["system", "user"]
```

Actualiza los tests existentes que siguen valiendo pero cambian de forma:
- `test_answer_is_posted_quoting_the_question` → sustituido por `test_single_chunk_answer_replaces_the_preview_in_place` (bórralo o renómbralo).
- Cooldown/admisión/deadline/blank: cambia `make_command(model)` por `command, _ = make_command(model)` y, donde esperaban `("followup", "> ... ", False)` para **un solo** mensaje, pásalos a `("edit", "> ...")` en la última entrada del log.
- `test_long_answer...` y `test_very_long_answer...`: **no cambian** su aserción sobre `sent` (siguen por `followup.send`), pero el modelo ahora es streaming: pásale `FakeModel(deltas=[answer])`. Como son varios chunks/adjunto, la ruta es `delete` + followups, así que `sent` sigue capturando lo mismo.
- `test_generated_mentions_are_disabled`: ese caso es un solo chunk → ahora va por `edit_original_response`; parchea `interaction.edit_original_response` (en vez de `followup.send`) para capturar que el envío final no incluye menciones (o verifica que la ruta de edición no activa menciones; `edit_original_response` no las propaga). Ajusta el test para parchear `edit_original_response` y comprobar el contenido.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-wsl/bin/python -m pytest tests/test_ia_command.py -v`
Expected: FAIL (firma de `register`, falta `ia-reset`, falta `edit`).

- [ ] **Step 3: Implement**

Reescribe `register` en `bot/ia.py`. Importa `from bot.lmstudio import ..., strip_reasoning` y `import time`. Estructura:

```python
PREVIEW_INTERVAL = 1.0
PREVIEW_LIMIT = 1900


def register(tree, client, store, history_tokens,
             operation_lock=None, clock=time.monotonic):
    cooldown = Cooldown(COOLDOWN_SECONDS, clock)
    admission = Admission(MAX_PENDING)
    lock = operation_lock if operation_lock is not None else asyncio.Lock()
    no_mentions = discord.AllowedMentions.none()

    @tree.command(name="ia", description="Pregunta al modelo local del grupo")
    @app_commands.describe(mensaje="Lo que quieres preguntar")
    async def ia(interaction, mensaje: app_commands.Range[str, 1, QUESTION_LIMIT]):
        # ... validación en blanco + admission.try_enter como hoy ...
        try:
            await answer_question(interaction, mensaje)
        finally:
            admission.leave(interaction.user.id)

    @tree.command(name="ia-reset", description="Borra la memoria de /ia en este canal")
    @app_commands.guild_only()
    async def ia_reset(interaction):
        await asyncio.to_thread(store.reset, interaction.channel_id)
        await interaction.response.send_message(
            "Memoria del canal borrada. Empezamos de cero.", ephemeral=True
        )

    async def answer_question(interaction, mensaje):
        user_id = interaction.user.id
        remaining = cooldown.remaining(user_id)
        if remaining > 0:
            await interaction.response.send_message(
                f"Espera {math.ceil(remaining)} s antes de volver a preguntar.",
                ephemeral=True)
            return
        cooldown.touch(user_id)
        await interaction.response.defer(thinking=True)
        try:
            history = await _read_history(interaction.channel_id)
            messages = (
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + history
                + [{"role": "user", "content": mensaje + "\n\nResponde en español."}]
            )
            answer = await asyncio.wait_for(
                _stream(interaction, mensaje, messages),
                timeout=REQUEST_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            cooldown.reset(user_id)
            await interaction.delete_original_response()
            await interaction.followup.send(LMStudioTimeout.user_message, ephemeral=True)
            return
        except LMStudioError as exc:
            cooldown.reset(user_id)
            log.warning("Fallo de LM Studio: %s: %s", type(exc).__name__, exc)
            await interaction.delete_original_response()
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        await _publish(interaction, mensaje, answer)
        await _store_turn(interaction.channel_id, mensaje, answer)

    async def _read_history(channel_id):
        try:
            return await asyncio.to_thread(store.window, channel_id, history_tokens)
        except Exception as exc:  # degradar: la respuesta no debe caerse por la BD
            log.warning("No se pudo leer el historial del canal %s: %s", channel_id, exc)
            return []

    async def _store_turn(channel_id, mensaje, answer):
        try:
            await asyncio.to_thread(store.append, channel_id, "user", mensaje)
            await asyncio.to_thread(store.append, channel_id, "assistant", answer)
        except Exception as exc:
            log.warning("No se pudo guardar el turno del canal %s: %s", channel_id, exc)

    async def _stream(interaction, mensaje, messages):
        raw = ""
        finish_reason = None
        last_edit = None
        async with lock:
            async for event in client.stream_chat(messages):
                raw += event.text
                finish_reason = event.finish_reason or finish_reason
                now = clock()
                if last_edit is None or now - last_edit >= PREVIEW_INTERVAL:
                    await _edit_preview(interaction, mensaje, raw)
                    last_edit = now
        if finish_reason == "length":
            raise LMStudioTruncated("límite de generación alcanzado")
        answer = strip_reasoning(raw)
        if not answer:
            raise LMStudioBadResponse("contenido vacío")
        return answer

    async def _edit_preview(interaction, mensaje, raw):
        visible = strip_reasoning(raw)
        content = "🤔 pensando…" if not visible else format_reply(mensaje, visible)
        await interaction.edit_original_response(content=content[:PREVIEW_LIMIT])

    async def _publish(interaction, mensaje, answer):
        chunks = chunk_text(format_reply(mensaje, answer))
        if len(chunks) == 1:
            await interaction.edit_original_response(content=chunks[0])
            return
        await interaction.delete_original_response()
        document = f"# Pregunta\n\n{mensaje}\n\n# Respuesta\n\n{answer}"
        with closing(discord.File(
                io.BytesIO(document.encode("utf-8")), filename="respuesta-ia.md")) as attachment:
            if len(chunks) > MAX_INLINE_CHUNKS:
                await interaction.followup.send(
                    format_reply(mensaje, "La respuesta completa está en el archivo adjunto."),
                    file=attachment, allowed_mentions=no_mentions)
                return
            await interaction.followup.send(
                chunks[0], file=attachment, allowed_mentions=no_mentions)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, allowed_mentions=no_mentions)
```

Mantén la validación de mensaje en blanco y `admission.try_enter` exactamente como en el código actual (cópialos dentro del nuevo `ia`). Conserva `Cooldown`, `Admission`, `chunk_text`, `format_reply`, constantes y `SYSTEM_PROMPT` sin tocar.

- [ ] **Step 4: Run the full suite**

Run: `.venv-wsl/bin/python -m pytest tests/test_ia_command.py tests/test_chunking.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/ia.py tests/test_ia_command.py
git commit -m "feat: stream /ia replies with per-channel memory and add /ia-reset"
```

---

### Task 5: Cableado en `main.py` y documentación

**Files:**
- Modify: `bot/main.py`
- Test: `tests/test_main.py`
- Modify: `.gitignore`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: `ConversationStore`, `ia.register(tree, client, store, history_tokens, operation_lock)`.

- [ ] **Step 1: Write/adjust the failing test**

En `tests/test_main.py`, comprueba que `build_bot` registra `/ia` y `/ia-reset` y no revienta. Si ya hay un test que lista comandos, añade `"ia-reset"` al conjunto esperado. Si no, añade:

```python
def test_build_bot_registers_reset_command(valid_config, tmp_path):
    valid_config = replace(valid_config, ia_db_path=str(tmp_path / "ia.db"))
    bot = build_bot(valid_config)
    names = {c.name for c in bot.tree.get_commands()}
    assert {"ia", "ia-reset", "panel", "help", "initai"} <= names
```

(Usa el fixture/constructor de `Config` que ya tengan los tests de `main`; `from dataclasses import replace` para fijar `ia_db_path` a un fichero temporal.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-wsl/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL (`ia-reset` no registrado / `ia.register` firma vieja).

- [ ] **Step 3: Implement**

En `bot/main.py`, dentro de `build_bot`:

```python
from bot.memory import ConversationStore
```

```python
    store = ConversationStore(config.ia_db_path)
    panel.register(bot.tree, config)
    bot.initializer = aiinit.ModelInitializer(client, config.lmstudio_base_url, config.lmstudio_model)
    ia.register(bot.tree, client, store, config.ia_history_tokens, bot.initializer.lock)
    aiinit.register(bot.tree, bot.initializer)
    help_command.register(bot.tree)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv-wsl/bin/python -m pytest -q`
Expected: PASS (toda la suite).

- [ ] **Step 5: Docs y `.gitignore`**

- `.gitignore`: añade una línea `ia_history.db` (y `*.db` si se prefiere). Verifica que el fichero no está ya trackeado (`git status`).
- `.env.example`: bajo `# Opcionales`, añade:

```
IA_HISTORY_TOKENS=3000
IA_DB_PATH=ia_history.db
```

- `README.md`: documenta `/ia-reset`, la memoria por canal (persistente en SQLite, recortada por `IA_HISTORY_TOKENS`) y el streaming. Recuerda que bajo WSL la BD se crea en el directorio de trabajo salvo que se fije `IA_DB_PATH`.

- [ ] **Step 6: Commit**

```bash
git add bot/main.py tests/test_main.py .gitignore .env.example README.md
git commit -m "feat: wire conversation store and document /ia memory and streaming"
```

---

## Self-Review

- **Spec coverage:** memoria por canal (Task 2), persistencia SQLite (Task 2), recorte por tokens (Task 2), `/ia-reset` (Task 4), streaming enfoque A con preview+formateo final (Task 4), `chat(messages)`+`stream_chat` (Task 3), config `IA_HISTORY_TOKENS`/`IA_DB_PATH` (Task 1), cableado + docs + `.gitignore` (Task 5). Todas las secciones de la spec tienen tarea.
- **Placeholder scan:** sin TBD/TODO; cada paso lleva código o comando concreto. La reescritura de `ia.py` y la migración de `test_lmstudio.py` se dan con el código y la transformación exacta.
- **Type consistency:** `chat(messages)`, `stream_chat(messages)->AsyncIterator[StreamEvent]`, `StreamEvent(text, reasoning, finish_reason)`, `strip_reasoning`, `ConversationStore.window/append/reset`, `register(tree, client, store, history_tokens, operation_lock=None, clock=...)` coherentes entre tareas y tests.
- **Review Focus:** los cinco casos tienen test en su tarea (turno sobredimensionado y orden estable → Task 2; fallo de BD, truncado y almacenamiento → Task 4; SSE robusto → Task 3).
