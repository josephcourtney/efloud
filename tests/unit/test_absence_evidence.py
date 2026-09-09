from __future__ import annotations

import pytest

from efloud.inventory import AbsenceEvidence, InventoryCoverage, SourceInventory
from efloud.repository_models import SourceId

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.mark.small
def test_inventory_absence_requires_complete_coverage() -> None:
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(scope=("aa",), complete=False),
        items=(),
    )

    with pytest.raises(ValueError, match="complete inventory coverage"):
        AbsenceEvidence.from_inventory(inventory, source_path="aa/item")


@pytest.mark.small
def test_inventory_absence_requires_target_inside_scope() -> None:
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(scope=("aa",), complete=True),
        items=(),
    )

    with pytest.raises(ValueError, match="does not establish absence"):
        AbsenceEvidence.from_inventory(inventory, source_path="bb/item")


@pytest.mark.small
def test_direct_negative_requires_exact_target() -> None:
    with pytest.raises(ValueError, match="exact locator or source path"):
        AbsenceEvidence.direct_negative(source_id=SourceId("source"), observed_at=10.0)
