import asyncio
from types import SimpleNamespace

import discord
from discord import app_commands

from bot import ia
from bot.lmstudio import LMStudioUnavailable


class FakeModel:
    def __init__(self, answer="respuesta", error=None, gate=None):
        self.answer = answer
        self.error = error
        self.gate = gate
        self.calls = 0

    async def chat(self, system, user):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.answer


class FakeInteraction:
    def __init__(self, user_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.log = []
        self.response = SimpleNamespace(send_message=self._send_message, defer=self._defer)
        self.followup = SimpleNamespace(send=self._followup)

    async def _send_message(self, content=None, **kwargs):
        self.log.append(("send_message", content, kwargs.get("ephemeral", False)))

    async def _defer(self, **kwargs):
        self.log.append(("defer",))

    async def _followup(self, content=None, **kwargs):
        self.log.append(("followup", content, kwargs.get("ephemeral", False)))

    async def delete_original_response(self):
        self.log.append(("delete",))


def make_command(model):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    ia.register(tree, model)
    return tree.get_command("ia").callback


async def test_answer_is_posted_quoting_the_question():
    command = make_command(FakeModel())
    interaction = FakeInteraction()
    await command(interaction, "hola")
    assert interaction.log == [("defer",), ("followup", "> hola\n\nrespuesta", False)]


async def test_second_question_within_cooldown_is_refused_privately():
    model = FakeModel()
    command = make_command(model)
    await command(FakeInteraction(), "hola")
    second = FakeInteraction()
    await command(second, "otra")
    assert len(second.log) == 1
    kind, content, ephemeral = second.log[0]
    assert kind == "send_message" and ephemeral and "Espera" in content
    assert model.calls == 1


async def test_model_failure_is_reported_privately_and_frees_the_cooldown():
    error = LMStudioUnavailable("apagado")
    command = make_command(FakeModel(error=error))
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
    command = make_command(model)
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
    command = make_command(model)
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
    command = make_command(model)
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
    command = make_command(model)
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
        assert retry.log[-1] == ("followup", "> otra\n\nrespuesta", False)


async def test_generated_mentions_are_disabled():
    interaction = FakeInteraction()
    mentions = []
    original = interaction._followup

    async def capture(content=None, **kwargs):
        mentions.append(kwargs["allowed_mentions"])
        await original(content, **kwargs)

    interaction.followup.send = capture
    await make_command(FakeModel(answer="@everyone <@123>"))(interaction, "hola")
    assert mentions[0].to_dict() == discord.AllowedMentions.none().to_dict()


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
    await make_command(FakeModel(answer=answer))(interaction, "pregunta")
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
    await make_command(FakeModel(answer=answer))(interaction, "pregunta")
    assert len(sent) == 1
    assert "archivo adjunto" in sent[0]
