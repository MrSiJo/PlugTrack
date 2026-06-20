# backend/tests/services/test_telegram_car_resolution.py
"""Tests for resolve_car_for_message — the per-message bot car resolver.

Rules under test (spec §4):
1. Exactly one active car  -> CarResolution(kind="auto", car_id=<id>)
2. 2+ active + caption matching one active car name  -> kind="matched"
3. 2+ active + no caption  -> kind="prompt", active_cars has both
4. Caption uniquely matching ONLY an archived car  -> kind="matched" (archived)
5. Zero active cars  -> kind="none"
6. Ambiguous caption (matches 2 active cars)  -> kind="prompt"
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from plugtrack.models import Car, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_user(s) -> int:
    user = User(username="tester", password_hash="x")
    s.add(user)
    await s.flush()
    return user.id


async def _add_car(s, *, user_id: int, make: str, model: str,
                   name: str | None = None, active: bool = True) -> Car:
    car = Car(
        user_id=user_id,
        make=make,
        model=model,
        name=name,
        battery_kwh=58.0,
        nominal_efficiency_mi_per_kwh=4.2,
        provider="manual",
        active=active,
    )
    s.add(car)
    await s.flush()
    return car


# ---------------------------------------------------------------------------
# Rule 1 — single active car => auto
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_active_car_is_auto(test_sessionmaker):
    from plugtrack.services.telegram_ingest import resolve_car_for_message, CarResolution

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        car = await _add_car(s, user_id=uid, make="Cupra", model="Born")
        await s.commit()
        car_id = car.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption=None)

    assert isinstance(result, CarResolution)
    assert result.kind == "auto"
    assert result.car_id == car_id


@pytest.mark.asyncio
async def test_single_active_car_ignores_caption(test_sessionmaker):
    """Even if caption is present, 1 active car -> auto (caption not needed)."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message, CarResolution

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        car = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Daily")
        await s.commit()
        car_id = car.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="Home 11001mi")

    assert result.kind == "auto"
    assert result.car_id == car_id


# ---------------------------------------------------------------------------
# Rule 2 — 2+ active + caption uniquely matching one active car
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_caption_matches_name_active(test_sessionmaker):
    """Caption contains the car's name => matched."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message, CarResolution

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        born = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Born")
        _formentor = await _add_car(s, user_id=uid, make="Cupra", model="Formentor", name="Formentor")
        await s.commit()
        born_id = born.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="Home Born 11001mi")

    assert result.kind == "matched"
    assert result.car_id == born_id


@pytest.mark.asyncio
async def test_caption_matches_make_model(test_sessionmaker):
    """Caption contains make+model string => matched."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        born = await _add_car(s, user_id=uid, make="Cupra", model="Born")
        _formentor = await _add_car(s, user_id=uid, make="Cupra", model="Formentor")
        await s.commit()
        born_id = born.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="Cupra Born 55%")

    assert result.kind == "matched"
    assert result.car_id == born_id


@pytest.mark.asyncio
async def test_caption_match_is_case_insensitive(test_sessionmaker):
    """Matching is case-insensitive."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        born = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Daily Driver")
        _other = await _add_car(s, user_id=uid, make="Tesla", model="Model 3")
        await s.commit()
        born_id = born.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="daily driver home 80%")

    assert result.kind == "matched"
    assert result.car_id == born_id


# ---------------------------------------------------------------------------
# Rule 3 — 2+ active + no caption => prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_active_no_caption_is_prompt(test_sessionmaker):
    from plugtrack.services.telegram_ingest import resolve_car_for_message, CarResolution

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        c1 = await _add_car(s, user_id=uid, make="Cupra", model="Born")
        c2 = await _add_car(s, user_id=uid, make="Cupra", model="Formentor")
        await s.commit()
        ids = {c1.id, c2.id}

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption=None)

    assert isinstance(result, CarResolution)
    assert result.kind == "prompt"
    assert {c.id for c in result.active_cars} == ids


@pytest.mark.asyncio
async def test_two_active_no_caption_prompt_lists_active_only(test_sessionmaker):
    """Archived cars do NOT appear in the prompt list."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        c1 = await _add_car(s, user_id=uid, make="Cupra", model="Born")
        c2 = await _add_car(s, user_id=uid, make="Cupra", model="Formentor")
        _archived = await _add_car(s, user_id=uid, make="VW", model="ID.3", active=False)
        await s.commit()
        active_ids = {c1.id, c2.id}

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption=None)

    assert result.kind == "prompt"
    assert {c.id for c in result.active_cars} == active_ids


# ---------------------------------------------------------------------------
# Rule 4 — caption uniquely matches an archived car (active-first, then archive)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_archived_car_matched_when_two_active_no_active_match(test_sessionmaker):
    """With 2 active cars and a caption that matches only an archived car => matched.

    Archive-match only applies when there are 2+ active cars (so Rule 1 doesn't
    fire) and none of the active cars matches the caption.
    """
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        archived = await _add_car(s, user_id=uid, make="VW", model="ID.3", active=False)
        _active1 = await _add_car(s, user_id=uid, make="Cupra", model="Born")
        _active2 = await _add_car(s, user_id=uid, make="Cupra", model="Formentor")
        await s.commit()
        archived_id = archived.id

    async with test_sessionmaker() as s:
        # Caption names the archived car specifically; neither active car matches.
        result = await resolve_car_for_message(s, user_id=uid, caption="VW ID.3 home 45%")

    assert result.kind == "matched"
    assert result.car_id == archived_id


@pytest.mark.asyncio
async def test_archived_car_matched_when_zero_active(test_sessionmaker):
    """With zero active cars, a uniquely-matching archived car => matched."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        archived = await _add_car(s, user_id=uid, make="VW", model="ID.3", active=False)
        await s.commit()
        archived_id = archived.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="VW ID.3 55%")

    assert result.kind == "matched"
    assert result.car_id == archived_id


# ---------------------------------------------------------------------------
# Rule 5 — zero active cars => none
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_active_cars_is_none(test_sessionmaker):
    from plugtrack.services.telegram_ingest import resolve_car_for_message, CarResolution

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        await s.commit()

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption=None)

    assert isinstance(result, CarResolution)
    assert result.kind == "none"
    assert result.car_id is None


@pytest.mark.asyncio
async def test_zero_active_but_archived_without_caption_is_none(test_sessionmaker):
    """With 0 active and no caption match, result is none."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        _archived = await _add_car(s, user_id=uid, make="VW", model="ID.3", active=False)
        await s.commit()

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption=None)

    assert result.kind == "none"


# ---------------------------------------------------------------------------
# Rule 6 — ambiguous caption (matches 2+ active cars) => prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ambiguous_caption_is_prompt(test_sessionmaker):
    """Caption 'Cupra' matches both active cars => prompt."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        c1 = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Cupra Born")
        c2 = await _add_car(s, user_id=uid, make="Cupra", model="Formentor", name="Cupra Formentor")
        await s.commit()
        ids = {c1.id, c2.id}

    async with test_sessionmaker() as s:
        # "Cupra" appears in both names
        result = await resolve_car_for_message(s, user_id=uid, caption="Cupra home charge")

    assert result.kind == "prompt"
    assert {c.id for c in result.active_cars} == ids


# ---------------------------------------------------------------------------
# Word-boundary matching regression tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_word_boundary_no_false_positive_airborne(test_sessionmaker):
    """Car named 'Born' must NOT match a caption containing 'airborne'."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        _born = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Born")
        _other = await _add_car(s, user_id=uid, make="Tesla", model="Model 3")
        await s.commit()

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="Took an airborne photo")

    # Should be prompt (no unique match), NOT matched to "Born"
    assert result.kind == "prompt"


@pytest.mark.asyncio
async def test_word_boundary_born_matches_standalone_word(test_sessionmaker):
    """Car named 'Born' MUST match a caption where 'Born' appears as a whole word."""
    from plugtrack.services.telegram_ingest import resolve_car_for_message

    async with test_sessionmaker() as s:
        uid = await _seed_user(s)
        born = await _add_car(s, user_id=uid, make="Cupra", model="Born", name="Born")
        _other = await _add_car(s, user_id=uid, make="Tesla", model="Model 3")
        await s.commit()
        born_id = born.id

    async with test_sessionmaker() as s:
        result = await resolve_car_for_message(s, user_id=uid, caption="Born home 12000mi")

    assert result.kind == "matched"
    assert result.car_id == born_id


# ---------------------------------------------------------------------------
# IngestContext — pending_car_choice field exists
# ---------------------------------------------------------------------------

def test_ingest_context_has_pending_car_choice():
    """IngestContext must have the pending_car_choice dict field."""
    from plugtrack.services.telegram_ingest import IngestContext
    ctx = IngestContext(
        telegram=None,
        sessionmaker=None,
        extractor=None,
        resolve_target=lambda: (1, 1),
        allowed_user_ids=set(),
    )
    assert hasattr(ctx, "pending_car_choice")
    assert isinstance(ctx.pending_car_choice, dict)
    assert ctx.pending_car_choice == {}
