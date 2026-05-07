"""Daemon/client resilience around slow startup and disconnected hooks."""

from __future__ import annotations

from ken.daemon import client
from ken.daemon.server import _Handler


def test_ranking_endpoints_get_longer_post_timeout():
    assert client._post_timeout("/prompts") == client.RANK_POST_TIMEOUT_S
    assert client._post_timeout("/rank") == client.RANK_POST_TIMEOUT_S
    assert client._post_timeout("/explain") == client.RANK_POST_TIMEOUT_S


def test_lifecycle_endpoints_keep_short_post_timeout():
    assert client._post_timeout("/sessions/start") == client.POST_TIMEOUT_S
    assert client._post_timeout("/tools/pre") == client.POST_TIMEOUT_S
    assert client._post_timeout("/turn-end") == client.POST_TIMEOUT_S


def test_post_timeout_does_not_respawn_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "_read_port", lambda _root: 12345)

    def timeout_request(*_args, **_kwargs):
        raise TimeoutError

    def fail_spawn(_root):
        raise AssertionError("timeout should not clear port and spawn")

    monkeypatch.setattr(client, "_request", timeout_request)
    monkeypatch.setattr(client, "_spawn_and_wait", fail_spawn)

    assert client._post_with_spawn(tmp_path, "/rank", {}) is None


def test_respond_ignores_disconnected_client(monkeypatch):
    handler = object.__new__(_Handler)
    handler.path = "/health"
    handler.wfile = _BrokenWriter()

    monkeypatch.setattr(handler, "send_response", lambda _status: None)
    monkeypatch.setattr(handler, "send_header", lambda _name, _value: None)
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._respond(200, {"ok": True})


class _BrokenWriter:
    def write(self, _body: bytes) -> None:
        raise BrokenPipeError
