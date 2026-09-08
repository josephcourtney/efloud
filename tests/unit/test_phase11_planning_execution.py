from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields
from pathlib import Path

import pytest

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    AdapterRegistry,
    HttpAcquisition,
)
from efloud.engine import Engine
from efloud.models import EngineConfig
from efloud.planner import SyncPlanner
from efloud.planning import SyncRequest
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import SourceId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


@dataclass
class RecordingHttpAdapter:
    fail_ids: set[str] = field(default_factory=set)
    delay_seconds: float = 0.0
    calls: list[str] = field(default_factory=list)
    active: int = 0
    max_active: int = 0
    descriptor: AdapterDescriptor = field(
        default_factory=lambda: AdapterDescriptor(
            adapter_id="test:http",
            version="7",
            source_kinds=(SourceKind.HTTP,),
            capabilities=AdapterCapabilities(inventory=False, fetch=True),
        )
    )

    async def acquire(self, context: AdapterExecutionContext):
        source = context.source
        self.calls.append(source.id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if source.id in self.fail_ids:
                return HttpAcquisition(
                    source_id=source.id,
                    status="failed",
                    destination=None,
                    observed_at=100.0,
                    error="fixture failure",
                )
            destination = Path(context.config.root) / "adapter-output" / f"{source.id}.txt"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source.id, encoding="utf-8")
            return HttpAcquisition(
                source_id=source.id,
                status="succeeded",
                destination=destination,
                observed_at=100.0,
                status_code=200,
            )
        finally:
            self.active -= 1


@dataclass
class DependentTask:
    name: str = "dependent"
    repository_version: str = "3"
    repository_input_source_ids: tuple[str, ...] = ("a",)
    calls: int = 0

    @staticmethod
    def repository_parameters():
        return {"fixture": True}

    async def run(self, *, sync_root, manifest, sources):
        del sync_root, manifest, sources
        self.calls += 1
        await asyncio.sleep(0)
        return {"ok": True}


def _source(source_id: str) -> SourceDefinition:
    return SourceDefinition(
        source_id,
        source_id.upper(),
        f"https://example.test/{source_id}.txt",
        SourceKind.HTTP,
    )


def test_planning_is_deterministic_and_performs_no_acquisition_or_authoritative_mutation(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    registry = AdapterRegistry((adapter,))
    config = EngineConfig(root=tmp_path, sources=[_source("b"), _source("a")])

    with Repository(tmp_path) as repository:
        planner = SyncPlanner(registry)
        first = planner.plan(config=config, repository=repository)
        second = planner.plan(config=config, repository=repository)

        assert first == second
        assert first.plan_id == second.plan_id
        assert [operation.operation_key for operation in first.operations] == ["source:a", "source:b"]
        assert adapter.calls == []
        assert repository.artifact_keys() == ()
        assert repository.metadata.operations_for_source(SourceId("a")) == ()
        assert first.decisions[0].refresh is not None
        assert first.decisions[0].refresh.reason
        assert first.operation("source:a").parameters["adapter_capabilities"] == {
            "inventory": False,
            "fetch": True,
        }


def test_repository_snapshot_changes_deterministic_plan_identity(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    source = _source("a")
    config = EngineConfig(root=tmp_path, sources=[source])

    with Repository(tmp_path) as repository:
        planner = SyncPlanner(AdapterRegistry((adapter,)))
        before = planner.plan(config=config, repository=repository)

        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        repository.record_source_snapshot(
            source_id=source.id,
            run_id=run_id,
            complete=True,
            observed_at=11.0,
            evidence={"fixture": True},
        )
        repository.finish_run(run_id, status="succeeded", finished_at=12.0)

        after = planner.plan(config=config, repository=repository)
        assert before.plan_id != after.plan_id
        assert "current_snapshot_id" not in before.operation("source:a").parameters
        assert "current_snapshot_id" in after.operation("source:a").parameters
        assert adapter.calls == []


def test_dry_run_executes_exact_plan_shape_without_repository_mutation(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    config = EngineConfig(root=tmp_path, sources=[_source("a")])
    request = SyncRequest(dry_run=True, max_concurrency=1)

    with Engine.from_config(config, adapters=AdapterRegistry((adapter,))) as engine:
        plan = engine.plan(request)
        result = asyncio.run(engine.sync(request))

        assert result.plan == plan
        assert result.repository_run_id is None
        assert result.execution.run_id is None
        assert [operation.operation_key for operation in result.execution.operations] == [
            operation.operation_key for operation in plan.operations
        ]
        assert {operation.status for operation in result.execution.operations} == {"not-executed"}
        assert adapter.calls == []
        assert engine.repository.artifact_keys() == ()
        assert engine.repository.metadata.operations_for_source(SourceId("a")) == ()
        assert not (tmp_path / config.log_dir / config.manifest_filename).exists()


def test_executor_enforces_requested_concurrency_bound(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter(delay_seconds=0.02)
    config = EngineConfig(root=tmp_path, sources=[_source("a"), _source("b"), _source("c")])

    with Engine.from_config(config, adapters=AdapterRegistry((adapter,))) as engine:
        result = asyncio.run(engine.sync(SyncRequest(max_concurrency=2)))
        assert result.ok
        assert adapter.max_active == 2
        assert sorted(adapter.calls) == ["a", "b", "c"]


def test_failed_dependency_blocks_derived_operation_and_persists_adapter_producer(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter(fail_ids={"a"})
    task = DependentTask()
    config = EngineConfig(root=tmp_path, sources=[_source("a")], derived_tasks=(task,))

    with Engine.from_config(config, adapters=AdapterRegistry((adapter,))) as engine:
        result = asyncio.run(engine.sync())
        statuses = {operation.operation_key: operation.status for operation in result.execution.operations}
        assert statuses == {"derived:dependent": "blocked", "source:a": "failed"}
        assert task.calls == 0
        assert result.ok is False
        assert result.repository_run_id is not None
        persisted = engine.repository.metadata.operations_for_run(result.repository_run_id)
        source_operation = next(operation for operation in persisted if operation.subject == "a")
        derived_operation = next(operation for operation in persisted if operation.subject == "dependent")
        assert source_operation.producer.producer_id == "test:http"
        assert source_operation.producer.version == "7"
        assert derived_operation.status == "cancelled"
        assert derived_operation.details["failed_dependencies"] == ["source:a"]


def test_housekeeping_is_explicit_in_plan_and_orders_dependent_operations(tmp_path: Path) -> None:
    http = _source("http")
    mirror = SourceDefinition(
        "mirror",
        "Mirror",
        "rsync://example.test/module",
        SourceKind.RSYNC,
        local_subpath="mirror",
    )
    config = EngineConfig(
        root=tmp_path,
        sources=[http, mirror],
        delete_http_caches=True,
        prune_orphan_mirrors=True,
    )

    with Repository(tmp_path) as repository:
        engine = Engine.from_config(config, repository=repository)
        plan = engine.plan()

    assert plan.operation("source:http").dependencies == ("housekeeping:delete-http-caches",)
    assert plan.operation("housekeeping:prune-orphan-mirrors").dependencies == ("source:mirror",)
    assert plan.operation("housekeeping:delete-http-caches").producer.producer_id == "efloud:housekeeping"


def test_source_definition_remains_declarative_data_only() -> None:
    field_names = {item.name for item in fields(SourceDefinition)}
    assert not field_names & {"client", "session", "adapter", "transport", "repository"}
