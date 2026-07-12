import hashlib
import secrets


def generate_api_key() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    raw_key = f"prism_{token}"
    key_prefix = f"prism_{token[:8]}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash, key_prefix


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
