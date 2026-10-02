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
