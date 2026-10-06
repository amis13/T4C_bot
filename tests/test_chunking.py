import pytest

from bot.ia import chunk_text, format_reply


def test_short_text_is_a_single_chunk():
    assert chunk_text("hola") == ["hola"]


def test_text_at_the_limit_is_not_split():
    text = "a" * 48
    assert chunk_text(text, limit=48) == [text]


def test_empty_or_blank_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n ") == []


def test_cuts_on_newline():
    text = "a" * 30 + "\n" + "b" * 30
    assert chunk_text(text, limit=48) == ["a" * 30, "b" * 30]


def test_cuts_on_space_when_there_is_no_newline():
    text = "a" * 30 + " " + "b" * 30
    assert chunk_text(text, limit=48) == ["a" * 30, "b" * 30]


def test_word_longer_than_limit_is_hard_split():
    text = "a" * 100
    chunks = chunk_text(text, limit=48)
    assert all(0 < len(chunk) <= 48 for chunk in chunks)
    assert "".join(chunks) == text


def test_code_block_stays_fenced_in_every_chunk():
    lines = [f"linea {i:02d}" for i in range(20)]
    text = "```\n" + "\n".join(lines) + "\n```"
    chunks = chunk_text(text, limit=48)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 48
        assert chunk.startswith("```")
        assert chunk.endswith("```")
        assert chunk.count("```") == 2
        assert chunk != "```\n```"
    body = "\n".join(chunk[4:-4] for chunk in chunks)
    assert body == "\n".join(lines)


def test_text_after_a_code_block_is_not_fenced():
    text = "```\n" + "x" * 30 + "\n```\n" + "y" * 30
    chunks = chunk_text(text, limit=48)
    assert chunks[-1] == "y" * 30


def test_format_reply_quotes_the_question():
    assert format_reply("¿qué es nmap?", "Un escáner.") == "> ¿qué es nmap?\n\nUn escáner."


def test_format_reply_flattens_and_truncates_long_questions():
    reply = format_reply("uno\ndos " + "x" * 300, "ok")
    quote = reply.split("\n\n")[0]
    assert "\n" not in quote
    assert quote.startswith("> uno dos ")
    assert len(quote) == 202
    assert quote.endswith("…")


def test_indentation_survives_a_chunk_boundary():
    lines = [f"    linea {i:02d}" for i in range(12)]
    text = "```\n" + "\n".join(lines) + "\n```"
    chunks = chunk_text(text, limit=48)
    assert len(chunks) > 1
    assert all(len(chunk) <= 48 for chunk in chunks)
    body = "\n".join(chunk[4:-4] for chunk in chunks)
    assert body == "\n".join(lines)


@pytest.mark.parametrize("language", ["python", "powershell", "bash", "sql"])
def test_code_language_and_whitespace_survive_chunk_boundaries(language):
    lines = [f"    linea {i:02d}  " for i in range(12)]
    text = f"```{language}\n" + "\n".join(lines) + "\n```"
    chunks = chunk_text(text, limit=64)
    header = f"```{language}\n"
    assert all(chunk.startswith(header) and chunk.endswith("\n```") for chunk in chunks)
    assert all(len(chunk) <= 64 for chunk in chunks)
    assert "\n".join(chunk[len(header):-4] for chunk in chunks) == "\n".join(lines)


def test_long_code_line_is_not_split_at_spaces_or_lost():
    body = 'token = "' + "a b " * 1000 + '"'
    chunks = chunk_text("```python\n" + body + "\n```")
    assert "".join(chunk[len("```python\n"):-4] for chunk in chunks) == body
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_emojis_fit_even_when_counted_as_utf16():
    text = "🔐" * 2000
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 2000 for chunk in chunks)


def test_backticks_inside_a_code_line_do_not_close_the_block():
    body = '\n'.join(['    print("```")'] * 300)
    chunks = chunk_text("```python\n" + body + "\n```")
    assert all(chunk.startswith("```python\n") and chunk.endswith("\n```") for chunk in chunks)
    assert "\n".join(chunk[len("```python\n"):-4] for chunk in chunks) == body


def test_multiple_blocks_keep_their_own_language_and_plain_text():
    chunks = chunk_text(
        "Introducción\n```bash\n" + "echo hola\n" * 300
        + "```\nExplicación\n```sql\n" + "SELECT 1;\n" * 300 + "```\nFinal"
    )
    assert chunks[0] == "Introducción"
    assert "Explicación" in chunks
    assert chunks[-1] == "Final"
    assert any(chunk.startswith("```bash\n") for chunk in chunks)
    assert any(chunk.startswith("```sql\n") for chunk in chunks)
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_unclosed_long_code_block_is_closed_for_display():
    chunks = chunk_text("```bash\n" + "echo hola\n" * 300)
    assert all(chunk.startswith("```bash\n") and chunk.endswith("\n```") for chunk in chunks)
