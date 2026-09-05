"""Packaging and installed-wheel smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import efloud


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )


def _build_wheel(tmp_path: Path) -> tuple[Path, Path]:
    """Build the release wheel.

    Must be called from a MEDIUM test because it spawns ``uv``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"

    build_env = os.environ.copy()
    build_env["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")

    _run(
        [
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(dist_dir),
        ],
        cwd=repo_root,
        env=build_env,
    )

    wheel_path = next(dist_dir.glob("efloud-*.whl"))
    return wheel_path, repo_root


@pytest.mark.contract
@pytest.mark.medium
@pytest.mark.smoke
def test_wheel_installs_and_public_api_runs(tmp_path: Path) -> None:
    wheel_path, repo_root = _build_wheel(tmp_path)
    venv_dir = tmp_path / "venv"

    _run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=repo_root,
    )

    venv_python = venv_dir / "bin" / "python"

    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            str(wheel_path),
        ],
        cwd=repo_root,
    )

    version_result = _run(
        [
            str(venv_python),
            "-c",
            (
                "from importlib.metadata import version; "
                "import efloud; "
                "assert efloud.__version__ == version('efloud'); "
                "print(efloud.__version__)"
            ),
        ],
        cwd=tmp_path,
    )
    assert version_result.stdout.strip() == efloud.__version__

    api_result = _run(
        [
            str(venv_python),
            "-c",
            (
                "from pathlib import Path; "
                "from efloud import EngineConfig, SourceDefinition, "
                "SourceKind, parse_query_target; "
                "cfg = EngineConfig("
                "root=Path('mirror'), "
                "sources=[SourceDefinition("
                "id='example', "
                "description='Example', "
                "url='https://example.test/data.json', "
                "kind=SourceKind.HTTP"
                ")]"
                "); "
                "target = parse_query_target('source:example'); "
                "assert cfg.sources[0].id == 'example'; "
                "assert target.identifier == 'example'; "
                "print('ok')"
            ),
        ],
        cwd=tmp_path,
    )
    assert api_result.stdout.strip() == "ok"


@pytest.mark.contract
@pytest.mark.medium
@pytest.mark.smoke
def test_wheel_contains_only_intended_package_files(tmp_path: Path) -> None:
    wheel_path, _ = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()

    assert "efloud/__init__.py" in names
    assert not any(".ropeproject" in name for name in names)
    assert not any("autoimport.db" in name for name in names)
    assert not any("/tests/" in name or name.startswith("tests/") for name in names)
