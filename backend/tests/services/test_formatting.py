"""Tests for services/formatting.py helpers."""
from __future__ import annotations

import pytest

from plugtrack.services.formatting import format_currency


def test_format_currency_typical_pence():
    assert format_currency(4210) == "£42.10"


def test_format_currency_zero():
    assert format_currency(0) == "£0.00"


def test_format_currency_small_amount():
    assert format_currency(99) == "£0.99"


def test_format_currency_negative():
    # Negative pence should render with a minus sign, not blow up.
    result = format_currency(-500)
    assert "-" in result
    assert "5.00" in result


def test_format_currency_non_gbp_fallback():
    # Non-GBP currencies get a symbol-less decimal representation.
    result = format_currency(4210, currency="EUR")
    assert "42.10" in result


def test_format_currency_default_is_gbp():
    assert format_currency(100) == "£1.00"
