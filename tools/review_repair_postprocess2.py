#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, text: str) -> None:
    (ROOT / relative).write_text(text, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    text = read(relative)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:100]!r}")
    write(relative, text.replace(old, new, 1))


def patch_repository_derived() -> None:
    relative = "src/efloud/repository_derived.py"
    text = read(relative)

    text, count = re.subn(
        r"\ndef _record_collection_absence\(.*?\n\ndef _record_collection_entry\(",
        "\n\ndef _record_collection_entry(",
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError("repository_derived: could not remove obsolete 404 absence helper")

    old_404 = '''    error = entry.get("error")
    if status == "error" and error == "404":
        _record_collection_absence(
            repository,
            state=state,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            item_id=item_id,
            relative_path=relative_path,
            locator=locator,
            item_metadata=item_metadata,
            decision=decision,
        )
        return
'''
    new_404 = '''    error = entry.get("error")
    if status == "error" and error == "404":
        state.tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="unresolved",
                metadata={
                    **item_metadata,
                    "error": "enumerated collection member returned 404",
                    "http_status": 404,
                    "reconciliation_state": decision.state,
                },
            )
        )
        state.unresolved_count += 1
        return
'''
    if old_404 not in text:
        raise RuntimeError("repository_derived: enumerated-404 branch did not match")
    text = text.replace(old_404, new_404, 1)

    old_signature = '''    observed_at: float,
    task_name: str,
    decisions: tuple[ReconciliationDecision, ...],
) -> list[ObservationId]:
'''
    new_signature = '''    observed_at: float,
    task_name: str,
    inventory: SourceInventory,
    decisions: tuple[ReconciliationDecision, ...],
) -> list[ObservationId]:
'''
    if old_signature not in text:
        raise RuntimeError("repository_derived: membership-absence signature did not match")
    text = text.replace(old_signature, new_signature, 1)

    old_call = '''            source_id=source_id,
            observed_at=observed_at,
            source_path=decision.previous.source_path,
            metadata={
                "collection_task": task_name,
                "item_id": decision.item_id,
                "reason": "removed-from-complete-enumeration",
'''
    new_call = '''            source_id=source_id,
            inventory=inventory,
            observed_at=observed_at,
            source_path=decision.previous.source_path,
            metadata={
                "collection_task": task_name,
                "item_id": decision.item_id,
                "reason": "removed-from-complete-enumeration",
'''
    if old_call not in text:
        raise RuntimeError("repository_derived: membership absence call did not match")
    text = text.replace(old_call, new_call, 1)

    old_invoke = '''        observed_at=observed_at,
        task_name=task_name,
        decisions=context.reconciliation.decisions,
    )
'''
    new_invoke = '''        observed_at=observed_at,
        task_name=task_name,
        inventory=context.inventory,
        decisions=context.reconciliation.decisions,
    )
'''
    if old_invoke not in text:
        raise RuntimeError("repository_derived: membership absence invocation did not match")
    text = text.replace(old_invoke, new_invoke, 1)
    write(relative, text)


def patch_repository_tests() -> None:
    relative = "tests/unit/test_repository.py"
    text = read(relative)
    old_import = "from efloud.datasets import DatasetDefinition, ExactObservation, Latest, LatestAll, LatestBefore\n"
    new_import = old_import + "from efloud.inventory import InventoryCoverage, SourceInventory\n"
    if old_import not in text:
        raise RuntimeError("test_repository: dataset import did not match")
    text = text.replace(old_import, new_import, 1)

    old_absence = '''        absence = repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
'''
    new_absence = '''        inventory = SourceInventory(
            source_id=source,
            observed_at=102.0,
            coverage=InventoryCoverage(complete=True),
            items=(),
        )
        absence = repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            inventory=inventory,
        )
'''
    if old_absence not in text:
        raise RuntimeError("test_repository: absence fixture did not match")
    text = text.replace(old_absence, new_absence, 1)
    write(relative, text)

    relative = "tests/unit/test_repository_query.py"
    text = read(relative)
    old_import = "from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none\n"
    new_import = "from efloud.inventory import InventoryCoverage, SourceInventory\n" + old_import
    if old_import not in text:
        raise RuntimeError("test_repository_query: json import did not match")
    text = text.replace(old_import, new_import, 1)
    old_absence = '''        repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
'''
    new_absence = '''        inventory = SourceInventory(
            source_id=source,
            observed_at=102.0,
            coverage=InventoryCoverage(complete=True),
            items=(),
        )
        repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            inventory=inventory,
        )
'''
    if old_absence not in text:
        raise RuntimeError("test_repository_query: absence fixture did not match")
    text = text.replace(old_absence, new_absence, 1)
    write(relative, text)


def patch_regression_type_narrowing() -> None:
    relative = "tests/test_review_regressions.py"
    text = read(relative)
    old_import = "from efloud.inventory import InventoryCoverage, InventoryItem, SourceInventory\n"
    new_import = old_import + "from efloud.json_types import json_mapping_or_none\n"
    if old_import not in text:
        raise RuntimeError("review regressions: inventory import did not match")
    text = text.replace(old_import, new_import, 1)
    old_assert = '''        assert absence.observed_at == complete.observed_at
        assert absence.metadata["absence_proof"]["coverage"] == {"scope": [], "complete": True}
'''
    new_assert = '''        assert absence.observed_at == complete.observed_at
        proof = json_mapping_or_none(absence.metadata.get("absence_proof"))
        assert proof is not None
        coverage = json_mapping_or_none(proof.get("coverage"))
        assert coverage == {"scope": [], "complete": True}
'''
    if old_assert not in text:
        raise RuntimeError("review regressions: absence proof assertion did not match")
    text = text.replace(old_assert, new_assert, 1)
    write(relative, text)


def main() -> None:
    patch_repository_derived()
    patch_repository_tests()
    patch_regression_type_narrowing()


if __name__ == "__main__":
    main()
