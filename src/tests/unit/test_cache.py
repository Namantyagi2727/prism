from prism.core.cache import exact_cache_key


def test_same_inputs_produce_same_key() -> None:
    messages = [{"role": "user", "content": "hello"}]
    key1 = exact_cache_key("fast", messages, 0.7)
    key2 = exact_cache_key("fast", messages, 0.7)
    assert key1 == key2


def test_different_model_produces_different_key() -> None:
    messages = [{"role": "user", "content": "hello"}]
    key1 = exact_cache_key("fast", messages, 0.7)
    key2 = exact_cache_key("slow", messages, 0.7)
    assert key1 != key2


def test_different_temperature_produces_different_key() -> None:
    messages = [{"role": "user", "content": "hello"}]
    key1 = exact_cache_key("fast", messages, 0.7)
    key2 = exact_cache_key("fast", messages, 0.0)
    assert key1 != key2


def test_key_is_hex_string() -> None:
    key = exact_cache_key("fast", [{"role": "user", "content": "hi"}], 0.7)
    assert len(key) == 64
    int(key, 16)  # raises ValueError if not valid hex
