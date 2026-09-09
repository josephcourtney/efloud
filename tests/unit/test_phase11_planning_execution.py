from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

import pytest

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    AdapterRegistry,
    HttpAcquisition,
)
from efloud.derivation import DerivedResult, DerivedTaskSpec
from efloud.engine import Engine
from efloud.planner import SyncPlanner
from efloud.planning import SyncRequest
from efloud.repository import Repository
from efloud.repository_models import SourceId
from efloud.runtime import EngineRuntime
from efloud.sources import HttpSource, RsyncSource

if TYPE_CHECKING:
    from pathlib import Path

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
            adapter_id="efloud:http",
            version="7",
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
            destination = context.runtime.root / "adapter-output" / f"{source.id}.txt"
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
    spec: DerivedTaskSpec = field(
        default_factory=lambda: DerivedTaskSpec(
            task_id="test:dependent",
            task_version="3",
            deterministic=True,
            dependency_semantics="content",
            parameters={"fixture": True},
        )
    )
    input_source_ids: tuple[str, ...] = ("a",)
    output_names: tuple[str, ...] = ()
    calls: int = 0

    async def run(self, *, context):
        del context
        self.calls += 1
        await asyncio.sleep(0)
        return DerivedResult()


def _source(source_id: str) -> HttpSource:
    return HttpSource(
        id=source_id,
        description=source_id.upper(),
        url=f"https://example.test/{source_id}.txt",
    )


def test_planning_is_deterministic_and_performs_no_acquisition_or_authoritative_mutation(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    registry = AdapterRegistry((adapter,))
    sources = (_source("b"), _source("a"))

    with Repository(tmp_path) as repository:
        planner = SyncPlanner(registry)
        first = planner.plan(sources=sources, repository=repository)
        second = planner.plan(sources=sources, repository=repository)

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
        assert first.operation("source:a").parameters["adapter_id"] == "efloud:http"


def test_repository_snapshot_changes_deterministic_plan_identity(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    source = _source("a")

    with Repository(tmp_path) as repository:
        planner = SyncPlanner(AdapterRegistry((adapter,)))
        before = planner.plan(sources=(source,), repository=repository)

        repository.register_source(SourceId(source.id), source.definition())
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        repository.record_source_snapshot(
            source_id=source.id,
            run_id=run_id,
            complete=True,
            observed_at=11.0,
            evidence={"fixture": True},
        )
        repository.finish_run(run_id, status="succeeded", finished_at=12.0)

        after = planner.plan(sources=(source,), repository=repository)
        assert before.plan_id != after.plan_id
        assert "current_snapshot_id" not in before.operation("source:a").parameters
        assert "current_snapshot_id" in after.operation("source:a").parameters
        assert adapter.calls == []


def test_dry_run_executes_exact_plan_shape_without_repository_mutation(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter()
    source = _source("a")
    request = SyncRequest(dry_run=True, max_concurrency=1)

    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,), adapters=AdapterRegistry((adapter,)))
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
        assert repository.artifact_keys() == ()
        assert repository.metadata.operations_for_source(SourceId("a")) == ()


def test_executor_enforces_requested_concurrency_bound(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter(delay_seconds=0.02)
    sources = (_source("a"), _source("b"), _source("c"))

    with Repository(tmp_path) as repository:
        engine = Engine(repository, sources, adapters=AdapterRegistry((adapter,)))
        result = asyncio.run(engine.sync(SyncRequest(max_concurrency=2)))
        assert result.ok
        assert adapter.max_active == 2
        assert sorted(adapter.calls) == ["a", "b", "c"]


def test_failed_dependency_blocks_derived_operation_and_persists_adapter_producer(tmp_path: Path) -> None:
    adapter = RecordingHttpAdapter(fail_ids={"a"})
    task = DependentTask()
    source = _source("a")

    with Repository(tmp_path) as repository:
        engine = Engine(
            repository,
            (source,),
            adapters=AdapterRegistry((adapter,)),
            derived_tasks=(task,),
        )
        result = asyncio.run(engine.sync())
        statuses = {operation.operation_key: operation.status for operation in result.execution.operations}
        assert statuses == {"derived:dependent": "blocked", "source:a": "failed"}
        assert task.calls == 0
        assert result.ok is False
        assert result.repository_run_id is not None
        persisted = repository.metadata.operations_for_run(result.repository_run_id)
        source_operation = next(operation for operation in persisted if operation.subject == "a")
        derived_operation = next(operation for operation in persisted if operation.subject == "dependent")
        assert source_operation.producer.producer_id == "efloud:http"
        assert source_operation.producer.version == "7"
        assert derived_operation.status == "cancelled"
        assert derived_operation.details["failed_dependencies"] == ["source:a"]


def test_runtime_storage_layout_does_not_affect_plan_identity(tmp_path: Path) -> None:
    source = RsyncSource(
        id="mirror",
        url="rsync://example.test/module",
        local_subpath="mirror",
    )
    with Repository(tmp_path) as repository:
        default = Engine(repository, (source,)).plan()
        alternate = Engine(
            repository,
            (source,),
            runtime=EngineRuntime(
                root=tmp_path,
                http_dir="alternate-http",
                cache_dir="alternate-cache",
                mirrors_dir="alternate-mirrors",
            ),
        ).plan()
    assert default.plan_id == alternate.plan_id


def test_source_definition_remains_declarative_data_only() -> None:
    field_names = {item.name for item in fields(HttpSource)}
    assert not field_names & {"client", "session", "adapter", "transport", "repository"}
