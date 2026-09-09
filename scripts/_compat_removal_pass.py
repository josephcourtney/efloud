from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new)


# Make the metadata store current-schema-only and reject old status/producer aliases.
path = "src/efloud/sqlite_metadata.py"
text = read(path)
text = replace_once(
    text,
    "from efloud.schema_migrations import initialize_or_migrate",
    "from efloud.schema_migrations import initialize_schema",
    label="schema initializer import",
)
text = text.replace("_legacy_storage_key_for", "_storage_key_for")
text = text.replace(
    '    """Derive the historical SQLite locator without consulting any blob backend."""',
    '    """Derive the canonical SQLite locator without consulting any blob backend."""',
)
text = replace_once(
    text,
    '''def _run_terminal_status(status: str) -> str:\n    normalized = "succeeded" if status == "success" else status\n    if normalized not in _RUN_TERMINAL:\n        msg = f"Invalid terminal run status: {status!r}"\n        raise ValueError(msg)\n    return normalized\n\n\ndef _operation_terminal_status(status: str) -> str:\n    normalized = "failed" if status == "partial" else "succeeded" if status == "success" else status\n    if normalized not in _OPERATION_TERMINAL:\n        msg = f"Invalid terminal operation status: {status!r}"\n        raise ValueError(msg)\n    return normalized\n''',
    '''def _run_terminal_status(status: str) -> str:\n    if status not in _RUN_TERMINAL:\n        msg = f"Invalid terminal run status: {status!r}"\n        raise ValueError(msg)\n    return status\n\n\ndef _operation_terminal_status(status: str) -> str:\n    if status not in _OPERATION_TERMINAL:\n        msg = f"Invalid terminal operation status: {status!r}"\n        raise ValueError(msg)\n    return status\n''',
    label="terminal status normalization",
)
text = replace_once(
    text,
    '''def _operation_parameters(parameters: JsonObject) -> JsonObject:\n    normalized = dict(parameters)\n    raw_producer = json_mapping_or_none(normalized.get("producer"))\n    if raw_producer is None:\n        normalized["producer"] = ProducerRef("efloud:legacy", "0").to_dict()\n    else:\n        ProducerRef.from_mapping(raw_producer)\n    return normalized\n''',
    '''def _operation_parameters(parameters: JsonObject) -> JsonObject:\n    normalized = dict(parameters)\n    raw_producer = json_mapping_or_none(normalized.get("producer"))\n    if raw_producer is None:\n        msg = "Operation parameters require canonical producer metadata."\n        raise ValueError(msg)\n    ProducerRef.from_mapping(raw_producer)\n    return normalized\n''',
    label="producer fallback",
)
text = replace_once(
    text,
    "        initialize_or_migrate(self._connection)",
    "        initialize_schema(self._connection)",
    label="schema initializer call",
)
write(path, text)

# Reject old status spellings at the repository boundary too.
path = "src/efloud/repository.py"
text = read(path)
text = replace_once(
    text,
    '''def _canonical_terminal_status(status: str, *, operation: bool) -> str:\n    normalized = "failed" if operation and status == "partial" else "succeeded" if status == "success" else status\n    allowed = _OPERATION_TERMINAL if operation else _RUN_TERMINAL\n    if normalized not in allowed:\n        kind = "operation" if operation else "run"\n        msg = f"Invalid terminal {kind} status: {status!r}"\n        raise ValueError(msg)\n    return normalized\n''',
    '''def _canonical_terminal_status(status: str, *, operation: bool) -> str:\n    allowed = _OPERATION_TERMINAL if operation else _RUN_TERMINAL\n    if status not in allowed:\n        kind = "operation" if operation else "run"\n        msg = f"Invalid terminal {kind} status: {status!r}"\n        raise ValueError(msg)\n    return status\n''',
    label="repository status aliases",
)
write(path, text)

# The read-only backend is internal and must fail, not instruct users to migrate.
path = "src/efloud/read_only_repository.py"
text = read(path)
text = replace_once(
    text,
    "from efloud.schema_migrations import CURRENT_SCHEMA_VERSION",
    "from efloud.schema import CURRENT_SCHEMA_VERSION",
    label="read-only schema import",
)
old = '''            msg = (\n                "Read-only repository access requires the current metadata schema "\n                f"version {CURRENT_SCHEMA_VERSION}; found {current}. Open the repository "\n                "writable once to perform supported migrations."\n            )'''
new = '''            msg = (\n                f"Unsupported efloud metadata schema version: {current}; "\n                f"expected {CURRENT_SCHEMA_VERSION}. Historical schemas are not migrated in place."\n            )'''
text = replace_once(text, old, new, label="read-only migration message")
write(path, text)

# Remove the old no-op lifecycle shim from the canonical engine.
path = "src/efloud/engine.py"
text = read(path)
text = replace_once(
    text,
    '''    def close(self) -> None:\n        """Compatibility no-op; repository lifetime is caller-owned."""\n\n''',
    "",
    label="engine close shim",
)
write(path, text)

# Keep transport scratch state, but move it under one explicitly non-authoritative root.
write(
    "src/efloud/runtime.py",
    '''from __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from pathlib import Path\n\n\n@dataclass(frozen=True, slots=True)\nclass EngineRuntime:\n    """Advanced local runtime settings for non-authoritative transport state."""\n\n    root: Path\n    operational_dir: str = ".efloud-runtime"\n    runtime_progress: bool = False\n    remove_empty_dirs_after_rsync: bool = True\n\n    @classmethod\n    def for_root(cls, root: Path) -> EngineRuntime:\n        return cls(root=root.resolve())\n\n    @property\n    def operational_root(self) -> Path:\n        return self.root / self.operational_dir\n\n    @property\n    def staging_root(self) -> Path:\n        return self.operational_root / "staging"\n\n    @property\n    def http_root(self) -> Path:\n        return self.staging_root / "http"\n\n    @property\n    def rsync_root(self) -> Path:\n        return self.staging_root / "rsync"\n\n    @property\n    def http_cache_root(self) -> Path:\n        return self.operational_root / "cache" / "http"\n\n    @property\n    def rate_limits_root(self) -> Path:\n        return self.operational_root / "rate-limits"\n\n\n__all__ = ["EngineRuntime"]\n''',
)

path = "src/efloud/rsync_adapter.py"
text = read(path).replace("runtime.mirrors_root", "runtime.rsync_root")
write(path, text)

# Generic filesystem helpers remain; alpha cache/mirror layout management does not.
write(
    "src/efloud/fs.py",
    '''from __future__ import annotations\n\nimport gzip\nimport json\nimport os\nimport tempfile\nfrom pathlib import Path\n\n\ndef atomic_write_bytes(dest: Path, data: bytes) -> None:\n    dest.parent.mkdir(parents=True, exist_ok=True)\n    with tempfile.NamedTemporaryFile(dir=str(dest.parent), delete=False) as tmp:\n        tmp_path = Path(tmp.name)\n        tmp.write(data)\n        tmp.flush()\n        os.fsync(tmp.fileno())\n    tmp_path.replace(dest)\n\n\ndef atomic_write_text(dest: Path, text: str) -> None:\n    atomic_write_bytes(dest, text.encode("utf-8"))\n\n\ndef safe_json_dump(obj: object) -> str:\n    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)\n\n\ndef read_gz_json(path: Path) -> object:\n    with gzip.open(path, "rt", encoding="utf-8") as handle:\n        return json.load(handle)\n\n\ndef read_text_maybe_gzip(path: Path) -> str:\n    if path.suffix == ".gz":\n        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:\n            return handle.read()\n    return path.read_text(encoding="utf-8", errors="replace")\n''',
)

print("compatibility-removal rewrite pass complete")
