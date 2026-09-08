from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.json_types import json_mapping_or_none
from efloud.repository_models import (
    DatasetSpecification,
    DatasetSpecificationId,
    SourceDefinitionRevision,
    SourceDefinitionRevisionId,
    SourceId,
    stable_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonArray, JsonObject

_SOURCE_HISTORY_MARKER = "_efloud_source_definition_history"
_DATASET_SPECIFICATIONS_MARKER = "_efloud_dataset_specifications"
_ENVELOPE_VERSION = 1


def source_definition_revision_id(
    source_id: SourceId | str,
    definition: JsonObject,
) -> SourceDefinitionRevisionId:
    return SourceDefinitionRevisionId(
        stable_id(
            "source-definition",
            {"source_id": str(source_id), "definition": definition},
        )
    )


def _source_revision_payload(revision: SourceDefinitionRevision) -> JsonObject:
    return {
        "revision_id": str(revision.revision_id),
        "definition": dict(revision.definition),
    }


def decode_source_definition_history(
    source_id: SourceId | str,
    payload: JsonObject,
) -> tuple[JsonObject, SourceDefinitionRevisionId, tuple[SourceDefinitionRevision, ...]]:
    marker = payload.get(_SOURCE_HISTORY_MARKER)
    if marker != _ENVELOPE_VERSION:
        revision_id = source_definition_revision_id(source_id, payload)
        revision = SourceDefinitionRevision(revision_id=revision_id, definition=dict(payload))
        return dict(payload), revision_id, (revision,)

    raw_revisions = payload.get("revisions")
    current_raw = payload.get("current_revision_id")
    if not isinstance(raw_revisions, list) or not isinstance(current_raw, str):
        msg = "Malformed source-definition history envelope."
        raise TypeError(msg)

    revisions: list[SourceDefinitionRevision] = []
    for raw_revision in raw_revisions:
        mapping = json_mapping_or_none(raw_revision)
        if mapping is None:
            msg = "Malformed source-definition revision."
            raise ValueError(msg)
        revision_id = mapping.get("revision_id")
        definition = json_mapping_or_none(mapping.get("definition"))
        if not isinstance(revision_id, str) or definition is None:
            msg = "Malformed source-definition revision."
            raise ValueError(msg)
        expected = source_definition_revision_id(source_id, dict(definition))
        if revision_id != str(expected):
            msg = f"Source-definition revision identity mismatch: {revision_id!r}."
            raise ValueError(msg)
        revisions.append(
            SourceDefinitionRevision(
                revision_id=SourceDefinitionRevisionId(revision_id),
                definition=dict(definition),
            )
        )

    by_id = {str(revision.revision_id): revision for revision in revisions}
    current = by_id.get(current_raw)
    if current is None:
        msg = f"Unknown current source-definition revision: {current_raw!r}."
        raise ValueError(msg)
    ordered = tuple(sorted(by_id.values(), key=lambda item: str(item.revision_id)))
    return dict(current.definition), current.revision_id, ordered


def source_definition_history_payload(
    source_id: SourceId | str,
    definition: JsonObject,
    *,
    existing: Iterable[SourceDefinitionRevision] = (),
) -> JsonObject:
    revision_id = source_definition_revision_id(source_id, definition)
    revisions = {str(item.revision_id): item for item in existing}
    revisions[str(revision_id)] = SourceDefinitionRevision(
        revision_id=revision_id,
        definition=dict(definition),
    )
    serialized: JsonArray = []
    serialized.extend(
        _source_revision_payload(revision)
        for revision in sorted(revisions.values(), key=lambda item: str(item.revision_id))
    )
    return {
        _SOURCE_HISTORY_MARKER: _ENVELOPE_VERSION,
        "current_revision_id": str(revision_id),
        "revisions": serialized,
    }


def dataset_specification_id(definition: JsonObject) -> DatasetSpecificationId:
    return DatasetSpecificationId(stable_id("dataset-specification", definition))


def _dataset_specification_payload(specification: DatasetSpecification) -> JsonObject:
    return {
        "specification_id": str(specification.specification_id),
        "definition": dict(specification.definition),
    }


def decode_dataset_specifications(
    payload: JsonObject,
) -> tuple[JsonObject, tuple[DatasetSpecification, ...]]:
    marker = payload.get(_DATASET_SPECIFICATIONS_MARKER)
    if marker != _ENVELOPE_VERSION:
        specification = DatasetSpecification(
            specification_id=dataset_specification_id(payload),
            definition=dict(payload),
        )
        return dict(payload), (specification,)

    raw_specifications = payload.get("specifications")
    if not isinstance(raw_specifications, list) or not raw_specifications:
        msg = "Malformed dataset-specification envelope."
        raise ValueError(msg)

    specifications: dict[str, DatasetSpecification] = {}
    for raw_specification in raw_specifications:
        mapping = json_mapping_or_none(raw_specification)
        if mapping is None:
            msg = "Malformed dataset specification."
            raise ValueError(msg)
        specification_id = mapping.get("specification_id")
        definition = json_mapping_or_none(mapping.get("definition"))
        if not isinstance(specification_id, str) or definition is None:
            msg = "Malformed dataset specification."
            raise ValueError(msg)
        expected = dataset_specification_id(dict(definition))
        if specification_id != str(expected):
            msg = f"Dataset specification identity mismatch: {specification_id!r}."
            raise ValueError(msg)
        specifications[specification_id] = DatasetSpecification(
            specification_id=DatasetSpecificationId(specification_id),
            definition=dict(definition),
        )

    ordered = tuple(sorted(specifications.values(), key=lambda item: str(item.specification_id)))
    return dict(ordered[0].definition), ordered


def dataset_specifications_payload(
    definition: JsonObject,
    *,
    existing: Iterable[DatasetSpecification] = (),
) -> JsonObject:
    specification_id = dataset_specification_id(definition)
    specifications = {str(item.specification_id): item for item in existing}
    specifications[str(specification_id)] = DatasetSpecification(
        specification_id=specification_id,
        definition=dict(definition),
    )
    serialized: JsonArray = []
    serialized.extend(
        _dataset_specification_payload(specification)
        for specification in sorted(
            specifications.values(),
            key=lambda item: str(item.specification_id),
        )
    )
    return {
        _DATASET_SPECIFICATIONS_MARKER: _ENVELOPE_VERSION,
        "specifications": serialized,
    }


__all__ = [
    "dataset_specification_id",
    "dataset_specifications_payload",
    "decode_dataset_specifications",
    "decode_source_definition_history",
    "source_definition_history_payload",
    "source_definition_revision_id",
]
