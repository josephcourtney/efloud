"""Packaging and installed-wheel smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import efloud

_REMOVED_MODULE_PATHS = {
    "efloud/adoption.py",
    "efloud/derived.py",
    "efloud/fanout.py",
    "efloud/health.py",
    "efloud/manifest.py",
    "efloud/models.py",
    "efloud/query.py",
    "efloud/query_targets.py",
    "efloud/registry.py",
    "efloud/repository_compat.py",
    "efloud/repository_outputs.py",
    "efloud/repository_query.py",
    "efloud/repository_state.py",
    "efloud/repository_status.py",
    "efloud/repository_view.py",
    "efloud/resolve.py",
    "efloud/source_aliases.py",
    "efloud/source_results.py",
    "efloud/sqlite_metadata_v3.py",
    "efloud/state.py",
    "efloud/status.py",
    "efloud/store_inspection.py",
    "efloud/summary.py",
    "efloud/sync.py",
}

_REMOVED_IMPORTS = tuple(
    sorted(
        {
            "efloud.compat",
            *(path.removesuffix(".py").replace("/", ".") for path in _REMOVED_MODULE_PATHS),
        }
    )
)


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

    script = (
        "from efloud import DatasetSpec, Engine, HttpSource, Repository, SyncRequest\n"
        "source = HttpSource(id='example', url='https://example.test/data.json')\n"
        "spec = DatasetSpec.latest('source:example')\n"
        "assert source.adapter_id == 'efloud:http'\n"
        "with Repository.create('repository') as repo:\n"
        "    engine = Engine(repo, [source])\n"
        "    plan = engine.plan(SyncRequest(dry_run=True))\n"
        "    assert plan.request.dry_run\n"
        "assert spec is not None\n"
        "print('ok')\n"
    )
    api_result = _run(
        [str(venv_python), "-c", script],
        cwd=tmp_path,
    )
    assert api_result.stdout.strip() == "ok"

    removed_imports = repr(_REMOVED_IMPORTS)
    absence_script = (
        "import importlib.util\n"
        f"removed = {removed_imports}\n"
        "present = [name for name in removed if importlib.util.find_spec(name) is not None]\n"
        "assert not present, present\n"
    )
    _run([str(venv_python), "-c", absence_script], cwd=tmp_path)


@pytest.mark.contract
@pytest.mark.medium
@pytest.mark.smoke
def test_wheel_contains_only_intended_package_files(tmp_path: Path) -> None:
    wheel_path, _ = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    assert "efloud/__init__.py" in names
    assert not any(name.startswith("efloud/compat/") for name in names)
    assert _REMOVED_MODULE_PATHS.isdisjoint(names)
    assert not any(".ropeproject" in name for name in names)
    assert not any("autoimport.db" in name for name in names)
    assert not any("/tests/" in name or name.startswith("tests/") for name in names)
