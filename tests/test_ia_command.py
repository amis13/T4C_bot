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
