import asyncio
from types import SimpleNamespace

import discord
from discord import app_commands

from bot import ia
from bot.lmstudio import LMStudioUnavailable


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


class FakeInteraction:
    def __init__(self, user_id=1, channel_id=100):
        self.user = SimpleNamespace(id=user_id)
        self.channel_id = channel_id
        self.log = []
        self.response = SimpleNamespace(send_message=self._send_message, defer=self._defer)
        self.followup = SimpleNamespace(send=self._followup)

    async def edit_original_response(self, content=None, **kwargs):
        self.log.append(("edit", content))

    async def _send_message(self, content=None, **kwargs):
        self.log.append(("send_message", content, kwargs.get("ephemeral", False)))

    async def _defer(self, **kwargs):
        self.log.append(("defer",))

    async def _followup(self, content=None, **kwargs):
        self.log.append(("followup", content, kwargs.get("ephemeral", False)))

    async def delete_original_response(self):
        self.log.append(("delete",))


def make_command(model, store=None, history_tokens=3000):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    store = store or FakeStore()
    ia.register(tree, model, store, history_tokens, clock=lambda: 0.0)
    return tree.get_command("ia").callback, store


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
    assert [m["role"] for m in model.messages] == ["system", "user"]


async def test_second_question_within_cooldown_is_refused_privately():
    model = FakeModel()
    command, _ = make_command(model)
    await command(FakeInteraction(), "hola")
    second = FakeInteraction()
    await command(second, "otra")
    assert len(second.log) == 1
    kind, content, ephemeral = second.log[0]
    assert kind == "send_message" and ephemeral and "Espera" in content
    assert model.calls == 1


async def test_model_failure_is_reported_privately_and_frees_the_cooldown():
    error = LMStudioUnavailable("apagado")
    command, _ = make_command(FakeModel(error=error))
    interaction = FakeInteraction()
    await command(interaction, "hola")
    assert interaction.log == [
        ("defer",),
        ("delete",),
        ("followup", error.user_message, True),
    ]
    retry = FakeInteraction()
    await command(retry, "hola")
    assert retry.log[0] == ("defer",)


async def test_user_with_a_question_in_flight_cannot_queue_another():
    gate = asyncio.Event()
    model = FakeModel(gate=gate)
    command, _ = make_command(model)
    first = asyncio.create_task(command(FakeInteraction(), "una"))
    await asyncio.sleep(0.05)
    second = FakeInteraction()
    await command(second, "otra")
    assert len(second.log) == 1
    kind, content, ephemeral = second.log[0]
    assert kind == "send_message" and ephemeral and "en curso" in content
    gate.set()
    await first
    assert model.calls == 1


async def test_queue_is_bounded_across_users():
    gate = asyncio.Event()
    model = FakeModel(gate=gate)
    command, _ = make_command(model)
    tasks = [
        asyncio.create_task(command(FakeInteraction(user_id=user), "pregunta"))
        for user in range(ia.MAX_PENDING)
    ]
    await asyncio.sleep(0.05)
    extra = FakeInteraction(user_id=999)
    await command(extra, "pregunta")
    assert len(extra.log) == 1
    kind, content, ephemeral = extra.log[0]
    assert kind == "send_message" and ephemeral and "ocupado" in content
    gate.set()
    await asyncio.gather(*tasks)
    assert model.calls == ia.MAX_PENDING
    after = FakeInteraction(user_id=999)
    await command(after, "pregunta")
    assert after.log[0] == ("defer",)


async def test_blank_question_does_not_call_model_or_consume_cooldown():
    model = FakeModel()
    command, _ = make_command(model)
    blank = FakeInteraction()
    await command(blank, " \n ")
    assert blank.log[0][2] is True
    assert model.calls == 0
    await command(FakeInteraction(), "pregunta")
    assert model.calls == 1


async def test_deadline_includes_queue_and_releases_admission(monkeypatch):
    monkeypatch.setattr(ia, "REQUEST_DEADLINE_SECONDS", 0.1)
    gate = asyncio.Event()
    model = FakeModel(gate=gate)
    command, _ = make_command(model)
    first, queued = FakeInteraction(1), FakeInteraction(2)
    await asyncio.gather(command(first, "una"), command(queued, "dos"))
    for interaction in (first, queued):
        assert interaction.log[-2] == ("delete",)
        assert interaction.log[-1][2] is True
        assert "tardado" in interaction.log[-1][1]
    gate.set()
    for user in (1, 2):
        retry = FakeInteraction(user)
        await command(retry, "otra")
        assert retry.log[-1] == ("edit", "> otra\n\nrespuesta")


async def test_generated_mentions_are_disabled():
    interaction = FakeInteraction()
    command, _ = make_command(FakeModel(deltas=["@everyone <@123>"]))
    await command(interaction, "hola")
    # La ruta de edición no propaga menciones: Discord no notifica al editar.
    assert interaction.log[-1] == ("edit", "> hola\n\n@everyone <@123>")
    assert not any(entry[0] == "followup" for entry in interaction.log)


async def test_long_answer_is_sent_in_order_with_exact_attachment():
    answer = "```python\n" + '    print("🔐")  \n' * 250 + "```"
    interaction = FakeInteraction()
    sent = []
    documents = []

    async def capture(content=None, **kwargs):
        sent.append(content)
        assert kwargs["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()
        if "file" in kwargs:
            file = kwargs["file"]
            assert file.filename == "respuesta-ia.md"
            documents.append(file.fp.read().decode("utf-8"))

    interaction.followup.send = capture
    command, _ = make_command(FakeModel(deltas=[answer]))
    await command(interaction, "pregunta")
    assert sent == ia.chunk_text(ia.format_reply("pregunta", answer))
    assert len(sent) > 1
    assert all(len(message.encode("utf-16-le")) // 2 <= 2000 for message in sent)
    assert documents == [f"# Pregunta\n\npregunta\n\n# Respuesta\n\n{answer}"]


async def test_very_long_answer_is_complete_in_one_attachment():
    answer = "x" * 20000
    interaction = FakeInteraction()
    sent = []

    async def capture(content=None, **kwargs):
        sent.append(content)
        assert kwargs["file"].fp.read().decode("utf-8").endswith(answer)
        assert kwargs["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()

    interaction.followup.send = capture
    command, _ = make_command(FakeModel(deltas=[answer]))
    await command(interaction, "pregunta")
    assert len(sent) == 1
    assert "archivo adjunto" in sent[0]
