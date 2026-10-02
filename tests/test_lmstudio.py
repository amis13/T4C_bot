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
