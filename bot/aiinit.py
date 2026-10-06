"""Preset Qwythos por el protocolo de carga de LM Studio 0.4.25.

Las claves KV y los mensajes WebSocket corresponden al protocolo del SDK:
https://github.com/lmstudio-ai/lmstudio-js/tree/main/packages/lms-kv-config
El SDK Python 1.5 todavía no representa todos estos ajustes de carga.
"""

import asyncio
import logging
import uuid

import aiohttp
import discord
from discord import app_commands

from bot.lmstudio import LMStudioClient, LMStudioError

log = logging.getLogger(__name__)
INIT_TIMEOUT = 600
LOAD_SETTINGS = {
    "llm.load.contextLength": 16384,
    "llm.load.numParallelSessions": 1,
    "llm.load.llama.acceleration.offloadRatio": 29 / 33,
    "llm.load.llama.speculativeDecoding.draftMtp": True,
}


class InitializationError(LMStudioError):
    user_message = (
        "No he podido configurar LM Studio. Comprueba el servidor y el modelo; "
        "si la recarga falló, puede ser necesario cargarlo manualmente."
    )


class ModelInitializer:
    def __init__(self, client: LMStudioClient, base_url: str, model: str):
        self.client = client
        self.root = base_url.rstrip("/").removesuffix("/v1")
        self.model = model
        self.lock = asyncio.Lock()
        self.busy = False

    async def _json(self, session, method, path, **kwargs):
        async with session.request(method, self.root + path, **kwargs) as response:
            if response.status != 200:
                raise InitializationError(f"{path}: HTTP {response.status}")
            return await response.json()

    async def _receive(self, ws):
        message = await ws.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise InitializationError("LM Studio cerró la conexión de configuración")
        data = message.json()
        if not isinstance(data, dict):
            raise InitializationError("mensaje de configuración no válido")
        if data.get("type") in ("rpcError", "channelError"):
            raise InitializationError(f"error del protocolo: {data.get('type')}")
        return data

    async def _config(self, ws, identifier):
        await ws.send_json({
            "type": "rpcCall", "endpoint": "getLoadConfig", "callId": 1,
            "parameter": {"specifier": {
                "type": "query", "query": {"identifier": identifier},
            }},
        })
        while True:
            data = await self._receive(ws)
            if data.get("type") == "rpcResult" and data.get("callId") == 1:
                return {item["key"]: item["value"] for item in data["result"]["fields"]}

    async def _apply(self):
        if not self.model:
            raise InitializationError("Configura LMSTUDIO_MODEL antes de usar /initai")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=INIT_TIMEOUT)) as session:
            catalog = await self._json(session, "GET", "/api/v1/models")
            matches = [
                model for model in catalog["models"]
                if model.get("type") == "llm" and (
                    model.get("key") == self.model or any(
                        instance["id"] == self.model for instance in model["loaded_instances"]
                    )
                )
            ]
            if len(matches) != 1:
                raise InitializationError("LMSTUDIO_MODEL no identifica un único modelo local")
            model = matches[0]
            instances = model["loaded_instances"]
            if len(instances) > 1:
                instances = [instance for instance in instances if instance["id"] == self.model]
                if len(instances) != 1:
                    raise InitializationError("El modelo tiene varias instancias; configura su ID exacto")
            ws_url = self.root.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/llm"
            async with session.ws_connect(ws_url) as ws:
                await ws.send_json({
                    "authVersion": 1, "clientIdentifier": "talent4cyber-aiinit",
                    "clientPasskey": str(uuid.uuid4()),
                })
                if not (await self._receive(ws)).get("success"):
                    raise InitializationError("LM Studio rechazó la conexión de configuración")
                previous = await self._config(ws, instances[0]["id"]) if instances else {}
                if instances and all(previous.get(key) == value for key, value in LOAD_SETTINGS.items()):
                    self.client.set_model(instances[0]["id"])
                    return "La configuración ya era correcta; no ha sido necesario recargar."
                # Conserva la plantilla y demás preferencias de la instancia existente.
                settings = {**previous, **LOAD_SETTINGS}
                if instances:
                    await self._json(session, "POST", "/api/v1/models/unload", json={
                        "instance_id": instances[0]["id"],
                    })
                await ws.send_json({
                    "type": "channelCreate", "endpoint": "loadModel", "channelId": 1,
                    "creationParameter": {
                        "modelKey": model["key"], "identifier": self.model,
                        "loadConfigStack": {"layers": [{
                            "layerName": "apiOverride", "config": {"fields": [
                                {"key": key, "value": value} for key, value in settings.items()
                            ]},
                        }]},
                    },
                })
                try:
                    while True:
                        data = await self._receive(ws)
                        if data.get("type") == "channelClose":
                            raise InitializationError("El canal de carga terminó sin confirmar el modelo")
                        event = data.get("message", {})
                        if event.get("type") in ("success", "loadSuccess", "alreadyLoaded"):
                            identifier = event["info"]["identifier"]
                            break
                except (asyncio.CancelledError, Exception):
                    if not ws.closed:
                        await ws.send_json({"type": "channelSend", "channelId": 1,
                                            "message": {"type": "cancel"}})
                    raise
                actual = await self._config(ws, identifier)
                if any(actual.get(key) != value for key, value in LOAD_SETTINGS.items()):
                    raise InitializationError("El servidor no aplicó todos los ajustes solicitados")
                self.client.set_model(identifier)
                return "Modelo cargado y configuración comprobada."

    async def initialize(self):
        if self.busy:
            raise InitializationError("Ya hay una inicialización en curso")
        self.busy = True
        try:
            async def apply_exclusively():
                async with self.lock:
                    return await self._apply()

            return await asyncio.wait_for(apply_exclusively(), INIT_TIMEOUT)
        except InitializationError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as exc:
            raise InitializationError(type(exc).__name__) from exc
        finally:
            self.busy = False


def register(tree: app_commands.CommandTree, initializer: ModelInitializer):
    @tree.command(name="initai", description="Carga y configura Qwythos para la competición")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def initai(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            status = await initializer.initialize()
        except InitializationError as exc:
            log.warning("Fallo en /initai: %s", exc)
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        await interaction.followup.send(
            f"{status}\nContexto: 16384 · Concurrencia: 1 · GPU: 29/33 capas · MTP: activo.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )
