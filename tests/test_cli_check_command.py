from __future__ import annotations

import json

import pytest
from efloud.app.check import CheckResult, TabInfo, WindowInfo
from efloud.cli.root import build_app
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.ui]


def _sample_result() -> CheckResult:
    return CheckResult(
        transport="rdp",
        host="127.0.0.1",
        port=6000,
        windows=(
            WindowInfo(
                id="1",
                tabs=(
                    TabInfo(title="Alpha", url="https://example.test/a"),
                    TabInfo(title="Beta", url="https://example.test/b"),
                ),
            ),
        ),
    )


def test_check_command_renders_text(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    app = build_app()

    def fake_check(**kwargs):
        assert kwargs["rdp_port"] == 6000
        assert kwargs["bidi_ws_url"] is None
        return _sample_result()

    monkeypatch.setattr("efloud.cli.commands.check.check", fake_check)

    result = runner.invoke(app, ["check", "--rdp-port", "6000"])

    assert result.exit_code == 0
    assert "transport: rdp" in result.stdout
    assert "window 1:" in result.stdout
    assert "1. Alpha | https://example.test/a" in result.stdout


def test_check_command_renders_json(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    app = build_app()

    monkeypatch.setattr("efloud.cli.commands.check.check", lambda **kwargs: _sample_result())

    result = runner.invoke(app, ["--json", "check", "--rdp-port", "6000"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["transport"] == "rdp"
    assert payload["window_count"] == 1
    assert payload["tab_count"] == 2
    assert payload["windows"][0]["tabs"][1]["title"] == "Beta"


def test_check_command_renders_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    app = build_app()

    monkeypatch.setattr("efloud.cli.commands.check.check", lambda **kwargs: _sample_result())

    result = runner.invoke(app, ["--csv", "check", "--rdp-port", "6000"])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "transport,address,window_id,tab_index,title,url"
    assert lines[1].endswith(",1,1,Alpha,https://example.test/a")
    assert lines[2].endswith(",1,2,Beta,https://example.test/b")


def test_check_command_passes_bidi_url(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    app = build_app()

    def fake_check(**kwargs):
        assert kwargs["rdp_port"] is None
        assert kwargs["bidi_ws_url"] == "ws://127.0.0.1:9222/session/abc"
        assert kwargs["marionette_port"] is None
        return _sample_result()

    monkeypatch.setattr("efloud.cli.commands.check.check", fake_check)

    result = runner.invoke(app, ["check", "--bidi-ws-url", "ws://127.0.0.1:9222/session/abc"])

    assert result.exit_code == 0
