from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from efloud.catalog.protocol import Catalog
from efloud.json_types import json_mapping_or_none
from efloud.metadata_envelopes import (
    dataset_specifications_payload,
    decode_dataset_specifications,
    decode_source_definition_history,
)
from efloud.repository_models import ProducerRef

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject
    from efloud.repository_models import (
        ArtifactKey,
        ContentId,
        DatasetId,
        DatasetSpecification,
        DatasetSpecificationId,
        ObservationId,
        OperationId,
        RunId,
        SourceDefinitionRevision,
        SourceDefinitionRevisionId,
        SourceId,
        TreeEntry,
        TreeId,
    )


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: SourceId
    definition: JsonObject
    revision_id: SourceDefinitionRevisionId = field(init=False)
    revisions: tuple[SourceDefinitionRevision, ...] = field(init=False)

    def __post_init__(self) -> None:
        """Decode and canonicalize source-definition revision history."""
        definition, revision_id, revisions = decode_source_definition_history(
            self.source_id,
            self.definition,
        )
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "revisions", revisions)


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: RunId
    started_at: float
    finished_at: float | None
    status: str
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: OperationId
    run_id: RunId
    source_id: SourceId | None
    kind: str
    subject: str
    started_at: float
    finished_at: float | None
    status: str
    parameters: JsonObject
    details: JsonObject

    @property
    def producer(self) -> ProducerRef:
        raw = json_mapping_or_none(self.parameters.get("producer"))
        if raw is None:
            msg = f"Operation {self.operation_id} has no producer metadata."
            raise ValueError(msg)
        return ProducerRef.from_mapping(raw)


@dataclass(frozen=True, slots=True)
class MaterializationRecord:
    content_id: ContentId
    kind: str
    path: str
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class DatasetMemberRecord:
    artifact_key: ArtifactKey
    observation_id: ObservationId
    content_id: ContentId
    role: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    dataset_id: DatasetId
    content_identity: str
    created_at: float
    definition: JsonObject
    metadata: JsonObject
    members: tuple[DatasetMemberRecord, ...]
    specifications: tuple[DatasetSpecification, ...] = ()
    specification_id: DatasetSpecificationId = field(init=False)

    def __post_init__(self) -> None:
        """Canonicalize dataset specifications and their derived metadata."""
        _definition, decoded = decode_dataset_specifications(self.definition)
        merged = {str(item.specification_id): item for item in decoded}
        merged.update({str(item.specification_id): item for item in self.specifications})
        ordered = tuple(sorted(merged.values(), key=lambda item: str(item.specification_id)))
        canonical_definition = dict(ordered[0].definition)
        canonical_metadata = json_mapping_or_none(canonical_definition.get("metadata"))
        object.__setattr__(self, "definition", canonical_definition)
        object.__setattr__(self, "metadata", dict(canonical_metadata) if canonical_metadata is not None else {})
        object.__setattr__(self, "specifications", ordered)
        object.__setattr__(self, "specification_id", ordered[0].specification_id)

    def with_specifications(
        self,
        specifications: Iterable[DatasetSpecification],
    ) -> DatasetRecord:
        return type(self)(
            dataset_id=self.dataset_id,
            content_identity=self.content_identity,
            created_at=self.created_at,
            definition=self.definition,
            metadata=self.metadata,
            members=self.members,
            specifications=(*self.specifications, *tuple(specifications)),
        )

    def storage_definition(self) -> JsonObject:
        return dataset_specifications_payload(
            self.definition,
            existing=self.specifications,
        )


class LegacyMetadataStore(Protocol):
    """Temporary persistence capabilities awaiting Git/tree-layout replacement."""

    def record_materialization(
        self,
        *,
        content_id: ContentId,
        kind: str,
        path: str,
        metadata: JsonObject,
    ) -> None: ...

    def materializations_for(self, content_id: ContentId) -> tuple[MaterializationRecord, ...]: ...

    def record_tree(self, tree_id: TreeId, entries: Iterable[TreeEntry], *, created_at: float) -> None: ...

    def tree_entries(self, tree_id: TreeId) -> tuple[TreeEntry, ...]: ...


class MetadataStore(Catalog, LegacyMetadataStore, Protocol):
    """Temporary combined SQLite contract during the infrastructure cutover."""


__all__ = [
    "DatasetMemberRecord",
    "DatasetRecord",
    "LegacyMetadataStore",
    "MaterializationRecord",
    "MetadataStore",
    "OperationRecord",
    "RunRecord",
    "SourceRecord",
]
