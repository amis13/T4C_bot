import time
from typing import Callable

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
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
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
