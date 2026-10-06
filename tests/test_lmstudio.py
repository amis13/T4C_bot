import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, unused_port

from bot.lmstudio import (
    LMStudioBadResponse,
    LMStudioClient,
    LMStudioTimeout,
    LMStudioTruncated,
    LMStudioUnavailable,
    StreamEvent,
    strip_reasoning,
)


def msgs(system, user):
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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
    assert await client.chat(msgs("sistema", "pregunta")) == "hola"
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
    await client.chat(msgs("s", "u"))
    assert received["model"] == "qwen"


async def test_strips_think_blocks(serve):
    async def handler(request):
        return web.json_response(ok_body("<think>razono\nmucho</think>\n\nrespuesta"))

    client = LMStudioClient(await serve(handler))
    assert await client.chat(msgs("s", "u")) == "respuesta"


async def test_http_error_is_bad_response(serve):
    async def handler(request):
        return web.Response(status=500, text="boom")

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat(msgs("s", "u"))


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
        await client.chat(msgs("s", "u"))


async def test_non_json_body_is_bad_response(serve):
    async def handler(request):
        return web.Response(text="<html>no soy json</html>")

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat(msgs("s", "u"))


async def test_slow_server_is_timeout(serve):
    async def handler(request):
        await asyncio.sleep(2)
        return web.json_response(ok_body("tarde"))

    client = LMStudioClient(await serve(handler), timeout=0.2)
    with pytest.raises(LMStudioTimeout):
        await client.chat(msgs("s", "u"))


async def test_closed_port_is_unavailable():
    client = LMStudioClient(f"http://127.0.0.1:{unused_port()}/v1", timeout=2)
    with pytest.raises(LMStudioUnavailable):
        await client.chat(msgs("s", "u"))


@pytest.mark.parametrize(
    "content",
    [
        "razono sin etiqueta de apertura</think>\n\nrespuesta",
        "<THINK>razono</THINK>respuesta",
        "<think>uno</think>respuesta<think>me cortan a medias",
    ],
)
async def test_strips_malformed_think_blocks(serve, content):
    async def handler(request):
        return web.json_response(ok_body(content))

    client = LMStudioClient(await serve(handler))
    assert await client.chat(msgs("s", "u")) == "respuesta"


async def test_unclosed_think_without_answer_is_bad_response(serve):
    async def handler(request):
        return web.json_response(ok_body("<think>razono y me cortan"))

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioBadResponse):
        await client.chat(msgs("s", "u"))


async def test_generation_settings_and_separate_reasoning(serve):
    received = {}

    async def handler(request):
        received.update(await request.json())
        body = ok_body("respuesta final")
        body["choices"][0]["message"]["reasoning_content"] = "razonamiento privado"
        return web.json_response(body)

    client = LMStudioClient(await serve(handler), max_tokens=16384)
    assert await client.chat(msgs("s", "u")) == "respuesta final"
    assert received["temperature"] == 0.6
    assert received["top_p"] == 0.95
    assert received["top_k"] == 20
    assert received["max_tokens"] == 16384
    assert received["stream"] is False


@pytest.mark.parametrize("content", [None, "<think>razonando", "```bash\nnmap -"])
async def test_token_limit_never_publishes_incomplete_answers(serve, content):
    async def handler(request):
        body = ok_body(content)
        body["choices"][0]["finish_reason"] = "length"
        return web.json_response(body)

    client = LMStudioClient(await serve(handler))
    with pytest.raises(LMStudioTruncated):
        await client.chat(msgs("s", "u"))


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


def test_strip_reasoning_is_public():
    assert strip_reasoning("<think>a</think>b") == "b"
    assert StreamEvent().text == ""
