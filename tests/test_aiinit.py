import asyncio
from types import SimpleNamespace

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.aiinit import LOAD_SETTINGS, InitializationError, ModelInitializer, register
from bot.lmstudio import LMStudioClient


@pytest.fixture
async def studio():
    state = {"loaded": True, "settings": dict(LOAD_SETTINGS), "loads": 0, "unloads": [],
             "reject_load": False, "ignore_settings": False, "missing": False}

    async def catalog(request):
        instances = [{"id": "qwythos", "config": {}}] if state["loaded"] else []
        models = [] if state["missing"] else [{
            "type": "llm", "key": "qwythos", "loaded_instances": instances,
        }]
        return web.json_response({"models": models})

    async def unload(request):
        payload = await request.json()
        state["unloads"].append(payload["instance_id"])
        state["loaded"] = False
        return web.json_response(payload)

    async def websocket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        auth = await ws.receive_json()
        assert auth["authVersion"] == 1
        await ws.send_json({"success": True})
        async for raw in ws:
            message = raw.json()
            if message["type"] == "rpcCall":
                await ws.send_json({"type": "rpcResult", "callId": message["callId"],
                                    "result": {"fields": [
                                        {"key": key, "value": value}
                                        for key, value in state["settings"].items()
                                    ]}})
            elif message["type"] == "channelCreate":
                state["loads"] += 1
                if state["reject_load"]:
                    await ws.send_json({"type": "channelError", "channelId": 1, "error": {}})
                    continue
                params = message["creationParameter"]
                assert params["modelKey"] == "qwythos"
                if not state["ignore_settings"]:
                    fields = params["loadConfigStack"]["layers"][0]["config"]["fields"]
                    state["settings"] = {field["key"]: field["value"] for field in fields}
                state["loaded"] = True
                await ws.send_json({"type": "channelSend", "channelId": 1,
                                    "message": {"type": "success", "info": {"identifier": "qwythos"}}})
                await ws.send_json({"type": "channelClose", "channelId": 1})
        return ws

    app = web.Application()
    app.router.add_get("/api/v1/models", catalog)
    app.router.add_post("/api/v1/models/unload", unload)
    app.router.add_get("/llm", websocket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1"))
        client = LMStudioClient(url, "qwythos")
        yield ModelInitializer(client, url, "qwythos"), state


async def test_correct_loaded_model_is_not_reloaded(studio):
    initializer, state = studio
    assert "no ha sido necesario recargar" in await initializer.initialize()
    assert state["loads"] == 0
    assert not state["unloads"]


async def test_reload_corrects_settings_and_preserves_chat_template(studio):
    initializer, state = studio
    state["settings"] = {"llm.load.contextLength": 8192, "llm.load.promptTemplate": {"custom": "keep"}}
    assert "comprobada" in await initializer.initialize()
    assert state["loads"] == 1
    assert state["unloads"] == ["qwythos"]
    assert all(state["settings"][key] == value for key, value in LOAD_SETTINGS.items())
    assert state["settings"]["llm.load.promptTemplate"] == {"custom": "keep"}


async def test_unloaded_model_is_loaded_without_unloading_other_models(studio):
    initializer, state = studio
    state["loaded"] = False
    state["settings"] = {}
    await initializer.initialize()
    assert state["loads"] == 1
    assert not state["unloads"]


@pytest.mark.parametrize("failure", ["reject_load", "ignore_settings", "missing"])
async def test_errors_never_report_success_and_release_lock(studio, failure):
    initializer, state = studio
    state["settings"] = {"llm.load.contextLength": 8192}
    state[failure] = True
    with pytest.raises(InitializationError):
        await initializer.initialize()
    assert not initializer.lock.locked()
    assert not initializer.busy


async def test_init_waits_for_generation_and_rejects_duplicate_initialization(studio):
    initializer, state = studio
    await initializer.lock.acquire()
    task = asyncio.create_task(initializer.initialize())
    await asyncio.sleep(0)
    assert initializer.busy
    with pytest.raises(InitializationError):
        await initializer.initialize()
    assert not task.done()
    initializer.lock.release()
    await task


async def test_cancellation_releases_initialization_state(studio):
    initializer, _ = studio
    await initializer.lock.acquire()
    task = asyncio.create_task(initializer.initialize())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not initializer.busy
    initializer.lock.release()


async def test_command_enforces_manage_guild_permissions(studio):
    initializer, _ = studio
    tree = discord.app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    register(tree, initializer)
    command = tree.get_command("initai")
    assert command.guild_only
    assert command.default_permissions.manage_guild
    interaction = SimpleNamespace(permissions=discord.Permissions.none())
    with pytest.raises(discord.app_commands.MissingPermissions):
        await command.checks[0](interaction)
