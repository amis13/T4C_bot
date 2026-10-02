import asyncio
import logging
import math
import time
from typing import Callable

import discord
from discord import app_commands

from bot.lmstudio import LMStudioClient, LMStudioError

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 10
# Una pregunta en curso más las que esperan; acota la espera muy por debajo de los
# 15 minutos que dura el token de la interacción
MAX_PENDING = 4
QUESTION_LIMIT = 1000
SYSTEM_PROMPT = (
    "Eres el asistente de un grupo que prepara las certificaciones eJPT y eCPPT "
    "para el evento Talent4Cyber. Ayudas con pentesting, redes, sistemas y "
    "ciberseguridad en entornos de laboratorio y con autorización. "
    "Responde siempre en español, de forma concisa y práctica, y usa bloques de "
    "código para los comandos."
)

MESSAGE_LIMIT = 2000
QUOTE_LIMIT = 200
FENCE = "```"
# Hueco para cerrar un bloque de código al final de un trozo y reabrirlo en el siguiente
_FENCE_ROOM = 2 * (len(FENCE) + 1)


def _split(text: str, limit: int) -> list[str]:
    pieces = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        piece = rest[:cut].rstrip()
        if piece:
            pieces.append(piece)
        # Se descarta solo el separador del corte: la sangría de la línea siguiente se conserva
        rest = rest[cut + 1 :] if rest[cut] == " " else rest[cut:].lstrip("\n")
    if rest.strip():
        pieces.append(rest.rstrip())
    return pieces


def chunk_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks = []
    in_code = False
    for piece in _split(text, limit - _FENCE_ROOM):
        if in_code:
            if piece == FENCE:
                in_code = False
                continue
            piece = FENCE + "\n" + piece
        in_code = piece.count(FENCE) % 2 == 1
        if in_code:
            piece += "\n" + FENCE
        chunks.append(piece)
    return chunks


def format_reply(question: str, answer: str) -> str:
    quote = " ".join(question.split())
    if len(quote) > QUOTE_LIMIT:
        quote = quote[: QUOTE_LIMIT - 1] + "…"
    return f"> {quote}\n\n{answer}"


class Cooldown:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def remaining(self, user_id: int) -> float:
        last = self._last.get(user_id)
        if last is None:
            return 0
        return max(0, self._seconds - (self._clock() - last))

    def touch(self, user_id: int) -> None:
        self._last[user_id] = self._clock()

    def reset(self, user_id: int) -> None:
        self._last.pop(user_id, None)


class Admission:
    """Limita las preguntas pendientes: una por usuario y `max_pending` en total."""

    def __init__(self, max_pending: int):
        self._max_pending = max_pending
        self._users: set[int] = set()

    def try_enter(self, user_id: int) -> str | None:
        if user_id in self._users:
            return "Ya tienes una pregunta en curso. Espera a que termine."
        if len(self._users) >= self._max_pending:
            return "El modelo está ocupado ahora mismo. Inténtalo en un momento."
        self._users.add(user_id)
        return None

    def leave(self, user_id: int) -> None:
        self._users.discard(user_id)


def register(tree: app_commands.CommandTree, client: LMStudioClient) -> None:
    cooldown = Cooldown(COOLDOWN_SECONDS)
    admission = Admission(MAX_PENDING)
    lock = asyncio.Lock()
    no_mentions = discord.AllowedMentions.none()

    @tree.command(name="ia", description="Pregunta al modelo local del grupo")
    @app_commands.describe(mensaje="Lo que quieres preguntar")
    async def ia(
        interaction: discord.Interaction,
        mensaje: app_commands.Range[str, 1, QUESTION_LIMIT],
    ):
        user_id = interaction.user.id
        refusal = admission.try_enter(user_id)
        if refusal:
            await interaction.response.send_message(refusal, ephemeral=True)
            return
        try:
            await answer_question(interaction, mensaje)
        finally:
            admission.leave(user_id)

    async def answer_question(interaction: discord.Interaction, mensaje: str) -> None:
        user_id = interaction.user.id
        remaining = cooldown.remaining(user_id)
        if remaining > 0:
            await interaction.response.send_message(
                f"Espera {math.ceil(remaining)} s antes de volver a preguntar.",
                ephemeral=True,
            )
            return
        # El cooldown cuenta desde la invocación para que no se encolen varias preguntas
        cooldown.touch(user_id)
        await interaction.response.defer(thinking=True)
        try:
            async with lock:
                answer = await client.chat(SYSTEM_PROMPT, mensaje)
        except LMStudioError as exc:
            cooldown.reset(user_id)
            log.warning("Fallo de LM Studio: %s: %s", type(exc).__name__, exc)
            # Se borra el "pensando…" público para que el aviso solo lo vea quien preguntó
            await interaction.delete_original_response()
            await interaction.followup.send(exc.user_message, ephemeral=True)
            return
        for chunk in chunk_text(format_reply(mensaje, answer)):
            await interaction.followup.send(chunk, allowed_mentions=no_mentions)
