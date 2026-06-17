import httpx
import pytest

from plugtrack.services.openai_admin import (
    ModelInfo,
    OpenAIAuthError,
    filter_vision_models,
    list_vision_models,
    pick_recommended,
    validate_key,
)

RAW_IDS = [
    "gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-mini", "gpt-5-mini",
    "gpt-5-nano", "gpt-5.3-codex", "gpt-5-codex-mini", "gpt-4o", "dall-e-3",
]


def test_filter_keeps_gpt5_excludes_codex_and_non_gpt5():
    out = filter_vision_models(RAW_IDS)
    assert "gpt-4o" not in out and "dall-e-3" not in out
    assert not any("codex" in m for m in out)
    assert all(m.startswith("gpt-5") for m in out)
    # mini/nano surface before the rest
    assert out.index("gpt-5-nano") < out.index("gpt-5.5")
    assert out.index("gpt-5-mini") < out.index("gpt-5.5")


def test_pick_recommended_prefers_cheapest_mini():
    assert pick_recommended(filter_vision_models(RAW_IDS)) == "gpt-5-nano"
    assert pick_recommended(["gpt-5.5", "gpt-5.4"]) == "gpt-5.5"  # no mini -> first
    assert pick_recommended([]) is None


@pytest.mark.asyncio
async def test_list_vision_models_parses_and_marks_recommended():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer sk-x"
        return httpx.Response(200, json={"data": [{"id": i} for i in RAW_IDS]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        models = await list_vision_models("sk-x", client=c)
    ids = [m.id for m in models]
    assert "gpt-5.3-codex" not in ids
    rec = [m.id for m in models if m.recommended]
    assert rec == ["gpt-5-nano"]
    assert isinstance(models[0], ModelInfo)


@pytest.mark.asyncio
async def test_list_vision_models_raises_on_401():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(OpenAIAuthError):
            await list_vision_models("sk-bad", client=c)


@pytest.mark.asyncio
async def test_validate_key_returns_ok_and_count():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-5.5"}, {"id": "gpt-4o"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ok, detail = await validate_key("sk-x", client=c)
    assert ok and "2" in detail
