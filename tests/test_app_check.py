from __future__ import annotations

import json
from typing import Self

import pytest
from efloud.app import check as check_mod
from efloud.domain.config import Configuration
from efloud.domain.errors import EfloudProtocolError, EfloudUsageError

pytestmark = [pytest.mark.unit]


class FakeSocket:
    def __init__(self, inbound_frames: list[bytes]) -> None:
        self._inbound = bytearray(b"".join(inbound_frames))
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        if not self._inbound:
            return b""
        chunk = self._inbound[:size]
        del self._inbound[:size]
        return bytes(chunk)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        _ = self.sent

    def __enter__(self) -> Self:
        """Support context-manager usage in socket.create_connection tests."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Match socket close semantics without suppressing exceptions."""
        return


def _frame(payload: object) -> bytes:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return str(len(raw)).encode("ascii") + b":" + raw


def test_check_requires_port() -> None:
    with pytest.raises(EfloudUsageError):
        check_mod.check(
            configuration=Configuration(),
            host="127.0.0.1",
            rdp_port=None,
            bidi_ws_url=None,
            marionette_port=None,
            timeout_seconds=1.0,
        )


def test_check_via_rdp_groups_tabs_by_window(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_socket = FakeSocket(
        [
            _frame({"from": "root", "applicationType": "browser"}),
            _frame(
                {
                    "from": "root",
                    "tabs": [
                        {"outerWindowID": 100, "title": "One", "url": "https://example.test/one"},
                        {"outerWindowID": 100, "title": "Two", "url": "https://example.test/two"},
                        {"outerWindowID": 101, "title": "Three", "url": "https://example.test/three"},
                    ],
                },
            ),
        ],
    )

    def fake_connect(address: tuple[str, int], timeout: float) -> FakeSocket:
        assert address == ("127.0.0.1", 6000)
        assert timeout == pytest.approx(2.5)
        return fake_socket

    monkeypatch.setattr(check_mod.socket, "create_connection", fake_connect)

    result = check_mod._check_via_rdp(host="127.0.0.1", port=6000, timeout_seconds=2.5)

    assert result.transport == "rdp"
    assert len(result.windows) == 2
    assert result.windows[0].id == "100"
    assert [tab.title for tab in result.windows[0].tabs] == ["One", "Two"]
    assert result.windows[1].id == "101"

    assert b'"type":"listTabs"' in bytes(fake_socket.sent)


def test_check_falls_back_to_marionette(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = check_mod.CheckResult(transport="marionette", host="127.0.0.1", port=2828, windows=())

    def fake_rdp(**kwargs):
        msg = "rdp unavailable"
        raise EfloudProtocolError(msg)

    def fake_marionette(**kwargs):
        assert kwargs["port"] == 2828
        return expected

    monkeypatch.setattr(check_mod, "_check_via_rdp", fake_rdp)
    monkeypatch.setattr(check_mod, "_check_via_marionette", fake_marionette)

    result = check_mod.check(
        configuration=Configuration(),
        host="127.0.0.1",
        rdp_port=6000,
        bidi_ws_url=None,
        marionette_port=2828,
        timeout_seconds=1.0,
    )

    assert result is expected


def test_check_via_marionette_lists_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_socket = FakeSocket(
        [
            _frame({"applicationType": "gecko", "marionetteProtocol": 3}),
            _frame([1, 1, None, {"sessionId": "abc"}]),
            _frame([1, 2, None, ["h1", "h2"]]),
            _frame([1, 11, None, {}]),
            _frame([1, 31, None, "Tab One"]),
            _frame([1, 51, None, "https://example.test/one"]),
            _frame([1, 12, None, {}]),
            _frame([1, 32, None, "Tab Two"]),
            _frame([1, 52, None, "https://example.test/two"]),
            _frame([1, 999, None, {}]),
        ],
    )

    def fake_connect(address: tuple[str, int], timeout: float) -> FakeSocket:
        assert address == ("127.0.0.1", 2828)
        assert timeout == pytest.approx(1.5)
        return fake_socket

    monkeypatch.setattr(check_mod.socket, "create_connection", fake_connect)

    result = check_mod._check_via_marionette(host="127.0.0.1", port=2828, timeout_seconds=1.5)

    assert result.transport == "marionette"
    assert [window.id for window in result.windows] == ["marionette-1", "marionette-2"]
    assert result.windows[0].tabs[0].title == "Tab One"
    assert result.windows[1].tabs[0].url == "https://example.test/two"

    sent = bytes(fake_socket.sent)
    assert b'"WebDriver:NewSession"' in sent
    assert b'"WebDriver:GetWindowHandles"' in sent
    assert b'"WebDriver:DeleteSession"' in sent


class FakeBiDiSocket:
    def __init__(self, inbound_messages: list[dict[str, object]]) -> None:
        self._messages = list(inbound_messages)
        self.sent_messages: list[dict[str, object]] = []

    def __enter__(self) -> Self:
        """Support context-manager use in the BiDi transport helper."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Match socket cleanup semantics without suppressing exceptions."""

    def send_json(self, payload: dict[str, object]) -> None:
        self.sent_messages.append(payload)

    def recv_json(self) -> dict[str, object]:
        return self._messages.pop(0)


def test_check_via_bidi_lists_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ws = FakeBiDiSocket(
        [
            {"method": "log.entryAdded", "params": {"text": "ignore event"}},
            {
                "id": 1,
                "result": {
                    "contexts": [
                        {"context": "tab-a", "url": "https://example.test/a", "title": "Alpha"},
                        {"context": "tab-b", "url": "https://example.test/b"},
                    ],
                },
            },
        ],
    )

    monkeypatch.setattr(
        check_mod,
        "_open_bidi_websocket",
        lambda **kwargs: fake_ws,
    )

    result = check_mod._check_via_bidi(
        ws_url="ws://127.0.0.1:9222/session/abc",
        timeout_seconds=1.0,
    )

    assert result.transport == "bidi"
    assert result.host == "127.0.0.1"
    assert result.port == 9222
    assert [window.id for window in result.windows] == ["bidi-tab-a", "bidi-tab-b"]
    assert result.windows[0].tabs[0].title == "Alpha"
    assert result.windows[1].tabs[0].title == "(untitled)"
    assert fake_ws.sent_messages == [
        {"id": 1, "method": "browsingContext.getTree", "params": {}},
    ]
