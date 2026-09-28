import pytest
import json
import logging
from fastapi import HTTPException
from starlette.requests import Request

from app.core.rate_limit import rate_limit
from app.core.logging import JsonFormatter
from app.core import cache


def make_request(client_ip: str) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [],
        "client": (client_ip, 12345),
        "server": ("testserver", 80),
    })


def test_rate_limit_returns_429_and_retry_after():
    dependency = rate_limit("unit-test", limit=2, window_seconds=60)
    request = make_request("192.0.2.1")
    dependency(request)
    dependency(request)

    with pytest.raises(HTTPException) as error:
        dependency(request)

    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0


def test_rate_limits_are_separated_by_client():
    dependency = rate_limit("per-client-test", limit=1, window_seconds=60)
    dependency(make_request("192.0.2.2"))
    dependency(make_request("192.0.2.3"))


def test_logs_are_json_and_only_include_approved_context_fields():
    record = logging.LogRecord("eve.test", logging.INFO, __file__, 1, "booking_created", (), None)
    record.event = "booking_created"
    record.booking_id = 12
    record.password = "must-not-be-logged"

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)
    assert payload["event"] == "booking_created"
    assert payload["booking_id"] == 12
    assert "password" not in payload


def test_redis_cache_round_trips_json(monkeypatch):
    class FakeRedis:
        value = None

        def setex(self, key, ttl, value):
            self.value = (key, ttl, value)

        def get(self, key):
            return self.value[2] if self.value and self.value[0] == key else None

    fake = FakeRedis()
    monkeypatch.setattr(cache.settings, "redis_url", "redis://fake")
    monkeypatch.setattr(cache, "_redis", fake)
    cache.set_cached_json("test:key", {"answer": 42}, ttl_seconds=30)
    assert cache.get_cached_json("test:key") == {"answer": 42}
    assert fake.value[1] == 30
