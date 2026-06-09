from __future__ import annotations

import os
from typing import Any, Optional


VALID_APP_ENVS = {"local", "cloud"}


def get_app_env(secrets: Optional[Any] = None) -> str:
    raw_value = os.getenv("APP_ENV")
    if not raw_value and secrets is not None:
        raw_value = _read_secret(secrets, "APP_ENV")
    env = str(raw_value or "local").strip().lower()
    return env if env in VALID_APP_ENVS else "local"


def is_cloud_env(app_env: Optional[str] = None, secrets: Optional[Any] = None) -> bool:
    env = app_env or get_app_env(secrets)
    return env == "cloud"


def _read_secret(secrets: Any, key: str) -> Optional[str]:
    try:
        value = secrets.get(key)
    except Exception:
        return None
    if value is None:
        return None
    return str(value)
