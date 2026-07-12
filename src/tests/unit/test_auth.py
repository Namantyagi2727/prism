import time

from prism.core.auth import check_rate_limit_key


def test_rate_limit_key_format() -> None:
    key = check_rate_limit_key("abc-123", 100)
    assert "abc-123" in key


def test_rate_limit_key_includes_minute_bucket() -> None:
    minute = int(time.time() // 60)
    key = check_rate_limit_key("abc-123", 100)
    assert str(minute) in key
