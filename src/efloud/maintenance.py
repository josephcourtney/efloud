"""Coordinated audit, crash recovery, and non-historical garbage collection."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.dataset_selectors import snapshot_observations
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository_models import stable_id
from efloud.schema import CURRENT_SCHEMA_VERSION
from efloud.writer_coordination import WriterLease

if TYPE_CHECKING:
    from pathlib import Path

_SHA256_HEX_LENGTH = 64

_REFERENCE_TABLES = ("observations", "tree_entries", "validations", "materializations")


@dataclass(frozen=True, slots=True, order=True)
class AuditIssue:
    code: str
    subject: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AuditReport:
    issues: tuple[AuditIssue, ...]
    reachability: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True, order=True)
class CleanupCandidate:
    content_id: str
    path: str
    reason: str


class RepositoryMaintenance:
    """Maintenance service for the default local SQLite/filesystem repository."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self.database = self.root / "metadata.sqlite"
        if not self.database.is_file():
            raise FileNotFoundError(self.database)

    def _connect(self, *, writable: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.database.as_uri()}?mode={'rw' if writable else 'ro'}", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != CURRENT_SCHEMA_VERSION:
            connection.close()
            msg = f"Maintenance requires schema {CURRENT_SCHEMA_VERSION}; found {version}"
            raise RuntimeError(msg)
        return connection

    @staticmethod
    def _reachability(connection: sqlite3.Connection) -> dict[str, set[str]]:
        roots: dict[str, set[str]] = {}
        for table in _REFERENCE_TABLES:
            for row in connection.execute(f"SELECT DISTINCT content_id FROM {table} WHERE content_id IS NOT NULL"):  # ruff: ignore[hardcoded-sql-expression] - fixed internal table names.
                roots.setdefault(row[0], set()).add(table)
        for row in connection.execute(
            "SELECT DISTINCT o.content_id FROM dataset_members d JOIN observations o USING(observation_id)"
        ):
            roots.setdefault(row[0], set()).add("datasets")
        for row in connection.execute(
            "SELECT DISTINCT o.content_id FROM provenance_edges p JOIN observations o "
            "ON o.observation_id = p.input_observation_id OR o.observation_id = p.output_observation_id"
        ):
            roots.setdefault(row[0], set()).add("provenance")
        return roots

    def fsck(self) -> AuditReport:
        """Inspect every historical content reference without migration or repair."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            issues = [
                AuditIssue("sqlite-integrity", str(row[0]))
                for row in connection.execute("PRAGMA integrity_check")
                if row[0] != "ok"
            ]
            issues.extend(
                AuditIssue("dangling-reference", str(row[0]), str(tuple(row)))
                for row in connection.execute("PRAGMA foreign_key_check")
            )
            roots = self._reachability(connection)
            with ReadOnlyRepository(self.root) as repository:
                for row in connection.execute("SELECT content_id, byte_size FROM content_objects ORDER BY content_id"):
                    content_id = row[0]
                    if not repository.contains_content(content_id):
                        issues.append(AuditIssue("missing-blob", content_id))
                    elif not repository.verify_content(content_id):
                        issues.append(AuditIssue("corrupt-blob", content_id))
                    else:
                        with repository.open_content(content_id) as stream:
                            size = sum(len(chunk) for chunk in iter(lambda: stream.read(1024 * 1024), b""))
                        if size != row[1]:
                            issues.append(AuditIssue("content-size", content_id))
                    if content_id not in roots:
                        issues.append(AuditIssue("unreferenced-content", content_id))
                try:
                    issues.extend(self._semantic_issues(connection, repository))
                except (ValueError, TypeError, KeyError) as error:
                    issues.append(AuditIssue("invalid-semantic-metadata", "metadata", str(error)))
            known = {row[0] for row in connection.execute("SELECT content_id FROM content_objects")}
            issues.extend(
                AuditIssue("orphan-blob", content_id) for content_id, _ in self._blobs() if content_id not in known
            )
            return AuditReport(
                tuple(sorted(issues)), tuple((key, tuple(sorted(value))) for key, value in sorted(roots.items()))
            )
        finally:
            connection.close()

    @staticmethod
    def _semantic_issues(connection: sqlite3.Connection, repository: ReadOnlyRepository) -> list[AuditIssue]:
        issues: list[AuditIssue] = []
        issues.extend(RepositoryMaintenance._snapshot_issues(repository))
        for row in connection.execute("SELECT tree_id FROM tree_snapshots"):
            entries = repository.tree_entries(row[0])
            if stable_id("tree", [entry.identity_payload() for entry in entries]) != row[0]:
                issues.append(AuditIssue("tree-identity", row[0]))
        for row in connection.execute("SELECT dataset_id FROM datasets"):
            dataset = repository.dataset(row[0])
            exact = [
                {"artifact_key": str(item.artifact_key), "observation_id": str(item.observation_id), "role": item.role}
                for item in dataset.artifacts()
            ]
            content = [
                {"artifact_key": str(item.artifact_key), "content_id": str(item.content_id), "role": item.role}
                for item in dataset.artifacts()
            ]
            if (
                stable_id("dataset", exact) != row[0]
                or stable_id("dataset-content", content) != dataset.content_identity
            ):
                issues.append(AuditIssue("dataset-identity", row[0]))
        for table, identity, payload in (
            ("observations", "observation_id", "metadata_json"),
            ("artifact_absences", "observation_id", "metadata_json"),
            ("source_snapshots", "snapshot_id", "evidence_json"),
        ):
            for row in connection.execute(
                f"SELECT {identity}, source_id, {payload} FROM {table} WHERE source_id IS NOT NULL"  # ruff: ignore[hardcoded-sql-expression] - fixed internal names.
            ):
                source = repository.source(row[1])
                revision = json.loads(row[2]).get("source_definition_revision_id")
                if revision is not None and (
                    source is None or revision not in {str(item.revision_id) for item in source.revisions}
                ):
                    issues.append(AuditIssue("source-revision", row[0]))
        for table, identity in (("runs", "run_id"), ("operations", "operation_id")):
            issues.extend(
                AuditIssue("running-lifecycle", row[0], table)
                for row in connection.execute(f"SELECT {identity} FROM {table} WHERE status = 'running'")  # ruff: ignore[hardcoded-sql-expression] - fixed internal names.
            )
        return issues

    @staticmethod
    def _snapshot_issues(repository: ReadOnlyRepository) -> list[AuditIssue]:
        issues: list[AuditIssue] = []
        for source in repository.sources():
            for snapshot in repository.source_snapshots_for(source.source_id, limit=-1):
                if snapshot.complete:
                    try:
                        snapshot_observations(repository, snapshot)
                    except ValueError as error:
                        issues.append(AuditIssue("incomplete-snapshot-evidence", str(snapshot.snapshot_id), str(error)))
        return issues

    def _blobs(self) -> tuple[tuple[str, Path], ...]:
        objects = self.root / "objects"
        result: list[tuple[str, Path]] = []
        for path in sorted(objects.glob("sha256/*/*")):
            digest = path.name
            if (
                len(digest) == _SHA256_HEX_LENGTH
                and all(char in "0123456789abcdef" for char in digest)
                and path.parent.name == digest[:2]
                and path.is_file()
                and not path.is_symlink()
            ):
                if not path.resolve().is_relative_to(objects.resolve()):
                    continue
                result.append((f"sha256:{digest}", path))
        return tuple(result)

    def cleanup(self, *, now: float, grace_period: float, dry_run: bool = True) -> tuple[CleanupCandidate, ...]:
        """Recompute safe orphans under the writer lease; preserve all history."""
        if not math.isfinite(now) or not math.isfinite(grace_period) or grace_period < 0:
            msg = "Cleanup requires a finite time and nonnegative grace period"
            raise ValueError(msg)
        lease = WriterLease(self.root)
        try:
            connection = self._connect(writable=not dry_run)
        except BaseException:
            lease.close()
            raise
        try:
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                msg = "Cleanup refused: repair dangling metadata references first"
                raise ValueError(msg)
            roots = self._reachability(connection)
            known = {row[0] for row in connection.execute("SELECT content_id FROM content_objects")}
            candidates = tuple(
                CleanupCandidate(
                    content_id,
                    path.relative_to(self.root).as_posix(),
                    "unreferenced-content" if content_id in known else "orphan-blob",
                )
                for content_id, path in self._blobs()
                if content_id not in roots and now - path.stat().st_mtime >= grace_period
            )
            available_ids = {content_id for content_id, _ in self._blobs()}
            if now - self.database.stat().st_mtime >= grace_period:
                missing = tuple(
                    CleanupCandidate(content_id, "", "unreferenced-missing-content")
                    for content_id in sorted(known - roots.keys() - available_ids)
                )
                candidates = tuple(sorted((*candidates, *missing)))
            if not dry_run:
                for candidate in candidates:
                    # Metadata deletion first: a crash can leave an orphan, never a missing referenced blob.
                    with connection:
                        connection.execute("DELETE FROM content_objects WHERE content_id = ?", (candidate.content_id,))
                    if candidate.path:
                        (self.root / candidate.path).unlink()
            return candidates
        finally:
            connection.close()
            lease.close()

    def recover(self, *, finished_at: float, dry_run: bool = True) -> tuple[str, ...]:
        """Fail abandoned lifecycle records; replay acquisition through a fresh Engine run."""
        if not math.isfinite(finished_at):
            msg = "Recovery time must be finite"
            raise ValueError(msg)
        lease = WriterLease(self.root)
        try:
            connection = self._connect(writable=not dry_run)
        except BaseException:
            lease.close()
            raise
        try:
            operations = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT operation_id FROM operations WHERE status = 'running' ORDER BY operation_id"
                )
            )
            runs = tuple(
                row[0] for row in connection.execute("SELECT run_id FROM runs WHERE status = 'running' ORDER BY run_id")
            )
            if not dry_run:
                with connection:
                    for operation_id in operations:
                        row = connection.execute(
                            "SELECT details_json FROM operations WHERE operation_id = ?", (operation_id,)
                        ).fetchone()
                        details = json.loads(row[0])
                        details["recovery"] = "interrupted; retry in a new run"
                        connection.execute(
                            "UPDATE operations SET status = 'failed', finished_at = MAX(started_at, ?), "
                            "details_json = ? WHERE operation_id = ?",
                            (finished_at, json.dumps(details, sort_keys=True, separators=(",", ":")), operation_id),
                        )
                    connection.execute(
                        "UPDATE runs SET status = 'failed', finished_at = MAX(started_at, ?) WHERE status = 'running'",
                        (finished_at,),
                    )
            return (*operations, *runs)
        finally:
            connection.close()
            lease.close()


__all__ = ["AuditIssue", "AuditReport", "CleanupCandidate", "RepositoryMaintenance"]
