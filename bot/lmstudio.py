import asyncio
import json
import re
from dataclasses import dataclass
from typing import AsyncIterator

import aiohttp

from bot.config import DEFAULT_MAX_TOKENS

_FLAGS = re.DOTALL | re.IGNORECASE
_THINK_PAIR = re.compile(r"<think>.*?</think>", _FLAGS)
# Cierre sin apertura: la plantilla del modelo puso <think> en el prompt
_THINK_ORPHAN_CLOSE = re.compile(r"^.*</think>", _FLAGS)
# Apertura sin cierre: la generación se cortó a medio razonar
_THINK_UNCLOSED = re.compile(r"<think>.*$", _FLAGS)


def strip_reasoning(content: str) -> str:
    for pattern in (_THINK_PAIR, _THINK_ORPHAN_CLOSE, _THINK_UNCLOSED):
        content = pattern.sub("", content)
    return content.strip()


@dataclass
class StreamEvent:
    text: str = ""
    reasoning: str = ""
    finish_reason: str | None = None


class LMStudioError(Exception):
    user_message = "No he podido consultar el modelo."


class LMStudioUnavailable(LMStudioError):
    user_message = "El modelo no está disponible ahora mismo."


class LMStudioTimeout(LMStudioError):
    user_message = "El modelo ha tardado demasiado en responder."


class LMStudioBadResponse(LMStudioError):
    user_message = "El modelo ha devuelto una respuesta no válida."


class LMStudioTruncated(LMStudioError):
    user_message = (
        "El modelo agotó el límite de tokens antes de completar la respuesta. "
        "Acota la pregunta o aumenta LMSTUDIO_MAX_TOKENS y el contexto en LM Studio."
    )


class LMStudioClient:
    def __init__(
        self, base_url: str, model: str = "", timeout: float = 120.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_tokens = max_tokens

    def set_model(self, identifier: str) -> None:
        self._model = identifier

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
            # No publicar comandos incompletos como si fueran una respuesta terminada.
            raise LMStudioTruncated("límite de generación alcanzado")
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
