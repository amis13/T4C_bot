from bot.memory import ConversationStore, estimate_tokens


def make_store(tmp_path):
    return ConversationStore(str(tmp_path / "ia.db"))


def test_estimate_tokens_grows_with_length():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("x" * 400) > estimate_tokens("x" * 40)


def test_window_returns_turns_in_chronological_order(tmp_path):
    store = make_store(tmp_path)
    store.append(10, "user", "uno")
    store.append(10, "assistant", "dos")
    store.append(10, "user", "tres")
    assert store.window(10, budget_tokens=1000) == [
        {"role": "user", "content": "uno"},
        {"role": "assistant", "content": "dos"},
        {"role": "user", "content": "tres"},
    ]


def test_window_is_isolated_per_channel(tmp_path):
    store = make_store(tmp_path)
    store.append(1, "user", "canal uno")
    store.append(2, "user", "canal dos")
    assert store.window(1, 1000) == [{"role": "user", "content": "canal uno"}]


def test_window_drops_oldest_turns_beyond_budget(tmp_path):
    store = make_store(tmp_path)
    for i in range(10):
        store.append(5, "user", "x" * 400)  # ~100 tokens cada uno
    result = store.window(5, budget_tokens=250)
    assert 1 <= len(result) < 10
    # conserva los más recientes: todos son iguales aquí, basta comprobar el recorte


def test_window_drops_a_single_oversized_recent_turn(tmp_path):
    store = make_store(tmp_path)
    store.append(5, "user", "contexto previo corto")
    store.append(5, "user", "y" * 100000)  # el más reciente no cabe
    assert store.window(5, budget_tokens=100) == []


def test_reset_clears_only_that_channel(tmp_path):
    store = make_store(tmp_path)
    store.append(1, "user", "a")
    store.append(2, "user", "b")
    store.reset(1)
    assert store.window(1, 1000) == []
    assert store.window(2, 1000) == [{"role": "user", "content": "b"}]


def test_history_survives_reopening_the_store(tmp_path):
    path = str(tmp_path / "ia.db")
    first = ConversationStore(path)
    first.append(7, "user", "persistente")
    second = ConversationStore(path)
    assert second.window(7, 1000) == [{"role": "user", "content": "persistente"}]


def test_ordering_is_stable_for_same_channel(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.append(3, "user", str(i))
    assert [m["content"] for m in store.window(3, 10000)] == ["0", "1", "2", "3", "4"]
