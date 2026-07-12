from prism.core.security import generate_api_key, hash_key


def test_generate_api_key_format() -> None:
    raw_key, key_hash, key_prefix = generate_api_key()
    assert raw_key.startswith("prism_")
    assert len(raw_key) > 20
    assert key_prefix.startswith("prism_")
    assert len(key_prefix) == 14  # "prism_" + 8 chars


def test_generate_api_key_is_unique() -> None:
    key1, _, _ = generate_api_key()
    key2, _, _ = generate_api_key()
    assert key1 != key2


def test_hash_key_is_deterministic() -> None:
    raw = "prism_test_key"
    assert hash_key(raw) == hash_key(raw)


def test_hash_key_differs_from_raw() -> None:
    raw = "prism_test_key"
    assert hash_key(raw) != raw


def test_hash_key_length() -> None:
    raw = "prism_test_key"
    assert len(hash_key(raw)) == 64  # SHA-256 hex digest
