"""Unit tests for the Car model (no DB required)."""
from __future__ import annotations

from plugtrack.models.car import Car


def test_display_name_prefers_name_then_make_model():
    c = Car(make="Cupra", model="Born", battery_kwh=58, nominal_efficiency_mi_per_kwh=3.5, user_id=1)
    assert c.display_name == "Cupra Born"
    c.name = "Daily"
    assert c.display_name == "Daily"


def test_max_ac_kw_column_exists_and_nullable():
    """Car model must have a nullable max_ac_kw Float column."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import Float

    mapper = sa_inspect(Car)
    col = mapper.columns["max_ac_kw"]
    assert col.nullable is True
    assert isinstance(col.type, Float)


def test_max_dc_kw_column_exists_and_nullable():
    """Car model must have a nullable max_dc_kw Float column."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import Float

    mapper = sa_inspect(Car)
    col = mapper.columns["max_dc_kw"]
    assert col.nullable is True
    assert isinstance(col.type, Float)


def test_max_kw_fields_default_to_none():
    """max_ac_kw and max_dc_kw are None when not set."""
    c = Car(make="Cupra", model="Born", battery_kwh=58, nominal_efficiency_mi_per_kwh=3.5, user_id=1)
    assert c.max_ac_kw is None
    assert c.max_dc_kw is None


def test_max_kw_fields_can_be_set():
    """max_ac_kw and max_dc_kw can be assigned float values."""
    c = Car(make="Cupra", model="Born", battery_kwh=58, nominal_efficiency_mi_per_kwh=3.5,
            user_id=1, max_ac_kw=11.0, max_dc_kw=160.0)
    assert c.max_ac_kw == 11.0
    assert c.max_dc_kw == 160.0
