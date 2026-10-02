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
