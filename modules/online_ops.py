from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd


REQUIRED_CLOUD_SECRETS = [
    "APP_ENV",
    "APP_PASSWORD",
    "AUTH_ALLOWED_EMAILS",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
]
OPTIONAL_CLOUD_SECRETS = [
    "SMTP_USE_TLS",
    "ALPHA_VANTAGE_API_KEY",
]
SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "smtp_username",
    "smtp_password",
)
SAFE_SECRET_REFERENCE_KEYS = {"api_key_secret_ref"}


def secret_status_rows(
    secret_lookup: Callable[[str], Optional[str]],
    app_env: str,
    optional_names: Optional[list[str]] = None,
) -> list[dict]:
    optional = optional_names or OPTIONAL_CLOUD_SECRETS
    rows = []
    for name in REQUIRED_CLOUD_SECRETS:
        rows.append(_secret_status_row(name, "Pflicht", secret_lookup))
    for name in optional:
        rows.append(_secret_status_row(name, "Optional", secret_lookup))

    if app_env != "cloud":
        for row in rows:
            row["cloud_required_now"] = False
    return rows


def build_health_report(base_dir: Path, config: dict, app_env: str, version: dict) -> list[dict]:
    base_dir = Path(base_dir)
    checks = [
        {
            "bereich": "Environment",
            "status": "OK" if app_env in {"local", "cloud"} else "WARN",
            "detail": f"APP_ENV={app_env}",
        },
        {
            "bereich": "Version",
            "status": "OK",
            "detail": str(version.get("version", "unbekannt")),
        },
        {
            "bereich": "Updates Cloud",
            "status": "OK" if app_env == "cloud" else "LOCAL",
            "detail": "Cloud deaktiviert lokale Updates" if app_env == "cloud" else "Lokal verfuegbar",
        },
        {
            "bereich": "Orders",
            "status": "OK",
            "detail": "Keine Orders, keine Broker-Ausfuehrung",
        },
        {
            "bereich": "Trading Safety",
            "status": "OK"
            if not config.get("trading_safety", {}).get("live_trading_enabled", False)
            else "WARN",
            "detail": "Live-Trading aus",
        },
    ]
    for label, rel_path in [
        ("Config", "config.json"),
        ("Version-Datei", "version.json"),
        ("Logs", config.get("logs_dir", "logs")),
        ("Reports", config.get("reports_dir", "reports")),
        ("Data", "data"),
    ]:
        path = base_dir / str(rel_path)
        checks.append(
            {
                "bereich": label,
                "status": "OK" if path.exists() else "INFO",
                "detail": _path_detail(path),
            }
        )
    return checks


def build_cloud_backup(
    base_dir: Path,
    config: dict,
    workspace_store,
    email: str,
    app_env: str,
) -> dict:
    topics = _df_records(_safe_store_call(workspace_store.list_topics, email))
    watchlists = _df_records(_safe_store_call(workspace_store.list_watchlists, email))
    symbols = _df_records(_safe_store_call(workspace_store.list_watchlist_symbols, email))
    return {
        "schema": "analyse_market_sensei_cut_cloud_backup_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_env": app_env,
        "email": email,
        "config": sanitize_config_for_backup(config),
        "workspace": {
            "watchlists": watchlists,
            "watchlist_symbols": symbols,
            "saved_topics": topics,
        },
    }


def restore_cloud_backup(
    backup: dict,
    workspace_store,
    email: str,
    replace_watchlists: bool = False,
) -> dict:
    if backup.get("schema") != "analyse_market_sensei_cut_cloud_backup_v1":
        raise ValueError("Backup-Schema ist nicht kompatibel.")

    workspace = backup.get("workspace", {}) or {}
    watchlists = workspace.get("watchlists", []) or []
    symbols = workspace.get("watchlist_symbols", []) or []

    if replace_watchlists:
        existing = _safe_store_call(workspace_store.list_watchlists, email)
        if not existing.empty:
            for watchlist_id in existing["id"].dropna().astype(str).tolist():
                workspace_store.delete_watchlist(email, watchlist_id)

    id_map = {}
    created_watchlists = 0
    for row in watchlists:
        old_id = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        new_id = workspace_store.save_watchlist(
            email=email,
            name=name,
            category=str(row.get("category", "Eigene Ideen")).strip() or "Eigene Ideen",
            pinned=bool(row.get("pinned", False)),
        )
        if old_id:
            id_map[old_id] = new_id
        created_watchlists += 1

    created_symbols = 0
    for row in symbols:
        old_watchlist_id = str(row.get("watchlist_id", "")).strip()
        watchlist_id = id_map.get(old_watchlist_id)
        if not watchlist_id:
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        workspace_store.add_watchlist_symbol(
            email=email,
            watchlist_id=watchlist_id,
            ticker=ticker,
            category=str(row.get("category", "Eigene Ideen")).strip() or "Eigene Ideen",
            note=str(row.get("note", "") or ""),
            pinned=bool(row.get("pinned", False)),
        )
        created_symbols += 1

    return {
        "watchlists": created_watchlists,
        "symbols": created_symbols,
    }


def select_config_backup_fields(backup: dict) -> dict:
    config = backup.get("config", {}) or {}
    allowed = [
        "dashboard_symbols",
        "sector_rotation_symbols",
        "sector_rotation_categories",
        "watchlist",
        "watchlist_categories",
        "benchmark",
        "risk_management",
        "score_model",
        "workspace",
        "tracking",
        "data",
    ]
    return {key: _remove_redacted(config[key]) for key in allowed if key in config}


def sanitize_config_for_backup(config: dict) -> dict:
    return _sanitize(config)


def write_monitoring_event(
    base_dir: Path,
    event_type: str,
    payload: Optional[dict] = None,
    actor: str = "system",
) -> Path:
    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "online_ops.jsonl"
    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "event_type": event_type,
        "actor": actor,
        "payload": payload or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_monitoring_log(base_dir: Path, max_lines: int = 80) -> str:
    path = Path(base_dir) / "logs" / "online_ops.jsonl"
    if not path.exists():
        return "Noch kein Online-Betrieb-Log vorhanden."
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[-max_lines:])


def summarize_error_logs(base_dir: Path, max_lines: int = 80) -> dict:
    log_dir = Path(base_dir) / "logs"
    candidates = [
        log_dir / "app.log",
        log_dir / "update_log.txt",
        log_dir / "evening_analysis.log",
        log_dir / "online_ops.jsonl",
        log_dir / "trading_safety_audit.jsonl",
    ]
    lines = []
    error_count = 0
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines()[-max_lines:]:
            if any(marker in line.lower() for marker in ["error", "exception", "traceback", "failed"]):
                error_count += 1
            lines.append(f"{path.name}: {line}")
    return {
        "error_count": error_count,
        "recent": "\n".join(lines[-max_lines:]) if lines else "Noch keine Logs vorhanden.",
    }


def _secret_status_row(
    name: str,
    level: str,
    secret_lookup: Callable[[str], Optional[str]],
) -> dict:
    value = secret_lookup(name) or os.getenv(name)
    present = bool(str(value or "").strip())
    return {
        "secret": name,
        "level": level,
        "present": present,
        "cloud_required_now": level == "Pflicht",
        "status": "OK" if present else ("FEHLT" if level == "Pflicht" else "Optional"),
        "value": "gesetzt" if present else "",
    }


def _path_detail(path: Path) -> str:
    if not path.exists():
        return f"{path} fehlt oder wird bei Bedarf erstellt"
    if path.is_file():
        return f"{path.name}, {path.stat().st_size} bytes"
    try:
        count = sum(1 for _ in path.iterdir())
    except OSError:
        count = 0
    return f"{path.name}/, {count} Eintraege"


def _df_records(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    safe = frame.copy()
    for column in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[column]):
            safe[column] = safe[column].astype(str)
    return json.loads(safe.to_json(orient="records", date_format="iso"))


def _safe_store_call(func, *args) -> pd.DataFrame:
    try:
        return func(*args)
    except Exception:
        return pd.DataFrame()


def _sanitize(value, key: str = ""):
    key_lower = str(key).lower()
    if key_lower in SAFE_SECRET_REFERENCE_KEYS:
        return value
    if any(part in key_lower for part in SENSITIVE_KEY_PARTS):
        if value in (None, "", [], {}):
            return value
        return "<redacted>"
    if isinstance(value, dict):
        return {item_key: _sanitize(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _remove_redacted(value):
    if value == "<redacted>":
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_item = _remove_redacted(item)
            if cleaned_item is None:
                continue
            cleaned[key] = cleaned_item
        return cleaned
    if isinstance(value, list):
        return [item for item in (_remove_redacted(item) for item in value) if item is not None]
    return value
