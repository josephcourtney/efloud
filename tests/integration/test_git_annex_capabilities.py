from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

import efloud.content.git_annex as git_annex
from efloud.content.git_annex import GitAnnexCapabilityError, GitAnnexContentStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.skipif(shutil.which("git-annex") is None, reason="git-annex is not installed"),
]


def test_annex_capability_probe_returns_raw_version(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")

    version = store.check_available()

    assert version
    assert "\n" not in version


def test_annex_capability_probe_reports_missing_command_with_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    monkeypatch.setattr(git_annex, "_REQUIRED_COMMANDS", frozenset({"efloud-impossible-command"}))

    with pytest.raises(GitAnnexCapabilityError, match=r"git-annex .* lacks required command.*efloud-impossible-command"):
        store.check_available()
