"""VIN input validation on the car create/update request models.

Real VINs are alphanumeric (e.g. ``VSSZZZK19SP001843``), so the request
models must reject any VIN containing path-traversal or other
non-alphanumeric characters before it is ever stored.
"""

from __future__ import annotations

import pytest
from plugtrack.api.routes.cars import CarCreateRequest, CarUpdateRequest
from pydantic import ValidationError

_BASE_CREATE = dict(
    make="Cupra",
    model="Born",
    battery_kwh=59.0,
    nominal_efficiency_mi_per_kwh=3.5,
)


def test_create_accepts_real_alphanumeric_vin():
    car = CarCreateRequest(vin="VSSZZZK19SP001843", **_BASE_CREATE)
    assert car.vin == "VSSZZZK19SP001843"


def test_create_accepts_none_vin():
    assert CarCreateRequest(vin=None, **_BASE_CREATE).vin is None


@pytest.mark.parametrize(
    "bad",
    ["../../../etc/passwd", "ABC/../X", "ABC_DEF", "ABC DEF", "ABC.DEF", "ABC-123", "../x"],
)
def test_create_rejects_non_alphanumeric_vin(bad):
    with pytest.raises(ValidationError):
        CarCreateRequest(vin=bad, **_BASE_CREATE)


def test_update_rejects_traversal_vin():
    with pytest.raises(ValidationError):
        CarUpdateRequest(vin="../../secret")


def test_update_accepts_alphanumeric_vin():
    assert CarUpdateRequest(vin="WVWZZZ1KZAW000001").vin == "WVWZZZ1KZAW000001"
