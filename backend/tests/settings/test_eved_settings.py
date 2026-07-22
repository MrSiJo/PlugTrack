from __future__ import annotations

from plugtrack.settings.catalogue import CATALOGUE

_BY_KEY = {e.key: e for e in CATALOGUE}


def test_eved_rate_setting_defined():
    e = _BY_KEY["eved_rate_p_per_mile"]
    assert e.value_type == "float"
    assert e.group_name == "cost"
    assert e.default_value == "3.0"


def test_ved_annual_cost_setting_defined():
    e = _BY_KEY["ved_annual_cost_gbp"]
    assert e.value_type == "float"
    assert e.group_name == "cost"
    assert e.default_value == "200"


def test_ved_renewal_date_setting_defined():
    e = _BY_KEY["ved_renewal_date"]
    assert e.value_type == "string"
    assert e.group_name == "cost"
    assert e.default_value == "07-31"
