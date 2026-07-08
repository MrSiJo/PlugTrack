# backend/tests/services/test_telegram_ingest.py
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from plugtrack.services.screenshot_extraction import (
    Extraction,
    ExtractionResult,
    Usage,
    parse_extraction,
)
from plugtrack.services.telegram_ingest import (
    IngestContext,
    MergedSession,
    _parse_caption,
    _summarise,
    handle_callback,
    handle_photo,
    handle_text,
)

FX = Path(__file__).parent.parent / "fixtures" / "screenshots"


class FakeTelegram:
    def __init__(self, files: dict[str, bytes]):
        self._files = files
        self.sent: list[dict] = []
        self.answered: list[str] = []

    async def get_file_path(self, file_id):  # noqa: ANN001
        return file_id

    async def download_file(self, file_path):  # noqa: ANN001
        return self._files[file_path]

    async def send_message(self, *, chat_id, text, reply_markup=None):  # noqa: ANN001
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    async def answer_callback(self, callback_id, text=""):  # noqa: ANN001
        self.answered.append(callback_id)


def _ctx(tg, test_sessionmaker, car_id, user_id):
    async def extractor(image_bytes: bytes):
        # Map fake file bytes -> the matching fixture by content tag.
        name = image_bytes.decode()
        return ExtractionResult(
            extraction=parse_extraction(json.loads((FX / name).read_text())),
            usage=Usage(None, None, None),
        )

    return IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )


@pytest.mark.asyncio
async def test_two_photos_one_session_staged_and_committed(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    files = {"osprey.json": b"osprey.json", "mycupra_1240.json": b"mycupra_1240.json"}
    tg = FakeTelegram(files)
    ctx = _ctx(tg, test_sessionmaker, car_id, user_id)

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="osprey.json")
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=2, file_id="mycupra_1240.json")

    # The last reply should summarise ONE merged session and offer Save.
    last = tg.sent[-1]
    assert "9.78" in last["text"] or "Osprey" in last["text"]
    assert last["reply_markup"] is not None

    # Simulate the Save button callback.
    await handle_callback(ctx, from_id=111, callback_id="cb1", data="save", chat_id=9)

    from sqlalchemy import select
    from plugtrack.models import ChargingSession
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].total_cost_pence_override == 851
    assert rows[0].start_soc == 56


@pytest.mark.asyncio
async def test_photo_extraction_failure_replies_to_user(test_sessionmaker, seeded_user_car):
    """PLUG-H1: an OpenAI/extractor error must not silently swallow the photo."""
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({"x": b"x"})

    async def boom(image_bytes: bytes):
        raise RuntimeError("openai down")

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=boom,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x")
    assert tg.sent, "user must get a failure reply"
    assert "resend" in tg.sent[-1]["text"].lower()


@pytest.mark.asyncio
async def test_photo_download_failure_replies_to_user(test_sessionmaker, seeded_user_car):
    """PLUG-H1: a Telegram file-download error must reply, not vanish."""
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({})  # file_id missing -> download_file raises KeyError

    async def extractor(image_bytes: bytes):  # pragma: no cover - never reached
        raise AssertionError("should not be called")

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="missing")
    assert tg.sent, "user must get a failure reply"
    assert "resend" in tg.sent[-1]["text"].lower()


# ---- caption parsing (photo path) -------------------------------------------

def test_parse_caption_home_and_mileage():
    assert _parse_caption("Home 11001mi") == ("Home", 11001.0, "mi")


def test_parse_caption_mileage_only_with_unit():
    assert _parse_caption("11056mi") == (None, 11056.0, "mi")


def test_parse_caption_bare_number_defaults_to_setting():
    # No unit -> leave unit None so commit applies the distance_unit setting (mi).
    assert _parse_caption("11056") == (None, 11056.0, None)


def test_parse_caption_explicit_km():
    assert _parse_caption("home 20000km") == ("home", 20000.0, "km")


def test_parse_caption_location_word_only():
    assert _parse_caption("home") == ("home", None, None)


def test_parse_caption_handles_thousands_separator_and_miles_word():
    assert _parse_caption("Home 11,001 miles") == ("Home", 11001.0, "mi")


def test_parse_caption_empty():
    assert _parse_caption("") == (None, None, None)


def _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction):
    async def extractor(image_bytes: bytes):
        return ExtractionResult(extraction=extraction, usage=Usage(None, None, None))

    return IngestContext(
        telegram=tg, sessionmaker=test_sessionmaker, extractor=extractor,
        resolve_target=lambda: (user_id, car_id), allowed_user_ids={111})


def _ex_photo(**kw):
    base = dict(source="mycupra", has_cost=False, energy_kwh=None, cost_total_pence=None,
                cost_per_kwh_pence=None, start_at="2026-06-17T16:36:00", end_at="2026-06-18T07:06:00",
                soc_start=75, soc_end=79, location_name=None, location_address=None,
                network=None, peak_kw=2.0, confidence=0.89)
    base.update(kw)
    return Extraction(**base)


async def _staged_extracted(test_sessionmaker, user_id):
    from sqlalchemy import select
    from plugtrack.models import ScreenshotImport
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport).where(
            ScreenshotImport.user_id == user_id,
            ScreenshotImport.status == "staged"))).scalars().all()
    return [r.extracted for r in rows]


@pytest.mark.asyncio
async def test_photo_caption_fills_home_and_mileage(test_sessionmaker, seeded_user_car):
    # MyCupra-style photo (no location), caption "Home 11001mi" -> location_name
    # "Home" + odometer 11001 mi on the staged extraction.
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, _ex_photo())
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x",
                       caption="Home 11001mi")
    ext = (await _staged_extracted(test_sessionmaker, user_id))[0]
    assert ext["location_name"] == "Home"
    assert ext["odometer"] == 11001.0
    assert ext["odometer_unit"] == "mi"


@pytest.mark.asyncio
async def test_photo_caption_mileage_does_not_clobber_found_location(test_sessionmaker, seeded_user_car):
    # Tesla-style photo (has a location), caption "11056mi" -> keep the found
    # location, still capture the odometer.
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({"x": b"x"})
    ext_in = _ex_photo(source="tesla", has_cost=True, cost_total_pence=972,
                       location_name="Dart Farm Village, Exeter", soc_start=None, soc_end=None,
                       network="Tesla")
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, ext_in)
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption="11056mi")
    ext = (await _staged_extracted(test_sessionmaker, user_id))[0]
    assert ext["location_name"] == "Dart Farm Village, Exeter"
    assert ext["odometer"] == 11056.0
    assert ext["odometer_unit"] == "mi"


@pytest.mark.asyncio
async def test_disallowed_user_ignored(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({"osprey.json": b"osprey.json"})
    ctx = _ctx(tg, test_sessionmaker, car_id, user_id)
    await handle_photo(ctx, from_id=999, chat_id=9, message_id=1, file_id="osprey.json")
    assert tg.sent == []  # silently ignored


def _merged():
    return MergedSession(
        start_at=dt.datetime(2026, 6, 12, 14, 25, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 12, 14, 40, tzinfo=dt.timezone.utc),
        energy_kwh=9.78, cost_total_pence=851, cost_per_kwh_pence=87.0,
        soc_start=56, soc_end=70, location_name="Land's End", location_address="TR19 7AA",
        network="Osprey", peak_kw=40.0, confidence=0.95, source_kinds=["mycupra", "osprey"])


def test_summarise_shows_all_fields():
    text = _summarise([_merged()])
    # Itemised card: kWh, cost (£8.51), SoC range, network/location — raw
    # confidence is no longer printed.
    for token in ("9.78", "8.51", "56", "70", "Osprey", "Land's End", "TR19 7AA"):
        assert token in text
    assert "conf 0." not in text


def test_summarise_shows_actual_charge_time():
    from plugtrack.services.screenshot_correlation import MergedSession
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 15, 18, 27, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 16, 5, 59, tzinfo=dt.timezone.utc),
        energy_kwh=None, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name=None, location_address=None,
        network=None, peak_kw=2.0, confidence=0.95,
        actual_charge_seconds=3 * 3600 + 49 * 60, source_kinds=["mycupra"])
    text = _summarise([m])
    assert "3h49m" in text


def test_summarise_shows_efficiency_and_location():
    from plugtrack.services.screenshot_correlation import MergedSession
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 16, 6, 59, tzinfo=dt.timezone.utc),
        energy_kwh=9.3, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name="home", location_address=None,
        network=None, peak_kw=2.0, confidence=0.95, source_kinds=["mycupra", "granny"])
    text = _summarise([m])
    assert "home" in text.lower()
    assert "%" in text  # efficiency or SoC percentage shown


def test_summarise_itemised_home_card():
    from plugtrack.services.screenshot_correlation import MergedSession
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 18, 13, 17, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 18, 17, 15, tzinfo=dt.timezone.utc),
        energy_kwh=None, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name="Home", location_address=None,
        network=None, peak_kw=2.0, confidence=0.95,
        actual_charge_seconds=14280, source_kinds=["mycupra", "granny"])
    text = _summarise([m], projected=[{
        "kwh_added": 9.22, "cost_pence": 178, "cost_basis": "location_rate",
        "odometer_km": 11110 * 1.609344}], unit="mi")
    assert "🏠 Home" in text
    assert "— 18 Jun 13:17" in text
    assert "🔋 67 → 80%" in text
    assert "⚡ 9.22 kWh in 3h58m" in text
    assert "💷 £1.78" in text
    assert "19p/kWh" in text
    assert "location rate" in text
    assert "location_rate" not in text
    assert "🛞 11,110 mi" in text
    assert "conf 0." not in text


def test_summarise_dc_uses_plug_emoji_and_basis_label():
    from plugtrack.services.screenshot_correlation import MergedSession
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 13, 8, 43, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 13, 9, 1, tzinfo=dt.timezone.utc),
        energy_kwh=37.9, cost_total_pence=1706, cost_per_kwh_pence=None,
        soc_start=None, soc_end=None, location_name="Lifton", location_address=None,
        network="Tesla", peak_kw=62.0, confidence=0.95, source_kinds=["tesla"])
    text = _summarise([m], projected=[{
        "kwh_added": 37.9, "cost_pence": 1706, "cost_basis": "override_total"}], unit="mi")
    assert "🔌" in text
    assert "💷 £17.06" in text
    assert "manual total" in text


def test_summarise_low_confidence_warning():
    from plugtrack.services.screenshot_correlation import MergedSession
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 18, 13, 17, tzinfo=dt.timezone.utc),
        end_at=None, energy_kwh=9.3, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name="Home", location_address=None,
        network=None, peak_kw=2.0, confidence=0.5, source_kinds=["mycupra"])
    text = _summarise([m], projected=[{
        "kwh_added": 9.3, "cost_pence": 178, "cost_basis": "location_rate"}], unit="mi")
    assert "⚠ low confidence" in text


class FakeTgText:
    def __init__(self): self.sent = []
    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_handle_text_runs_health_for_command():
    tg = FakeTgText()
    called = {}
    async def health(from_id):
        called["id"] = from_id
        from plugtrack.services.telegram_health import HealthReport, Check
        return HealthReport(checks=[Check("Telegram", True, "ok")], all_ok=True, usage_this_month=None)
    ctx = IngestContext(telegram=tg, sessionmaker=None, extractor=None,
                        resolve_target=lambda: (1, 1), allowed_user_ids={111}, health_check=health)
    await handle_text(ctx, from_id=111, chat_id=9, text="/test")
    assert called["id"] == 111 and tg.sent and "Telegram" in tg.sent[-1]


@pytest.mark.asyncio
async def test_handle_text_disallowed_ignored():
    tg = FakeTgText()
    ctx = IngestContext(telegram=tg, sessionmaker=None, extractor=None,
                        resolve_target=lambda: (1, 1), allowed_user_ids={111})
    await handle_text(ctx, from_id=999, chat_id=9, text="/test")
    assert tg.sent == []


def _ex_text(**kw):
    base = dict(source="text", has_cost=False, energy_kwh=9.3, cost_total_pence=None,
                cost_per_kwh_pence=None, start_at="2026-06-15T19:27:00", end_at=None,
                soc_start=None, soc_end=None, location_name="home", location_address=None,
                network=None, peak_kw=None, confidence=0.9)
    base.update(kw)
    return Extraction(**base)


class FakeTg2:
    def __init__(self): self.sent = []
    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append({"text": text, "kb": reply_markup})


@pytest.mark.asyncio
async def test_handle_text_charge_note_stages_and_cards(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTg2()

    async def extractor_text(text):
        return ExtractionResult(extraction=_ex_text(), usage=Usage(10, 10, 0))

    ctx = IngestContext(
        telegram=tg, sessionmaker=test_sessionmaker, extractor=None,
        resolve_target=lambda: (user_id, None),  # production-realistic: no car_id
        allowed_user_ids={111},
        extractor_text=extractor_text)
    await handle_text(ctx, from_id=111, chat_id=9, text="home 9.3kwh 8h31m")
    assert tg.sent and tg.sent[-1]["kb"] is not None       # confirm card with buttons
    assert "9.3" in tg.sent[-1]["text"] or "home" in tg.sent[-1]["text"]


@pytest.mark.asyncio
async def test_handle_text_non_charge_falls_back_to_help(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTg2()

    async def extractor_text(text):
        return ExtractionResult(extraction=_ex_text(energy_kwh=None, location_name=None,
                                start_at=None, confidence=0.0), usage=Usage(5, 5, 0))

    ctx = IngestContext(
        telegram=tg, sessionmaker=test_sessionmaker, extractor=None,
        resolve_target=lambda: (user_id, car_id), allowed_user_ids={111},
        extractor_text=extractor_text)
    await handle_text(ctx, from_id=111, chat_id=9, text="how much have I spent?")
    assert tg.sent and tg.sent[-1]["kb"] is None           # help line, no buttons
    assert "screenshot" in tg.sent[-1]["text"].lower()


@pytest.mark.asyncio
async def test_non_charge_text_routes_to_usage_answerer():
    import plugtrack.services.telegram_ingest as ti

    sent = []

    class FakeTg:
        async def send_message(self, *, chat_id, text, reply_markup=None):
            sent.append(text); return 1

    async def fake_text_extractor(text):
        # charge-parse proves NOT usable (a question, not a charge note)
        from plugtrack.services.screenshot_extraction import Extraction, ExtractionResult, Usage
        e = Extraction(source="text", has_cost=False, energy_kwh=None, cost_total_pence=None,
                       cost_per_kwh_pence=None, start_at=None, end_at=None, soc_start=None,
                       soc_end=None, location_name=None, location_address=None, network=None,
                       peak_kw=None, confidence=0.0)
        return ExtractionResult(extraction=e, usage=Usage(None, None, None))

    async def fake_answerer(question):
        return (f"answer to: {question}", object())

    ctx = ti.IngestContext(
        telegram=FakeTg(), sessionmaker=None, extractor=None,
        resolve_target=lambda: (1, 1), allowed_user_ids={42},
        extractor_text=fake_text_extractor, usage_answerer=fake_answerer,
    )
    await ti.handle_text(ctx, from_id=42, chat_id=99, text="how much did I spend this month?")
    assert any("answer to: how much did I spend this month?" in s for s in sent)


@pytest.mark.asyncio
async def test_usage_answerer_error_is_graceful():
    import plugtrack.services.telegram_ingest as ti
    sent = []

    class FakeTg:
        async def send_message(self, *, chat_id, text, reply_markup=None):
            sent.append(text); return 1

    async def fake_text_extractor(text):
        from plugtrack.services.screenshot_extraction import Extraction, ExtractionResult, Usage
        e = Extraction(source="text", has_cost=False, energy_kwh=None, cost_total_pence=None,
                       cost_per_kwh_pence=None, start_at=None, end_at=None, soc_start=None,
                       soc_end=None, location_name=None, location_address=None, network=None,
                       peak_kw=None, confidence=0.0)
        return ExtractionResult(extraction=e, usage=Usage(None, None, None))

    async def boom(question):
        raise RuntimeError("openai down")

    ctx = ti.IngestContext(
        telegram=FakeTg(), sessionmaker=None, extractor=None,
        resolve_target=lambda: (1, 1), allowed_user_ids={42},
        extractor_text=fake_text_extractor, usage_answerer=boom,
    )
    await ti.handle_text(ctx, from_id=42, chat_id=99, text="anything")
    assert any("couldn't answer" in s.lower() for s in sent)


@pytest.mark.asyncio
async def test_charge_parse_failure_falls_through_to_usage():
    # A charge-parse (extractor_text) exception must NOT black-hole the message:
    # it should fall through to the usage answerer. Regression: an OpenAI 400 on
    # the unguarded charge-parse call left the user with no reply at all.
    import plugtrack.services.telegram_ingest as ti
    sent = []

    class FakeTg:
        async def send_message(self, *, chat_id, text, reply_markup=None):
            sent.append(text); return 1

    async def boom_extractor(text):
        raise RuntimeError("openai 400 invalid schema")

    async def fake_answerer(question):
        return (f"answer: {question}", object())

    ctx = ti.IngestContext(
        telegram=FakeTg(), sessionmaker=None, extractor=None,
        resolve_target=lambda: (1, 1), allowed_user_ids={42},
        extractor_text=boom_extractor, usage_answerer=fake_answerer,
    )
    await ti.handle_text(ctx, from_id=42, chat_id=99, text="how many miles this month?")
    assert any("answer: how many miles this month?" in s for s in sent)


def test_summarise_renders_odometer_and_warning():
    import datetime as dt
    from plugtrack.services.screenshot_correlation import MergedSession
    from plugtrack.services.telegram_ingest import _summarise
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc),
        end_at=None, energy_kwh=9.3, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=None, soc_end=None, location_name="home", location_address=None,
        network=None, peak_kw=None, confidence=0.9,
    )
    # normal reading
    text = _summarise([m], projected=[{"kwh_added": 9.3, "cost_pence": 179,
                       "cost_basis": "home_rate", "odometer_km": 12345 * 1.609344}], unit="mi")
    assert "🛞 12,345 mi" in text
    # regressing reading
    warn = _summarise([m], projected=[{"kwh_added": 9.3, "cost_pence": 179,
                       "cost_basis": "home_rate", "odometer_km": 10000 * 1.609344,
                       "odometer_regressed": True, "existing_max_km": 12000 * 1.609344}], unit="mi")
    assert "🛞 10,000 mi" in warn
    assert "⚠" in warn and "12,000 mi" in warn


@pytest.mark.asyncio
async def test_save_reply_includes_committed_cost(test_sessionmaker, seeded_user_car):
    from sqlalchemy import select
    from plugtrack.models import Location, Setting
    from plugtrack.settings.seeds import seed_defaults

    user_id, car_id = seeded_user_car

    # Seed defaults + a home rate, plus a "home" location for rate-based costing.
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        row = (await s.execute(select(Setting).where(
            Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = "19.26"
        s.add(Location(user_id=user_id, name="Home", is_free=False,
                       default_cost_per_kwh_p=19.26, centroid_lat=0.0, centroid_lng=0.0,
                       radius_m=50))
        await s.commit()

    tg = FakeTelegram({})

    async def extractor_text(text):
        return ExtractionResult(extraction=_ex_text(), usage=Usage(10, 10, 0))

    ctx = IngestContext(
        telegram=tg, sessionmaker=test_sessionmaker, extractor=None,
        resolve_target=lambda: (user_id, None),  # production-realistic: no car_id
        allowed_user_ids={111},
        extractor_text=extractor_text)

    # Stage a home charge note, then Save it.
    await handle_text(ctx, from_id=111, chat_id=9, text="home 9.3kwh 8h31m")
    await handle_callback(ctx, from_id=111, callback_id="cb1", data="save", chat_id=9)

    reply = tg.sent[-1]["text"]
    assert "Saved 1 session(s)." in reply
    assert "£" in reply


# ---------------------------------------------------------------------------
# Task 6: multi-car carpick flow
# ---------------------------------------------------------------------------

async def _seed_two_cars(test_sessionmaker):
    """Insert a User + two active Cars; return (user_id, car_id_1, car_id_2)."""
    from plugtrack.models import Car, User
    async with test_sessionmaker() as s:
        user = User(username="bob", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car1 = Car(user_id=user.id, make="Cupra", model="Born",
                   battery_kwh=58.0, nominal_efficiency_mi_per_kwh=4.2,
                   provider="manual", active=True, name="Born")
        car2 = Car(user_id=user.id, make="Tesla", model="Model 3",
                   battery_kwh=75.0, nominal_efficiency_mi_per_kwh=4.5,
                   provider="manual", active=True, name="Model3")
        s.add_all([car1, car2])
        await s.commit()
        await s.refresh(car1)
        await s.refresh(car2)
        return user.id, car1.id, car2.id


@pytest.mark.asyncio
async def test_two_active_cars_no_caption_sends_carpick_keyboard(test_sessionmaker):
    """Two active cars + no caption → carpick keyboard listing both cars, no commit yet."""
    from sqlalchemy import select
    from plugtrack.models import ChargingSession

    user_id, car_id_1, car_id_2 = await _seed_two_cars(test_sessionmaker)
    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id, _ex_photo())

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)

    # Should have sent exactly one message (the carpick keyboard), not a Save/Discard card
    assert len(tg.sent) == 1
    msg = tg.sent[0]
    assert msg["reply_markup"] is not None
    kb = msg["reply_markup"]["inline_keyboard"]
    # One button per car, each with carpick: prefix
    cb_datas = [btn["callback_data"] for row in kb for btn in row]
    assert f"carpick:{car_id_1}" in cb_datas
    assert f"carpick:{car_id_2}" in cb_datas
    # No session committed yet
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_carpick_callback_then_save_commits_with_chosen_car(test_sessionmaker):
    """Tapping carpick:{id} shows Save/Discard card; Save commits with that car_id."""
    from sqlalchemy import select
    from plugtrack.models import ChargingSession

    user_id, car_id_1, car_id_2 = await _seed_two_cars(test_sessionmaker)
    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id, _ex_photo())

    # Send photo → carpick keyboard
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)

    # User taps car2
    await handle_callback(ctx, from_id=111, callback_id="cb_pick", data=f"carpick:{car_id_2}",
                          chat_id=9)

    # Should now show Save/Discard card
    save_card = tg.sent[-1]
    assert save_card["reply_markup"] is not None
    # The Save/Discard keyboard has "save" and "discard" callback_datas
    all_cb = [btn["callback_data"]
              for row in save_card["reply_markup"]["inline_keyboard"]
              for btn in row]
    assert "save" in all_cb
    assert "discard" in all_cb

    # Tap Save
    await handle_callback(ctx, from_id=111, callback_id="cb_save", data="save", chat_id=9)

    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].car_id == car_id_2  # committed with the CHOSEN car


@pytest.mark.asyncio
async def test_second_photo_reuses_pending_car_choice(test_sessionmaker):
    """A second photo before Save should reuse pending_car_choice, not re-prompt."""
    user_id, car_id_1, car_id_2 = await _seed_two_cars(test_sessionmaker)
    tg = FakeTelegram({"x": b"x", "y": b"y"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id, _ex_photo())

    # First photo → carpick
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)
    assert ctx.pending_car_choice.get(9) is None  # not yet set (prompt was sent)

    # User picks car2
    await handle_callback(ctx, from_id=111, callback_id="cb_pick", data=f"carpick:{car_id_2}",
                          chat_id=9)
    assert ctx.pending_car_choice.get(9) == car_id_2

    carpick_msg_count = len(tg.sent)

    # Second photo (different sha) — should NOT re-prompt
    ctx2 = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id,
                     _ex_photo(start_at="2026-06-17T18:00:00"))
    ctx2.pending_car_choice[9] = car_id_2  # carry forward the chosen car
    await handle_photo(ctx2, from_id=111, chat_id=9, message_id=2, file_id="y", caption=None)

    # No new carpick keyboard should have been sent (message count grew only by the confirm card)
    new_msgs = tg.sent[carpick_msg_count:]
    carpick_msgs = [m for m in new_msgs
                    if m.get("reply_markup") and any(
                        btn["callback_data"].startswith("carpick:")
                        for row in m["reply_markup"]["inline_keyboard"]
                        for btn in row
                    )]
    assert carpick_msgs == []


@pytest.mark.asyncio
async def test_save_clears_pending_car_choice(test_sessionmaker):
    """Save must clear pending_car_choice."""
    user_id, car_id_1, car_id_2 = await _seed_two_cars(test_sessionmaker)
    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id, _ex_photo())

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)
    await handle_callback(ctx, from_id=111, callback_id="cb_pick", data=f"carpick:{car_id_2}",
                          chat_id=9)
    assert ctx.pending_car_choice.get(9) == car_id_2

    await handle_callback(ctx, from_id=111, callback_id="cb_save", data="save", chat_id=9)
    assert ctx.pending_car_choice.get(9) is None


@pytest.mark.asyncio
async def test_discard_clears_pending_car_choice(test_sessionmaker):
    """Discard must clear pending_car_choice."""
    user_id, car_id_1, car_id_2 = await _seed_two_cars(test_sessionmaker)
    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id_1, user_id, _ex_photo())

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)
    await handle_callback(ctx, from_id=111, callback_id="cb_pick", data=f"carpick:{car_id_2}",
                          chat_id=9)
    assert ctx.pending_car_choice.get(9) == car_id_2

    await handle_callback(ctx, from_id=111, callback_id="cb_discard", data="discard", chat_id=9)
    assert ctx.pending_car_choice.get(9) is None


@pytest.mark.asyncio
async def test_zero_active_cars_sends_friendly_message(test_sessionmaker):
    """Zero active cars → friendly message, nothing staged."""
    from sqlalchemy import select
    from plugtrack.models import Car, User, ScreenshotImport

    # Create a user with NO active car
    async with test_sessionmaker() as s:
        user = User(username="carol", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car = Car(user_id=user.id, make="Cupra", model="Born",
                  battery_kwh=58.0, nominal_efficiency_mi_per_kwh=4.2,
                  provider="manual", active=False)  # INACTIVE
        s.add(car)
        await s.commit()
        await s.refresh(car)
        uid, cid = user.id, car.id

    tg = FakeTelegram({"x": b"x"})
    ctx = _stub_ctx(tg, test_sessionmaker, cid, uid, _ex_photo())

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="x", caption=None)

    assert len(tg.sent) == 1
    assert "active car" in tg.sent[0]["text"].lower() or "no active" in tg.sent[0]["text"].lower()
    # Nothing staged
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Task 6 bug fix: text path must resolve car_id (not pass None to commit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_charge_note_save_resolves_car_not_none(test_sessionmaker, seeded_user_car):
    """Primary bug: handle_text with resolve_target returning car_id=None must
    still commit the session with the correct car_id (not raise IntegrityError).
    """
    from sqlalchemy import select
    from plugtrack.models import ChargingSession

    user_id, car_id = seeded_user_car
    tg = FakeTelegram({})

    async def extractor_text(text):
        return ExtractionResult(extraction=_ex_text(), usage=Usage(10, 10, 0))

    # Production-realistic: resolve_target returns (user_id, None) — no car_id.
    ctx = IngestContext(
        telegram=tg, sessionmaker=test_sessionmaker, extractor=None,
        resolve_target=lambda: (user_id, None),
        allowed_user_ids={111},
        extractor_text=extractor_text)

    await handle_text(ctx, from_id=111, chat_id=9, text="home 9.3kwh 8h31m")
    await handle_callback(ctx, from_id=111, callback_id="cb1", data="save", chat_id=9)

    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].car_id == car_id  # must be the seeded car, not None


@pytest.mark.asyncio
async def test_save_after_bot_restart_resolves_car_from_single_active(test_sessionmaker, seeded_user_car):
    """I1 — bot restart: pending_car_choice is cleared (simulating process restart).
    Save must re-resolve from the single active car instead of crashing with IntegrityError.
    """
    from sqlalchemy import select
    from plugtrack.models import ChargingSession

    user_id, car_id = seeded_user_car
    files = {"osprey.json": b"osprey.json"}
    tg = FakeTelegram(files)
    ctx = _ctx(tg, test_sessionmaker, car_id, user_id)

    # Stage a photo (car resolution runs, pending_car_choice is set)
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="osprey.json")

    # Simulate bot restart: clear in-memory state
    ctx.pending_car_choice.clear()
    # Also simulate that resolve_target now returns None for car_id (production reality)
    ctx.resolve_target = lambda: (user_id, None)

    # Tap Save — must re-resolve car from DB
    await handle_callback(ctx, from_id=111, callback_id="cb1", data="save", chat_id=9)

    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].car_id == car_id  # correct car despite pending_car_choice being empty
