from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


DEFAULT_TRADING_SAFETY = {
    "enabled": True,
    "live_trading_enabled": False,
    "sandbox_required": True,
    "paper_api_first": True,
    "order_preview_required": True,
    "two_click_confirmation_required": True,
    "hard_approval_required": True,
    "automatic_orders_allowed": False,
    "kill_switch_active": True,
    "daily_loss_limit_enabled": True,
    "daily_loss_limit_pct": 1.0,
    "daily_loss_limit_amount": 0.0,
    "audit_log_enabled": True,
    "audit_log_path": "logs/trading_safety_audit.jsonl",
    "default_connection_mode": "sandbox_paper",
    "allowed_connection_modes": ["sandbox_paper"],
    "description": (
        "Sicherheits-Gate fuer spaetere Broker-Anbindung. "
        "Live-Ausfuehrung bleibt aus, bis Sandbox, Vorschau, 2-Klick-Freigabe, "
        "Limits und Audit-Log hart erfuellt sind."
    ),
}


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    status: str
    reasons: list[str]
    required_steps: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def trading_safety_config(config: dict | None) -> dict:
    safety = DEFAULT_TRADING_SAFETY.copy()
    safety.update((config or {}).get("trading_safety", {}) or {})
    return safety


def safety_checklist(config: dict | None) -> list[dict]:
    safety = trading_safety_config(config)
    return [
        {
            "check": "Sandbox/Paper-API zuerst",
            "required": True,
            "active": bool(safety.get("sandbox_required")) and bool(safety.get("paper_api_first")),
            "status": "Pflicht",
        },
        {
            "check": "Live-Trading global aus",
            "required": True,
            "active": not bool(safety.get("live_trading_enabled")),
            "status": "Blockiert",
        },
        {
            "check": "Order-Vorschau verpflichtend",
            "required": True,
            "active": bool(safety.get("order_preview_required")),
            "status": "Pflicht",
        },
        {
            "check": "2-Klick-Bestaetigung verpflichtend",
            "required": True,
            "active": bool(safety.get("two_click_confirmation_required")),
            "status": "Pflicht",
        },
        {
            "check": "Kill-Switch aktiv",
            "required": True,
            "active": bool(safety.get("kill_switch_active")),
            "status": "Blockiert",
        },
        {
            "check": "Tagesverlustlimit aktiv",
            "required": True,
            "active": bool(safety.get("daily_loss_limit_enabled")),
            "status": f"{float(safety.get('daily_loss_limit_pct', 0.0)):.2f}%",
        },
        {
            "check": "Audit-Log aktiv",
            "required": True,
            "active": bool(safety.get("audit_log_enabled")),
            "status": "Pflicht",
        },
        {
            "check": "Automatische Orders gesperrt",
            "required": True,
            "active": not bool(safety.get("automatic_orders_allowed")),
            "status": "Nie automatisch",
        },
    ]


def evaluate_trading_request(
    config: dict | None,
    request: Optional[dict] = None,
    confirmation_step_1: bool = False,
    confirmation_step_2: bool = False,
    hard_approval: bool = False,
) -> SafetyDecision:
    safety = trading_safety_config(config)
    request = request or {}
    reasons: list[str] = []
    required_steps = [
        "Sandbox/Paper-API verwenden",
        "Order-Vorschau erzeugen",
        "2-Klick-Bestaetigung ausfuehren",
        "Kill-Switch pruefen",
        "Tagesverlustlimit pruefen",
        "Audit-Log schreiben",
        "Harte manuelle Freigabe einholen",
    ]

    if not bool(safety.get("enabled", True)):
        reasons.append("Trading-Safety ist deaktiviert.")
    if not bool(safety.get("live_trading_enabled", False)):
        reasons.append("Live-Trading ist global deaktiviert.")
    if bool(safety.get("kill_switch_active", True)):
        reasons.append("Kill-Switch ist aktiv.")
    if bool(request.get("automatic", False)):
        reasons.append("Automatische Orders sind niemals erlaubt.")
    if bool(safety.get("automatic_orders_allowed", False)):
        reasons.append("Config darf automatische Orders nicht erlauben.")

    connection_mode = str(request.get("connection_mode") or safety.get("default_connection_mode", "sandbox_paper"))
    allowed_modes = [str(mode) for mode in safety.get("allowed_connection_modes", ["sandbox_paper"])]
    if bool(safety.get("sandbox_required", True)) and connection_mode not in allowed_modes:
        reasons.append("Nur Sandbox/Paper-API ist als erster Schritt erlaubt.")

    if bool(safety.get("order_preview_required", True)) and not bool(request.get("preview_created", False)):
        reasons.append("Order-Vorschau fehlt.")
    if bool(safety.get("two_click_confirmation_required", True)) and not (confirmation_step_1 and confirmation_step_2):
        reasons.append("2-Klick-Bestaetigung fehlt.")
    if bool(safety.get("hard_approval_required", True)) and not hard_approval:
        reasons.append("Harte manuelle Freigabe fehlt.")
    if bool(safety.get("daily_loss_limit_enabled", True)) and not bool(request.get("daily_loss_checked", False)):
        reasons.append("Tagesverlustlimit wurde nicht geprueft.")
    if bool(safety.get("audit_log_enabled", True)) and not bool(request.get("audit_logged", False)):
        reasons.append("Audit-Log-Eintrag fehlt.")

    allowed = not reasons
    return SafetyDecision(
        allowed=allowed,
        status="allowed" if allowed else "blocked",
        reasons=reasons,
        required_steps=required_steps,
    )


def build_order_preview(
    ticker: str,
    side: str,
    quantity: float,
    order_type: str,
    limit_price: float | None = None,
    stop_price: float | None = None,
    account_type: str = "papertrading",
) -> dict:
    return {
        "preview_id": str(uuid4()),
        "ticker": str(ticker or "").strip().upper(),
        "side": str(side or "").strip().lower(),
        "quantity": float(quantity or 0),
        "order_type": str(order_type or "market").strip().lower(),
        "limit_price": None if limit_price is None else float(limit_price),
        "stop_price": None if stop_price is None else float(stop_price),
        "account_type": account_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "execution_state": "preview_only",
        "note": "Vorschau-only. Keine Order, keine Broker-API, keine Ausfuehrung.",
    }


def write_audit_event(
    base_dir: Path,
    config: dict | None,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
    actor: str = "local",
) -> Path:
    safety = trading_safety_config(config)
    path = Path(safety.get("audit_log_path", "logs/trading_safety_audit.jsonl"))
    if not path.is_absolute():
        path = base_dir / path
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": str(uuid4()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "event_type": event_type,
        "payload": payload or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
    return path


def read_audit_log(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return "Noch kein Trading-Safety-Audit vorhanden."
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[-max_lines:])
