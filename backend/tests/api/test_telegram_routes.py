import pytest

from tests.api.conftest import csrf_headers


class StubManager:
    async def health(self, requesting_user_id=None):
        from plugtrack.services.telegram_health import Check, HealthReport

        return HealthReport(
            checks=[Check("Telegram", True, "ok")],
            all_ok=True,
            usage_this_month=None,
        )

    async def stop(self):
        # No-op: the route tests swap this in for the real manager, whose
        # stop() is awaited during lifespan shutdown.
        return None


@pytest.mark.asyncio
async def test_telegram_test_returns_report(authed_client, app):
    app.state.telegram_manager = StubManager()
    r = await authed_client.post("/api/telegram/test", headers=csrf_headers(authed_client))
    assert r.status_code == 200
    body = r.json()
    assert body["all_ok"] is True and body["checks"][0]["name"] == "Telegram"


@pytest.mark.asyncio
async def test_openai_models_400_without_key(authed_client):
    r = await authed_client.get("/api/openai/models")
    assert r.status_code == 400
