# backend/tests/settings/test_catalogue_workflow_keys.py
import pytest
from plugtrack.settings.catalogue import CATALOGUE
from plugtrack.settings.seeds import seed_defaults

NEW = {
    "public_base_url": ("string", "display"),
    "openai_input_price_per_1k_pence": ("float", "openai"),
    "openai_output_price_per_1k_pence": ("float", "openai"),
}


def test_keys_present_with_types_and_groups():
    by_key = {e.key: e for e in CATALOGUE}
    for key, (vtype, group) in NEW.items():
        assert key in by_key, f"{key} missing"
        assert by_key[key].value_type == vtype
        assert by_key[key].group_name == group
        assert by_key[key].default_value is None


@pytest.mark.asyncio
async def test_seed_inserts_new_keys(test_sessionmaker):
    from sqlalchemy import select
    from plugtrack.models import Setting
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
        rows = {r.key for r in (await s.execute(select(Setting))).scalars().all()}
    for key in NEW:
        assert key in rows
