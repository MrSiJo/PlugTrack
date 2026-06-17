"""List + validate OpenAI models for the screenshot-extraction dropdown.

`GET /v1/models` validates the API key and lists model ids without spending
tokens. We surface only vision-capable gpt-5 chat models (exclude `codex`),
mini/nano first, and flag a recommended cheapest-mini default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

MODELS_URL = "https://api.openai.com/v1/models"
# Cheapest-first preference among mini/nano families.
_MINI_PREFERENCE = ("gpt-5-nano", "gpt-5.4-nano", "gpt-5-mini", "gpt-5.4-mini")


class OpenAIAuthError(Exception):
    """Raised when OpenAI rejects the API key (401)."""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    recommended: bool


def filter_vision_models(ids: list[str]) -> list[str]:
    keep = [i for i in ids if i.startswith("gpt-5") and "codex" not in i]
    # mini/nano first (they're cheaper and the preferred default), then the rest;
    # alphabetical within each band for stable ordering.
    minis = sorted(i for i in keep if "mini" in i or "nano" in i)
    rest = sorted(i for i in keep if "mini" not in i and "nano" not in i)
    return minis + rest


def pick_recommended(ids: list[str]) -> Optional[str]:
    for pref in _MINI_PREFERENCE:
        if pref in ids:
            return pref
    mini = next((i for i in ids if "mini" in i or "nano" in i), None)
    if mini:
        return mini
    return ids[0] if ids else None


async def _get_model_ids(api_key: str, *, client: Optional[httpx.AsyncClient]) -> list[str]:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.get(
            MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}
        )
        if resp.status_code == 401:
            raise OpenAIAuthError("OpenAI rejected the API key (401)")
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]
    finally:
        if owns:
            await client.aclose()


async def list_vision_models(
    api_key: str, *, client: Optional[httpx.AsyncClient] = None
) -> list[ModelInfo]:
    ids = filter_vision_models(await _get_model_ids(api_key, client=client))
    rec = pick_recommended(ids)
    return [ModelInfo(id=i, recommended=(i == rec)) for i in ids]


async def validate_key(
    api_key: str, *, client: Optional[httpx.AsyncClient] = None
) -> tuple[bool, str]:
    try:
        ids = await _get_model_ids(api_key, client=client)
    except OpenAIAuthError:
        return False, "invalid key (401)"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"
    return True, f"{len(ids)} models"
