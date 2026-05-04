"""Health-check route.

Returns a fixed payload including the short git SHA so the frontend
build can show "you're running commit abc1234" without needing a build
step.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache

from fastapi import APIRouter


router = APIRouter(prefix="/api", tags=["health"])


@lru_cache(maxsize=1)
def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode("ascii")
            .strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "commit": _git_sha()}
