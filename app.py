from __future__ import annotations

import hashlib
import json
import hmac
import inspect
import logging
import os
import re
import secrets
import subprocess
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from main import run_evening_analysis
from modules.app_env import get_app_env, is_cloud_env
from modules.auth import AuthStore, send_two_factor_email, send_verification_email
try:
    from modules.auth import send_password_reset_email
except ImportError:
    try:
        from modules.auth import send_auth_code_email
    except ImportError:
        send_auth_code_email = None

    if send_auth_code_email is not None:
        def send_password_reset_email(email: str, code: str, settings: dict):
            return send_auth_code_email(
                email=email,
                code=code,
                settings=settings,
                subject="Analyse Market Sensei Cut - Passwort zuruecksetzen",
                intro="Dein Passwort-Reset-Code fuer Analyse Market Sensei Cut lautet:",
            )
    else:
        def send_password_reset_email(email: str, code: str, settings: dict):
            return send_two_factor_email(email, code, settings)
from modules.broker_router import broker_status, execution_plan, provider_matrix
from modules.backtester import BACKTEST_SETUPS, BacktestSettings, Backtester
from modules.data_provider import DataProvider
from modules.indicators import add_indicators
try:
    from modules.market_regime import evaluate_market_regime, write_market_regime_reports
    MARKET_REGIME_IMPORT_ERROR: Optional[Exception] = None
except ModuleNotFoundError as exc:
    MARKET_REGIME_IMPORT_ERROR = exc

    def evaluate_market_regime(config: dict, analysis_result: dict) -> dict:
        return {
            "issues": [
                "Market-Regime-Modul fehlt im Deployment. Bitte modules/market_regime.py mit hochladen."
            ],
            "contexts": {},
            "summary": pd.DataFrame(),
            "rankings": {},
            "history": pd.DataFrame(),
            "strategy_map": pd.DataFrame(
                columns=["Regime", "Strategy Type", "Description"]
            ),
        }

    def write_market_regime_reports(
        evaluation: dict,
        reports_dir="reports",
    ) -> list[Path]:
        reports_path = Path(reports_dir)
        reports_path.mkdir(parents=True, exist_ok=True)
        paths = [
            reports_path / "market_regime_report.csv",
            reports_path / "regime_history.csv",
            reports_path / "regime_strategy_map.csv",
        ]
        for path in paths:
            pd.DataFrame().to_csv(path, index=False)
        return paths
from modules.online_ops import (
    build_cloud_backup,
    build_health_report,
    read_monitoring_log,
    restore_cloud_backup,
    secret_status_rows,
    select_config_backup_fields,
    summarize_error_logs,
    write_monitoring_event,
)
from modules.portfolio_tracker import PortfolioTracker
from modules.report_generator import list_report_files
from modules.trading_safety import (
    DEFAULT_TRADING_SAFETY,
    build_order_preview,
    evaluate_trading_request,
    read_audit_log,
    safety_checklist,
    trading_safety_config,
    write_audit_event,
)
from modules.updater import (
    apply_code_update,
    create_backup,
    get_current_version,
    inspect_update_files,
    list_backups,
    load_config,
    read_changelog,
    read_update_log,
    restore_latest_backup,
    run_full_update,
    save_config,
)
from modules.workspace_store import (
    DEFAULT_CATEGORIES,
    DEFAULT_WATCHLIST_CATEGORIES,
    WorkspaceStore,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SYSTEM_ALERT_COLOR = "#ff2bd6"
DEV_LOGIN_EMAIL = "dev@local"
DASHBOARD_WATCHLIST_NAME = "Hauptliste"
CHART_SYSTEM_TOOLS = [
    "Linien",
    "Beobachtung",
    "EMA Signale",
    "RSI",
    "Relative Staerke",
    "Fibonacci",
    "Alligator",
    "Order Blocks",
    "Breakouts",
    "Tick-Waves",
    "Volumen",
    "Monat Aufstieg",
    "Monat Abstieg",
]
DEFAULT_DASHBOARD_SYMBOLS = [
    {"label": "SPY", "ticker": "SPY"},
    {"label": "SPX500", "ticker": "^GSPC"},
    {"label": "QQQ", "ticker": "QQQ"},
    {"label": "Nasdaq100", "ticker": "^NDX"},
    {"label": "GLD", "ticker": "GLD"},
    {"label": "Gold", "ticker": "GC=F"},
    {"label": "DAX", "ticker": "^GDAXI"},
]
MARKET_CHART_GROUPS = [
    {
        "title": "SPY / SPX500",
        "symbols": [("SPY", "SPY"), ("SPX500", "^GSPC")],
    },
    {
        "title": "QQQ / Nasdaq100",
        "symbols": [("QQQ", "QQQ"), ("Nasdaq100", "^NDX")],
    },
    {
        "title": "GLD / Gold",
        "symbols": [("GLD", "GLD"), ("Gold", "GC=F")],
    },
    {
        "title": "DAX",
        "symbols": [("DAX", "^GDAXI")],
    },
]
DEFAULT_SECTOR_ROTATION_SYMBOLS = [
    {"label": "S&P 500", "ticker": "SPY", "category": "Breiter Markt"},
    {"label": "Nasdaq 100", "ticker": "QQQ", "category": "Breiter Markt"},
    {"label": "Russell 2000", "ticker": "IWM", "category": "Breiter Markt"},
    {"label": "Technology", "ticker": "XLK", "category": "US Sektoren"},
    {"label": "Financials", "ticker": "XLF", "category": "US Sektoren"},
    {"label": "Industrials", "ticker": "XLI", "category": "US Sektoren"},
    {"label": "Consumer Discretionary", "ticker": "XLY", "category": "US Sektoren"},
    {"label": "Consumer Staples", "ticker": "XLP", "category": "US Sektoren"},
    {"label": "Healthcare", "ticker": "XLV", "category": "US Sektoren"},
    {"label": "Energy", "ticker": "XLE", "category": "US Sektoren"},
    {"label": "Utilities", "ticker": "XLU", "category": "US Sektoren"},
    {"label": "Materials", "ticker": "XLB", "category": "US Sektoren"},
    {"label": "Real Estate", "ticker": "XLRE", "category": "US Sektoren"},
    {"label": "Communication Services", "ticker": "XLC", "category": "US Sektoren"},
    {"label": "Homebuilders / Bau", "ticker": "XHB", "category": "Bau"},
    {"label": "Infrastructure", "ticker": "PAVE", "category": "Bau"},
    {"label": "Semiconductors", "ticker": "SMH", "category": "Themen"},
    {"label": "Gold", "ticker": "GLD", "category": "Rohstoffe"},
    {"label": "Oil", "ticker": "USO", "category": "Rohstoffe"},
    {"label": "Bitcoin", "ticker": "BTC-USD", "category": "Krypto"},
    {"label": "US Dollar Index", "ticker": "DX-Y.NYB", "category": "Waehrung"},
    {"label": "Treasury 1-3Y", "ticker": "SHY", "category": "Treasuries"},
    {"label": "Treasury 3-7Y", "ticker": "IEI", "category": "Treasuries"},
    {"label": "Treasury 7-10Y", "ticker": "IEF", "category": "Treasuries"},
    {"label": "Treasury Yield 5Y", "ticker": "^FVX", "category": "Treasury Yields"},
    {"label": "Treasury Yield 10Y", "ticker": "^TNX", "category": "Treasury Yields"},
]
DEFAULT_SECTOR_ROTATION_CATEGORIES = [
    "Breiter Markt",
    "US Sektoren",
    "Bau",
    "Themen",
    "Rohstoffe",
    "Krypto",
    "Waehrung",
    "Treasuries",
    "Treasury Yields",
]
SECTOR_ROTATION_COMPARISON_GROUPS = [
    {"name": "Tech", "tickers": ["QQQ", "^NDX", "XLK", "SMH"], "risk_profile": "risk_on"},
    {"name": "Finance", "tickers": ["XLF"], "risk_profile": "risk_on"},
    {"name": "Bau", "tickers": ["XHB", "PAVE"], "risk_profile": "risk_on"},
    {"name": "Energie", "tickers": ["XLE", "USO"], "risk_profile": "risk_on"},
    {"name": "Gold", "tickers": ["GLD", "GC=F"], "risk_profile": "risk_off"},
    {"name": "Dollar", "tickers": ["DX-Y.NYB"], "risk_profile": "risk_off"},
    {"name": "Treasuries", "tickers": ["SHY", "IEI", "IEF", "^FVX", "^TNX"], "risk_profile": "risk_off"},
]
RISK_ON_ROTATION_TICKERS = {
    "QQQ",
    "^NDX",
    "IWM",
    "XLK",
    "XLY",
    "XLF",
    "XLI",
    "XHB",
    "PAVE",
    "SMH",
    "XLE",
}
RISK_OFF_ROTATION_TICKERS = {
    "GLD",
    "GC=F",
    "DX-Y.NYB",
    "SHY",
    "IEI",
    "IEF",
    "^FVX",
    "^TNX",
    "XLU",
    "XLP",
    "XLV",
}
COMPAT_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COMPAT_PBKDF2_ITERATIONS = 220_000
COMPAT_RATE_LIMIT = {
    "enabled": True,
    "window_minutes": 15,
    "password_max_failures": 5,
    "two_factor_max_failures": 5,
    "verification_max_failures": 5,
    "registration_max_attempts": 3,
    "two_factor_send_max_attempts": 3,
    "password_reset_send_max_attempts": 3,
    "password_reset_max_failures": 5,
}


def make_key(*parts):
    return "_".join(
        str(p)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "_")
        .replace(":", "_")
        for p in parts
    )


PLOTLY_CHART_SUPPORTS_WIDTH = "width" in inspect.signature(st.plotly_chart).parameters


def render_plotly_chart(fig, key: str, config: Optional[dict] = None) -> None:
    kwargs = {}
    if config is not None:
        kwargs["config"] = config
    if PLOTLY_CHART_SUPPORTS_WIDTH:
        kwargs["width"] = "stretch"
    else:
        kwargs["use_container_width"] = True
    st.plotly_chart(fig, key=key, **kwargs)


def dev_login_available(app_env: str) -> bool:
    return not is_cloud_env(app_env)


def activate_dev_login() -> None:
    st.session_state.authenticated_email = DEV_LOGIN_EMAIL
    st.session_state.authenticated = True
    st.session_state.app_password_ok = True
    st.session_state.dev_login_active = True
    st.session_state.sensitive_unlocked = True
    st.session_state.sensitive_unlocked_until = time.time() + 12 * 60 * 60
    st.session_state.pop("pending_2fa_email", None)
    st.session_state.pop("local_2fa_code", None)


def render_dev_login_button(app_env: str, key_prefix: str) -> None:
    if not dev_login_available(app_env):
        return
    st.markdown(
        "<div class='sensei-dev-panel'>Dev-Zugang: lokale Session sofort entsperren.</div>",
        unsafe_allow_html=True,
    )
    if st.button(
        "Eingeloggt bleiben",
        key=make_key(key_prefix, "dev_login"),
        width="stretch",
        type="primary",
    ):
        activate_dev_login()
        st.success("Dev-Login aktiv.")
        st.rerun()


class CompatAuthResult:
    def __init__(
        self,
        ok: bool,
        message: str,
        email: Optional[str] = None,
        verification_code: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.message = message
        self.email = email
        self.verification_code = verification_code


def ensure_password_reset_backend(store: AuthStore) -> bool:
    if hasattr(store, "create_password_reset_code") and hasattr(store, "reset_password"):
        return True

    store_class = store.__class__
    if not hasattr(store_class, "create_password_reset_code"):
        setattr(store_class, "create_password_reset_code", _compat_create_password_reset_code)
    if not hasattr(store_class, "reset_password"):
        setattr(store_class, "reset_password", _compat_reset_password)
    return hasattr(store, "create_password_reset_code") and hasattr(store, "reset_password")


def _compat_create_password_reset_code(
    self,
    email: str,
    code_minutes: int,
    rate_limit: Optional[dict] = None,
):
    normalized = _compat_normalize_email(email)
    if not COMPAT_EMAIL_RE.match(normalized):
        return CompatAuthResult(False, "Bitte gib eine gueltige E-Mail-Adresse ein.")

    settings = _compat_rate_limit_settings(rate_limit)
    max_attempts = int(
        settings.get(
            "password_reset_send_max_attempts",
            settings.get("two_factor_send_max_attempts", 3),
        )
    )
    if _compat_too_many_recent_attempts(
        self,
        normalized,
        "password_reset_send",
        max_attempts,
        int(settings["window_minutes"]),
    ):
        return CompatAuthResult(
            False,
            "Zu viele Passwort-Reset-Anforderungen. Bitte spaeter erneut versuchen.",
        )

    now = datetime.now()
    con = duckdb.connect(str(self.database_path))
    try:
        _compat_ensure_auth_tables(con)
        existing = con.execute(
            """
            SELECT email, is_verified
            FROM users
            WHERE email = ?
            """,
            [normalized],
        ).fetchone()
        if not existing or not existing[1]:
            _compat_record_auth_attempt(con, normalized, "password_reset_send", False)
            return CompatAuthResult(
                True,
                "Wenn die E-Mail registriert ist, wurde ein Reset-Code vorbereitet.",
                email=normalized,
            )

        code = _compat_create_verification_code()
        salt = _compat_create_salt()
        code_hash = _compat_hash_secret(code, salt)
        expires_at = now + timedelta(minutes=code_minutes)
        con.execute(
            """
            INSERT INTO two_factor_codes VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            [normalized, code_hash, salt, "password_reset", expires_at, now],
        )
        _compat_record_auth_attempt(con, normalized, "password_reset_send", True)
    finally:
        con.close()

    return CompatAuthResult(
        True,
        "Passwort-Reset-Code erstellt.",
        email=normalized,
        verification_code=code,
    )


def _compat_reset_password(
    self,
    email: str,
    code: str,
    new_password: str,
    rate_limit: Optional[dict] = None,
):
    normalized = _compat_normalize_email(email)
    validation = _compat_validate_email_and_password(normalized, new_password)
    if validation:
        return CompatAuthResult(False, validation)

    settings = _compat_rate_limit_settings(rate_limit)
    max_failures = int(
        settings.get(
            "password_reset_max_failures",
            settings.get("verification_max_failures", 5),
        )
    )
    if _compat_too_many_recent_failures(
        self,
        normalized,
        "password_reset",
        max_failures,
        int(settings["window_minutes"]),
    ):
        return CompatAuthResult(False, "Zu viele falsche Reset-Codes. Bitte spaeter erneut versuchen.")

    con = duckdb.connect(str(self.database_path))
    try:
        _compat_ensure_auth_tables(con)
        row = con.execute(
            """
            SELECT code_hash, salt, expires_at
            FROM two_factor_codes
            WHERE email = ? AND purpose = 'password_reset' AND used_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [normalized],
        ).fetchone()
        if not row:
            _compat_record_auth_attempt(con, normalized, "password_reset", False)
            return CompatAuthResult(False, "Kein offener Reset-Code gefunden.")

        code_hash, salt, expires_at = row
        if datetime.now() > expires_at:
            _compat_record_auth_attempt(con, normalized, "password_reset", False)
            return CompatAuthResult(False, "Der Reset-Code ist abgelaufen.")
        if not hmac.compare_digest(_compat_hash_secret(code.strip(), salt), code_hash):
            _compat_record_auth_attempt(con, normalized, "password_reset", False)
            return CompatAuthResult(False, "Der Reset-Code ist falsch.")

        password_salt = _compat_create_salt()
        password_hash = _compat_hash_secret(new_password, password_salt)
        now = datetime.now()
        con.execute(
            """
            UPDATE users
            SET password_hash = ?, salt = ?, is_verified = true, verified_at = COALESCE(verified_at, ?)
            WHERE email = ?
            """,
            [password_hash, password_salt, now, normalized],
        )
        con.execute(
            """
            UPDATE two_factor_codes
            SET used_at = ?
            WHERE email = ? AND purpose = 'password_reset' AND used_at IS NULL
            """,
            [now, normalized],
        )
        _compat_record_auth_attempt(con, normalized, "password_reset", True)
    finally:
        con.close()

    return CompatAuthResult(True, "Passwort wurde aktualisiert. Du kannst dich jetzt anmelden.", normalized)


def _compat_ensure_auth_tables(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS two_factor_codes (
            email VARCHAR NOT NULL,
            code_hash VARCHAR NOT NULL,
            salt VARCHAR NOT NULL,
            purpose VARCHAR NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_attempts (
            email VARCHAR NOT NULL,
            purpose VARCHAR NOT NULL,
            success BOOLEAN NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )


def _compat_recent_attempt_count(
    store,
    email: str,
    purpose: str,
    window_minutes: int,
    success: Optional[bool] = None,
) -> int:
    cutoff = datetime.now() - timedelta(minutes=max(1, int(window_minutes)))
    con = duckdb.connect(str(store.database_path))
    try:
        _compat_ensure_auth_tables(con)
        if success is None:
            return int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM auth_attempts
                    WHERE email = ? AND purpose = ? AND created_at >= ?
                    """,
                    [email, purpose, cutoff],
                ).fetchone()[0]
            )
        return int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM auth_attempts
                WHERE email = ? AND purpose = ? AND success = ? AND created_at >= ?
                """,
                [email, purpose, bool(success), cutoff],
            ).fetchone()[0]
        )
    finally:
        con.close()


def _compat_too_many_recent_attempts(
    store,
    email: str,
    purpose: str,
    max_attempts: int,
    window_minutes: int,
) -> bool:
    if max_attempts <= 0:
        return False
    return _compat_recent_attempt_count(store, email, purpose, window_minutes) >= max_attempts


def _compat_too_many_recent_failures(
    store,
    email: str,
    purpose: str,
    max_failures: int,
    window_minutes: int,
) -> bool:
    if max_failures <= 0:
        return False
    return _compat_recent_attempt_count(
        store,
        email,
        purpose,
        window_minutes,
        success=False,
    ) >= max_failures


def _compat_record_auth_attempt(con, email: str, purpose: str, success: bool) -> None:
    con.execute(
        """
        INSERT INTO auth_attempts VALUES (?, ?, ?, ?)
        """,
        [_compat_normalize_email(email), purpose, bool(success), datetime.now()],
    )


def _compat_rate_limit_settings(rate_limit: Optional[dict]) -> dict:
    settings = COMPAT_RATE_LIMIT.copy()
    if rate_limit:
        settings.update({key: value for key, value in rate_limit.items() if value is not None})
    if not settings.get("enabled", True):
        for key in [
            "password_max_failures",
            "two_factor_max_failures",
            "verification_max_failures",
            "registration_max_attempts",
            "two_factor_send_max_attempts",
            "password_reset_send_max_attempts",
            "password_reset_max_failures",
        ]:
            settings[key] = 0
    return settings


def _compat_normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _compat_validate_email_and_password(email: str, password: str) -> Optional[str]:
    if not COMPAT_EMAIL_RE.match(email):
        return "Bitte gib eine gueltige E-Mail-Adresse ein."
    if len(password) < 10:
        return "Das Passwort muss mindestens 10 Zeichen lang sein."
    if password.lower() == password or password.upper() == password:
        return "Das Passwort braucht Gross- und Kleinbuchstaben."
    if not any(char.isdigit() for char in password):
        return "Das Passwort braucht mindestens eine Zahl."
    return None


def _compat_create_salt() -> str:
    return secrets.token_hex(16)


def _compat_create_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _compat_hash_secret(value: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("utf-8"),
        COMPAT_PBKDF2_ITERATIONS,
    )
    return digest.hex()


def main() -> None:
    st.set_page_config(
        page_title="Analyse Market Sensei Cut",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    apply_responsive_css()

    app_env = get_app_env(st.secrets)
    config = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
    config = inject_runtime_secrets(config)
    if not st.session_state.get("authenticated_email"):
        render_header(app_env=app_env, page="Login")
    if not require_app_password_gate(app_env):
        st.stop()
    if not authenticate(app_env, config):
        st.stop()
    record_online_session_start(config, app_env)

    _ensure_result(config, app_env)
    _refresh_tracking_snapshots(config)
    _sync_alert_history(config)
    page = render_top_navigation(app_env)
    render_header(app_env=app_env, page=page)
    render_account_bar()
    render_mode_banner(config, app_env)
    layout_left, layout_main = st.columns([0.30, 0.70], gap="large")

    with layout_left:
        render_market_price_rail(
            config,
            st.session_state.analysis_result,
            key_prefix="market_price_rail",
        )
    with layout_main:
        render_selected_page(page, config, app_env)
    render_footer()


def render_selected_page(page: str, config: dict, app_env: str) -> None:
    if page == "Heute ansehen":
        render_today_home(config, app_env, key_prefix="today_home")
    elif page == "Workspace":
        render_workspace(config, app_env, key_prefix="workspace")
    elif page == "Dashboard":
        render_dashboard(config, app_env, key_prefix="dashboard")
    elif page == "Watchlist":
        render_watchlist(config, key_prefix="watchlist")
    elif page == "Sektorrotation":
        render_sector_rotation(config, key_prefix="sector_rotation")
    elif page == "Market Regime":
        render_market_regime(config, key_prefix="market_regime")
    elif page == "Backtesting":
        render_backtesting(config, key_prefix="backtesting")
    elif page == "Papertrading":
        render_papertrading(config, key_prefix="papertrading")
    elif page == "Real Money":
        render_real_money(config, key_prefix="real_money")
    elif page == "Reports":
        render_reports(config, key_prefix="reports")
    elif page == "Updates":
        render_updates(config, app_env, key_prefix="updates")
    elif page == "Online-Betrieb":
        render_online_operations(config, app_env, key_prefix="online_ops")
    elif page == "Settings":
        render_settings(app_env, key_prefix="settings")


def inject_runtime_secrets(config: dict) -> dict:
    runtime_config = json.loads(json.dumps(config))
    alpha_vantage_key = get_secret("ALPHA_VANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")
    if alpha_vantage_key:
        runtime_config.setdefault("data", {})["alpha_vantage_api_key"] = alpha_vantage_key
    return runtime_config


def _ensure_result(config: dict, app_env: str) -> None:
    if "analysis_result" not in st.session_state:
        with st.spinner("Lade Kernmarktdaten und berechne Analyse..."):
            st.session_state.analysis_result = _run_full_update_compatible(
                config,
                generate_reports=False,
                include_sector_rotation=False,
            )


def _run_full_update_compatible(
    config: dict,
    generate_reports: bool = False,
    include_sector_rotation: bool = True,
) -> dict:
    kwargs = {"generate_reports": generate_reports}
    try:
        parameters = inspect.signature(run_full_update).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "include_sector_rotation" in parameters:
        kwargs["include_sector_rotation"] = include_sector_rotation
    return run_full_update(config, **kwargs)


def _run_update(
    config: dict,
    generate_reports: bool = False,
    include_sector_rotation: bool = True,
) -> None:
    with st.spinner("Analyse laeuft..."):
        st.session_state.analysis_result = _run_full_update_compatible(
            config,
            generate_reports=generate_reports,
            include_sector_rotation=include_sector_rotation,
        )
        _refresh_tracking_snapshots(config, force=True)
        _sync_alert_history(config, force=True)
    st.success("Analyse aktualisiert.")


def _run_update_with_extra_symbols(config: dict, extra_symbols: list[str]) -> None:
    cleaned_extra = [symbol.strip().upper() for symbol in extra_symbols if symbol.strip()]
    if not cleaned_extra:
        st.warning("Keine Symbole fuer die Analyse gefunden.")
        return

    temporary_config = json.loads(json.dumps(config))
    merged_watchlist = []
    for symbol in list(temporary_config.get("watchlist", [])) + cleaned_extra:
        text = str(symbol).strip().upper()
        if text and text not in merged_watchlist:
            merged_watchlist.append(text)
    temporary_config["watchlist"] = merged_watchlist

    with st.spinner("Eigene Watchlist wird analysiert..."):
        st.session_state.analysis_result = _run_full_update_compatible(
            temporary_config,
            generate_reports=False,
            include_sector_rotation=False,
        )
        _refresh_tracking_snapshots(temporary_config, force=True)
        _sync_alert_history(temporary_config, force=True)
    st.success("Eigene Watchlist analysiert.")


def _tracking_database_path(config: dict) -> Path:
    raw_path = config.get("tracking", {}).get("database_path", "data/portfolio_tracker.duckdb")
    path = Path(raw_path)
    return path if path.is_absolute() else BASE_DIR / path


def _tracker(config: dict) -> PortfolioTracker:
    return PortfolioTracker(_tracking_database_path(config))


def _workspace_database_path(config: dict) -> Path:
    raw_path = config.get("workspace", {}).get("database_path", "data/workspace.duckdb")
    path = Path(raw_path)
    return path if path.is_absolute() else BASE_DIR / path


def _workspace_store(config: dict) -> WorkspaceStore:
    return WorkspaceStore(_workspace_database_path(config))


def record_online_session_start(config: dict, app_env: str) -> None:
    if st.session_state.get("online_session_logged"):
        return
    try:
        write_monitoring_event(
            BASE_DIR,
            "session_started",
            {
                "app_env": app_env,
                "email": st.session_state.get("authenticated_email", ""),
                "version": get_current_version(BASE_DIR).get("version", "unbekannt"),
                "updates_disabled_in_cloud": bool(is_cloud_env(app_env)),
                "orders_enabled": bool(config.get("runtime_mode", {}).get("orders_enabled", False)),
            },
            actor=st.session_state.get("authenticated_email", "system"),
        )
        st.session_state.online_session_logged = True
    except Exception:
        logger.exception("Could not write online session event")


def apply_responsive_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sensei-alert: #ff2bd6;
            --sensei-alert-soft: rgba(255, 43, 214, 0.10);
            --sensei-alert-line: rgba(255, 43, 214, 0.36);
            --sensei-bg: #000000;
            --sensei-panel: #111113;
            --sensei-panel-2: #1c1c1e;
            --sensei-panel-3: #242426;
            --sensei-line: rgba(255, 255, 255, 0.11);
            --sensei-text: #f5f5f7;
            --sensei-muted: #a1a1a6;
            --sensei-green: #30d158;
            --sensei-blue: #0a84ff;
            --sensei-yellow: #ffd60a;
            --sensei-gray: #8e8e93;
            --sensei-red: #ff453a;
        }
        .stApp {
            background: var(--sensei-bg);
            color: var(--sensei-text);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", Inter, sans-serif;
        }
        .block-container {
            padding-top: 1rem;
            padding-bottom: 2rem;
            max-width: 1540px;
        }
        [data-testid="stSidebar"] {
            display: none;
        }
        [data-testid="collapsedControl"] {
            display: none;
        }
        h1, h2, h3, h4, h5, h6, p, label, span {
            color: var(--sensei-text);
        }
        div[data-testid="stCaptionContainer"],
        .sensei-muted {
            color: var(--sensei-muted);
        }
        .sensei-hero {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 1.1rem 1.2rem;
            margin-bottom: 1rem;
            background: linear-gradient(180deg, rgba(28, 28, 30, 0.96), rgba(17, 17, 19, 0.96));
            box-shadow: none;
        }
        .sensei-hero-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
        }
        .sensei-site-nav {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.75rem;
            margin-bottom: 0.9rem;
            background: rgba(17, 17, 19, 0.92);
            box-shadow: none;
        }
        .sensei-site-nav-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            flex-wrap: wrap;
            margin-bottom: 0.6rem;
        }
        .sensei-site-brand {
            font-size: 1.08rem;
            font-weight: 900;
            letter-spacing: 0.02em;
        }
        .sensei-site-brand span {
            color: var(--sensei-alert);
        }
        .sensei-site-meta {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            font-weight: 800;
        }
        .sensei-account-strip {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.58rem 0.7rem;
            margin-bottom: 0.9rem;
            background: rgba(17, 17, 19, 0.78);
        }
        .sensei-market-rail-head {
            position: sticky;
            top: 0;
            z-index: 2;
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.75rem;
            background: rgba(17, 17, 19, 0.96);
            margin-bottom: 0.75rem;
        }
        .sensei-market-rail-title {
            font-size: 1rem;
            font-weight: 900;
            line-height: 1.2;
        }
        .sensei-market-rail-subtitle {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            margin-top: 0.2rem;
            line-height: 1.35;
        }
        .sensei-market-section {
            color: var(--sensei-alert);
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 0.85rem 0 0.4rem;
        }
        .sensei-market-row {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.62rem 0.66rem;
            margin-bottom: 0.42rem;
            background: rgba(28, 28, 30, 0.74);
        }
        .sensei-market-row:hover {
            border-color: rgba(255, 255, 255, 0.22);
            background: rgba(36, 36, 38, 0.92);
        }
        .sensei-market-row-top,
        .sensei-market-row-bottom {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.55rem;
        }
        .sensei-market-symbol {
            font-weight: 900;
            letter-spacing: 0.02em;
            word-break: break-word;
        }
        .sensei-market-price {
            font-size: 0.96rem;
            font-weight: 900;
            white-space: nowrap;
        }
        .sensei-market-label,
        .sensei-market-meta {
            color: var(--sensei-muted);
            font-size: 0.76rem;
            line-height: 1.35;
        }
        .sensei-market-meta {
            margin-top: 0.32rem;
        }
        .sensei-kicker {
            color: var(--sensei-alert);
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .sensei-title {
            font-size: 2rem;
            font-weight: 850;
            line-height: 1.05;
            margin-top: 0.25rem;
        }
        .sensei-subtitle {
            color: var(--sensei-muted);
            margin-top: 0.4rem;
            max-width: 760px;
        }
        .sensei-card,
        .sensei-score-card,
        .sensei-sync-card,
        .sensei-table-card,
        .sensei-mini-card,
        .sensei-alert-card {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(28, 28, 30, 0.96), rgba(17, 17, 19, 0.96));
            padding: 0.95rem;
            box-shadow: none;
        }
        .sensei-alert-card {
            border-color: rgba(255, 43, 214, 0.28);
            margin-bottom: 0.65rem;
        }
        .sensei-mini-card {
            min-height: 7rem;
        }
        .sensei-card-label {
            color: var(--sensei-muted);
            font-size: 0.72rem;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.75rem;
        }
        .sensei-card-value {
            color: var(--sensei-text);
            font-size: 0.98rem;
            line-height: 1.45;
            word-break: break-word;
        }
        .sensei-callout {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.95rem 1rem;
            background: rgba(28, 28, 30, 0.76);
            margin: 0.85rem 0 1rem;
            line-height: 1.55;
        }
        .sensei-alert-callout {
            border-color: var(--sensei-alert-line);
            background: var(--sensei-alert-soft);
        }
        .sensei-mobile-only,
        .sensei-mobile-card-grid {
            display: none;
        }
        .sensei-mobile-card {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.75rem;
            background: rgba(28, 28, 30, 0.86);
            margin-bottom: 0.6rem;
        }
        .sensei-mobile-card-active {
            border-color: var(--sensei-alert);
            background: rgba(255, 43, 214, 0.08);
        }
        .sensei-mobile-card-top,
        .sensei-mobile-kpi-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.65rem;
            flex-wrap: wrap;
        }
        .sensei-mobile-card-symbol {
            font-size: 1.08rem;
            font-weight: 900;
            letter-spacing: 0.02em;
        }
        .sensei-mobile-card-meta {
            color: var(--sensei-muted);
            font-size: 0.8rem;
            margin-top: 0.35rem;
            line-height: 1.35;
        }
        .sensei-mobile-kpi {
            min-width: 5.8rem;
        }
        .sensei-mobile-kpi-label {
            color: var(--sensei-muted);
            font-size: 0.68rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .sensei-mobile-kpi-value {
            font-size: 0.98rem;
            font-weight: 900;
            margin-top: 0.12rem;
        }
        .sensei-mobile-flow-note {
            display: none;
            border: 1px solid rgba(255, 43, 214, 0.24);
            border-radius: 8px;
            background: rgba(255, 43, 214, 0.06);
            color: #ffd7f7;
            padding: 0.62rem 0.7rem;
            margin: 0.55rem 0 0.75rem;
            font-size: 0.82rem;
        }
        .sensei-guidance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0 1rem;
        }
        .sensei-guidance-card {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(28, 28, 30, 0.96), rgba(17, 17, 19, 0.96));
            padding: 0.95rem;
            min-height: 136px;
            box-shadow: none;
        }
        .sensei-guidance-card-pink {
            border-color: rgba(255, 43, 214, 0.34);
            background: linear-gradient(180deg, rgba(255, 43, 214, 0.09), rgba(17, 17, 19, 0.96));
        }
        .sensei-guidance-label {
            color: var(--sensei-muted);
            font-size: 0.72rem;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .sensei-guidance-value {
            font-size: 1.35rem;
            font-weight: 900;
            margin-top: 0.42rem;
            line-height: 1.1;
        }
        .sensei-guidance-detail {
            color: var(--sensei-muted);
            font-size: 0.82rem;
            margin-top: 0.5rem;
            line-height: 1.35;
        }
        .sensei-traffic-card {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 1rem;
            margin: 0.75rem 0 1rem;
            background: rgba(28, 28, 30, 0.82);
        }
        .sensei-traffic-ok {
            border-color: rgba(34, 197, 94, 0.5);
            box-shadow: inset 0 0 0 1px rgba(34, 197, 94, 0.08);
        }
        .sensei-traffic-caution {
            border-color: rgba(250, 204, 21, 0.5);
            box-shadow: inset 0 0 0 1px rgba(250, 204, 21, 0.08);
        }
        .sensei-traffic-blocked {
            border-color: rgba(244, 63, 94, 0.55);
            box-shadow: inset 0 0 0 1px rgba(244, 63, 94, 0.08);
        }
        .sensei-traffic-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
        }
        .sensei-traffic-label {
            font-size: 1.6rem;
            font-weight: 900;
            line-height: 1.1;
        }
        .sensei-topic-card {
            border: 1px solid rgba(255, 43, 214, 0.22);
            border-radius: 8px;
            padding: 0.85rem;
            background: rgba(28, 28, 30, 0.82);
            min-height: 118px;
        }
        .sensei-topic-title {
            font-weight: 850;
            font-size: 0.98rem;
        }
        .sensei-topic-meta {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            margin-top: 0.25rem;
        }
        .sensei-score-card {
            min-height: 145px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .sensei-score-head {
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            align-items: flex-start;
        }
        .sensei-score-symbol {
            font-size: 1.05rem;
            font-weight: 850;
        }
        .sensei-score-label {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            margin-top: 0.12rem;
        }
        .sensei-score-value {
            font-size: 2.15rem;
            font-weight: 900;
            line-height: 1;
            margin: 0.8rem 0 0.25rem;
        }
        .sensei-score-meta {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .sensei-score-elite { border-color: rgba(34, 197, 94, 0.5); }
        .sensei-score-elite .sensei-score-value { color: var(--sensei-green); }
        .sensei-score-a { border-color: rgba(56, 189, 248, 0.5); }
        .sensei-score-a .sensei-score-value { color: var(--sensei-blue); }
        .sensei-score-b { border-color: rgba(250, 204, 21, 0.48); }
        .sensei-score-b .sensei-score-value { color: var(--sensei-yellow); }
        .sensei-score-watch { border-color: rgba(148, 163, 184, 0.32); }
        .sensei-score-watch .sensei-score-value { color: var(--sensei-gray); }
        .sensei-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            padding: 0.25rem 0.55rem;
            font-size: 0.72rem;
            line-height: 1;
            font-weight: 800;
            letter-spacing: 0.02em;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .sensei-badge-green {
            color: #bbf7d0;
            background: rgba(34, 197, 94, 0.14);
            border-color: rgba(34, 197, 94, 0.42);
        }
        .sensei-badge-blue {
            color: #bae6fd;
            background: rgba(56, 189, 248, 0.14);
            border-color: rgba(56, 189, 248, 0.42);
        }
        .sensei-badge-yellow {
            color: #fef08a;
            background: rgba(250, 204, 21, 0.14);
            border-color: rgba(250, 204, 21, 0.42);
        }
        .sensei-badge-gray {
            color: #d8dee8;
            background: rgba(148, 163, 184, 0.12);
            border-color: rgba(148, 163, 184, 0.24);
        }
        .sensei-badge-red {
            color: #fecdd3;
            background: rgba(244, 63, 94, 0.14);
            border-color: rgba(244, 63, 94, 0.42);
        }
        .sensei-section-title {
            margin: 1.25rem 0 0.7rem;
        }
        .sensei-section-title h3 {
            font-size: 1rem;
            font-weight: 850;
            margin: 0;
        }
        .sensei-section-title p {
            color: var(--sensei-muted);
            margin: 0.2rem 0 0;
            font-size: 0.86rem;
        }
        .sensei-feature-strip {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.65rem;
            background: rgba(17, 17, 19, 0.70);
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin: 0.7rem 0 0.9rem;
        }
        .sensei-feature-pill {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 999px;
            padding: 0.28rem 0.58rem;
            background: rgba(28, 28, 30, 0.84);
            color: var(--sensei-muted);
            font-size: 0.76rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .sensei-feature-pill strong {
            color: var(--sensei-alert);
        }
        .sensei-action-panel {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.9rem;
            background: rgba(17, 17, 19, 0.78);
        }
        .sensei-table {
            width: 100%;
            border-collapse: collapse;
            overflow: hidden;
        }
        .sensei-table th {
            color: var(--sensei-muted);
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            text-align: left;
            padding: 0.6rem 0.55rem;
            border-bottom: 1px solid var(--sensei-line);
        }
        .sensei-table td {
            padding: 0.72rem 0.55rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.1);
            color: var(--sensei-text);
            vertical-align: middle;
        }
        .sensei-table tr:last-child td {
            border-bottom: none;
        }
        .sensei-chart-card,
        .sensei-fullscreen-panel {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.85rem;
            background: rgba(17, 17, 19, 0.88);
            margin-bottom: 0.85rem;
        }
        .sensei-fullscreen-panel {
            min-height: 78vh;
        }
        .sensei-chart-toolbar {
            border: 1px solid rgba(255, 43, 214, 0.28);
            border-radius: 8px;
            padding: 0.7rem 0.75rem;
            background: rgba(255, 43, 214, 0.055);
            margin: 0.35rem 0 0.75rem;
        }
        .sensei-chart-top-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(250px, 320px);
            gap: 0.85rem;
            align-items: stretch;
            margin-bottom: 0.75rem;
        }
        .sensei-chart-score-box {
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 8px;
            padding: 0.85rem;
            background: linear-gradient(180deg, rgba(36, 36, 38, 0.96), rgba(17, 17, 19, 0.96));
            min-height: 100%;
        }
        div[data-testid="stPopover"] > button {
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 8px;
            padding: 0.95rem 1rem;
            min-height: 5.8rem;
            width: 100%;
            justify-content: flex-start;
            background: linear-gradient(180deg, rgba(42, 42, 44, 0.98), rgba(14, 14, 16, 0.98));
            color: #ffffff;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
        }
        div[data-testid="stPopover"] > button:hover,
        div[data-testid="stPopover"] > button:focus {
            border-color: rgba(255, 255, 255, 0.38);
            background: linear-gradient(180deg, rgba(52, 52, 55, 0.98), rgba(18, 18, 20, 0.98));
        }
        div[data-testid="stPopover"] > button p {
            color: #ffffff;
            font-size: 1.35rem;
            line-height: 1.1;
            font-weight: 950;
            letter-spacing: 0.01em;
        }
        .sensei-chart-score-label {
            color: var(--sensei-muted);
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .sensei-chart-score-value {
            color: #ffffff;
            font-size: 2.5rem;
            line-height: 1;
            font-weight: 950;
            letter-spacing: 0.01em;
            margin: 0.35rem 0 0.55rem;
        }
        .sensei-score-breakdown {
            border-top: 1px solid rgba(255, 255, 255, 0.09);
            padding-top: 0.55rem;
            display: grid;
            gap: 0.32rem;
        }
        .sensei-score-breakdown-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.65rem;
            color: var(--sensei-muted);
            font-size: 0.76rem;
            line-height: 1.2;
        }
        .sensei-score-breakdown-points {
            color: #ffffff;
            font-weight: 900;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .sensei-score-breakdown-note {
            color: var(--sensei-muted);
            font-size: 0.74rem;
            line-height: 1.35;
            margin-top: 0.5rem;
        }
        .sensei-score-popover-head {
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            padding: 0.75rem;
            background: rgba(28, 28, 30, 0.92);
            margin-bottom: 0.65rem;
        }
        .sensei-timeframe-trend-strip {
            display: flex;
            align-items: stretch;
            gap: 0.45rem;
            flex-wrap: wrap;
            margin: 0.55rem 0 0.65rem;
        }
        .sensei-timeframe-trend-chip {
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            padding: 0.45rem 0.55rem;
            min-width: 94px;
            background: rgba(28, 28, 30, 0.78);
        }
        .sensei-timeframe-trend-chip.active {
            border-color: rgba(255, 255, 255, 0.42);
            background: rgba(255, 255, 255, 0.075);
        }
        .sensei-timeframe-label {
            color: var(--sensei-muted);
            font-size: 0.68rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .sensei-timeframe-direction {
            font-size: 0.9rem;
            font-weight: 950;
            line-height: 1.15;
            margin-top: 0.14rem;
        }
        .sensei-timeframe-direction.bullish {
            color: #30d158;
        }
        .sensei-timeframe-direction.bearish {
            color: #ff453a;
        }
        .sensei-timeframe-direction.neutral {
            color: #ffd60a;
        }
        .sensei-timeframe-direction.unknown {
            color: var(--sensei-muted);
        }
        .sensei-timeframe-score {
            color: var(--sensei-muted);
            font-size: 0.7rem;
            margin-top: 0.12rem;
            white-space: nowrap;
        }
        .sensei-chart-toolbar-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            flex-wrap: wrap;
            margin-bottom: 0.35rem;
        }
        .sensei-chart-toolbar-title strong {
            color: var(--sensei-alert);
        }
        .sensei-workbench-shell {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.85rem;
            background: rgba(0, 0, 0, 0.32);
            margin-bottom: 1rem;
        }
        .sensei-watchlist-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.65rem;
        }
        .sensei-watchlist-title {
            font-size: 1.05rem;
            font-weight: 850;
        }
        .sensei-watch-row {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.55rem 0.6rem;
            margin-bottom: 0.45rem;
            background: rgba(28, 28, 30, 0.72);
        }
        .sensei-watch-row-active {
            border-color: var(--sensei-alert);
            box-shadow: none;
            background: rgba(255, 43, 214, 0.075);
        }
        .sensei-watch-symbol {
            font-weight: 850;
            letter-spacing: 0.02em;
        }
        .sensei-watch-meta {
            color: var(--sensei-muted);
            font-size: 0.78rem;
            margin-top: 0.15rem;
        }
        .sensei-chart-workspace-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.75rem;
            flex-wrap: wrap;
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.8rem 0.9rem;
            background: rgba(28, 28, 30, 0.82);
            margin-bottom: 0.75rem;
        }
        .sensei-chart-workspace-title {
            font-size: 1.18rem;
            font-weight: 850;
            line-height: 1.2;
        }
        .sensei-chart-workspace-meta {
            color: var(--sensei-muted);
            font-size: 0.8rem;
            margin-top: 0.25rem;
        }
        .sensei-chart-badge-row,
        .sensei-fullscreen-strip {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            flex-wrap: wrap;
        }
        .sensei-fullscreen-strip {
            border: 1px solid rgba(255, 43, 214, 0.24);
            border-radius: 8px;
            padding: 0.65rem 0.75rem;
            background: rgba(255, 43, 214, 0.06);
            margin-bottom: 0.75rem;
        }
        .sensei-fullscreen-strip-title {
            font-weight: 850;
            margin-right: 0.45rem;
        }
        .sensei-line-status {
            border: 1px solid rgba(255, 43, 214, 0.24);
            border-radius: 8px;
            padding: 0.48rem 0.6rem;
            background: rgba(255, 43, 214, 0.055);
            margin: 0.35rem 0 0.65rem;
            color: #ffd7f7;
            font-size: 0.82rem;
        }
        .sensei-terminal {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
            background: rgba(28, 28, 30, 0.82);
            margin: 0.35rem 0 0.75rem 0;
        }
        .sensei-terminal-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .sensei-terminal-symbol {
            font-weight: 700;
            font-size: 1.05rem;
            letter-spacing: 0.02em;
        }
        .sensei-alert-badge,
        .sensei-alert-chip {
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--sensei-alert-line);
            background: var(--sensei-alert-soft);
            color: var(--sensei-alert);
            border-radius: 999px;
            font-weight: 700;
            line-height: 1.1;
            white-space: nowrap;
        }
        .sensei-alert-badge {
            padding: 0.22rem 0.48rem;
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .sensei-alert-chip {
            padding: 0.18rem 0.42rem;
            margin: 0.08rem 0.18rem 0.08rem 0;
            font-size: 0.72rem;
        }
        .sensei-alert-panel {
            border-left: 4px solid var(--sensei-alert);
            background: var(--sensei-alert-soft);
            border-radius: 8px;
            padding: 0.65rem 0.75rem;
            margin: 0.5rem 0;
        }
        .sensei-alert-panel strong {
            color: var(--sensei-alert);
        }
        .sensei-dev-panel {
            border: 1px solid rgba(255, 43, 214, 0.34);
            background: rgba(255, 43, 214, 0.08);
            color: #ffd7f7;
            border-radius: 8px;
            padding: 0.7rem 0.8rem;
            margin: 0.75rem 0 0.5rem;
            font-size: 0.86rem;
        }
        .stButton > button,
        .stDownloadButton > button,
        button[kind="primary"] {
            border-radius: 8px;
            border: 1px solid var(--sensei-line);
            background: rgba(28, 28, 30, 0.96);
            color: var(--sensei-text);
            min-height: 2.8rem;
            font-weight: 800;
        }
        button[kind="primary"] {
            border-color: rgba(255, 43, 214, 0.34);
            background: linear-gradient(180deg, rgba(255, 43, 214, 0.16), rgba(36, 36, 38, 0.94));
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: rgba(255, 255, 255, 0.28);
            color: white;
            background: rgba(44, 44, 46, 0.96);
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            overflow: hidden;
        }
        input, textarea, [data-baseweb="select"] {
            color: var(--sensei-text);
        }
        [data-testid="stMetric"] {
            border: 1px solid var(--sensei-line);
            border-radius: 8px;
            padding: 0.75rem;
            background: rgba(28, 28, 30, 0.82);
        }
        [data-testid="stMetricLabel"] p {
            color: var(--sensei-muted);
        }
        [data-testid="stMetricValue"] {
            color: var(--sensei-text);
            font-weight: 850;
        }
        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-top: 1rem;
            }
            .sensei-mobile-only {
                display: block;
            }
            .sensei-mobile-card-grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.55rem;
                margin: 0.55rem 0 0.8rem;
            }
            .sensei-desktop-table {
                display: none;
            }
            .sensei-mobile-flow-note {
                display: block;
            }
            .stButton > button,
            .stDownloadButton > button,
            button[kind="primary"] {
                min-height: 3.35rem;
                font-size: 0.96rem;
                padding: 0.65rem 0.75rem;
            }
            [data-testid="stMetric"] {
                padding: 0.55rem 0.65rem;
            }
            [data-testid="stMetricLabel"] p {
                font-size: 0.78rem;
            }
            [data-testid="stMetricValue"] {
                font-size: 1.15rem;
            }
            [data-baseweb="tab-list"] {
                gap: 0.25rem;
                overflow-x: auto;
                scrollbar-width: thin;
            }
            [data-baseweb="tab"] {
                padding-left: 0.65rem;
                padding-right: 0.65rem;
                white-space: nowrap;
            }
            div[data-testid="stDataFrame"] {
                font-size: 0.82rem;
            }
            .stPlotlyChart {
                margin-top: 0.25rem;
            }
            .sensei-terminal {
                padding: 0.6rem;
            }
            .sensei-title {
                font-size: 1.5rem;
            }
            .sensei-site-nav {
                padding: 0.6rem;
            }
            .sensei-site-brand {
                font-size: 0.98rem;
            }
            .sensei-market-rail-head {
                position: static;
            }
            .sensei-market-row {
                padding: 0.72rem;
            }
            .sensei-score-card {
                min-height: 120px;
            }
            .sensei-workbench-shell {
                padding: 0.6rem;
            }
            .sensei-watch-row {
                padding: 0.72rem;
                margin-bottom: 0.55rem;
            }
            .sensei-watch-symbol {
                font-size: 1.02rem;
            }
            .sensei-watch-meta {
                font-size: 0.84rem;
            }
            .sensei-table-card {
                padding: 0.65rem;
            }
            .sensei-table th,
            .sensei-table td {
                padding: 0.55rem 0.45rem;
            }
            .sensei-chart-workspace-header,
            .sensei-fullscreen-strip {
                padding: 0.6rem;
            }
            .sensei-chart-workspace-title {
                font-size: 1rem;
            }
            .sensei-chart-top-grid {
                grid-template-columns: 1fr;
            }
            .sensei-chart-score-value {
                font-size: 2.1rem;
            }
            .sensei-feature-strip {
                gap: 0.3rem;
                padding: 0.55rem;
            }
            .sensei-feature-pill {
                font-size: 0.7rem;
                padding: 0.24rem 0.48rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(app_env: str = "local", page: str = "") -> None:
    mode = "Cloud" if is_cloud_env(app_env) else "Local"
    page_text = f" / {escape(page)}" if page else ""
    st.markdown(
        f"""
        <div class="sensei-hero">
            <div class="sensei-hero-top">
                <div>
                    <div class="sensei-kicker">Analyse-only Dashboard{page_text}</div>
                    <div class="sensei-title">Analyse Market Sensei Cut</div>
                    <div class="sensei-subtitle">
                        Marktstatus, Watchlists, Papertracking und Reports. Keine Orders. Keine Broker-API.
                    </div>
                </div>
                <div>{status_badge_html(mode, "blue")}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def app_pages() -> list[str]:
    return [
        "Heute ansehen",
        "Dashboard",
        "Workspace",
        "Watchlist",
        "Sektorrotation",
        "Market Regime",
        "Backtesting",
        "Papertrading",
        "Real Money",
        "Reports",
        "Updates",
        "Online-Betrieb",
        "Settings",
    ]


def current_navigation_page() -> str:
    pages = app_pages()
    current = str(st.session_state.get("navigation_page", pages[0]))
    if current not in pages:
        current = pages[0]
        st.session_state.navigation_page = current
    return current


def render_top_navigation(app_env: str) -> str:
    pages = app_pages()
    current = current_navigation_page()
    mode = "Cloud" if is_cloud_env(app_env) else "Local"
    nav_col, clock_col = st.columns([0.76, 0.24], gap="large")
    with nav_col:
        st.markdown(
            f"""
            <div class="sensei-site-nav">
                <div class="sensei-site-nav-top">
                    <div>
                        <div class="sensei-site-brand">Analyse Market <span>Sensei Cut</span></div>
                        <div class="sensei-site-meta">Website-Navigation oben · Analyse-only · keine Orders</div>
                    </div>
                    <div>{status_badge_html(mode, "blue")}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with clock_col:
        render_live_market_clock()
    primary_pages = pages[:7]
    utility_pages = pages[7:]
    for group_index, group in enumerate([primary_pages, utility_pages]):
        columns = st.columns(len(group), gap="small")
        for index, page in enumerate(group):
            with columns[index]:
                if st.button(
                    page,
                    key=make_key("top_navigation", group_index, page),
                    width="stretch",
                    type="primary" if page == current else "secondary",
                ):
                    st.session_state.navigation_page = page
                    st.rerun()
    return current


def render_live_market_clock() -> None:
    components.html(
        """
        <div class="sensei-clock-card">
            <div class="sensei-clock-label">Market Time</div>
            <div id="sensei-live-clock-time" class="sensei-clock-time">--:--:--</div>
            <div id="sensei-live-clock-date" class="sensei-clock-date">Lokale Zeit</div>
        </div>
        <style>
            html, body {
                margin: 0;
                padding: 0;
                overflow: hidden;
                background: transparent;
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", Inter, sans-serif;
            }
            .sensei-clock-card {
                box-sizing: border-box;
                width: 100%;
                min-height: 92px;
                border: 1px solid rgba(255, 69, 58, 0.38);
                border-radius: 8px;
                padding: 0.72rem 0.82rem;
                background: linear-gradient(180deg, rgba(28, 28, 30, 0.96), rgba(17, 17, 19, 0.96));
            }
            .sensei-clock-label {
                color: #a1a1a6;
                font-size: 0.72rem;
                font-weight: 900;
                letter-spacing: 0.11em;
                text-transform: uppercase;
                line-height: 1;
                margin-bottom: 0.42rem;
            }
            .sensei-clock-time {
                color: #ff453a;
                font-size: clamp(1.85rem, 4.4vw, 2.55rem);
                font-weight: 950;
                line-height: 1;
                letter-spacing: 0.02em;
                font-variant-numeric: tabular-nums;
                text-align: right;
                text-shadow: 0 0 18px rgba(255, 69, 58, 0.12);
            }
            .sensei-clock-date {
                color: #a1a1a6;
                font-size: 0.76rem;
                font-weight: 750;
                margin-top: 0.38rem;
                text-align: right;
                white-space: nowrap;
            }
            @media (max-width: 760px) {
                .sensei-clock-card {
                    min-height: 78px;
                    padding: 0.62rem 0.72rem;
                }
                .sensei-clock-time {
                    font-size: 1.95rem;
                    text-align: left;
                }
                .sensei-clock-date {
                    text-align: left;
                }
            }
        </style>
        <script>
            const timeTarget = document.getElementById("sensei-live-clock-time");
            const dateTarget = document.getElementById("sensei-live-clock-date");
            const timeFormatter = new Intl.DateTimeFormat("de-DE", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false
            });
            const dateFormatter = new Intl.DateTimeFormat("de-DE", {
                weekday: "short",
                day: "2-digit",
                month: "2-digit",
                year: "numeric"
            });
            function updateSenseiClock() {
                const now = new Date();
                timeTarget.textContent = timeFormatter.format(now);
                dateTarget.textContent = dateFormatter.format(now);
            }
            updateSenseiClock();
            const delay = 1000 - new Date().getMilliseconds();
            setTimeout(() => {
                updateSenseiClock();
                setInterval(updateSenseiClock, 1000);
            }, delay);
        </script>
        """,
        height=104,
        scrolling=False,
    )


def render_market_price_rail(config: dict, result: dict, key_prefix: str) -> None:
    timeframes = config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"])
    if not timeframes:
        timeframes = ["1d"]
    timeframe_key = make_key(key_prefix, "timeframe")
    if timeframe_key not in st.session_state:
        st.session_state[timeframe_key] = timeframes[0]
    selected_timeframe = st.selectbox(
        "Marktlisten-Timeframe",
        timeframes,
        key=timeframe_key,
        label_visibility="collapsed",
    )
    rows = market_price_rail_rows(config, result, selected_timeframe)
    loaded_count = sum(1 for row in rows if row.get("has_data"))
    st.markdown(
        f"""
        <div class="sensei-market-rail-head">
            <div class="sensei-market-rail-title">Markt-Schnelluebersicht</div>
            <div class="sensei-market-rail-subtitle">
                Indizes, Aktien, Gold und Sektoren. {loaded_count}/{len(rows)} mit aktuellem Analysewert.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        "Preise aktualisieren",
        key=make_key(key_prefix, "refresh_prices"),
        width="stretch",
        type="primary",
    ):
        _run_update(config, generate_reports=False, include_sector_rotation=True)
        st.rerun()

    if not rows:
        render_empty_state("Keine Symbole", "In config.json sind noch keine Maerkte hinterlegt.")
        return

    try:
        rail_container = st.container(height=720, border=False)
    except TypeError:
        rail_container = st.container()

    current_section = ""
    with rail_container:
        for index, row in enumerate(rows):
            section = str(row.get("category") or "Maerkte")
            if section != current_section:
                current_section = section
                st.markdown(
                    f"<div class='sensei-market-section'>{escape(current_section)}</div>",
                    unsafe_allow_html=True,
                )
            render_market_price_rail_row(row)
            open_label = f"{row.get('label') or row['ticker']} | {row['ticker']} ansehen"
            if st.button(
                open_label,
                key=make_key(key_prefix, "open_chart", index, safe_widget_key(row["ticker"])),
                width="stretch",
            ):
                st.session_state.navigation_page = "Dashboard"
                st.session_state[make_key("dashboard", "timeframe_state")] = selected_timeframe
                st.session_state[make_key("dashboard", "watchlist_workbench", "selected_ticker")] = row[
                    "ticker"
                ]
                st.session_state.workspace_ticker = row["ticker"]
                st.session_state.workspace_timeframe = selected_timeframe
                st.rerun()


def market_price_rail_rows(config: dict, result: dict, timeframe: str) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()

    def add(label: str, ticker: str, category: str) -> None:
        cleaned = str(ticker).strip().upper()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        row = analysis_row_for_ticker(result, cleaned, timeframe)
        close_value = safe_optional_float(row.get("close")) if row else None
        score_value = safe_optional_float(row.get("score")) if row else None
        entries.append(
            {
                "label": str(label or cleaned),
                "ticker": cleaned,
                "category": str(category or "Maerkte"),
                "close": close_value,
                "score": score_value,
                "trend": str(row.get("trend", "nicht analysiert")) if row else "nicht analysiert",
                "risk_state": str(row.get("risk_state", "offen")) if row else "offen",
                "data_status": str(row.get("data_status", "keine Daten")) if row else "keine Daten",
                "has_data": bool(row),
            }
        )

    for item in dashboard_seed_symbols(config):
        add(item.get("label", item.get("ticker", "")), item.get("ticker", ""), item.get("category", "Maerkte"))

    for item in config.get("sector_rotation_symbols", DEFAULT_SECTOR_ROTATION_SYMBOLS):
        if isinstance(item, dict):
            add(item.get("label", item.get("ticker", "")), item.get("ticker", ""), item.get("category", "Sektoren"))
        else:
            add(str(item), str(item), "Sektoren")

    category_order = {
        "Indizes": 0,
        "Gold": 1,
        "Aktien": 2,
        "US Sektoren": 3,
        "Bau": 4,
        "Themen": 5,
        "Rohstoffe": 6,
        "Krypto": 7,
        "Waehrung": 8,
        "Treasuries": 9,
        "Treasury Yields": 10,
    }
    return sorted(entries, key=lambda row: (category_order.get(str(row["category"]), 99), row["label"]))


def render_market_price_rail_row(row: dict) -> None:
    ticker = str(row.get("ticker", ""))
    label = str(row.get("label") or ticker)
    close = row.get("close")
    price_text = "--" if close is None else f"{safe_float(close):,.2f}"
    score = row.get("score")
    score_text = "--" if score is None else f"{int(safe_float(score))}/100"
    trend = str(row.get("trend", "nicht analysiert"))
    risk_state = str(row.get("risk_state", "offen"))
    data_status = str(row.get("data_status", "keine Daten"))
    st.markdown(
        f"""
        <div class="sensei-market-row">
            <div class="sensei-market-row-top">
                <div>
                    <div class="sensei-market-symbol">{escape(ticker)}</div>
                    <div class="sensei-market-label">{escape(label)}</div>
                </div>
                <div class="sensei-market-price">{escape(price_text)}</div>
            </div>
            <div class="sensei-market-row-bottom sensei-market-meta">
                <span>Score {escape(score_text)}</span>
                <span>{escape(trend)}</span>
                <span>{escape(risk_state)}</span>
            </div>
            <div class="sensei-market-meta">Daten: {escape(data_status)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def score_tier(score: float) -> tuple[str, str, str]:
    value = safe_float(score)
    if value >= 90:
        return "Elite", "elite", "green"
    if value >= 80:
        return "A", "a", "blue"
    if value >= 70:
        return "B", "b", "yellow"
    return "Beobachten", "watch", "gray"


def status_color(value) -> str:
    text = str(value).lower()
    if text in ["green", "blue", "yellow", "gray", "red"]:
        return text
    if text in ["bullish", "ok", "markt ok", "elite"]:
        return "green"
    if text in ["a", "cloud", "local"]:
        return "blue"
    if text in ["neutral", "reduced", "vorsicht", "b"]:
        return "yellow"
    if text in ["bearish", "blocked", "blockiert"]:
        return "red"
    if text == "pink":
        return "pink"
    return "gray"


def status_badge_html(label: str, kind: str = "gray") -> str:
    color = "gray" if kind == "pink" else status_color(kind)
    extra = " sensei-alert-badge" if kind == "pink" else ""
    return (
        f"<span class='sensei-badge sensei-badge-{escape(color)}{extra}'>"
        f"{escape(str(label))}</span>"
    )


def render_status_badge(label: str, kind: str = "gray") -> None:
    st.markdown(status_badge_html(label, kind), unsafe_allow_html=True)


def render_section_title(title: str, subtitle: str = "") -> None:
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f"""
        <div class="sensei-section-title">
            <h3>{escape(title)}</h3>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ui_feature_strip() -> None:
    features = [
        "Dark Mode",
        "TradingView Stil",
        "Große Marktkarten",
        "Score Karten",
        "Top 5 Chancen",
        "Marktstatus",
        "Alerts",
        "Responsive Layout",
    ]
    pills = "".join(
        f"<span class='sensei-feature-pill'><strong>OK</strong> {escape(feature)}</span>"
        for feature in features
    )
    st.markdown(f"<div class='sensei-feature-strip'>{pills}</div>", unsafe_allow_html=True)


def render_score_card(row, title: str = "", subtitle: str = "") -> None:
    if not row:
        st.markdown(
            f"""
            <div class="sensei-score-card sensei-score-watch">
                <div class="sensei-score-head">
                    <div>
                        <div class="sensei-score-symbol">{escape(title or "n/a")}</div>
                        <div class="sensei-score-label">Keine Daten</div>
                    </div>
                    {status_badge_html("Offen", "gray")}
                </div>
                <div class="sensei-score-value">--</div>
                <div class="sensei-score-meta"><span>Analyse starten</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    score = int(safe_float(row.get("score"), 0))
    tier_label, tier_class, tier_color = score_tier(score)
    label = title or str(row.get("label") or row.get("ticker") or "Symbol")
    ticker = str(row.get("ticker", ""))
    trend = str(row.get("trend", "neutral"))
    risk = str(row.get("risk_state", "offen"))
    close = safe_float(row.get("close"), 0)
    st.markdown(
        f"""
        <div class="sensei-score-card sensei-score-{tier_class}">
            <div class="sensei-score-head">
                <div>
                    <div class="sensei-score-symbol">{escape(label)}</div>
                    <div class="sensei-score-label">{escape(ticker)} {escape(subtitle)}</div>
                </div>
                {status_badge_html(tier_label, tier_color)}
            </div>
            <div class="sensei-score-value">{score}/100</div>
            <div class="sensei-score-meta">
                <span>{status_badge_html(trend, status_color(trend))}</span>
                <span>{status_badge_html(risk, status_color(risk))}</span>
                <span>{close:.2f}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_action_button_area(config: dict, app_env: str, key_prefix: str) -> None:
    st.markdown("<div class='sensei-action-panel'>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button(
            "Analysieren",
            key=make_key(key_prefix, "analyze"),
            type="primary",
            width="stretch",
        ):
            _run_update(config, generate_reports=True)
    with col2:
        if st.button(
            "Reports aktualisieren",
            key=make_key(key_prefix, "refresh_reports"),
            width="stretch",
        ):
            _run_update(config, generate_reports=True)
    with col3:
        if st.button(
            "Abendanalyse",
            key=make_key(key_prefix, "evening_analysis"),
            width="stretch",
        ):
            evening_result = run_evening_analysis(
                require_power=not is_cloud_env(app_env),
                allow_cloud=True,
            )
            if evening_result["ok"]:
                st.session_state.analysis_result = evening_result["analysis_result"]
                st.success("Abendanalyse abgeschlossen.")
                st.info("reports/evening_summary.txt wurde aktualisiert.")
            elif evening_result.get("skipped"):
                st.warning(evening_result["message"])
            else:
                st.error(evening_result["message"])
    st.markdown("</div>", unsafe_allow_html=True)


def data_status_color(status: str) -> str:
    value = str(status).lower()
    if value == "live":
        return "green"
    if value == "delayed":
        return "blue"
    if value == "cache":
        return "yellow"
    if value == "fehlerhaft":
        return "red"
    return "gray"


def data_quality_frame(result: dict, timeframe: str) -> pd.DataFrame:
    frames = []
    for key in ["dashboard", "watchlist", "sector_rotation"]:
        frame = result.get(key)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "timeframe" in combined:
        combined = combined[combined["timeframe"] == timeframe]
    required = [
        "ticker",
        "label",
        "timeframe",
        "data_status",
        "data_source",
        "last_clean_date",
        "data_rows",
        "data_message",
    ]
    for column in required:
        if column not in combined:
            combined[column] = "" if column != "data_rows" else 0
    combined["ticker"] = combined["ticker"].astype(str).str.upper()
    return combined[required].drop_duplicates(["ticker", "timeframe"], keep="first")


def render_data_quality_summary(result: dict, timeframe: str, key_prefix: str) -> None:
    quality = data_quality_frame(result, timeframe)
    if quality.empty or "data_status" not in quality:
        st.info("Datenqualitaet: Noch keine Statusdaten vorhanden. Starte eine Analyse.")
        return

    quality["data_status"] = quality["data_status"].replace("", "unbekannt").fillna("unbekannt")
    counts = quality["data_status"].str.lower().value_counts().to_dict()
    clean_dates = pd.to_datetime(quality["last_clean_date"], errors="coerce").dropna()
    last_clean = clean_dates.max().date().isoformat() if not clean_dates.empty else "nicht verfuegbar"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Daten live", int(counts.get("live", 0)))
    col2.metric("Delayed", int(counts.get("delayed", 0)))
    col3.metric("Cache", int(counts.get("cache", 0)))
    col4.metric("Fehlerhaft", int(counts.get("fehlerhaft", 0)))

    badge_html = " ".join(
        status_badge_html(f"{status}: {int(counts.get(status, 0))}", data_status_color(status))
        for status in ["live", "delayed", "cache", "fehlerhaft"]
    )
    st.markdown(
        f"<div class='sensei-muted'>Letzter sauberer Datenstand: <b>{escape(last_clean)}</b></div>{badge_html}",
        unsafe_allow_html=True,
    )

    problematic = quality[
        quality["data_status"].astype(str).str.lower().isin(["cache", "fehlerhaft", "unbekannt"])
    ].copy()
    if problematic.empty:
        st.success("Datenqualitaet OK: Fuer diesen Timeframe wurden echte verzoegerte Daten geladen.")
        return

    failed = problematic[problematic["data_status"].astype(str).str.lower() == "fehlerhaft"]
    if not failed.empty:
        st.error(
            "Daten fehlen oder sind fehlerhaft: "
            + ", ".join(failed["ticker"].astype(str).head(8).tolist())
        )
    cache_only = problematic[problematic["data_status"].astype(str).str.lower() == "cache"]
    if not cache_only.empty:
        st.warning(
            "Einige Symbole nutzen Cache-Daten statt frischer Quelle: "
            + ", ".join(cache_only["ticker"].astype(str).head(8).tolist())
        )

    display = problematic[
        ["ticker", "label", "data_status", "data_source", "last_clean_date", "data_rows", "data_message"]
    ].copy()
    with st.expander("Datenqualitaet Details", expanded=not failed.empty):
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "dataframe"),
            column_config={
                "ticker": "Ticker",
                "label": "Name",
                "data_status": "Status",
                "data_source": "Quelle",
                "last_clean_date": "Letzter sauberer Stand",
                "data_rows": st.column_config.NumberColumn("Zeilen", format="%d"),
                "data_message": "Meldung",
            },
        )


def _refresh_tracking_snapshots(config: dict, force: bool = False) -> None:
    result = st.session_state.get("analysis_result")
    if not result:
        return
    updated_at = result.get("updated_at", "")
    marker = f"tracking-snapshots-{updated_at}"
    if not force and st.session_state.get("tracking_snapshot_marker") == marker:
        return

    tracker = _tracker(config)
    tracker.record_snapshots("papertrading", result, updated_at)
    tracker.record_snapshots("real_money", result, updated_at)
    st.session_state.tracking_snapshot_marker = marker


def _sync_alert_history(config: dict, force: bool = False) -> None:
    result = st.session_state.get("analysis_result")
    if not result:
        return
    email = st.session_state.get("authenticated_email", "local")
    updated_at = result.get("updated_at", "")
    marker = f"alert-history-{email}-{updated_at}"
    if not force and st.session_state.get("alert_history_marker") == marker:
        return

    try:
        store = _workspace_store(config)
        alerts = build_system_alerts(config, result)
        created_ids = store.record_system_alerts(email, alerts)
        st.session_state.alert_history_marker = marker
        st.session_state.alert_history_created_count = len(created_ids)
    except Exception:
        logger.exception("Could not sync system alert history")


def build_system_alerts(config: dict, result: dict) -> list[dict]:
    alerts: list[dict] = []
    timeframes = config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"])
    benchmark = config.get("benchmark", "QQQ")

    for timeframe in timeframes:
        status = market_traffic_light(result, timeframe)
        alerts.append(
            make_alert_payload(
                alert_type="market_status",
                ticker="MARKET",
                timeframe=timeframe,
                title=f"Marktstatus: {status['label']}",
                detail=f"{status['summary']} {status['rule']}",
                current_value=status["level"],
                fingerprint=status["level"],
                severity="pink" if status["level"] != "ok" else "blue",
            )
        )

    rows = analysis_alert_rows(result)
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        timeframe = str(row.get("timeframe", ""))
        if not ticker or not timeframe:
            continue

        history = alert_history_frame(result, ticker, timeframe)
        breakout = detect_breakout_alert(ticker, timeframe, history)
        if breakout:
            alerts.append(breakout)

        ema_cross = detect_ema_cross_alert(ticker, timeframe, history)
        if ema_cross:
            alerts.append(ema_cross)

        if ticker != benchmark:
            benchmark_history = alert_history_frame(result, benchmark, timeframe)
            rs_shift = detect_relative_strength_shift_alert(
                ticker,
                timeframe,
                history,
                benchmark_history,
                benchmark,
            )
            if rs_shift:
                alerts.append(rs_shift)

    return alerts


def make_alert_payload(
    alert_type: str,
    ticker: str,
    timeframe: str,
    title: str,
    detail: str,
    current_value: str,
    fingerprint: str,
    severity: str = "pink",
) -> dict:
    cleaned_ticker = str(ticker or "").strip().upper()
    cleaned_timeframe = str(timeframe or "").strip()
    cleaned_type = str(alert_type or "system").strip()
    return {
        "alert_key": make_key(cleaned_type, cleaned_ticker or "market", cleaned_timeframe),
        "alert_type": cleaned_type,
        "severity": severity,
        "ticker": cleaned_ticker,
        "timeframe": cleaned_timeframe,
        "title": title,
        "detail": detail,
        "current_value": current_value,
        "fingerprint": fingerprint,
    }


def analysis_alert_rows(result: dict) -> pd.DataFrame:
    frames = [
        result.get("dashboard", pd.DataFrame()),
        result.get("watchlist", pd.DataFrame()),
        result.get("sector_rotation", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "ticker" not in combined or "timeframe" not in combined:
        return pd.DataFrame()
    combined["ticker"] = combined["ticker"].astype(str).str.upper()
    combined["timeframe"] = combined["timeframe"].astype(str)
    return combined.drop_duplicates(["ticker", "timeframe"]).copy()


def alert_history_frame(result: dict, ticker: str, timeframe: str) -> pd.DataFrame:
    history = result.get("histories", {}).get(f"{ticker}|{timeframe}")
    if history is None or history.empty:
        return pd.DataFrame()
    return normalize_chart_history(history).sort_values("date").copy()


def detect_breakout_alert(ticker: str, timeframe: str, history: pd.DataFrame) -> Optional[dict]:
    if history.empty or len(history) < 22:
        return None
    frame = history.dropna(subset=["date", "high", "close"]).copy()
    if len(frame) < 22:
        return None
    frame["prior_high_20"] = frame["high"].rolling(20, min_periods=10).max().shift(1)
    latest = frame.iloc[-1]
    prior_high = latest.get("prior_high_20")
    close = latest.get("close")
    if prior_high is None or pd.isna(prior_high) or close is None or pd.isna(close):
        return None
    if float(close) <= float(prior_high):
        return None
    latest_date = pd.to_datetime(latest["date"]).date()
    return make_alert_payload(
        alert_type="breakout",
        ticker=ticker,
        timeframe=timeframe,
        title="Breakout erkannt",
        detail=f"{ticker} schliesst ueber dem 20er-Hoch {float(prior_high):.2f}. Close {float(close):.2f}.",
        current_value=f"{float(close):.2f}>{float(prior_high):.2f}",
        fingerprint=f"{latest_date}:{float(close):.4f}:{float(prior_high):.4f}",
        severity="pink",
    )


def detect_ema_cross_alert(ticker: str, timeframe: str, history: pd.DataFrame) -> Optional[dict]:
    if history.empty or len(history) < 3:
        return None
    frame = history.dropna(subset=["date", "ema_20", "ema_50"]).copy()
    if len(frame) < 2:
        return None
    previous = frame.iloc[-2]
    latest = frame.iloc[-1]
    previous_diff = float(previous["ema_20"]) - float(previous["ema_50"])
    current_diff = float(latest["ema_20"]) - float(latest["ema_50"])
    direction = ""
    if previous_diff <= 0 < current_diff:
        direction = "bullish"
        title = "EMA-Cross erkannt"
        detail = f"{ticker}: EMA20 kreuzt ueber EMA50."
    elif previous_diff >= 0 > current_diff:
        direction = "bearish"
        title = "EMA-Cross erkannt"
        detail = f"{ticker}: EMA20 kreuzt unter EMA50."
    else:
        return None
    latest_date = pd.to_datetime(latest["date"]).date()
    return make_alert_payload(
        alert_type="ema_cross",
        ticker=ticker,
        timeframe=timeframe,
        title=title,
        detail=detail,
        current_value=direction,
        fingerprint=f"{latest_date}:{direction}:{current_diff:.6f}",
        severity="pink",
    )


def detect_relative_strength_shift_alert(
    ticker: str,
    timeframe: str,
    history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    benchmark: str,
) -> Optional[dict]:
    if history.empty or benchmark_history.empty:
        return None
    symbol = history[["date", "close"]].dropna().sort_values("date").copy()
    bench = benchmark_history[["date", "close"]].dropna().sort_values("date").copy()
    if len(symbol) < 22 or len(bench) < 22:
        return None
    merged = pd.merge(
        symbol.rename(columns={"close": "symbol_close"}),
        bench.rename(columns={"close": "benchmark_close"}),
        on="date",
        how="inner",
    )
    if len(merged) < 22:
        return None
    merged["symbol_return_20"] = pd.to_numeric(merged["symbol_close"], errors="coerce").pct_change(20) * 100
    merged["benchmark_return_20"] = pd.to_numeric(merged["benchmark_close"], errors="coerce").pct_change(20) * 100
    merged["relative_strength"] = merged["symbol_return_20"] - merged["benchmark_return_20"]
    valid = merged.dropna(subset=["relative_strength"]).copy()
    if len(valid) < 2:
        return None
    previous = valid.iloc[-2]
    latest = valid.iloc[-1]
    previous_rs = float(previous["relative_strength"])
    current_rs = float(latest["relative_strength"])
    if previous_rs <= 0 < current_rs:
        direction = "positive"
        detail = f"{ticker} wechselt auf relative Staerke gegen {benchmark}: {current_rs:.2f}."
    elif previous_rs >= 0 > current_rs:
        direction = "negative"
        detail = f"{ticker} verliert relative Staerke gegen {benchmark}: {current_rs:.2f}."
    else:
        return None
    latest_date = pd.to_datetime(latest["date"]).date()
    return make_alert_payload(
        alert_type="relative_strength_shift",
        ticker=ticker,
        timeframe=timeframe,
        title="Relative-Staerke-Wechsel",
        detail=detail,
        current_value=f"{direction}:{current_rs:.2f}",
        fingerprint=f"{latest_date}:{direction}:{current_rs:.4f}",
        severity="pink",
    )


def enforce_security_defaults(config: dict, app_env: str) -> dict:
    auth = config.setdefault("auth", {})
    auth["enabled"] = True
    auth["require_email_verification"] = True
    auth.setdefault("allow_registration", True)
    auth.setdefault("verification_code_minutes", 30)
    auth.setdefault("password_reset_code_minutes", 15)
    auth.setdefault("database_path", "data/auth.duckdb")
    if is_cloud_env(app_env):
        auth["require_allowed_emails_in_cloud"] = True

    two_factor = auth.setdefault("two_factor", {})
    two_factor.setdefault("enabled", True)
    two_factor.setdefault("required_for_login", bool(two_factor.get("enabled", True)))
    if is_cloud_env(app_env):
        two_factor["enabled"] = True
        two_factor["required_for_login"] = True
    elif not two_factor.get("enabled", True):
        two_factor["required_for_login"] = False
    two_factor.setdefault("method", "email_code")
    two_factor.setdefault("code_minutes", 10)
    two_factor.setdefault("local_display_code", True)

    rate_limit = auth.setdefault("rate_limit", {})
    rate_limit.setdefault("enabled", True)
    rate_limit.setdefault("window_minutes", 15)
    rate_limit.setdefault("password_max_failures", 5)
    rate_limit.setdefault("two_factor_max_failures", 5)
    rate_limit.setdefault("verification_max_failures", 5)
    rate_limit.setdefault("registration_max_attempts", 3)
    rate_limit.setdefault("two_factor_send_max_attempts", 3)
    rate_limit.setdefault("password_reset_send_max_attempts", 3)
    rate_limit.setdefault("password_reset_max_failures", 5)

    security = config.setdefault("security", {})
    security["require_password_for_sensitive_settings"] = True
    security["settings_password_gate"] = True
    security["updates_password_gate"] = True
    security["ports_and_integrations_password_gate"] = True
    security["store_api_keys_in_config"] = False
    security.setdefault("sensitive_unlock_minutes", 15)

    online_ops = config.setdefault("online_operations", {})
    online_ops["cloud_updates_disabled"] = True
    online_ops["local_shell_disabled_in_cloud"] = True
    online_ops["secrets_visible_values"] = False
    online_ops.setdefault(
        "required_cloud_secrets",
        [
            "APP_ENV",
            "APP_PASSWORD",
            "AUTH_ALLOWED_EMAILS",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
        ],
    )
    online_ops.setdefault(
        "optional_cloud_secrets",
        [
            "SMTP_USE_TLS",
            "ALPHA_VANTAGE_API_KEY",
        ],
    )
    online_ops.setdefault("backup_schema", "analyse_market_sensei_cut_cloud_backup_v1")
    online_ops.setdefault("monitoring_log", "logs/online_ops.jsonl")
    online_ops.setdefault(
        "deploy_routine",
        [
            "./scripts/check_project.sh",
            "./scripts/security_check.sh",
            "APP_ENV=cloud APP_PASSWORD=test python scripts/smoke_app.py",
            "./scripts/prepare_cloud_deploy.sh",
        ],
    )

    ports = config.setdefault("ports_and_integrations", {})
    ports["protected"] = True
    ports["execute_api_calls"] = False

    ui = config.setdefault("ui", {})
    ui.setdefault("style_reference", "TradingView-artige Analyseoberflaeche, ohne Marken-Kopie")
    ui["system_alert_color"] = SYSTEM_ALERT_COLOR
    ui.setdefault(
        "system_alert_meaning",
        "Pink markiert System-Erkennung, Speicherung, Breakout-Watch und Bot-Vorbereitung. Keine Orders.",
    )

    data = config.setdefault("data", {})
    data.setdefault("timeframes", ["1d", "1wk", "1mo"])
    data.setdefault("periods", {"1d": "2y", "1wk": "10y", "1mo": "20y"})
    data.setdefault("cache_dir", "data/cache")
    data.setdefault("database_path", "data/market.duckdb")
    data.setdefault("prefer_cache", True)
    data.setdefault("primary_source", "yfinance")
    data.setdefault("secondary_sources", ["alpha_vantage"])
    data.setdefault(
        "quality_statuses",
        {
            "live": "Direkte Live-Datenquelle. Aktuell nicht aktiv.",
            "delayed": "Verzoegerte echte Marktdaten.",
            "cache": "Lokaler Cache, nicht frisch von der Quelle.",
            "fehlerhaft": "Keine sauberen echten Daten verfuegbar.",
        },
    )
    data.setdefault(
        "cache_max_age_hours",
        {
            "1d": 6,
            "1wk": 24,
            "1mo": 72,
            "default": 24,
        },
    )

    score_model = config.setdefault("score_model", {})
    score_model.setdefault("name", "sensei_chain_v2")
    score_model.setdefault(
        "logic",
        [
            "SPY Trend",
            "QQQ Trend",
            "SPY + QQQ Bestaetigung",
            "Mag7",
            "Sektor-Staerke",
            "Relative Staerke",
            "Trendfolge",
        ],
    )
    score_model.setdefault(
        "weights",
        {
            "spy_trend": 15,
            "qqq_trend": 15,
            "market_confirmation": 15,
            "mag7": 15,
            "sector_strength": 15,
            "relative_strength": 10,
            "trend_following": 15,
        },
    )
    score_model.setdefault("mag7_symbols", ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"])
    score_model.setdefault(
        "sector_map",
        {
            "AAPL": "XLK",
            "MSFT": "XLK",
            "NVDA": "XLK",
            "AMZN": "XLY",
            "TSLA": "XLY",
            "META": "XLC",
            "GOOGL": "XLC",
            "GOOG": "XLC",
            "SPY": "SPY",
            "QQQ": "QQQ",
            "^GSPC": "SPY",
            "^NDX": "QQQ",
            "GLD": "GLD",
            "GC=F": "GLD",
            "^GDAXI": "EWG",
            "IWM": "IWM",
            "XLK": "XLK",
            "XLF": "XLF",
            "XLI": "XLI",
            "XLY": "XLY",
            "XLP": "XLP",
            "XLV": "XLV",
            "XLE": "XLE",
            "XLU": "XLU",
            "XLB": "XLB",
            "XLRE": "XLRE",
            "XLC": "XLC",
            "XHB": "XHB",
            "PAVE": "PAVE",
            "SMH": "SMH",
            "USO": "USO",
            "BTC-USD": "BTC-USD",
            "DX-Y.NYB": "DX-Y.NYB",
            "SHY": "SHY",
            "IEI": "IEI",
            "IEF": "IEF",
            "^FVX": "^FVX",
            "^TNX": "^TNX",
        },
    )

    tracking = config.setdefault("tracking", {})
    tracking.setdefault("database_path", "data/portfolio_tracker.duckdb")
    tracking.setdefault("default_quantity", 1.0)
    tracking.setdefault("paper_enabled", True)
    tracking.setdefault("real_money_enabled", True)
    tracking.setdefault(
        "setup_categories",
        [
            "Trendfolge",
            "Breakout",
            "Pullback",
            "Mean Reversion",
            "Relative Staerke",
            "Defensiv Beobachtung",
            "Sonstiges",
        ],
    )
    tracking.setdefault(
        "rule_violation_options",
        [
            "Score unter Mindestwert",
            "Risk State BLOCKED ignoriert",
            "Trend gegen Richtung",
            "Close unter EMA200",
            "Stop fehlt",
            "Ziel fehlt",
            "Positionsgroesse zu hoch",
            "Marktampel nicht OK",
            "Keine klare These",
        ],
    )

    workspace = config.setdefault("workspace", {})
    workspace.setdefault("database_path", "data/workspace.duckdb")
    workspace.setdefault("default_focus", "Schnellblick")
    workspace["energy_mode"] = "manual_cache"
    workspace.setdefault("data_collection", {})
    workspace["data_collection"].setdefault("manual_button", True)
    workspace["data_collection"]["auto_collect_on_analysis"] = False
    workspace["data_collection"].setdefault("load_on_start", True)
    workspace["data_collection"].setdefault("reports_only_on_button", True)
    workspace["data_collection"].setdefault("snapshots_only_on_analysis", True)
    workspace["data_collection"]["background_jobs_cloud"] = False
    workspace["data_collection"]["background_jobs_local"] = True
    workspace.setdefault("categories", DEFAULT_CATEGORIES)
    for category in DEFAULT_CATEGORIES:
        if category not in workspace["categories"]:
            workspace["categories"].append(category)
    config.setdefault("watchlist_categories", DEFAULT_WATCHLIST_CATEGORIES)
    config["dashboard_symbols"] = merge_symbol_entries(
        config.get("dashboard_symbols", []),
        DEFAULT_DASHBOARD_SYMBOLS,
    )
    config["sector_rotation_symbols"] = merge_sector_entries(
        config.get("sector_rotation_symbols", []),
        DEFAULT_SECTOR_ROTATION_SYMBOLS,
    )
    config.setdefault("sector_rotation_categories", DEFAULT_SECTOR_ROTATION_CATEGORIES)

    runtime = config.setdefault("runtime_mode", {})
    runtime["orders_enabled"] = False
    runtime["broker_enabled"] = False
    broker_planning = config.setdefault("broker_planning", {})
    broker_planning.setdefault("enabled", True)
    broker_planning["execution_enabled"] = False
    broker_planning["api_calls_enabled"] = False
    broker_planning["live_connection_enabled"] = False
    broker_planning.setdefault("default_provider", "Interactive Brokers")
    broker_planning.setdefault(
        "preferred_providers",
        [
            "Interactive Brokers",
            "Alpaca",
            "Tradier",
            "Saxo",
            "Kraken",
            "Coinbase Advanced",
            "Binance",
            "IG",
        ],
    )
    broker_planning.setdefault(
        "description",
        "Provider-Matrix fuer spaetere Anbindung. Heute nur Planung, Journal und Sicherheitsstatus.",
    )
    trading_safety = config.setdefault("trading_safety", {})
    for key, value in DEFAULT_TRADING_SAFETY.items():
        trading_safety.setdefault(key, value)
    trading_safety["live_trading_enabled"] = False
    trading_safety["automatic_orders_allowed"] = False
    trading_safety["sandbox_required"] = True
    trading_safety["paper_api_first"] = True
    trading_safety["order_preview_required"] = True
    trading_safety["two_click_confirmation_required"] = True
    trading_safety["hard_approval_required"] = True
    trading_safety["daily_loss_limit_enabled"] = True
    trading_safety["audit_log_enabled"] = True
    trading_safety["allowed_connection_modes"] = ["sandbox_paper"]
    trading_safety["default_connection_mode"] = "sandbox_paper"
    return config


def merge_symbol_entries(existing: list, required: list[dict]) -> list:
    merged = []
    seen = set()
    for entry in list(existing or []) + list(required or []):
        if isinstance(entry, dict):
            ticker = str(entry.get("ticker", "")).strip()
            label = str(entry.get("label", ticker)).strip() or ticker
        else:
            ticker = str(entry).strip()
            label = ticker
        if not ticker:
            continue
        lookup = ticker.upper()
        if lookup in seen:
            continue
        seen.add(lookup)
        merged.append({"label": label, "ticker": ticker})
    return merged


def merge_sector_entries(existing: list, required: list[dict]) -> list:
    merged = []
    seen = set()
    for entry in list(existing or []) + list(required or []):
        if isinstance(entry, dict):
            ticker = str(entry.get("ticker", "")).strip()
            label = str(entry.get("label", ticker)).strip() or ticker
            category = str(entry.get("category", "Eigene Sektoren")).strip() or "Eigene Sektoren"
        else:
            ticker = str(entry).strip()
            label = ticker
            category = "Eigene Sektoren"
        if not ticker:
            continue
        lookup = ticker.upper()
        if lookup in seen:
            continue
        seen.add(lookup)
        merged.append({"label": label, "ticker": ticker, "category": category})
    return merged


def render_dashboard(config: dict, app_env: str, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    dashboard = result["dashboard"]

    render_section_title(
        "Marktstatus",
        f"Letzte Aktualisierung: {result.get('updated_at', 'offen')}",
    )
    timeframe_state_key = make_key(key_prefix, "timeframe_state")
    render_timeframe_buttons(
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        timeframe_state_key,
        key_prefix,
    )
    timeframe = st.selectbox(
        "Timeframe",
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        key=timeframe_state_key,
    )
    filtered = dashboard[dashboard["timeframe"] == timeframe]

    render_section_title(
        "Watchlist + Chart",
        "Mobile zuerst: Watchlist oben, Chart direkt darunter. Desktop nutzt links/rechts.",
    )
    st.markdown(
        "<div class='sensei-mobile-flow-note'>Tippe ein Symbol an. Der Chart laedt direkt darunter.</div>",
        unsafe_allow_html=True,
    )
    render_dashboard_watchlist_workbench(
        config,
        result,
        timeframe,
        timeframe_state_key,
        key_prefix=make_key(key_prefix, "watchlist_workbench"),
    )

    render_market_traffic_light(result, timeframe)
    render_data_quality_summary(
        result,
        timeframe,
        key_prefix=make_key(key_prefix, "data_quality"),
    )
    render_ui_feature_strip()

    render_section_title("Große Marktkarten", "SPY, QQQ, GLD und DAX als Score-Karten.")
    render_market_header_cards(filtered, key_prefix=make_key(key_prefix, "market_cards"))

    render_section_title("SPY / QQQ Synchronität", "Der wichtigste Risiko-Filter fuer den Tagesblick.")
    render_spy_qqq_sync(result, timeframe)

    top_col, alert_col = st.columns([1.35, 0.85], gap="large")
    with top_col:
        render_section_title("Top 5 Chancen", "Hoechste Scores aus Watchlist und Marktuebersicht.")
        render_top_opportunities(result, timeframe, key_prefix=make_key(key_prefix, "top_opportunities"))
    with alert_col:
        render_section_title("Alerts", "Pink markiert System-Erkennung und Breakout-Vorbereitung.")
        render_dashboard_alerts(
            config,
            result,
            timeframe,
            key_prefix=make_key(key_prefix, "alerts"),
        )

    render_section_title(
        "Marktcharts",
        "Detail-Grid fuer SPY, SPX500, QQQ, Nasdaq100, GLD, Gold und DAX.",
    )
    with st.expander("Marktchart-Grid anzeigen", expanded=False):
        if render_dashboard_market_charts(
            config,
            result,
            timeframe,
            key_prefix=make_key(key_prefix, "market_charts"),
        ):
            return

    render_section_title(
        "Market Summary / Watchlist Summary",
        "Kurzfassung fuer Hauptmaerkte und deine Watchlist.",
    )
    render_market_watchlist_summaries(
        result,
        timeframe,
        key_prefix=make_key(key_prefix, "summaries"),
    )

    render_section_title("Reports", "Analyse und CSV-Reports manuell aktualisieren.")
    render_action_button_area(config, app_env, key_prefix=make_key(key_prefix, "actions"))
    render_report_previews(config, compact=True, key_prefix=make_key(key_prefix, "report_previews"))

    with st.expander(f"Details anzeigen ({key_prefix})", expanded=False):
        render_analysis_table(filtered, key_prefix=make_key(key_prefix, "details_table"))
    with st.expander(f"Score-Chart anzeigen ({key_prefix})", expanded=False):
        render_score_chart(
            filtered,
            f"Dashboard Scores {timeframe}",
            key_prefix=make_key(key_prefix, "score_chart"),
        )


def render_dashboard_watchlist_workbench(
    config: dict,
    result: dict,
    timeframe: str,
    timeframe_state_key: str,
    key_prefix: str,
) -> None:
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    watchlist_id = ensure_dashboard_watchlist(config, store, email)
    display = dashboard_watchlist_display(config, store, email, watchlist_id, result, timeframe)
    if display.empty:
        render_empty_state(
            "Hauptliste ist leer",
            "Fuege oben links ein Symbol hinzu oder starte eine Analyse, damit die Watchlist gefuellt wird.",
        )
        return

    selected_key = make_key(key_prefix, "selected_ticker")
    available_tickers = display["ticker"].astype(str).str.upper().tolist()
    selected_ticker = str(st.session_state.get(selected_key, available_tickers[0])).upper()
    if selected_ticker not in available_tickers:
        selected_ticker = available_tickers[0]
        st.session_state[selected_key] = selected_ticker

    fullscreen_key = make_key(key_prefix, "fullscreen_mode")
    if fullscreen_key not in st.session_state:
        st.session_state[fullscreen_key] = False
    fullscreen_mode = bool(st.session_state.get(fullscreen_key, False))
    st.markdown("<div class='sensei-workbench-shell'>", unsafe_allow_html=True)
    if fullscreen_mode:
        render_dashboard_fullscreen_symbol_strip(
            display,
            selected_ticker,
            selected_key,
            key_prefix=make_key(key_prefix, "fullscreen_strip"),
        )
        render_dashboard_selected_chart(
            config,
            result,
            store,
            email,
            display,
            selected_ticker,
            timeframe,
            timeframe_state_key,
            fullscreen_key,
            fullscreen_mode=True,
            key_prefix=make_key(key_prefix, "chart"),
        )
    else:
        left, right = st.columns([1, 2.25], gap="large")
        with left:
            render_dashboard_watchlist_panel(
                config,
                store,
                email,
                watchlist_id,
                display,
                selected_ticker,
                selected_key,
                timeframe,
                key_prefix=make_key(key_prefix, "panel"),
            )
        with right:
            render_dashboard_selected_chart(
                config,
                result,
                store,
                email,
                display,
                selected_ticker,
                timeframe,
                timeframe_state_key,
                fullscreen_key,
                fullscreen_mode=False,
                key_prefix=make_key(key_prefix, "chart"),
            )
    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard_watchlist_panel(
    config: dict,
    store: WorkspaceStore,
    email: str,
    watchlist_id: str,
    display: pd.DataFrame,
    selected_ticker: str,
    selected_key: str,
    timeframe: str,
    key_prefix: str,
) -> None:
    st.markdown(
        (
            "<div class='sensei-watchlist-header'>"
            "<div>"
            "<div class='sensei-watchlist-title'>Watchlist</div>"
            "<div class='sensei-watch-meta'>Hauptindizes, Gold, Mag7 und eigene Symbole</div>"
            "</div>"
            f"{status_badge_html('Pink Alert', 'pink')}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    render_dashboard_add_symbol_form(
        store,
        email,
        watchlist_id,
        watchlist_categories(config),
        key_prefix=make_key(key_prefix, "add_symbol"),
    )

    if st.button(
        "Hauptliste analysieren",
        key=make_key(key_prefix, "analyze"),
        type="primary",
        width="stretch",
    ):
        _run_update_with_extra_symbols(config, display["ticker"].tolist())

    st.caption("Symbolbutton oeffnet sofort den Chart rechts. Hoch/Runter speichert deine Reihenfolge.")
    for index, row in enumerate(display.to_dict("records")):
        ticker = str(row.get("ticker", "")).upper()
        label = str(row.get("label") or ticker)
        score = row.get("score")
        score_label = "-" if score is None or pd.isna(score) else f"{int(float(score))}/100"
        trend = str(row.get("trend") or "offen")
        risk_state = str(row.get("risk_state") or "offen")
        data_status = str(row.get("data_status") or "unbekannt")
        active_class = " sensei-watch-row-active" if ticker == selected_ticker else ""
        st.markdown(
            (
                f"<div class='sensei-watch-row{active_class}'>"
                f"<div class='sensei-watch-symbol'>{escape(label)} · {escape(ticker)}</div>"
                f"<div class='sensei-watch-meta'>{escape(score_label)} · "
                f"{escape(trend)} · {escape(risk_state)} · Daten {escape(data_status)}</div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        col_open, col_up, col_down = st.columns([0.58, 0.21, 0.21])
        with col_open:
            if st.button(
                f"{ticker} oeffnen",
                key=make_key(key_prefix, "open", index, safe_widget_key(ticker)),
                width="stretch",
                type="primary" if ticker == selected_ticker else "secondary",
            ):
                st.session_state[selected_key] = ticker
                st.session_state.workspace_ticker = ticker
                st.session_state.workspace_timeframe = timeframe
                st.rerun()
        with col_up:
            if st.button(
                "Hoch",
                key=make_key(key_prefix, "up", index, row.get("id", ticker)),
                width="stretch",
                disabled=index == 0,
            ):
                store.move_watchlist_symbol(email, watchlist_id, str(row.get("id")), "up")
                st.rerun()
        with col_down:
            if st.button(
                "Runter",
                key=make_key(key_prefix, "down", index, row.get("id", ticker)),
                width="stretch",
                disabled=index >= len(display) - 1,
            ):
                store.move_watchlist_symbol(email, watchlist_id, str(row.get("id")), "down")
                st.rerun()


def render_dashboard_add_symbol_form(
    store: WorkspaceStore,
    email: str,
    watchlist_id: str,
    categories: list[str],
    key_prefix: str,
) -> None:
    with st.expander("+ Symbol aufnehmen", expanded=False):
        render_alert_badge("Pink Alert: Beobachten")
        with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
            symbol = st.text_input(
                "Ticker",
                placeholder="z.B. BTC-USD, IWM, V, EURUSD=X",
                key=make_key(key_prefix, "ticker"),
            )
            category = st.selectbox(
                "Kategorie",
                categories,
                index=safe_index(categories, "Eigene Ideen"),
                key=make_key(key_prefix, "category"),
            )
            note = st.text_input(
                "Notiz optional",
                placeholder="Warum soll das auf die Hauptliste?",
                key=make_key(key_prefix, "note"),
            )
            pinned = st.checkbox(
                "Pin",
                value=False,
                key=make_key(key_prefix, "pin"),
            )
            submitted = st.form_submit_button(
                "Speichern",
                key=make_key(key_prefix, "submit"),
                width="stretch",
            )
            if submitted:
                try:
                    symbol_id = store.add_watchlist_symbol(
                        email=email,
                        watchlist_id=watchlist_id,
                        ticker=symbol,
                        category=category,
                        note=note,
                        pinned=pinned,
                    )
                    store.normalize_watchlist_order(email, watchlist_id)
                    store.record_event(email, "dashboard_watchlist_symbol_saved", symbol, "", symbol_id)
                    st.success("Symbol gespeichert. Analyse startet erst, wenn du Hauptliste analysieren klickst.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Symbol konnte nicht gespeichert werden: {exc}")


def render_dashboard_fullscreen_symbol_strip(
    display: pd.DataFrame,
    selected_ticker: str,
    selected_key: str,
    key_prefix: str,
) -> None:
    available_tickers = display["ticker"].astype(str).str.upper().tolist()
    label_map = {
        str(row.get("ticker", "")).upper(): str(row.get("label") or row.get("ticker", ""))
        for row in display.to_dict("records")
    }
    selected_index = safe_index(available_tickers, selected_ticker)
    st.markdown(
        (
            "<div class='sensei-fullscreen-strip'>"
            "<span class='sensei-fullscreen-strip-title'>Vollbild-Arbeitsflaeche</span>"
            f"{status_badge_html(selected_ticker, 'pink')}"
            f"{status_badge_html('Watchlist-Schnellwechsel', 'blue')}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    select_col, quick_col = st.columns([0.32, 0.68], gap="large")
    with select_col:
        selected = st.selectbox(
            "Symbol",
            available_tickers,
            index=selected_index,
            format_func=lambda value: f"{label_map.get(value, value)} | {value}",
            key=make_key(key_prefix, "select_symbol"),
        )
        if selected != selected_ticker:
            st.session_state[selected_key] = selected
            st.session_state.workspace_ticker = selected
            st.rerun()

    with quick_col:
        quick_symbols = available_tickers[:12]
        columns = st.columns(min(6, max(1, len(quick_symbols))))
        for index, ticker in enumerate(quick_symbols):
            with columns[index % len(columns)]:
                if st.button(
                    ticker,
                    key=make_key(key_prefix, "quick_symbol", index, safe_widget_key(ticker)),
                    width="stretch",
                    type="primary" if ticker == selected_ticker else "secondary",
                ):
                    st.session_state[selected_key] = ticker
                    st.session_state.workspace_ticker = ticker
                    st.rerun()


def render_dashboard_selected_chart(
    config: dict,
    result: dict,
    store: WorkspaceStore,
    email: str,
    display: pd.DataFrame,
    selected_ticker: str,
    timeframe: str,
    timeframe_state_key: str,
    fullscreen_key: str,
    fullscreen_mode: bool,
    key_prefix: str,
) -> None:
    selected_rows = display[display["ticker"].astype(str).str.upper() == selected_ticker]
    label = selected_ticker if selected_rows.empty else str(selected_rows.iloc[0].get("label") or selected_ticker)
    row = analysis_row_for_ticker(result, selected_ticker, timeframe)
    chart_lines = store.list_chart_lines(email, selected_ticker, timeframe)
    line_count = len(chart_lines) if not chart_lines.empty else 0
    line_badge_kind = "pink" if line_count else "gray"

    st.markdown(
        (
            "<div class='sensei-chart-workspace-header'>"
            "<div>"
            f"<div class='sensei-chart-workspace-title'>{escape(label)} | {escape(selected_ticker)}</div>"
            f"<div class='sensei-chart-workspace-meta'>Arbeitsflaeche fuer {escape(timeframe)}. "
            "Linien werden pro Symbol und Timeframe gespeichert.</div>"
            "</div>"
            "<div class='sensei-chart-badge-row'>"
            f"{status_badge_html('Vollbild' if fullscreen_mode else 'Workspace', 'pink' if fullscreen_mode else 'blue')}"
            f"{status_badge_html(f'{line_count} Linien geladen', line_badge_kind)}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    top_left, top_right = st.columns([0.64, 0.36], gap="large")
    with top_left:
        if row:
            trend_badge = status_badge_html(
                str(row.get("trend", "neutral")),
                status_color(row.get("trend", "neutral")),
            )
            risk_badge = status_badge_html(
                str(row.get("risk_state", "offen")),
                status_color(row.get("risk_state", "offen")),
            )
            data_badge = status_badge_html(
                f"Daten {row.get('data_status', 'unbekannt')}",
                data_status_color(str(row.get("data_status", "unbekannt"))),
            )
            st.markdown(
                f"{trend_badge} {risk_badge} {data_badge}",
                unsafe_allow_html=True,
            )
        else:
            st.info("Noch keine Analyse fuer dieses Symbol. Klicke links auf Hauptliste analysieren.")
        render_timeframe_buttons(
            config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"]),
            timeframe_state_key,
            key_prefix=make_key(key_prefix, "timeframe_buttons", safe_widget_key(selected_ticker)),
            result=result,
            ticker=selected_ticker,
        )
        render_timeframe_trend_strip(
            config,
            result,
            selected_ticker,
            timeframe,
            key_prefix=make_key(key_prefix, "timeframe_trends", safe_widget_key(selected_ticker)),
        )
        chart_type = st.radio(
            "Charttyp",
            ["Kerzen", "Linie"],
            horizontal=True,
            key=make_key(key_prefix, "chart_type", safe_widget_key(selected_ticker), timeframe),
        )
        st.checkbox(
            "Vollbild Arbeitsflaeche",
            key=fullscreen_key,
        )
    with top_right:
        render_chart_score_box(row, key_prefix=make_key(key_prefix, "score_box", selected_ticker, timeframe))

    if fullscreen_mode:
        st.markdown("<div class='sensei-fullscreen-panel'>", unsafe_allow_html=True)

    render_symbol_chart(
        config,
        result,
        selected_ticker,
        timeframe,
        store,
        email,
        key_prefix=make_key(
            key_prefix,
            safe_widget_key(selected_ticker),
            timeframe,
            chart_type,
            "fullscreen" if fullscreen_mode else "normal",
        ),
        chart_type=chart_type,
        height=920 if fullscreen_mode else 720,
    )

    if fullscreen_mode:
        st.markdown("</div>", unsafe_allow_html=True)


def render_chart_score_box(row: dict, key_prefix: str) -> None:
    if not row:
        with st.popover(
            "Bewertung --/100",
            help="Klicken fuer die Punkte-Erklaerung. Klick ausserhalb schliesst.",
            use_container_width=True,
        ):
            st.info("Starte eine Analyse, damit die Punkte-Bausteine geladen werden.")
        return

    score = int(safe_float(row.get("score"), 0))
    breakdown = chart_score_breakdown(row)
    rows_html = "".join(
        (
            "<div class='sensei-score-breakdown-row'>"
            f"<span>{escape(label)}</span>"
            f"<span class='sensei-score-breakdown-points'>{int(points)}</span>"
            "</div>"
        )
        for label, points in breakdown
    )
    explanation = chart_score_explanation(row)
    with st.popover(
        f"Bewertung {score}/100",
        help="Klicken fuer die Punkte-Erklaerung. Klick ausserhalb schliesst.",
        use_container_width=True,
    ):
        st.markdown(
            f"""
            <div class="sensei-score-popover-head">
                <div class="sensei-chart-score-label">Bewertung</div>
                <div class="sensei-chart-score-value">{score}/100</div>
                <div class="sensei-score-breakdown-note">{escape(explanation)}</div>
            </div>
            <div class="sensei-score-breakdown">{rows_html}</div>
            """,
            unsafe_allow_html=True,
        )


def chart_score_breakdown(row: dict) -> list[tuple[str, int]]:
    items = [
        ("SPY Trend", row.get("spy_trend_points")),
        ("QQQ Trend", row.get("qqq_trend_points")),
        ("SPY + QQQ", row.get("market_alignment_points")),
        ("Mag7", row.get("mag7_points")),
        ("Sektor-Staerke", row.get("sector_strength_points")),
        ("EMA20", row.get("ema20_points")),
        ("EMA50", row.get("ema50_points")),
        ("EMA100", row.get("ema100_points")),
        ("EMA200", row.get("ema200_points")),
        ("Relative Staerke", row.get("relative_strength_points")),
        ("Trendfolge", row.get("trend_following_points")),
    ]
    return [(label, int(safe_float(value, 0))) for label, value in items]


def chart_score_explanation(row: dict) -> str:
    trend = str(row.get("trend", "offen"))
    risk = str(row.get("risk_state", "offen"))
    close = safe_optional_float(row.get("close"))
    ema20 = safe_optional_float(row.get("ema_20"))
    ema50 = safe_optional_float(row.get("ema_50"))
    rs = safe_optional_float(row.get("relative_strength"))
    parts = [f"Trend: {trend}", f"Risk State: {risk}"]
    if close is not None and ema20 is not None and ema50 is not None:
        ema_state = "ueber EMA20/50" if close > ema20 and close > ema50 else "nicht sauber ueber EMA20/50"
        parts.append(ema_state)
    if rs is not None:
        parts.append(f"RS vs Benchmark: {rs:.2f}")
    return " | ".join(parts)


def ensure_dashboard_watchlist(config: dict, store: WorkspaceStore, email: str) -> str:
    categories = watchlist_categories(config)
    store.ensure_default_watchlists(email, categories)
    watchlists = store.list_watchlists(email)
    matches = watchlists[watchlists["name"].astype(str) == DASHBOARD_WATCHLIST_NAME]
    if matches.empty:
        watchlist_id = store.save_watchlist(
            email=email,
            name=DASHBOARD_WATCHLIST_NAME,
            category="Eigene Ideen",
            pinned=True,
        )
    else:
        watchlist_id = str(matches.iloc[0]["id"])

    existing = store.list_watchlist_symbols(email, watchlist_id)
    existing_tickers = set(existing["ticker"].astype(str).str.upper().tolist()) if not existing.empty else set()
    for item in dashboard_seed_symbols(config):
        ticker = item["ticker"]
        if ticker.upper() in existing_tickers:
            continue
        store.add_watchlist_symbol(
            email=email,
            watchlist_id=watchlist_id,
            ticker=ticker,
            category=item["category"],
            note=item["label"],
            pinned=item["category"] in ["Indizes", "Gold"],
        )
        existing_tickers.add(ticker.upper())
    store.normalize_watchlist_order(email, watchlist_id)
    return watchlist_id


def dashboard_seed_symbols(config: dict) -> list[dict]:
    seeds = []
    seen = set()
    for entry in config.get("dashboard_symbols", DEFAULT_DASHBOARD_SYMBOLS):
        label = str(entry.get("label", entry.get("ticker", ""))) if isinstance(entry, dict) else str(entry)
        ticker = str(entry.get("ticker", label)) if isinstance(entry, dict) else str(entry)
        cleaned = ticker.strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seeds.append(
            {
                "label": label.strip() or cleaned,
                "ticker": cleaned,
                "category": dashboard_symbol_category(cleaned, label),
            }
        )
        seen.add(cleaned)

    for symbol in ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]:
        if symbol not in seen:
            seeds.append({"label": symbol, "ticker": symbol, "category": "Aktien"})
            seen.add(symbol)

    for symbol in config.get("watchlist", []):
        cleaned = str(symbol).strip().upper()
        if cleaned and cleaned not in seen:
            seeds.append({"label": cleaned, "ticker": cleaned, "category": "Aktien"})
            seen.add(cleaned)

    for entry in config.get("sector_rotation_symbols", DEFAULT_SECTOR_ROTATION_SYMBOLS):
        if isinstance(entry, dict):
            label = str(entry.get("label", entry.get("ticker", ""))).strip()
            ticker = str(entry.get("ticker", label)).strip().upper()
            category = str(entry.get("category", "Sektoren")).strip() or "Sektoren"
        else:
            label = str(entry).strip()
            ticker = label.upper()
            category = "Sektoren"
        if ticker and ticker not in seen:
            seeds.append({"label": label or ticker, "ticker": ticker, "category": category})
            seen.add(ticker)
    return seeds


def dashboard_symbol_category(ticker: str, label: str) -> str:
    text = f"{ticker} {label}".upper()
    if "GLD" in text or "GOLD" in text or "GC=F" in text:
        return "Gold"
    if ticker.startswith("^") or ticker in {"SPY", "QQQ", "DIA", "IWM"}:
        return "Indizes"
    if ticker.endswith("-USD") or ticker.endswith("USDT"):
        return "Krypto"
    return "Aktien"


def dashboard_watchlist_display(
    config: dict,
    store: WorkspaceStore,
    email: str,
    watchlist_id: str,
    result: dict,
    timeframe: str,
) -> pd.DataFrame:
    symbols = store.list_watchlist_symbols(email, watchlist_id)
    if symbols.empty:
        return pd.DataFrame()

    label_map = {item["ticker"].upper(): item["label"] for item in dashboard_seed_symbols(config)}
    rows = []
    for _, saved in symbols.iterrows():
        ticker = str(saved.get("ticker", "")).upper()
        analysis = analysis_row_for_ticker(result, ticker, timeframe)
        rows.append(
            {
                "id": saved.get("id"),
                "ticker": ticker,
                "label": label_map.get(ticker, saved.get("note") or ticker),
                "category": saved.get("category", ""),
                "pinned": bool(saved.get("pinned")),
                "score": safe_optional_float(analysis.get("score")),
                "trend": analysis.get("trend", "nicht analysiert"),
                "risk_state": analysis.get("risk_state", "offen"),
                "close": safe_optional_float(analysis.get("close")),
                "relative_strength": safe_optional_float(analysis.get("relative_strength")),
                "data_status": analysis.get("data_status", "unbekannt"),
                "last_clean_date": analysis.get("last_clean_date", ""),
            }
        )
    return pd.DataFrame(rows)


def render_market_header_cards(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        render_empty_state("Keine Marktdaten", "Klicke Analysieren, um die Header-Karten zu laden.")
        return
    preferred = ["SPY", "QQQ", "GLD", "^GDAXI"]
    all_rows = df.to_dict("records")
    rows = []
    used = set()
    for ticker in preferred:
        for row in all_rows:
            row_ticker = str(row.get("ticker", "")).upper()
            if row_ticker == ticker and row_ticker not in used:
                rows.append(row)
                used.add(row_ticker)
                break
    for row in all_rows:
        row_ticker = str(row.get("ticker", "")).upper()
        if row_ticker and row_ticker not in used:
            rows.append(row)
            used.add(row_ticker)
        if len(rows) >= 4:
            break
    columns = st.columns(4)
    for index, column in enumerate(columns):
        row = rows[index] if index < len(rows) else {}
        with column:
            render_score_card(row, title=str(row.get("label", row.get("ticker", "offen"))))


def render_dashboard_market_charts(
    config: dict,
    result: dict,
    timeframe: str,
    key_prefix: str,
) -> bool:
    mode = st.radio(
        "Chartmodus",
        ["Grid", "Vollbild"],
        horizontal=True,
        key=make_key(key_prefix, "mode"),
    )
    groups = MARKET_CHART_GROUPS
    if mode == "Vollbild":
        symbols = [
            (f"{group['title']} - {label}", label, ticker)
            for group in groups
            for label, ticker in group["symbols"]
        ]
        labels = [item[0] for item in symbols]
        selected = st.selectbox(
            "Vollbild-Chart",
            labels,
            key=make_key(key_prefix, "fullscreen_symbol"),
        )
        _, label, ticker = symbols[safe_index(labels, selected)]
        st.markdown("<div class='sensei-fullscreen-panel'>", unsafe_allow_html=True)
        render_market_symbol_chart(
            config,
            result,
            label,
            ticker,
            timeframe,
            key_prefix=make_key(key_prefix, "fullscreen", safe_widget_key(ticker)),
            height=780,
            trade_expanded=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return True

    for group in groups:
        st.markdown(f"#### {group['title']}")
        columns = st.columns(len(group["symbols"]))
        for column, (label, ticker) in zip(columns, group["symbols"]):
            with column:
                render_market_symbol_chart(
                    config,
                    result,
                    label,
                    ticker,
                    timeframe,
                    key_prefix=make_key(key_prefix, "grid", safe_widget_key(ticker)),
                    height=430,
                    trade_expanded=False,
                )
    return False


def render_market_symbol_chart(
    config: dict,
    result: dict,
    label: str,
    ticker: str,
    timeframe: str,
    key_prefix: str,
    height: int,
    trade_expanded: bool,
) -> None:
    history = chart_history(config, result, ticker, timeframe)
    row = analysis_row_for_ticker(result, ticker, timeframe)
    st.markdown("<div class='sensei-chart-card'>", unsafe_allow_html=True)
    if row:
        score = int(safe_float(row.get("score"), 0))
        tier_label, _, tier_color = score_tier(score)
        st.markdown(
            f"{status_badge_html(label, 'blue')} "
            f"{status_badge_html(f'{score}/100 {tier_label}', tier_color)} "
            f"{status_badge_html(str(row.get('trend', 'neutral')), status_color(row.get('trend', 'neutral')))}",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"{status_badge_html(label, 'blue')} {status_badge_html('Chartdaten', 'gray')}",
            unsafe_allow_html=True,
        )

    if history.empty:
        render_empty_state("Chart fehlt", f"{label} ({ticker}) konnte nicht geladen werden.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    history = history.sort_values("date").tail(chart_point_limit(timeframe)).copy()
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.74, 0.26],
    )
    volume_colors = [
        "#22c55e" if close >= open_price else "#f43f5e"
        for close, open_price in zip(history["close"], history["open"])
    ]
    fig.add_trace(
        go.Candlestick(
            x=history["date"],
            open=history["open"],
            high=history["high"],
            low=history["low"],
            close=history["close"],
            name=label,
            increasing_line_color="#22c55e",
            decreasing_line_color="#f43f5e",
        ),
        row=1,
        col=1,
    )
    ema_styles = {
        "ema_20": ("EMA20", "#38bdf8"),
        "ema_50": ("EMA50", "#facc15"),
        "ema_100": ("EMA100", "#a78bfa"),
        "ema_200": ("EMA200", "#e5e7eb"),
    }
    for column, (ema_label, color) in ema_styles.items():
        if column in history:
            fig.add_trace(
                go.Scatter(
                    x=history["date"],
                    y=history[column],
                    mode="lines",
                    name=ema_label,
                    line=dict(width=1.25, color=color),
                    connectgaps=True,
                ),
                row=1,
                col=1,
            )
    fig.add_trace(
        go.Bar(
            x=history["date"],
            y=history["volume"],
            name="Volumen",
            marker_color=volume_colors,
            opacity=0.42,
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        title=f"{label} ({ticker}) {timeframe}",
        height=height,
        margin=dict(l=10, r=10, t=42, b=10),
        hovermode="x unified",
        dragmode="pan",
        newshape=dict(line_color=SYSTEM_ALERT_COLOR, line_width=2),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        uirevision=f"dashboard-{ticker}-{timeframe}",
    )
    style_plotly_figure(fig)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_yaxes(title_text="Preis", row=1, col=1)
    fig.update_yaxes(title_text="Volumen", row=2, col=1)
    render_plotly_chart(
        fig,
        key=make_key(key_prefix, "plotly", ticker, timeframe),
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": ["drawline", "eraseshape"],
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        },
    )
    with st.expander(
        f"Trade-Plan vorbereiten ({label})",
        expanded=trade_expanded,
    ):
        render_prepared_trade_ticket(
            config,
            result,
            ticker,
            timeframe,
            key_prefix=make_key(key_prefix, "trade_ticket", safe_widget_key(ticker), timeframe),
            default_price=safe_float(history["close"].iloc[-1], 1.0),
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_prepared_trade_ticket(
    config: dict,
    result: dict,
    ticker: str,
    timeframe: str,
    key_prefix: str,
    default_price: float,
) -> None:
    st.caption(
        "Vorbereitung fuer spaetere Interactive-Brokers-Anbindung. "
        "Jetzt wird nur ein Journal-Eintrag gespeichert, keine Order ausgefuehrt."
    )
    render_alert_badge("Pink Alert: Trade-Plan")
    tracker = _tracker(config)
    setup_categories = tracking_setup_categories(config)
    rule_options = tracking_rule_options(config)
    analysis_row = analysis_row_for_ticker(result, ticker, timeframe)
    market_status = market_traffic_light(result, timeframe)
    plan_preview = execution_plan(ticker, "papertrading", config)
    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html('Broker-Planung', 'pink')}
            {status_badge_html(plan_preview['asset_class'], 'blue')}
            {status_badge_html(plan_preview['recommended_provider'], 'gray')}
            <span class="sensei-muted" style="margin-left:.35rem;">Prepared only. Keine API. Keine Ausfuehrung.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            account_type = st.selectbox(
                "Modus",
                ["papertrading", "real_money"],
                format_func=lambda value: "Papertrading" if value == "papertrading" else "Real Money",
                key=make_key(key_prefix, "account_type"),
            )
        with col2:
            direction = st.selectbox(
                "Richtung",
                ["long", "short"],
                format_func=lambda value: value.upper(),
                key=make_key(key_prefix, "direction"),
            )
        with col3:
            quantity = st.number_input(
                "Groesse",
                min_value=0.0001,
                value=float(config.get("tracking", {}).get("default_quantity", 1.0)),
                step=1.0,
                key=make_key(key_prefix, "quantity"),
            )

        col4, col5, col6 = st.columns(3)
        with col4:
            entry_price = st.number_input(
                "Referenzpreis",
                min_value=0.01,
                value=max(float(default_price), 0.01),
                step=0.01,
                key=make_key(key_prefix, "entry_price"),
            )
        with col5:
            stop_price = st.number_input(
                "Stop optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=make_key(key_prefix, "stop_price"),
            )
        with col6:
            target_price = st.number_input(
                "Ziel optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=make_key(key_prefix, "target_price"),
            )

        col7, col8 = st.columns(2)
        with col7:
            setup_category = st.selectbox(
                "Setup",
                setup_categories,
                index=safe_index(setup_categories, "Trendfolge"),
                key=make_key(key_prefix, "setup_category"),
            )
        with col8:
            entry_date = st.date_input(
                "Datum",
                value=pd.Timestamp.today().date(),
                key=make_key(key_prefix, "entry_date"),
            )

        thesis = st.text_area(
            "Notiz",
            placeholder="Warum wird dieser Trade-Plan gespeichert?",
            key=make_key(key_prefix, "thesis"),
        )
        automatic_violations = auto_rule_violations(
            config=config,
            analysis_row=analysis_row,
            market_status=market_status,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            thesis=thesis,
        )
        render_auto_rule_violations(automatic_violations)
        rule_violations = st.multiselect(
            "Zusaetzliche Regelverletzungen",
            merge_rule_options(rule_options, automatic_violations),
            key=make_key(key_prefix, "rule_violations"),
        )
        submitted = st.form_submit_button(
            "Trade-Plan speichern",
            key=make_key(key_prefix, "submit"),
            width="stretch",
        )
        if submitted:
            try:
                plan = execution_plan(ticker, account_type, config)
                enriched_thesis = (
                    f"{thesis.strip()}\n\n"
                    f"Broker-Plan: {plan['recommended_provider']} | "
                    f"Asset: {plan['asset_class']} | Status: {plan['routing_state']} | "
                    "Keine API-Ausfuehrung."
                ).strip()
                entry_id = tracker.add_entry(
                    account_type=account_type,
                    ticker=ticker,
                    direction=direction,
                    quantity=quantity,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    stop_price=stop_price,
                    target_price=target_price,
                    timeframe=timeframe,
                    thesis=enriched_thesis,
                    setup_category=setup_category,
                    rule_violations=merge_rule_options(automatic_violations, rule_violations),
                    analysis_row=analysis_row,
                )
                tracker.record_snapshots(account_type, result, result["updated_at"])
                st.success(
                    f"Trade-Plan gespeichert: {ticker} ({entry_id[:8]}). Keine Order ausgefuehrt."
                )
            except Exception as exc:
                logger.exception("Could not save prepared trade")
                st.error(f"Trade-Plan konnte nicht gespeichert werden: {exc}")


def render_spy_qqq_sync(result: dict, timeframe: str) -> None:
    spy = analysis_row_for_ticker(result, "SPY", timeframe)
    qqq = analysis_row_for_ticker(result, "QQQ", timeframe)
    if not spy or not qqq:
        render_empty_state("Synchronität offen", "SPY oder QQQ fehlen fuer diesen Timeframe.")
        return

    spy_trend = str(spy.get("trend", "neutral"))
    qqq_trend = str(qqq.get("trend", "neutral"))
    same_direction = spy_trend == qqq_trend
    avg_score = (safe_float(spy.get("score")) + safe_float(qqq.get("score"))) / 2
    label = "Synchron" if same_direction else "Nicht synchron"
    badge_kind = "green" if same_direction else "yellow"
    st.markdown(
        f"""
        <div class="sensei-sync-card">
            <div class="sensei-score-head">
                <div>
                    <div class="sensei-score-symbol">SPY / QQQ</div>
                    <div class="sensei-score-label">Trendfilter fuer neue Ideen</div>
                </div>
                {status_badge_html(label, badge_kind)}
            </div>
            <div class="sensei-score-value">{avg_score:.0f}/100</div>
            <div class="sensei-score-meta">
                <span>SPY {status_badge_html(spy_trend, status_color(spy_trend))}</span>
                <span>QQQ {status_badge_html(qqq_trend, status_color(qqq_trend))}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_top_opportunities(result: dict, timeframe: str, key_prefix: str) -> None:
    frames = [
        result.get("watchlist", pd.DataFrame()),
        result.get("dashboard", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        render_empty_state("Keine Chancen", "Klicke Analysieren, um Kandidaten zu berechnen.")
        return
    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["timeframe"] == timeframe].copy()
    if combined.empty:
        render_empty_state("Keine Chancen", "Fuer diesen Timeframe liegen noch keine Kandidaten vor.")
        return
    combined = combined.sort_values("score", ascending=False).drop_duplicates("ticker").head(5)
    render_watchlist_badge_table(combined, key_prefix=key_prefix, compact=True)


def render_dashboard_alerts(config: dict, result: dict, timeframe: str, key_prefix: str) -> None:
    active_alerts = [
        alert
        for alert in build_system_alerts(config, result)
        if alert.get("timeframe") == timeframe
        and not (
            alert.get("alert_type") == "market_status"
            and alert.get("current_value") == "ok"
        )
    ]
    active_alerts = sorted(active_alerts, key=alert_priority)[:5]
    if active_alerts:
        for alert in active_alerts:
            render_system_alert_card(alert)
        render_alert_history(config, timeframe, key_prefix=make_key(key_prefix, "history"))
        return

    frames = [
        result.get("watchlist", pd.DataFrame()),
        result.get("dashboard", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        render_empty_state("Keine Alerts", "Noch keine Analyse geladen.")
        return
    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["timeframe"] == timeframe].copy()
    alert_rows = []
    for _, row in combined.sort_values("score", ascending=False).iterrows():
        tags = system_alert_tags(row)
        risk = str(row.get("risk_state", ""))
        if tags or risk in ["BLOCKED", "REDUCED"]:
            alert_rows.append((row, tags))
        if len(alert_rows) >= 4:
            break
    if not alert_rows:
        st.markdown(
            "<div class='sensei-alert-card'>Keine aktiven System-Alerts fuer diesen Timeframe.</div>",
            unsafe_allow_html=True,
        )
        return
    for row, tags in alert_rows:
        tag_html = "".join(status_badge_html(tag, "pink") for tag in tags[:3]) or status_badge_html(
            str(row.get("risk_state", "offen")),
            status_color(row.get("risk_state", "offen")),
        )
        st.markdown(
            f"""
            <div class="sensei-alert-card">
                <div class="sensei-score-head">
                    <div>
                        <div class="sensei-score-symbol">{escape(str(row.get('ticker', '')))}</div>
                        <div class="sensei-score-label">Score {int(safe_float(row.get('score'), 0))}/100</div>
                    </div>
                    <div>{tag_html}</div>
                </div>
            </div>
            """,
        unsafe_allow_html=True,
    )
    render_alert_history(config, timeframe, key_prefix=make_key(key_prefix, "history"))


def alert_priority(alert: dict) -> tuple[int, str]:
    order = {
        "market_status": 0,
        "breakout": 1,
        "ema_cross": 2,
        "relative_strength_shift": 3,
    }
    return (
        order.get(str(alert.get("alert_type", "")), 9),
        str(alert.get("ticker", "")),
    )


def render_system_alert_card(alert: dict) -> None:
    ticker = str(alert.get("ticker") or "MARKET")
    timeframe = str(alert.get("timeframe") or "")
    title = str(alert.get("title") or "System-Alert")
    detail = str(alert.get("detail") or "")
    alert_type = str(alert.get("alert_type") or "system")
    st.markdown(
        f"""
        <div class="sensei-alert-card">
            <div class="sensei-score-head">
                <div>
                    <div class="sensei-score-symbol">{escape(ticker)}</div>
                    <div class="sensei-score-label">{escape(timeframe)} · {escape(detail)}</div>
                </div>
                <div>
                    {status_badge_html(title, 'pink')}
                    {status_badge_html(alert_type.replace('_', ' '), 'pink')}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_alert_history(config: dict, timeframe: str, key_prefix: str) -> None:
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    history = store.recent_system_alerts(email, limit=30, timeframe=timeframe)
    with st.expander("Alert-Historie", expanded=False):
        render_system_alert_panel(
            "Pink Alert-Historie",
            "Gespeichert werden Marktstatus-Wechsel, Breakouts, EMA-Crosses und Relative-Staerke-Wechsel. Keine Orders.",
        )
        if history.empty:
            render_empty_state(
                "Noch keine Alert-Historie",
                "Starte eine Analyse. Neue oder geaenderte Systemsignale werden hier gespeichert.",
            )
            return
        display = history[
            [
                "created_at",
                "alert_type",
                "ticker",
                "timeframe",
                "title",
                "current_value",
                "previous_value",
                "detail",
            ]
        ].copy()
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "dataframe"),
            column_config={
                "created_at": "Zeit",
                "alert_type": "Typ",
                "ticker": "Symbol",
                "timeframe": "TF",
                "title": "Alert",
                "current_value": "Aktuell",
                "previous_value": "Vorher",
                "detail": "Detail",
            },
        )


def render_market_watchlist_summaries(result: dict, timeframe: str, key_prefix: str) -> None:
    market_summary = build_frame_summary(
        result.get("dashboard", pd.DataFrame()),
        timeframe,
        title="Market Summary",
    )
    watchlist_summary = build_frame_summary(
        result.get("watchlist", pd.DataFrame()),
        timeframe,
        title="Watchlist Summary",
    )

    col_market, col_watchlist = st.columns(2)
    with col_market:
        render_summary_card(market_summary, key_prefix=make_key(key_prefix, "market"))
    with col_watchlist:
        render_summary_card(watchlist_summary, key_prefix=make_key(key_prefix, "watchlist"))


def build_frame_summary(df: pd.DataFrame, timeframe: str, title: str) -> dict:
    if df is None or df.empty or "timeframe" not in df:
        return {
            "title": title,
            "timeframe": timeframe,
            "count": 0,
            "average_score": 0.0,
            "bullish_count": 0,
            "neutral_count": 0,
            "bearish_count": 0,
            "ok_count": 0,
            "reduced_count": 0,
            "blocked_count": 0,
            "top_symbol": "offen",
            "top_score": 0.0,
            "weak_symbol": "offen",
            "weak_score": 0.0,
            "positive_rs_count": 0,
            "state": "offen",
            "state_color": "gray",
        }

    frame = df[df["timeframe"] == timeframe].copy()
    if frame.empty:
        return build_frame_summary(pd.DataFrame(), timeframe, title)

    if "score" in frame:
        frame["score_numeric"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0)
    else:
        frame["score_numeric"] = 0
    if "relative_strength" in frame:
        frame["rs_numeric"] = pd.to_numeric(frame["relative_strength"], errors="coerce").fillna(0)
    else:
        frame["rs_numeric"] = 0

    trend = frame.get("trend", pd.Series(dtype=str)).astype(str).str.lower()
    risk = frame.get("risk_state", pd.Series(dtype=str)).astype(str).str.upper()
    top = frame.sort_values("score_numeric", ascending=False).iloc[0]
    weak = frame.sort_values("score_numeric", ascending=True).iloc[0]
    average_score = float(frame["score_numeric"].mean())
    blocked_count = int((risk == "BLOCKED").sum())
    reduced_count = int((risk == "REDUCED").sum())
    ok_count = int((risk == "OK").sum())

    if blocked_count > 0 or average_score < 50:
        state = "Blockiert"
        state_color = "red"
    elif reduced_count > ok_count or average_score < 70:
        state = "Vorsicht"
        state_color = "yellow"
    else:
        state = "OK"
        state_color = "green"

    return {
        "title": title,
        "timeframe": timeframe,
        "count": int(len(frame)),
        "average_score": average_score,
        "bullish_count": int((trend == "bullish").sum()),
        "neutral_count": int((trend == "neutral").sum()),
        "bearish_count": int((trend == "bearish").sum()),
        "ok_count": ok_count,
        "reduced_count": reduced_count,
        "blocked_count": blocked_count,
        "top_symbol": str(top.get("ticker", "offen")),
        "top_score": float(top.get("score_numeric", 0)),
        "weak_symbol": str(weak.get("ticker", "offen")),
        "weak_score": float(weak.get("score_numeric", 0)),
        "positive_rs_count": int((frame["rs_numeric"] > 0).sum()),
        "state": state,
        "state_color": state_color,
    }


def render_summary_card(summary: dict, key_prefix: str) -> None:
    score = int(safe_float(summary.get("average_score"), 0))
    top_symbol = summary.get("top_symbol", "offen")
    weak_symbol = summary.get("weak_symbol", "offen")
    state = summary.get("state", "offen")
    state_color = summary.get("state_color", "gray")
    st.markdown(
        f"""
        <div class="sensei-card">
            <div class="sensei-score-head">
                <div>
                    <div class="sensei-score-symbol">{escape(str(summary.get('title', 'Summary')))}</div>
                    <div class="sensei-score-label">{escape(str(summary.get('timeframe', '')))} · {int(summary.get('count', 0))} Symbole</div>
                </div>
                {status_badge_html(state, state_color)}
            </div>
            <div class="sensei-score-value">{score}/100</div>
            <div class="sensei-score-meta">
                <span>Bullish {int(summary.get('bullish_count', 0))}</span>
                <span>Neutral {int(summary.get('neutral_count', 0))}</span>
                <span>Bearish {int(summary.get('bearish_count', 0))}</span>
            </div>
            <div class="sensei-score-meta" style="margin-top:.45rem;">
                <span>OK {int(summary.get('ok_count', 0))}</span>
                <span>Reduced {int(summary.get('reduced_count', 0))}</span>
                <span>Blocked {int(summary.get('blocked_count', 0))}</span>
            </div>
            <div class="sensei-score-meta" style="margin-top:.45rem;">
                <span>Top {escape(str(top_symbol))} {int(safe_float(summary.get('top_score'), 0))}</span>
                <span>Weak {escape(str(weak_symbol))} {int(safe_float(summary.get('weak_score'), 0))}</span>
                <span>RS+ {int(summary.get('positive_rs_count', 0))}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_today_home(config: dict, app_env: str, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    store.ensure_default_watchlists(email, watchlist_categories(config))
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])

    render_section_title(
        "Heute ansehen",
        "Erst Ampel, dann die wichtigsten Kandidaten, Alerts und gespeicherten Screens.",
    )
    timeframe_state_key = make_key(key_prefix, "timeframe")
    render_timeframe_buttons(timeframes, timeframe_state_key, make_key(key_prefix, "timeframe_buttons"))
    timeframe = st.session_state.get(timeframe_state_key, timeframes[0])
    candidates = today_candidates(result, timeframe)
    topics = store.list_topics(email)

    render_today_importance_cards(
        result=result,
        candidates=candidates,
        topics=topics,
        timeframe=timeframe,
        key_prefix=make_key(key_prefix, "importance"),
    )
    render_market_traffic_light(result, timeframe)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button(
            "Analysieren",
            key=make_key(key_prefix, "analyze"),
            type="primary",
            width="stretch",
        ):
            _run_update(config, generate_reports=True)
            store.record_event(email, "today_home_analyze", "", timeframe, "manual")
    with col2:
        top_ticker = str(candidates.iloc[0].get("ticker", "SPY")) if not candidates.empty else "SPY"
        if st.button(
            "Top Chart",
            key=make_key(key_prefix, "top_chart"),
            width="stretch",
        ):
            st.session_state.workspace_ticker = top_ticker
            st.session_state.workspace_timeframe = timeframe
            st.session_state.workspace_focus_mode = "Chart"
            st.session_state.navigation_page = "Workspace"
            st.rerun()
    with col3:
        if st.button(
            "Screen speichern",
            key=make_key(key_prefix, "quick_save_button"),
            width="stretch",
        ):
            st.session_state[make_key(key_prefix, "show_save_screen")] = True
    with col4:
        if st.button(
            "Workspace",
            key=make_key(key_prefix, "open_workspace"),
            width="stretch",
        ):
            st.session_state.navigation_page = "Workspace"
            st.rerun()

    if st.session_state.get(make_key(key_prefix, "show_save_screen")):
        render_quick_screen_save_form(
            store=store,
            email=email,
            candidates=candidates,
            timeframe=timeframe,
            key_prefix=make_key(key_prefix, "quick_save"),
        )

    render_section_title("Was heute wichtig ist", "Karten statt Rohdaten. Details liegen in Dashboard und Workspace.")
    if candidates.empty:
        render_empty_state(
            "Noch keine Kandidaten",
            "Klicke Analysieren. Danach zeigt diese Startseite nur die wichtigsten Karten.",
        )
    else:
        render_home_candidate_cards(
            candidates.head(6),
            store,
            email,
            timeframe,
            key_prefix=make_key(key_prefix, "candidate_cards"),
        )

    render_section_title("Gespeicherte Themen / Screens", "Schnell zur letzten Idee, ohne lange Suche.")
    render_saved_topic_cards(
        store=store,
        email=email,
        topics=topics,
        key_prefix=make_key(key_prefix, "saved_topics"),
    )


def render_today_importance_cards(
    result: dict,
    candidates: pd.DataFrame,
    topics: pd.DataFrame,
    timeframe: str,
    key_prefix: str,
) -> None:
    status = market_traffic_light(result, timeframe)
    cards = [
        {
            "label": "Marktampel",
            "value": status["label"],
            "detail": status["next_step"],
            "kind": traffic_badge_kind(status["level"]),
        }
    ]

    if candidates.empty:
        cards.append(
            {
                "label": "Top Kandidat",
                "value": "Noch offen",
                "detail": "Analyse starten, damit die App Chancen sortiert.",
                "kind": "gray",
            }
        )
        cards.append(
            {
                "label": "System Alert",
                "value": "Keine Daten",
                "detail": "Alerts entstehen nach Analyse aus Score, Trend und relativer Staerke.",
                "kind": "pink",
            }
        )
    else:
        top = candidates.iloc[0]
        top_ticker = str(top.get("ticker", ""))
        cards.append(
            {
                "label": "Top Kandidat",
                "value": f"{top_ticker} {int(safe_float(top.get('score'), 0))}/100",
                "detail": f"{top.get('trend', 'offen')} | Risk {top.get('risk_state', 'offen')}",
                "kind": status_color(top.get("risk_state", "gray")),
            }
        )
        alert = first_today_alert(candidates)
        cards.append(
            {
                "label": "System Alert",
                "value": alert["title"],
                "detail": alert["detail"],
                "kind": "pink",
            }
        )

    topic_count = 0 if topics.empty else len(topics)
    pinned_count = 0 if topics.empty or "pinned" not in topics else int((topics["pinned"] == True).sum())
    cards.append(
        {
            "label": "Gespeichert",
            "value": f"{topic_count} Themen",
            "detail": f"{pinned_count} oben gehalten. Screens koennen direkt wieder geoeffnet werden.",
            "kind": "blue",
        }
    )

    html_parts = ["<div class='sensei-guidance-grid'>"]
    for card in cards:
        extra_class = " sensei-guidance-card-pink" if card["kind"] == "pink" else ""
        badge_label = "Pink Alert" if card["kind"] == "pink" else str(card["value"]).split(" ")[0]
        html_parts.append(
            f"""
            <div class="sensei-guidance-card{extra_class}">
                <div class="sensei-guidance-label">{escape(card["label"])}</div>
                <div class="sensei-guidance-value">{escape(card["value"])}</div>
                <div class="sensei-guidance-detail">{escape(card["detail"])}</div>
                <div style="margin-top:0.55rem">{status_badge_html(badge_label, card["kind"])}</div>
            </div>
            """
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def first_today_alert(candidates: pd.DataFrame) -> dict:
    for _, row in candidates.head(10).iterrows():
        tags = system_alert_tags(row)
        if tags:
            ticker = str(row.get("ticker", ""))
            return {
                "title": tags[0],
                "detail": f"{ticker}: {row.get('trend', 'offen')}, Score {int(safe_float(row.get('score'), 0))}/100.",
            }
    return {
        "title": "Keine Warnung",
        "detail": "Keine klare System-Meldung unter den Top-Kandidaten.",
    }


def render_home_candidate_cards(
    candidates: pd.DataFrame,
    store: WorkspaceStore,
    email: str,
    timeframe: str,
    key_prefix: str,
) -> None:
    columns = st.columns(3)
    for index, (_, row) in enumerate(candidates.iterrows()):
        ticker = str(row.get("ticker", "")).upper()
        score = int(safe_float(row.get("score"), 0))
        trend = str(row.get("trend", "offen"))
        risk = str(row.get("risk_state", "offen"))
        with columns[index % 3]:
            st.markdown(
                f"""
                <div class="sensei-guidance-card">
                    <div class="sensei-guidance-label">{escape(ticker)} · {escape(timeframe)}</div>
                    <div class="sensei-guidance-value">{score}/100</div>
                    <div class="sensei-guidance-detail">
                        {status_badge_html(trend, status_color(trend))}
                        {status_badge_html(risk, status_color(risk))}
                        <br>Close {safe_float(row.get('close')):.2f}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_system_alert_tags(row)
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(
                    "Ansehen",
                    key=make_key(key_prefix, "view", index, ticker, timeframe),
                    width="stretch",
                ):
                    st.session_state.workspace_ticker = ticker
                    st.session_state.workspace_timeframe = timeframe
                    st.session_state.workspace_focus_mode = "Chart"
                    st.session_state.navigation_page = "Workspace"
                    st.rerun()
            with col_b:
                if st.button(
                    "Beobachten",
                    key=make_key(key_prefix, "watch", index, ticker, timeframe),
                    width="stretch",
                ):
                    observe_symbol(store, email, ticker, note=f"Heute ansehen {timeframe}")
                    st.success(f"{ticker} wurde beobachtet.")
                    st.rerun()


def render_quick_screen_save_form(
    store: WorkspaceStore,
    email: str,
    candidates: pd.DataFrame,
    timeframe: str,
    key_prefix: str,
) -> None:
    if candidates.empty:
        symbols = ["SPY", "QQQ", "GLD"]
    else:
        symbols = candidates["ticker"].astype(str).str.upper().drop_duplicates().head(12).tolist()
    with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
        st.markdown("#### Screen speichern")
        col1, col2, col3 = st.columns([1, 1.4, 0.8])
        with col1:
            ticker = st.selectbox(
                "Symbol",
                symbols,
                key=make_key(key_prefix, "ticker"),
            )
        with col2:
            name = st.text_input(
                "Name",
                value=f"{ticker} {timeframe} Screen",
                key=make_key(key_prefix, "name"),
            )
        with col3:
            pinned = st.checkbox(
                "Oben halten",
                value=True,
                key=make_key(key_prefix, "pinned"),
            )
        note = st.text_input(
            "Notiz",
            placeholder="Warum willst du diesen Screen wiederfinden?",
            key=make_key(key_prefix, "note"),
        )
        if st.form_submit_button(
            "Screen speichern",
            key=make_key(key_prefix, "submit"),
            width="stretch",
        ):
            store.save_topic(
                email=email,
                name=name.strip() or f"{ticker} {timeframe} Screen",
                ticker=ticker,
                timeframe=timeframe,
                category="Screens",
                note=note,
                pinned=pinned,
            )
            store.record_event(email, "screen_saved", ticker, timeframe, "today_home")
            st.session_state[make_key(key_prefix.rsplit("_quick_save", 1)[0], "show_save_screen")] = False
            st.success("Screen gespeichert.")
            st.rerun()


def render_saved_topic_cards(
    store: WorkspaceStore,
    email: str,
    topics: pd.DataFrame,
    key_prefix: str,
    limit: int = 6,
) -> None:
    if topics.empty:
        render_empty_state(
            "Noch keine Themen oder Screens",
            "Speichere einen Screen. Danach oeffnest du ihn hier mit einem Klick.",
        )
        return

    display = topics.head(limit).copy()
    columns = st.columns(3)
    for index, (_, row) in enumerate(display.iterrows()):
        topic_id = str(row.get("id", ""))
        ticker = str(row.get("ticker", "")).upper()
        timeframe = str(row.get("timeframe", ""))
        category = str(row.get("category", "Thema"))
        raw_note = row.get("note", "")
        note = "" if pd.isna(raw_note) else str(raw_note)
        raw_pinned = row.get("pinned", False)
        pinned = False if pd.isna(raw_pinned) else bool(raw_pinned)
        with columns[index % 3]:
            st.markdown(
                f"""
                <div class="sensei-topic-card">
                    <div class="sensei-guidance-label">{escape(category)}</div>
                    <div class="sensei-topic-title">{escape(str(row.get('name', ticker)))}</div>
                    <div class="sensei-topic-meta">
                        {escape(ticker)} · {escape(timeframe)}
                        {" · Pin" if pinned else ""}
                    </div>
                    <div class="sensei-guidance-detail">{escape(note[:110])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(
                    "Oeffnen",
                    key=make_key(key_prefix, "open", index, topic_id),
                    width="stretch",
                ):
                    store.mark_opened(email, topic_id)
                    st.session_state.workspace_ticker = ticker
                    st.session_state.workspace_timeframe = timeframe
                    st.session_state.workspace_focus_mode = "Chart"
                    st.session_state.navigation_page = "Workspace"
                    st.rerun()
            with col_b:
                if st.button(
                    "Loeschen",
                    key=make_key(key_prefix, "delete", index, topic_id),
                    width="stretch",
                ):
                    store.delete_topic(email, topic_id)
                    st.success("Thema geloescht.")
                    st.rerun()


def render_workspace(config: dict, app_env: str, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    store.ensure_default_watchlists(email, watchlist_categories(config))
    symbols = workspace_symbols(config, store, email)
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])

    st.subheader("Workspace")
    st.caption("Schneller Marktueberblick, gespeicherte Themen und Datensammlung.")

    render_workspace_status(config, result)
    render_analysis_terminal_bar(result, timeframes)
    render_mobile_quick_view(config, store, email, result, timeframes, key_prefix=make_key(key_prefix, "mobile"))
    render_today_overview(config, store, email, result, timeframes, key_prefix=make_key(key_prefix, "today"))
    st.divider()
    st.markdown("### Detailansicht")

    col_left, col_right = st.columns([1, 2])
    with col_left:
        st.markdown("### Fokus")
        selected_topic = render_saved_topics_picker(store, email, key_prefix=make_key(key_prefix, "saved_topics"))
        default_ticker = selected_topic.get("ticker") if selected_topic else symbols[0]
        default_timeframe = selected_topic.get("timeframe") if selected_topic else timeframes[0]
        if default_ticker and default_ticker not in symbols:
            symbols.insert(0, default_ticker)
        apply_selected_topic(selected_topic)
        render_quick_symbol_buttons(symbols, key_prefix=make_key(key_prefix, "quick_symbols"))
        render_timeframe_buttons(timeframes, make_key(key_prefix, "timeframe"), make_key(key_prefix, "timeframe_buttons"))
        ticker = st.selectbox(
            "Ticker",
            symbols,
            index=safe_index(symbols, default_ticker),
            key=make_key(key_prefix, "ticker"),
        )
        timeframe = st.selectbox(
            "Timeframe",
            timeframes,
            index=safe_index(timeframes, default_timeframe),
            key=make_key(key_prefix, "timeframe"),
        )
        focus_modes = ["Schnellblick", "Chart", "Daten sammeln"]
        focus_mode = st.radio(
            "Ansicht",
            focus_modes,
            index=safe_index(
                focus_modes,
                config.get("workspace", {}).get("default_focus", "Schnellblick"),
            ),
            horizontal=False,
            key=make_key(key_prefix, "focus_mode"),
        )

        col_action_1, col_action_2 = st.columns(2)
        with col_action_1:
            if st.button(
                "Analysieren",
                key=make_key(key_prefix, "analyze"),
                type="primary",
                width="stretch",
            ):
                _run_update(config, generate_reports=True)
                store.record_event(email, "data_collection", ticker, timeframe, "manual")
        with col_action_2:
            if st.button(
                "Beobachten",
                key=make_key(key_prefix, "observe"),
                width="stretch",
            ):
                observe_symbol(store, email, ticker, note=f"Fokus {timeframe}")
                st.success(f"{ticker} wurde beobachtet. Pink markiert den Alert-Datenpunkt.")
                st.rerun()

        render_save_topic_form(config, store, email, ticker, timeframe, key_prefix=make_key(key_prefix, "save_topic"))
        render_custom_watchlists(
            config=config,
            store=store,
            email=email,
            result=result,
            key_prefix="workspace",
            compact=True,
        )

    with col_right:
        row = analysis_row_for_ticker(result, ticker, timeframe)
        render_workspace_focus_card(row, ticker, timeframe, key_prefix=make_key(key_prefix, "focus_card"))
        if focus_mode in ["Chart", "Daten sammeln"]:
            render_symbol_chart(
                config,
                result,
                ticker,
                timeframe,
                store,
                email,
                key_prefix=make_key(key_prefix, "chart"),
            )
        if focus_mode == "Daten sammeln":
            render_collection_overview(config, store, email, key_prefix=make_key(key_prefix, "collection"))


def render_workspace_status(config: dict, result: dict) -> None:
    workspace = config.get("workspace", {})
    data_config = config.get("data", {})
    energy_mode = workspace.get("energy_mode", "balanced")
    cache_ages = data_config.get("cache_max_age_hours", {})
    cache_label = (
        f"1d {cache_ages.get('1d', '-')}h | "
        f"1wk {cache_ages.get('1wk', '-')}h | "
        f"1mo {cache_ages.get('1mo', '-')}h"
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Letzte Analyse", result.get("updated_at", "n/a"))
    col2.metric("Energie-Modus", energy_mode)
    col3.metric("Datenmodus", "manuell")
    col4.metric("Cache", cache_label)
    st.caption(
        "Schnellblick nutzt geladene Daten. Neue Downloads, Reports und Snapshots laufen nur bei Start, Analysieren oder lokalen Jobs."
    )


def render_mobile_quick_view(
    config: dict,
    store: WorkspaceStore,
    email: str,
    result: dict,
    timeframes: list[str],
    key_prefix: str,
) -> None:
    with st.expander(f"Mobile Schnellansicht ({key_prefix})", expanded=True):
        st.caption("Watchlist zuerst, Chart direkt darunter. Tabellen bleiben in Details.")
        timeframe_state_key = make_key(key_prefix, "timeframe")
        ticker_state_key = make_key(key_prefix, "ticker")
        render_timeframe_buttons(timeframes, timeframe_state_key, make_key(key_prefix, "timeframe_buttons"))
        timeframe = st.session_state.get(timeframe_state_key, timeframes[0])

        candidates = today_candidates(result, timeframe)
        watchlist = result.get("watchlist", pd.DataFrame())
        watchlist = watchlist[watchlist["timeframe"] == timeframe].copy() if not watchlist.empty else watchlist
        display = watchlist if not watchlist.empty else candidates

        if display.empty:
            render_empty_state(
                "Keine Watchlist-Daten",
                "Klicke Analysieren. Danach zeigt die mobile Ansicht kompakte Karten und den Chart darunter.",
            )
            return

        display = display.sort_values("score", ascending=False).head(8)
        render_mobile_watchlist_cards(display, timeframe, key_prefix=make_key(key_prefix, "cards"))

        tickers = display["ticker"].astype(str).str.upper().tolist()
        current_ticker = st.session_state.get(ticker_state_key, tickers[0])
        if current_ticker not in tickers:
            current_ticker = tickers[0]
        selected_ticker = st.selectbox(
            "Chart-Symbol",
            tickers,
            index=safe_index(tickers, current_ticker),
            key=ticker_state_key,
        )

        row = analysis_row_for_ticker(result, selected_ticker, timeframe)
        render_workspace_focus_card(
            row,
            selected_ticker,
            timeframe,
            key_prefix=make_key(key_prefix, "focus_card"),
        )
        render_symbol_chart(
            config,
            result,
            selected_ticker,
            timeframe,
            store,
            email,
            key_prefix=make_key(key_prefix, "chart"),
        )


def render_mobile_watchlist_cards(display: pd.DataFrame, timeframe: str, key_prefix: str) -> None:
    st.markdown("#### Watchlist")
    for index in range(0, len(display), 2):
        columns = st.columns(2)
        for offset, column in enumerate(columns):
            row_index = index + offset
            if row_index >= len(display):
                continue
            row = display.iloc[row_index]
            ticker = str(row.get("ticker", "")).upper()
            with column:
                st.metric(
                    ticker,
                    f"{int(safe_float(row.get('score'), 0))}/100",
                    str(row.get("risk_state", "offen")),
                )
                st.caption(f"{row.get('trend', 'offen')} | {safe_float(row.get('close')):.2f}")
                render_system_alert_tags(row)
                if st.button(
                    "Chart",
                    key=make_key(key_prefix, "chart", ticker, timeframe),
                    width="stretch",
                ):
                    st.session_state[make_key(key_prefix, "ticker")] = ticker
                    st.session_state.workspace_ticker = ticker
                    st.session_state.workspace_timeframe = timeframe
                    st.rerun()


def render_analysis_terminal_bar(result: dict, timeframes: list[str]) -> None:
    timeframe = st.session_state.get("workspace_timeframe", timeframes[0])
    ticker = st.session_state.get("workspace_ticker") or "SPY"
    row = analysis_row_for_ticker(result, ticker, timeframe)
    tags = system_alert_tags(row)
    chips = "".join(
        f"<span class='sensei-alert-chip'>{escape(tag)}</span>"
        for tag in (tags or ["SYSTEM-BEOBACHTUNG"])
    )
    st.markdown(
        (
            "<div class='sensei-terminal'>"
            "<div class='sensei-terminal-row'>"
            f"<span class='sensei-terminal-symbol'>{escape(str(ticker).upper())} · {escape(str(timeframe))}</span>"
            "<span class='sensei-alert-badge'>Pink = System / Alert / Bot-Vorbereitung</span>"
            "</div>"
            f"<div>{chips}</div>"
            "<small>Analyse-only: pink markiert Erkennung, Speicherung und Beobachtung. Keine Orders.</small>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_alert_badge(label: str = "System-Alert") -> None:
    st.markdown(
        f"<span class='sensei-alert-badge'>{escape(label)}</span>",
        unsafe_allow_html=True,
    )


def render_system_alert_panel(title: str, body: str) -> None:
    st.markdown(
        (
            "<div class='sensei-alert-panel'>"
            f"<strong>{escape(title)}</strong><br>{escape(body)}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_system_alert_tags(row, compact: bool = True) -> None:
    tags = system_alert_tags(row)
    if not tags:
        return
    chips = "".join(
        f"<span class='sensei-alert-chip'>{escape(tag)}</span>"
        for tag in tags[:4 if compact else 8]
    )
    st.markdown(chips, unsafe_allow_html=True)


def system_alert_tags(row) -> list[str]:
    if row is None:
        return []
    getter = row.get if hasattr(row, "get") else lambda key, default=None: default
    trend = str(getter("trend", "")).lower()
    risk_state = str(getter("risk_state", ""))
    score = safe_float(getter("score"), 0)
    close = safe_float(getter("close"), 0)
    ema20 = safe_float(getter("ema_20"), 0)
    ema50 = safe_float(getter("ema_50"), 0)
    ema200 = safe_float(getter("ema_200"), 0)
    relative_strength = safe_float(getter("relative_strength"), 0)
    return_20 = safe_float(getter("return_20"), 0)

    tags = []
    if risk_state == "BLOCKED":
        tags.append("SYSTEM: BLOCKIERT")
    if risk_state == "REDUCED":
        tags.append("SYSTEM: VORSICHT")
    if (
        trend == "bullish"
        and risk_state == "OK"
        and score >= 70
        and close > ema20 > 0
        and close > ema50 > 0
        and relative_strength > 0
    ):
        tags.append("BREAKOUT-WATCH")
    if trend == "bullish" and close > ema20 > ema50 > 0:
        tags.append("TREND-ERKENNUNG")
    if relative_strength > 0 and score >= 60:
        tags.append("RELATIVE-STAERKE")
    if close > ema200 > 0 and score >= 60:
        tags.append("EMA200-FILTER OK")
    if return_20 > 8 and score >= 65:
        tags.append("MOMENTUM-ALERT")
    if not tags and score >= 60:
        tags.append("SYSTEM-BEOBACHTUNG")
    return tags


def render_today_overview(
    config: dict,
    store: WorkspaceStore,
    email: str,
    result: dict,
    timeframes: list[str],
    key_prefix: str,
) -> None:
    st.markdown("### Heute ansehen")
    st.caption("Erst Ampel lesen, dann Kandidaten ansehen. Details bleiben darunter.")
    timeframe_state_key = make_key(key_prefix, "timeframe")
    render_timeframe_buttons(timeframes, timeframe_state_key, make_key(key_prefix, "timeframe_buttons"))
    timeframe = st.session_state.get(timeframe_state_key, timeframes[0])

    render_market_traffic_light(result, timeframe)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button(
            "Analysieren",
            key=make_key(key_prefix, "analyze"),
            type="primary",
            width="stretch",
        ):
            _run_update(config, generate_reports=True)
            store.record_event(email, "today_analyze", "", timeframe, "manual")
    with col2:
        selected_focus = st.session_state.get("workspace_ticker") or tracking_symbols(config)[0]
        if st.button(
            "Beobachten",
            key=make_key(key_prefix, "observe"),
            width="stretch",
        ):
            observe_symbol(store, email, selected_focus, note=f"Heute ansehen {timeframe}")
            st.success(f"{selected_focus} wurde beobachtet. Pink markiert den Alert-Datenpunkt.")
            st.rerun()
    with col3:
        if st.button(
            "Zum Chart",
            key=make_key(key_prefix, "to_chart"),
            width="stretch",
        ):
            st.session_state.workspace_timeframe = timeframe
            st.session_state.workspace_focus_mode = "Chart"
            st.rerun()

    candidates = today_candidates(result, timeframe)
    if candidates.empty:
        render_empty_state(
            "Noch keine Kandidaten fuer heute",
            "Starte Analysieren. Danach zeigt die App die staerksten Symbole mit Score, Trend und Risk State.",
        )
        return

    st.markdown("#### Kandidaten")
    render_today_cards(candidates.head(6), store, email, timeframe, key_prefix=make_key(key_prefix, "cards"))


def render_market_traffic_light(result: dict, timeframe: str) -> None:
    status = market_traffic_light(result, timeframe)
    traffic_class = {
        "ok": "sensei-traffic-ok",
        "caution": "sensei-traffic-caution",
        "blocked": "sensei-traffic-blocked",
    }.get(status["level"], "sensei-traffic-caution")
    badge_kind = traffic_badge_kind(status["level"])
    st.markdown(
        f"""
        <div class="sensei-traffic-card {traffic_class}">
            <div class="sensei-traffic-row">
                <div>
                    <div class="sensei-guidance-label">Marktampel</div>
                    <div class="sensei-traffic-label">{escape(status["label"])}</div>
                    <div class="sensei-guidance-detail">
                        {escape(status["summary"])}<br>
                        Regel: {escape(status["rule"])}
                    </div>
                </div>
                <div>{status_badge_html(status["label"], badge_kind)}</div>
            </div>
            <div class="sensei-guidance-detail">
                Naechster Schritt: <strong>{escape(status["next_step"])}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ampel", status["label"])
    col2.metric("SPY", status["spy"])
    col3.metric("QQQ", status["qqq"])
    col4.metric("Score", f"{status['average_score']:.0f}/100")


def traffic_badge_kind(level: str) -> str:
    if level == "ok":
        return "green"
    if level == "blocked":
        return "red"
    return "yellow"


def market_traffic_light(result: dict, timeframe: str) -> dict:
    spy = analysis_row_for_ticker(result, "SPY", timeframe)
    qqq = analysis_row_for_ticker(result, "QQQ", timeframe)
    if not spy or not qqq:
        return {
            "level": "caution",
            "label": "Vorsicht",
            "summary": "SPY oder QQQ fehlen in der Analyse.",
            "rule": "Daten unvollstaendig.",
            "next_step": "Analysieren starten und Datenstatus pruefen.",
            "spy": "fehlt" if not spy else str(spy.get("trend", "offen")),
            "qqq": "fehlt" if not qqq else str(qqq.get("trend", "offen")),
            "average_score": 0.0,
        }

    spy_trend = str(spy.get("trend", "neutral"))
    qqq_trend = str(qqq.get("trend", "neutral"))
    spy_risk = str(spy.get("risk_state", "offen"))
    qqq_risk = str(qqq.get("risk_state", "offen"))
    average_score = (safe_float(spy.get("score")) + safe_float(qqq.get("score"))) / 2
    same_direction = spy_trend == qqq_trend

    blocked = (
        "BLOCKED" in [spy_risk, qqq_risk]
        or (spy_trend == "bearish" and qqq_trend == "bearish")
        or average_score < 40
    )
    caution = (
        "REDUCED" in [spy_risk, qqq_risk]
        or "bearish" in [spy_trend, qqq_trend]
        or not same_direction
        or average_score < 60
    )

    if blocked:
        label = "Blockiert"
        level = "blocked"
        summary = "Marktfilter blockiert neue aggressive Ideen."
        next_step = "Nur beobachten, keine neuen Risiko-Ideen aufnehmen."
    elif caution:
        label = "Vorsicht"
        level = "caution"
        summary = "Markt ist nicht klar synchron."
        next_step = "Kandidaten enger filtern und Risk State beachten."
    else:
        label = "Markt OK"
        level = "ok"
        summary = "SPY und QQQ bestaetigen den Markt."
        next_step = "Beste Kandidaten ansehen und bei Bedarf speichern."

    return {
        "level": level,
        "label": label,
        "summary": summary,
        "rule": f"SPY {spy_trend}/{spy_risk}, QQQ {qqq_trend}/{qqq_risk}.",
        "next_step": next_step,
        "spy": spy_trend,
        "qqq": qqq_trend,
        "average_score": average_score,
    }


def today_candidates(result: dict, timeframe: str) -> pd.DataFrame:
    frames = [
        result.get("dashboard", pd.DataFrame()),
        result.get("watchlist", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["timeframe"] == timeframe].copy()
    if combined.empty:
        return combined

    combined["_risk_sort"] = combined["risk_state"].map(risk_sort_rank).fillna(99)
    combined["_trend_sort"] = combined["trend"].map(trend_sort_rank).fillna(99)
    combined["_score_sort"] = pd.to_numeric(combined["score"], errors="coerce").fillna(-1)
    combined = combined.sort_values(
        ["_risk_sort", "_trend_sort", "_score_sort"],
        ascending=[True, True, False],
    )
    return combined.drop(columns=["_risk_sort", "_trend_sort", "_score_sort"])


def render_today_cards(
    candidates: pd.DataFrame,
    store: WorkspaceStore,
    email: str,
    timeframe: str,
    key_prefix: str,
) -> None:
    columns = st.columns(3)
    for index, (_, row) in enumerate(candidates.iterrows()):
        ticker = str(row.get("ticker", ""))
        with columns[index % 3]:
            st.metric(
                ticker,
                f"{int(safe_float(row.get('score'), 0))}/100",
                str(row.get("trend", "offen")),
            )
            st.caption(f"Risk: {row.get('risk_state', 'offen')} | Close: {safe_float(row.get('close')):.2f}")
            render_system_alert_tags(row)
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(
                    "Ansehen",
                    key=make_key(key_prefix, "view", index, ticker, timeframe),
                    width="stretch",
                ):
                    st.session_state.workspace_ticker = ticker
                    st.session_state.workspace_timeframe = timeframe
                    st.session_state.workspace_focus_mode = "Chart"
                    st.rerun()
            with col_b:
                if st.button(
                    "Beobachten",
                    key=make_key(key_prefix, "watch", index, ticker, timeframe),
                    width="stretch",
                ):
                    observe_symbol(store, email, ticker, note=f"Heute ansehen {timeframe}")
                    st.success(f"{ticker} wurde beobachtet. Pink markiert den Alert-Datenpunkt.")
                    st.rerun()


def observe_symbol(
    store: WorkspaceStore,
    email: str,
    ticker: str,
    note: str = "",
    category: str = "Eigene Ideen",
) -> None:
    store.ensure_default_watchlists(email, DEFAULT_WATCHLIST_CATEGORIES)
    watchlists = store.list_watchlists(email)
    target = watchlists[
        (watchlists["category"].astype(str) == category)
        | (watchlists["name"].astype(str) == category)
    ]
    if target.empty:
        watchlist_id = store.save_watchlist(email, category, category, pinned=True)
    else:
        watchlist_id = target.iloc[0]["id"]

    store.add_watchlist_symbol(
        email=email,
        watchlist_id=watchlist_id,
        ticker=ticker,
        category=category,
        note=note,
        pinned=True,
    )
    store.record_event(email, "symbol_observed", ticker, "", note)


def workspace_symbols(config: dict, store: WorkspaceStore, email: str) -> list[str]:
    symbols = tracking_symbols(config)
    custom_symbols = store.list_watchlist_symbols(email)
    if not custom_symbols.empty:
        pinned = custom_symbols[custom_symbols["pinned"] == True]["ticker"].tolist()
        rest = custom_symbols[custom_symbols["pinned"] != True]["ticker"].tolist()
        symbols = pinned + symbols + rest

    unique = []
    for symbol in symbols:
        cleaned = str(symbol).strip().upper()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique or ["SPY"]


def apply_selected_topic(selected_topic: dict) -> None:
    if not selected_topic:
        return
    topic_id = selected_topic.get("id")
    if st.session_state.get("workspace_applied_topic") == topic_id:
        return
    st.session_state.workspace_ticker = selected_topic.get("ticker")
    st.session_state.workspace_timeframe = selected_topic.get("timeframe")
    st.session_state.workspace_applied_topic = topic_id


def render_saved_topics_picker(store: WorkspaceStore, email: str, key_prefix: str) -> dict:
    topics = store.list_topics(email)
    if topics.empty:
        render_empty_state(
            "Noch nichts gespeichert",
            "Speichere einen Chart oder eine Idee, damit du spaeter direkt wieder an derselben Stelle einsteigen kannst.",
        )
        return {}

    labels = {
        row["id"]: f"{row['name']} | {row['ticker']} | {row['timeframe']}"
        for _, row in topics.iterrows()
    }
    selected_id = st.selectbox(
        "Gespeicherte Themen",
        [""] + topics["id"].tolist(),
        format_func=lambda value: "Auswahl" if value == "" else labels.get(value, value),
        key=make_key(key_prefix, "select"),
    )
    if not selected_id:
        return {}

    store.mark_opened(email, selected_id)
    selected = topics[topics["id"] == selected_id].iloc[0].to_dict()
    if st.button(
        "Thema loeschen",
        key=make_key(key_prefix, "delete", selected_id),
        width="stretch",
    ):
        store.delete_topic(email, selected_id)
        st.success("Thema geloescht.")
        st.rerun()
    return selected


def render_quick_symbol_buttons(symbols: list[str], key_prefix: str) -> None:
    st.caption("Schnellwechsel")
    quick_symbols = symbols[:8]
    columns = st.columns(4)
    for index, symbol in enumerate(quick_symbols):
        with columns[index % 4]:
            if st.button(
                symbol,
                key=make_key(key_prefix, index, symbol),
                width="stretch",
            ):
                st.session_state.workspace_ticker = symbol
                st.rerun()


def render_timeframe_buttons(
    timeframes: list[str],
    state_key: str,
    key_prefix: str,
    result: Optional[dict] = None,
    ticker: Optional[str] = None,
) -> None:
    current = st.session_state.get(state_key, timeframes[0])
    current_trend = timeframe_trend_value(result, ticker, current) if result and ticker else ""
    caption = "Timeframe"
    if current_trend:
        caption = f"Timeframe · aktuell {timeframe_display_label(current)} {current_trend}"
    st.caption(caption)
    columns = st.columns(max(1, len(timeframes)))
    for index, timeframe in enumerate(timeframes):
        trend = timeframe_trend_value(result, ticker, timeframe) if result and ticker else ""
        label = timeframe
        if result and ticker:
            suffix = trend if trend else "offen"
            label = f"{timeframe_display_label(timeframe)} · {suffix}"
        with columns[index % len(columns)]:
            if st.button(
                label,
                key=make_key(key_prefix, "timeframe", index, timeframe),
                type="primary" if timeframe == current else "secondary",
                width="stretch",
            ):
                st.session_state[state_key] = timeframe
                st.rerun()


def timeframe_display_label(timeframe: str) -> str:
    labels = {
        "1mo": "Monat",
        "1wk": "Woche",
        "1d": "Tag",
        "4h": "4h",
        "1h": "Stunde",
        "30m": "30m",
        "15m": "15m",
    }
    return labels.get(str(timeframe), str(timeframe))


def timeframe_trend_value(result: Optional[dict], ticker: Optional[str], timeframe: str) -> str:
    if not result or not ticker:
        return ""
    row = exact_analysis_row_for_ticker(result, ticker, timeframe)
    return str(row.get("trend", "")).strip() if row else ""


def timeframe_direction_class(trend: str) -> str:
    text = str(trend).lower()
    if text == "bullish":
        return "bullish"
    if text == "bearish":
        return "bearish"
    if text == "neutral":
        return "neutral"
    return "unknown"


def render_timeframe_trend_strip(
    config: dict,
    result: dict,
    ticker: str,
    current_timeframe: str,
    key_prefix: str,
) -> None:
    timeframes = timeframes_for_trend_strip(config, result, ticker)
    if not timeframes:
        return

    chips = []
    for timeframe in timeframes:
        row = exact_analysis_row_for_ticker(result, ticker, timeframe)
        trend = str(row.get("trend", "nicht geladen")) if row else "nicht geladen"
        css_class = timeframe_direction_class(trend)
        active_class = " active" if timeframe == current_timeframe else ""
        score = safe_optional_float(row.get("score")) if row else None
        score_text = f"{int(score)}/100" if score is not None else "kein Wert"
        chips.append(
            f"""
            <div class="sensei-timeframe-trend-chip{active_class}">
                <div class="sensei-timeframe-label">{escape(timeframe_display_label(timeframe))}</div>
                <div class="sensei-timeframe-direction {escape(css_class)}">{escape(trend)}</div>
                <div class="sensei-timeframe-score">{escape(str(timeframe))} · {escape(score_text)}</div>
            </div>
            """
        )

    st.markdown(
        f"""
        <div class="sensei-timeframe-trend-strip">
            {''.join(chips)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def timeframes_for_trend_strip(config: dict, result: dict, ticker: str) -> list[str]:
    configured = [str(item) for item in config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"])]
    discovered = set(configured)
    ticker_lookup = str(ticker).upper()
    for key in result.get("histories", {}):
        if "|" not in str(key):
            continue
        symbol, timeframe = str(key).split("|", 1)
        if symbol.upper() == ticker_lookup:
            discovered.add(timeframe)

    combined = analysis_combined_frame(result)
    if not combined.empty and {"ticker", "timeframe"}.issubset(combined.columns):
        rows = combined[combined["ticker"].astype(str).str.upper() == ticker_lookup]
        discovered.update(str(value) for value in rows["timeframe"].dropna().unique())

    preferred_order = ["1mo", "1wk", "1d", "4h", "1h", "30m", "15m"]
    ordered = [item for item in preferred_order if item in discovered]
    ordered.extend(sorted(item for item in discovered if item not in preferred_order))
    return ordered


def render_save_topic_form(
    config: dict,
    store: WorkspaceStore,
    email: str,
    ticker: str,
    timeframe: str,
    key_prefix: str,
) -> None:
    categories = config.get("workspace", {}).get("categories", DEFAULT_CATEGORIES)
    with st.expander(f"Speichern ({key_prefix})", expanded=False):
        render_system_alert_panel(
            "Pink Alert: Speicherung",
            "Alles, was fuer spaetere System-Erkennung, Beobachtung oder Bot-Vorbereitung gespeichert wird, ist pink markiert.",
        )
        with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
            name = st.text_input(
                "Name",
                value=f"{ticker} {timeframe}",
                key=make_key(key_prefix, "name"),
            )
            category = st.selectbox(
                "Kategorie",
                categories,
                index=safe_index(categories, "Research"),
                key=make_key(key_prefix, "category"),
            )
            note = st.text_area(
                "Notiz",
                placeholder="Worauf willst du spaeter schnell zugreifen?",
                key=make_key(key_prefix, "note"),
            )
            pinned = st.checkbox(
                "Oben halten",
                value=True,
                key=make_key(key_prefix, "pinned"),
            )
            if st.form_submit_button(
                "Speichern",
                key=make_key(key_prefix, "submit"),
                width="stretch",
            ):
                try:
                    topic_id = store.save_topic(
                        email=email,
                        name=name,
                        ticker=ticker,
                        timeframe=timeframe,
                        category=category,
                        note=note,
                        pinned=pinned,
                    )
                    store.record_event(email, "topic_saved", ticker, timeframe, topic_id)
                    st.success("Thema gespeichert. Pink markiert diesen Speicherpunkt als System-/Alert-Datenpunkt.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Thema konnte nicht gespeichert werden: {exc}")


def render_custom_watchlists(
    config: dict,
    store: WorkspaceStore,
    email: str,
    result: dict,
    key_prefix: str,
    compact: bool = False,
) -> None:
    if compact:
        with st.expander(f"Eigene Watchlists ({key_prefix})", expanded=False):
            render_custom_watchlists_body(config, store, email, result, key_prefix, compact)
    else:
        render_custom_watchlists_body(config, store, email, result, key_prefix, compact)


def render_custom_watchlists_body(
    config: dict,
    store: WorkspaceStore,
    email: str,
    result: dict,
    key_prefix: str,
    compact: bool,
) -> None:
    categories = watchlist_categories(config)
    store.ensure_default_watchlists(email, categories)
    watchlists = store.list_watchlists(email)
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])

    if watchlists.empty:
        render_empty_state(
            "Noch keine Watchlist",
            "Lege eine Watchlist an oder nutze Beobachten. Danach sortiert die App deine Symbole nach Score, Trend und Risk State.",
        )
        return

    labels = {
        row["id"]: f"{row['name']} ({int(row['symbol_count'])})"
        for _, row in watchlists.iterrows()
    }
    selected_watchlist_id = st.selectbox(
        "Watchlist",
        watchlists["id"].tolist(),
        format_func=lambda value: labels.get(value, value),
        key=make_key(key_prefix, "custom_watchlist_select"),
    )
    selected_watchlist = watchlists[watchlists["id"] == selected_watchlist_id].iloc[0].to_dict()

    col_a, col_b = st.columns(2)
    with col_a:
        timeframe = st.selectbox(
            "Analyse-Timeframe",
            timeframes,
            index=safe_index(timeframes, st.session_state.get("workspace_timeframe", timeframes[0])),
            key=make_key(key_prefix, "custom_watchlist_timeframe"),
        )
    with col_b:
        sort_mode = st.selectbox(
            "Sortierung",
            ["Risk State", "Score hoch", "Trend", "Favoriten/Pins"],
            key=make_key(key_prefix, "custom_watchlist_sort"),
        )

    render_create_watchlist_form(store, email, categories, key_prefix, collapsed=not compact)
    render_add_symbol_form(store, email, selected_watchlist_id, categories, key_prefix)

    symbols_df = store.list_watchlist_symbols(email, selected_watchlist_id)
    if symbols_df.empty:
        render_empty_state(
            "Diese Watchlist ist leer",
            "Gib ein Symbol ein und klicke Beobachten. Danach bleibt es in dieser Liste gespeichert.",
        )
    else:
        display = build_custom_watchlist_display(symbols_df, result, timeframe, sort_mode)
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "custom_watchlist_dataframe"),
            column_config={
                "pin": "Pin",
                "ticker": "Ticker",
                "category": "Kategorie",
                "system_alerts": "Pink Alerts",
                "score": st.column_config.NumberColumn("Score", format="%.0f"),
                "trend": "Trend",
                "risk_state": "Risk State",
                "close": st.column_config.NumberColumn("Close", format="%.2f"),
                "relative_strength": st.column_config.NumberColumn("RS vs QQQ", format="%.2f"),
                "note": "Notiz",
            },
        )

        focus_symbols = display["ticker"].head(8).tolist()
        if focus_symbols:
            st.caption("Fokus-Schnellwahl")
            columns = st.columns(min(4, len(focus_symbols)))
            for index, symbol in enumerate(focus_symbols):
                with columns[index % len(columns)]:
                    if st.button(
                        symbol,
                        key=make_key(key_prefix, "custom_focus", index, symbol),
                        width="stretch",
                    ):
                        st.session_state.workspace_ticker = symbol
                        st.session_state.workspace_timeframe = timeframe
                        st.rerun()

        if st.button(
            "Analysieren",
            key=make_key(key_prefix, "analyze_custom_watchlist"),
            type="primary",
            width="stretch",
        ):
            _run_update_with_extra_symbols(config, symbols_df["ticker"].tolist())

        render_delete_symbol_control(store, email, symbols_df, key_prefix, collapsed=not compact)

    if not compact:
        st.caption(
            "Eigene Symbole werden lokal gespeichert. Neue Ticker bekommen Scores, "
            "sobald du die jeweilige Watchlist analysierst."
        )
        if st.button(
            "Ausgewaehlte Watchlist loeschen",
            key=make_key(key_prefix, "delete_watchlist"),
            width="stretch",
        ):
            store.delete_watchlist(email, selected_watchlist_id)
            st.success(f"Watchlist geloescht: {selected_watchlist['name']}")
            st.rerun()


def render_create_watchlist_form(
    store: WorkspaceStore,
    email: str,
    categories: list[str],
    key_prefix: str,
    collapsed: bool = True,
) -> None:
    if collapsed:
        with st.expander(f"Neue Watchlist ({key_prefix})", expanded=False):
            render_alert_badge("Pink Alert: Speicherung")
            render_create_watchlist_fields(store, email, categories, key_prefix)
    else:
        st.markdown("#### Neue Watchlist")
        render_alert_badge("Pink Alert: Speicherung")
        render_create_watchlist_fields(store, email, categories, key_prefix)


def render_create_watchlist_fields(
    store: WorkspaceStore,
    email: str,
    categories: list[str],
    key_prefix: str,
) -> None:
    with st.form(make_key(key_prefix, "create_watchlist_form"), clear_on_submit=True):
        name = st.text_input(
            "Name",
            placeholder="z.B. Breakout Ideen",
            key=make_key(key_prefix, "create_watchlist_name"),
        )
        category = st.selectbox(
            "Kategorie",
            categories,
            index=safe_index(categories, "Eigene Ideen"),
            key=make_key(key_prefix, "create_watchlist_category"),
        )
        pinned = st.checkbox(
            "Oben halten",
            value=True,
            key=make_key(key_prefix, "create_watchlist_pinned"),
        )
        if st.form_submit_button(
            "Watchlist anlegen",
            key=make_key(key_prefix, "create_watchlist_submit"),
            width="stretch",
        ):
            try:
                store.save_watchlist(email, name, category, pinned)
                st.success("Watchlist angelegt.")
                st.rerun()
            except Exception as exc:
                st.error(f"Watchlist konnte nicht angelegt werden: {exc}")


def render_add_symbol_form(
    store: WorkspaceStore,
    email: str,
    watchlist_id: str,
    categories: list[str],
    key_prefix: str,
) -> None:
    render_alert_badge("Pink Alert: Beobachten")
    with st.form(make_key(key_prefix, "add_watchlist_symbol_form"), clear_on_submit=True):
        symbol = st.text_input(
            "Symbol hinzufuegen",
            placeholder="z.B. BTC-USD",
            key=make_key(key_prefix, "add_symbol_ticker"),
        )
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(
                "Kategorie",
                categories,
                index=safe_index(categories, "Eigene Ideen"),
                key=make_key(key_prefix, "add_symbol_category"),
            )
        with col2:
            pinned = st.checkbox(
                "Pin",
                value=False,
                key=make_key(key_prefix, "add_symbol_pinned"),
            )
        note = st.text_input(
            "Notiz optional",
            placeholder="Warum ist das Symbol interessant?",
            key=make_key(key_prefix, "add_symbol_note"),
        )
        if st.form_submit_button(
            "Beobachten",
            key=make_key(key_prefix, "add_symbol_submit"),
            width="stretch",
        ):
            try:
                symbol_id = store.add_watchlist_symbol(
                    email=email,
                    watchlist_id=watchlist_id,
                    ticker=symbol,
                    category=category,
                    note=note,
                    pinned=pinned,
                )
                store.record_event(email, "watchlist_symbol_saved", symbol, "", symbol_id)
                st.success("Symbol gespeichert. Pink markiert es als Alert-/Beobachtungsdatenpunkt.")
                st.rerun()
            except Exception as exc:
                st.error(f"Symbol konnte nicht gespeichert werden: {exc}")


def render_delete_symbol_control(
    store: WorkspaceStore,
    email: str,
    symbols_df: pd.DataFrame,
    key_prefix: str,
    collapsed: bool = True,
) -> None:
    if collapsed:
        with st.expander(f"Symbol entfernen ({key_prefix})", expanded=False):
            render_delete_symbol_fields(store, email, symbols_df, key_prefix)
    else:
        render_delete_symbol_fields(store, email, symbols_df, key_prefix)


def render_delete_symbol_fields(
    store: WorkspaceStore,
    email: str,
    symbols_df: pd.DataFrame,
    key_prefix: str,
) -> None:
    labels = {
        row["id"]: f"{row['ticker']} | {row['category']}"
        for _, row in symbols_df.iterrows()
    }
    selected_symbol_id = st.selectbox(
        "Symbol entfernen",
        symbols_df["id"].tolist(),
        format_func=lambda value: labels.get(value, value),
        key=make_key(key_prefix, "delete_symbol_select"),
    )
    if st.button(
        "Symbol entfernen",
        key=make_key(key_prefix, "delete_symbol_button"),
        width="stretch",
    ):
        store.delete_watchlist_symbol(email, selected_symbol_id)
        st.success("Symbol entfernt.")
        st.rerun()


def build_custom_watchlist_display(
    symbols_df: pd.DataFrame,
    result: dict,
    timeframe: str,
    sort_mode: str,
) -> pd.DataFrame:
    rows = []
    for _, saved in symbols_df.iterrows():
        ticker = str(saved["ticker"]).upper()
        analysis = analysis_row_for_ticker(result, ticker, timeframe)
        alerts = system_alert_tags(analysis)
        rows.append(
            {
                "pin": "yes" if bool(saved.get("pinned")) else "",
                "ticker": ticker,
                "category": saved.get("category", ""),
                "system_alerts": ", ".join(alerts),
                "score": safe_optional_float(analysis.get("score")),
                "trend": analysis.get("trend", "nicht analysiert"),
                "risk_state": analysis.get("risk_state", "offen"),
                "close": safe_optional_float(analysis.get("close")),
                "relative_strength": safe_optional_float(analysis.get("relative_strength")),
                "note": saved.get("note", ""),
                "_pinned_sort": 1 if bool(saved.get("pinned")) else 0,
            }
        )

    display = pd.DataFrame(rows)
    if display.empty:
        return display

    display["_score_sort"] = pd.to_numeric(display["score"], errors="coerce").fillna(-1)
    display["_risk_sort"] = display["risk_state"].map(risk_sort_rank).fillna(99)
    display["_trend_sort"] = display["trend"].map(trend_sort_rank).fillna(99)

    if sort_mode == "Score hoch":
        display = display.sort_values(["_score_sort", "_pinned_sort"], ascending=[False, False])
    elif sort_mode == "Trend":
        display = display.sort_values(["_trend_sort", "_score_sort"], ascending=[True, False])
    elif sort_mode == "Favoriten/Pins":
        display = display.sort_values(["_pinned_sort", "_score_sort"], ascending=[False, False])
    else:
        display = display.sort_values(["_risk_sort", "_score_sort"], ascending=[True, False])

    return display.drop(columns=["_pinned_sort", "_score_sort", "_risk_sort", "_trend_sort"])


def render_workspace_focus_card(row: dict, ticker: str, timeframe: str, key_prefix: str) -> None:
    st.markdown("### Schnellblick")
    if not row:
        st.warning("Keine Analyse fuer diesen Fokus vorhanden.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ticker", ticker)
    col2.metric("Score", f"{int(safe_float(row.get('score'), 0))}/100")
    col3.metric("Trend", str(row.get("trend", "n/a")))
    col4.metric("Risk", str(row.get("risk_state", "n/a")))
    render_system_alert_tags(row, compact=False)

    compact = pd.DataFrame(
        [
            {
                "Close": safe_float(row.get("close")),
                "EMA20": safe_float(row.get("ema_20")),
                "EMA50": safe_float(row.get("ema_50")),
                "EMA200": safe_float(row.get("ema_200")),
                "RS vs QQQ": safe_float(row.get("relative_strength")),
                "Letzte Daten": row.get("last_updated", ""),
                "Datenstatus": row.get("data_status", "unbekannt"),
                "Quelle": row.get("data_source", "unknown"),
                "Sauberer Stand": row.get("last_clean_date", ""),
            }
        ]
    )
    st.dataframe(
        compact,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe", ticker, timeframe),
    )


def render_symbol_chart(
    config: dict,
    result: dict,
    ticker: str,
    timeframe: str,
    store: Optional[WorkspaceStore] = None,
    email: str = "local",
    key_prefix: str = "chart",
    chart_type: Optional[str] = None,
    height: int = 660,
) -> None:
    history = chart_history(config, result, ticker, timeframe)
    if history.empty:
        st.warning("Keine historischen Chartdaten fuer diesen Fokus vorhanden.")
        return

    if chart_type is None:
        chart_type = st.radio(
            "Charttyp",
            ["Kerzen", "Linie"],
            horizontal=True,
            key=make_key(key_prefix, "chart_type", safe_widget_key(ticker), timeframe),
        )

    row = analysis_row_for_ticker(result, ticker, timeframe)
    if row:
        render_system_alert_tags(row, compact=False)
    history = history.sort_values("date").tail(chart_point_limit(timeframe)).copy()
    active_tools = chart_system_toolbar_state(key_prefix, ticker, timeframe)
    chart_lines = (
        store.list_chart_lines(email, ticker, timeframe)
        if store is not None
        else pd.DataFrame()
    )
    line_count = len(chart_lines) if not chart_lines.empty else 0
    line_label = (
        f"{line_count} gespeicherte Linien fuer {ticker} {timeframe} geladen"
        if line_count
        else f"Keine gespeicherten Linien fuer {ticker} {timeframe}"
    )
    st.markdown(
        f"<div class='sensei-line-status'>{escape(line_label)}</div>",
        unsafe_allow_html=True,
    )
    up_color = "#16803c"
    down_color = "#b42318"
    volume_colors = [
        up_color if close >= open_price else down_color
        for close, open_price in zip(history["close"], history["open"])
    ]

    show_volume = bool(active_tools.get("Volumen"))
    show_rsi = bool(active_tools.get("RSI"))
    show_relative_strength = bool(active_tools.get("Relative Staerke"))
    panel_rows = []
    if show_volume:
        panel_rows.append("volume")
    if show_rsi:
        panel_rows.append("rsi")
    if show_relative_strength:
        panel_rows.append("relative_strength")
    row_count = 1 + len(panel_rows)
    row_heights = [0.68] + [0.16] * len(panel_rows) if panel_rows else [1.0]
    fig = make_subplots(
        rows=row_count,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=row_heights,
    )
    if chart_type == "Linie":
        fig.add_trace(
            go.Scatter(
                x=history["date"],
                y=history["close"],
                mode="lines",
                name="Close",
                line=dict(width=2.2, color=SYSTEM_ALERT_COLOR),
                connectgaps=True,
            ),
            row=1,
            col=1,
        )
    else:
        fig.add_trace(
            go.Candlestick(
                x=history["date"],
                open=history["open"],
                high=history["high"],
                low=history["low"],
                close=history["close"],
                name="OHLC",
                increasing_line_color=up_color,
                decreasing_line_color=down_color,
            ),
            row=1,
            col=1,
        )
    ema_styles = {
        "ema_20": ("EMA20", "#2563eb"),
        "ema_50": ("EMA50", "#f59e0b"),
        "ema_100": ("EMA100", "#7c3aed"),
        "ema_200": ("EMA200", "#e5e7eb"),
    }
    for column, (label, color) in ema_styles.items():
        if column in history:
            fig.add_trace(
                go.Scatter(
                    x=history["date"],
                    y=history[column],
                    mode="lines",
                    name=label,
                    line=dict(width=1.4, color=color),
                    connectgaps=True,
                ),
                row=1,
                col=1,
            )

    if active_tools.get("Linien", False):
        add_chart_line_traces(fig, chart_lines)
    add_chart_system_overlays(fig, history, active_tools, row=row, timeframe=timeframe)

    panel_row = 2
    if show_volume:
        fig.add_trace(
            go.Bar(
                x=history["date"],
                y=history["volume"],
                name="Volumen",
                marker_color=volume_colors,
                opacity=0.45,
            ),
            row=panel_row,
            col=1,
        )
        fig.update_yaxes(title_text="Volumen", row=panel_row, col=1)
        panel_row += 1
    if show_rsi:
        add_rsi_panel(fig, history, panel_row)
        panel_row += 1
    if show_relative_strength:
        add_relative_strength_panel(fig, config, result, ticker, timeframe, panel_row)
        panel_row += 1
    fig.update_layout(
        title=f"{ticker} {chart_type} {timeframe}",
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        dragmode="pan",
        newshape=dict(line_color=SYSTEM_ALERT_COLOR, line_width=2),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        uirevision=f"{ticker}-{timeframe}",
    )
    style_plotly_figure(fig)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        row=1,
        col=1,
    )
    fig.update_yaxes(title_text="Preis", row=1, col=1)
    chart_config = {
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["select2d", "lasso2d"],
    }
    if active_tools.get("Linien", False):
        chart_config["modeBarButtonsToAdd"] = ["drawline", "eraseshape"]
    render_plotly_chart(
        fig,
        key=make_key(key_prefix, "plotly", ticker, timeframe),
        config=chart_config,
    )
    render_chart_system_toolbar(
        key_prefix=key_prefix,
        ticker=ticker,
        timeframe=timeframe,
        active_tools=active_tools,
    )
    st.caption(
        "Zoom mit Mausrad, Pan ueber Ziehen. Pink markiert System-/Alert-Linien und gespeicherte Erkennungspunkte."
    )
    if active_tools.get("Linien", False):
        render_chart_line_tools(
            store,
            email,
            ticker,
            timeframe,
            history,
            chart_lines,
            key_prefix=make_key(key_prefix, "lines"),
        )
    else:
        st.caption("Linien sind ausgeblendet. Aktiviere unten in der Werkzeugleiste 'Linien', um gespeicherte Linien und Linienwerkzeuge zu sehen.")


def chart_system_toolbar_state(key_prefix: str, ticker: str, timeframe: str) -> dict[str, bool]:
    defaults = {"Linien": True}
    return {
        tool: bool(
            st.session_state.get(
                chart_system_tool_key(key_prefix, ticker, timeframe, tool),
                defaults.get(tool, False),
            )
        )
        for tool in CHART_SYSTEM_TOOLS
    }


def chart_system_tool_key(key_prefix: str, ticker: str, timeframe: str, tool: str) -> str:
    return make_key(key_prefix, "hauptsystem", safe_widget_key(ticker), timeframe, tool)


def render_chart_system_toolbar(
    key_prefix: str,
    ticker: str,
    timeframe: str,
    active_tools: dict[str, bool],
) -> None:
    active_count = sum(1 for value in active_tools.values() if value)
    st.markdown(
        (
            "<div class='sensei-chart-toolbar'>"
            "<div class='sensei-chart-toolbar-title'>"
            "<strong>Hauptsystem Werkzeugleiste</strong>"
            f"{status_badge_html(f'{active_count} sichtbar', 'pink')}"
            "</div>"
            "<span class='sensei-muted'>Setups laufen im Hintergrund. Sichtbar werden sie nur, wenn du sie hier einschaltest.</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    tool_rows = [
        CHART_SYSTEM_TOOLS[index : index + 5]
        for index in range(0, len(CHART_SYSTEM_TOOLS), 5)
    ]
    for row_index, tools in enumerate(tool_rows):
        columns = st.columns(len(tools))
        for index, tool in enumerate(tools):
            with columns[index]:
                st.checkbox(
                    tool,
                    value=active_tools.get(tool, False),
                    key=chart_system_tool_key(key_prefix, ticker, timeframe, tool),
                )


def add_chart_system_overlays(
    fig,
    history: pd.DataFrame,
    active_tools: dict[str, bool],
    row: dict,
    timeframe: str,
) -> None:
    if active_tools.get("Beobachtung"):
        add_observation_overlay(fig, history, row)
    if active_tools.get("EMA Signale"):
        add_ema_signal_overlay(fig, history)
    if active_tools.get("Fibonacci"):
        add_fibonacci_overlay(fig, history)
    if active_tools.get("Alligator"):
        add_alligator_overlay(fig, history)
    if active_tools.get("Order Blocks"):
        add_order_block_overlay(fig, history)
    if active_tools.get("Breakouts"):
        add_breakout_overlay(fig, history)
    if active_tools.get("Tick-Waves"):
        add_tick_wave_overlay(fig, history)
    if active_tools.get("Monat Aufstieg") or active_tools.get("Monat Abstieg"):
        add_monthly_direction_overlay(
            fig,
            history,
            show_up=active_tools.get("Monat Aufstieg", False),
            show_down=active_tools.get("Monat Abstieg", False),
        )


def add_observation_overlay(fig, history: pd.DataFrame, row: dict) -> None:
    if history.empty:
        return
    latest = history.iloc[-1]
    tags = system_alert_tags(row)
    label = "Beobachtung"
    if tags:
        label = " / ".join(tags[:2])
    fig.add_trace(
        go.Scatter(
            x=[latest["date"]],
            y=[latest["close"]],
            mode="markers+text",
            name="Beobachtung",
            text=[label],
            textposition="top center",
            marker=dict(size=11, color=SYSTEM_ALERT_COLOR, symbol="diamond"),
            hovertemplate=f"{label}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>",
        ),
        row=1,
        col=1,
    )


def add_ema_signal_overlay(fig, history: pd.DataFrame) -> None:
    if history.empty or not {"ema_20", "ema_50", "close"}.issubset(history.columns):
        return
    frame = history[["date", "close", "ema_20", "ema_50"]].copy()
    frame["ema_spread"] = pd.to_numeric(frame["ema_20"], errors="coerce") - pd.to_numeric(
        frame["ema_50"],
        errors="coerce",
    )
    frame["prev_spread"] = frame["ema_spread"].shift(1)
    frame = frame.dropna(subset=["date", "close", "ema_spread", "prev_spread"])
    if frame.empty:
        return

    bullish = frame[(frame["ema_spread"] > 0) & (frame["prev_spread"] <= 0)].tail(10)
    bearish = frame[(frame["ema_spread"] < 0) & (frame["prev_spread"] >= 0)].tail(10)
    if not bullish.empty:
        fig.add_trace(
            go.Scatter(
                x=bullish["date"],
                y=bullish["close"],
                mode="markers",
                name="EMA20 > EMA50",
                marker=dict(symbol="triangle-up", size=11, color="#22c55e"),
                hovertemplate="EMA-Cross hoch<br>%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if not bearish.empty:
        fig.add_trace(
            go.Scatter(
                x=bearish["date"],
                y=bearish["close"],
                mode="markers",
                name="EMA20 < EMA50",
                marker=dict(symbol="triangle-down", size=11, color="#f43f5e"),
                hovertemplate="EMA-Cross runter<br>%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.clip(lower=0, upper=100)


def add_rsi_panel(fig, history: pd.DataFrame, panel_row: int) -> None:
    if history.empty or "close" not in history:
        return
    frame = history[["date", "close"]].copy()
    frame["rsi_14"] = calculate_rsi(frame["close"], period=14)
    frame = frame.dropna(subset=["date", "rsi_14"])
    if frame.empty:
        return

    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["rsi_14"],
            mode="lines",
            name="RSI14",
            line=dict(width=1.7, color=SYSTEM_ALERT_COLOR),
            hovertemplate="RSI14<br>%{x|%Y-%m-%d}<br>%{y:.1f}<extra></extra>",
        ),
        row=panel_row,
        col=1,
    )
    for level, color in [(70, "rgba(244, 63, 94, 0.72)"), (30, "rgba(34, 197, 94, 0.72)")]:
        fig.add_trace(
            go.Scatter(
                x=[frame["date"].iloc[0], frame["date"].iloc[-1]],
                y=[level, level],
                mode="lines",
                name=f"RSI {level}",
                line=dict(width=1, dash="dot", color=color),
                hoverinfo="skip",
            ),
            row=panel_row,
            col=1,
        )
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=panel_row, col=1)


def add_relative_strength_panel(
    fig,
    config: dict,
    result: dict,
    ticker: str,
    timeframe: str,
    panel_row: int,
) -> None:
    benchmark = str(config.get("benchmark", "QQQ") or "QQQ").upper()
    ticker_key = str(ticker).upper()
    if benchmark == ticker_key:
        benchmark = "SPY"

    symbol_history = chart_history(config, result, ticker_key, timeframe)
    benchmark_history = chart_history(config, result, benchmark, timeframe)
    if symbol_history.empty or benchmark_history.empty:
        return

    symbol = symbol_history[["date", "close"]].rename(columns={"close": "symbol_close"}).copy()
    bench = benchmark_history[["date", "close"]].rename(columns={"close": "benchmark_close"}).copy()
    merged = symbol.merge(bench, on="date", how="inner").sort_values("date")
    merged["symbol_close"] = pd.to_numeric(merged["symbol_close"], errors="coerce")
    merged["benchmark_close"] = pd.to_numeric(merged["benchmark_close"], errors="coerce")
    merged = merged.dropna(subset=["date", "symbol_close", "benchmark_close"])
    merged = merged[(merged["symbol_close"] > 0) & (merged["benchmark_close"] > 0)]
    if merged.empty:
        return

    merged["rs_line"] = merged["symbol_close"] / merged["benchmark_close"]
    first_value = float(merged["rs_line"].iloc[0])
    if first_value <= 0:
        return
    merged["rs_line"] = merged["rs_line"] / first_value * 100
    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["rs_line"],
            mode="lines",
            name=f"RS vs {benchmark}",
            line=dict(width=1.8, color="#38bdf8"),
            hovertemplate=f"RS vs {benchmark}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>",
        ),
        row=panel_row,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[merged["date"].iloc[0], merged["date"].iloc[-1]],
            y=[100, 100],
            mode="lines",
            name="RS Basis 100",
            line=dict(width=1, dash="dot", color="rgba(245, 245, 247, 0.42)"),
            hoverinfo="skip",
        ),
        row=panel_row,
        col=1,
    )
    fig.update_yaxes(title_text=f"RS {benchmark}", row=panel_row, col=1)


def add_fibonacci_overlay(fig, history: pd.DataFrame) -> None:
    window = history.tail(min(len(history), 160)).copy()
    if window.empty:
        return
    high = float(window["high"].max())
    low = float(window["low"].min())
    if high <= low:
        return
    start = window["date"].iloc[0]
    end = window["date"].iloc[-1]
    levels = [
        ("0.0", high),
        ("23.6", high - (high - low) * 0.236),
        ("38.2", high - (high - low) * 0.382),
        ("50.0", high - (high - low) * 0.5),
        ("61.8", high - (high - low) * 0.618),
        ("78.6", high - (high - low) * 0.786),
        ("100.0", low),
    ]
    for label, value in levels:
        fig.add_trace(
            go.Scatter(
                x=[start, end],
                y=[value, value],
                mode="lines",
                name=f"Fib {label}",
                line=dict(color="rgba(255, 43, 214, 0.42)", width=1, dash="dot"),
                hovertemplate=f"Fib {label}<br>%{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )


def add_alligator_overlay(fig, history: pd.DataFrame) -> None:
    frame = history.copy()
    median_price = (frame["high"] + frame["low"]) / 2
    alligator_lines = {
        "Alligator Jaw": (median_price.ewm(span=13, adjust=False, min_periods=13).mean().shift(8), "#38bdf8"),
        "Alligator Teeth": (median_price.ewm(span=8, adjust=False, min_periods=8).mean().shift(5), "#f43f5e"),
        "Alligator Lips": (median_price.ewm(span=5, adjust=False, min_periods=5).mean().shift(3), "#22c55e"),
    }
    for name, (values, color) in alligator_lines.items():
        fig.add_trace(
            go.Scatter(
                x=frame["date"],
                y=values,
                mode="lines",
                name=name,
                line=dict(width=1.35, color=color),
                connectgaps=True,
            ),
            row=1,
            col=1,
        )


def add_order_block_overlay(fig, history: pd.DataFrame) -> None:
    frame = history.tail(min(len(history), 140)).copy()
    if frame.empty or "volume" not in frame:
        return
    frame["volume_avg"] = frame["volume"].rolling(20, min_periods=8).mean()
    candidates = frame[
        (frame["volume_avg"] > 0)
        & (frame["volume"] >= frame["volume_avg"] * 1.35)
        & ((frame["close"] - frame["open"]).abs() > 0)
    ].tail(6)
    if candidates.empty:
        return
    chart_end = frame["date"].iloc[-1]
    for index, candle in candidates.iterrows():
        bullish = float(candle["close"]) >= float(candle["open"])
        y0 = min(float(candle["open"]), float(candle["close"]))
        y1 = max(float(candle["open"]), float(candle["close"]))
        color = "rgba(34, 197, 94, 0.12)" if bullish else "rgba(244, 63, 94, 0.13)"
        line_color = "rgba(34, 197, 94, 0.38)" if bullish else "rgba(244, 63, 94, 0.38)"
        fig.add_shape(
            type="rect",
            x0=candle["date"],
            x1=chart_end,
            y0=y0,
            y1=y1,
            xref="x",
            yref="y",
            fillcolor=color,
            line=dict(color=line_color, width=1),
            layer="below",
        )


def add_breakout_overlay(fig, history: pd.DataFrame) -> None:
    frame = history.copy()
    if len(frame) < 25:
        return
    frame["prior_high_20"] = frame["high"].rolling(20, min_periods=10).max().shift(1)
    frame["prior_low_20"] = frame["low"].rolling(20, min_periods=10).min().shift(1)
    latest = frame.iloc[-1]
    for label, column, color in [
        ("Breakout High 20", "prior_high_20", "#22c55e"),
        ("Breakdown Low 20", "prior_low_20", "#f43f5e"),
    ]:
        value = latest.get(column)
        if value is None or pd.isna(value):
            continue
        fig.add_trace(
            go.Scatter(
                x=[frame["date"].iloc[0], frame["date"].iloc[-1]],
                y=[value, value],
                mode="lines",
                name=label,
                line=dict(color=color, width=1.4, dash="dash"),
                hovertemplate=f"{label}<br>%{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    up = frame[frame["close"] > frame["prior_high_20"]].tail(8)
    down = frame[frame["close"] < frame["prior_low_20"]].tail(8)
    if not up.empty:
        fig.add_trace(
            go.Scatter(
                x=up["date"],
                y=up["close"],
                mode="markers",
                name="Breakout",
                marker=dict(symbol="triangle-up", size=10, color="#22c55e"),
            ),
            row=1,
            col=1,
        )
    if not down.empty:
        fig.add_trace(
            go.Scatter(
                x=down["date"],
                y=down["close"],
                mode="markers",
                name="Breakdown",
                marker=dict(symbol="triangle-down", size=10, color="#f43f5e"),
            ),
            row=1,
            col=1,
        )


def add_tick_wave_overlay(fig, history: pd.DataFrame) -> None:
    pivots = tick_wave_pivots(history)
    if len(pivots) < 2:
        return
    fig.add_trace(
        go.Scatter(
            x=[point["date"] for point in pivots],
            y=[point["price"] for point in pivots],
            mode="lines+markers",
            name="Tick-Waves",
            line=dict(color=SYSTEM_ALERT_COLOR, width=1.7),
            marker=dict(size=6, color=SYSTEM_ALERT_COLOR),
            hovertemplate="Tick-Wave<br>%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )


def tick_wave_pivots(history: pd.DataFrame) -> list[dict]:
    frame = history.tail(min(len(history), 220)).copy()
    if frame.empty:
        return []
    threshold = max(0.018, float(frame["close"].pct_change().rolling(20, min_periods=8).std().iloc[-1] or 0) * 1.5)
    pivots = [{"date": frame["date"].iloc[0], "price": float(frame["close"].iloc[0])}]
    direction = 0
    extreme_price = float(frame["close"].iloc[0])
    extreme_date = frame["date"].iloc[0]
    for _, row in frame.iloc[1:].iterrows():
        price = float(row["close"])
        change = (price - extreme_price) / extreme_price if extreme_price else 0
        if direction >= 0:
            if price >= extreme_price:
                extreme_price = price
                extreme_date = row["date"]
            elif change <= -threshold:
                pivots.append({"date": extreme_date, "price": extreme_price})
                direction = -1
                extreme_price = price
                extreme_date = row["date"]
        if direction <= 0:
            if price <= extreme_price:
                extreme_price = price
                extreme_date = row["date"]
            elif change >= threshold:
                pivots.append({"date": extreme_date, "price": extreme_price})
                direction = 1
                extreme_price = price
                extreme_date = row["date"]
    pivots.append({"date": extreme_date, "price": extreme_price})
    return pivots[-24:]


def add_monthly_direction_overlay(
    fig,
    history: pd.DataFrame,
    show_up: bool,
    show_down: bool,
) -> None:
    if history.empty:
        return
    frame = history.copy()
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M")
    monthly = (
        frame.groupby("month")
        .agg(
            date=("date", "max"),
            open=("open", "first"),
            close=("close", "last"),
        )
        .reset_index(drop=True)
        .tail(18)
    )
    if show_up:
        up = monthly[monthly["close"] >= monthly["open"]]
        if not up.empty:
            fig.add_trace(
                go.Scatter(
                    x=up["date"],
                    y=up["close"],
                    mode="markers",
                    name="Monat Aufstieg",
                    marker=dict(symbol="triangle-up", size=12, color="#22c55e"),
                ),
                row=1,
                col=1,
            )
    if show_down:
        down = monthly[monthly["close"] < monthly["open"]]
        if not down.empty:
            fig.add_trace(
                go.Scatter(
                    x=down["date"],
                    y=down["close"],
                    mode="markers",
                    name="Monat Abstieg",
                    marker=dict(symbol="triangle-down", size=12, color="#f43f5e"),
                ),
                row=1,
                col=1,
            )


def add_chart_line_traces(fig, chart_lines: pd.DataFrame) -> None:
    if chart_lines is None or chart_lines.empty:
        return

    for _, line in chart_lines.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[pd.to_datetime(line["start_date"]), pd.to_datetime(line["end_date"])],
                y=[float(line["start_price"]), float(line["end_price"])],
                mode="lines+markers",
                name=f"Linie: {line['name']}",
                line=dict(color=line.get("color") or SYSTEM_ALERT_COLOR, width=2),
                marker=dict(size=6),
                hovertemplate=(
                    f"{line['name']}<br>"
                    "%{x|%Y-%m-%d}<br>"
                    "%{y:.2f}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )


def chart_line_presets(ticker: str, timeframe: str, history: pd.DataFrame) -> list[dict]:
    if history.empty:
        return []

    frame = history.sort_values("date").dropna(subset=["date", "high", "low", "close"]).copy()
    if frame.empty:
        return []

    frame = frame.tail(min(len(frame), chart_point_limit(timeframe)))
    visible_start = frame.iloc[0]
    latest = frame.iloc[-1]
    trend_start = frame.iloc[max(0, len(frame) - 30)]
    low_row = frame.loc[frame["low"].idxmin()]
    high_row = frame.loc[frame["high"].idxmax()]
    latest_close = float(latest["close"])
    support_price = float(low_row["low"])
    resistance_price = float(high_row["high"])

    return [
        {
            "label": "Close-Linie",
            "name": f"{ticker} Close {timeframe}",
            "start_date": visible_start["date"],
            "start_price": latest_close,
            "end_date": latest["date"],
            "end_price": latest_close,
            "color": SYSTEM_ALERT_COLOR,
            "note": "Schnelllinie: letzter Close.",
        },
        {
            "label": "Support",
            "name": f"{ticker} Support {timeframe}",
            "start_date": visible_start["date"],
            "start_price": support_price,
            "end_date": latest["date"],
            "end_price": support_price,
            "color": "#22c55e",
            "note": "Schnelllinie: sichtbares Tief.",
        },
        {
            "label": "Widerstand",
            "name": f"{ticker} Widerstand {timeframe}",
            "start_date": visible_start["date"],
            "start_price": resistance_price,
            "end_date": latest["date"],
            "end_price": resistance_price,
            "color": "#f43f5e",
            "note": "Schnelllinie: sichtbares Hoch.",
        },
        {
            "label": "Trend 30",
            "name": f"{ticker} Trend 30 {timeframe}",
            "start_date": trend_start["date"],
            "start_price": float(trend_start["close"]),
            "end_date": latest["date"],
            "end_price": latest_close,
            "color": SYSTEM_ALERT_COLOR,
            "note": "Schnelllinie: 30-Kerzen-Trend.",
        },
    ]


def render_chart_line_tools(
    store: Optional[WorkspaceStore],
    email: str,
    ticker: str,
    timeframe: str,
    history: pd.DataFrame,
    chart_lines: pd.DataFrame,
    key_prefix: str,
) -> None:
    if store is None:
        return

    safe_key = make_key(key_prefix, ticker, timeframe)
    last_row = history.iloc[-1]
    start_row = history.iloc[max(0, len(history) - 30)]
    default_start_date = pd.to_datetime(start_row["date"]).date()
    default_end_date = pd.to_datetime(last_row["date"]).date()
    default_start_price = float(start_row["close"])
    default_end_price = float(last_row["close"])

    with st.expander(f"Linien speichern und verwalten ({safe_key})", expanded=False):
        render_system_alert_panel(
            "Pink Alert: Linien",
            "Gespeicherte Linien sind Alert- und Erkennungspunkte. Sie markieren keine Order und keine Ausfuehrung.",
        )
        presets = chart_line_presets(ticker, timeframe, history)
        if presets:
            st.markdown("**Schnelllinien speichern**")
            preset_columns = st.columns(min(4, len(presets)))
            for index, preset in enumerate(presets):
                with preset_columns[index % len(preset_columns)]:
                    if st.button(
                        preset["label"],
                        key=make_key(safe_key, "quick_line", index, preset["label"]),
                        width="stretch",
                    ):
                        try:
                            store.save_chart_line(
                                email=email,
                                ticker=ticker,
                                timeframe=timeframe,
                                name=preset["name"],
                                start_date=preset["start_date"],
                                start_price=preset["start_price"],
                                end_date=preset["end_date"],
                                end_price=preset["end_price"],
                                color=preset["color"],
                                note=preset["note"],
                                pinned=True,
                            )
                            store.record_event(
                                email,
                                "chart_quick_line_saved",
                                ticker,
                                timeframe,
                                preset["name"],
                            )
                            st.success(f"{preset['label']} gespeichert.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Schnelllinie konnte nicht gespeichert werden: {exc}")
            st.caption("Schnelllinien werden dauerhaft pro Symbol und Timeframe gespeichert.")

        with st.form(make_key(safe_key, "chart_line_form"), clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input(
                    "Name",
                    value=f"{ticker} Linie",
                    key=make_key(safe_key, "line_name"),
                )
                start_date = st.date_input(
                    "Startdatum",
                    value=default_start_date,
                    key=make_key(safe_key, "start_date"),
                )
                start_price = st.number_input(
                    "Startpreis",
                    min_value=0.01,
                    value=max(default_start_price, 0.01),
                    step=0.01,
                    key=make_key(safe_key, "start_price"),
                )
            with col2:
                color = st.color_picker(
                    "Farbe",
                    value=SYSTEM_ALERT_COLOR,
                    key=make_key(safe_key, "color"),
                )
                end_date = st.date_input(
                    "Enddatum",
                    value=default_end_date,
                    key=make_key(safe_key, "end_date"),
                )
                end_price = st.number_input(
                    "Endpreis",
                    min_value=0.01,
                    value=max(default_end_price, 0.01),
                    step=0.01,
                    key=make_key(safe_key, "end_price"),
                )
            note = st.text_input(
                "Notiz optional",
                placeholder="z.B. Widerstand oder Trendlinie",
                key=make_key(safe_key, "note"),
            )
            pinned = st.checkbox(
                "Linie oben halten",
                value=True,
                key=make_key(safe_key, "pinned"),
            )
            submitted = st.form_submit_button(
                "Linie speichern",
                key=make_key(safe_key, "submit"),
                width="stretch",
            )
            if submitted:
                if pd.Timestamp(start_date) > pd.Timestamp(end_date):
                    st.error("Startdatum muss vor dem Enddatum liegen.")
                else:
                    try:
                        store.save_chart_line(
                            email=email,
                            ticker=ticker,
                            timeframe=timeframe,
                            name=name,
                            start_date=start_date,
                            start_price=start_price,
                            end_date=end_date,
                            end_price=end_price,
                            color=color,
                            note=note,
                            pinned=pinned,
                        )
                        store.record_event(email, "chart_line_saved", ticker, timeframe, name)
                        st.success("Linie gespeichert.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Linie konnte nicht gespeichert werden: {exc}")

        if chart_lines.empty:
            render_empty_state(
                "Noch keine gespeicherten Linien",
                "Nutze eine Schnelllinie oder trage Start und Ende ein. Gespeicherte Linien erscheinen beim naechsten Oeffnen wieder.",
            )
            return

        display = chart_lines[
            [
                "name",
                "start_date",
                "start_price",
                "end_date",
                "end_price",
                "color",
                "note",
            ]
        ].copy()
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(safe_key, "chart_lines_dataframe"),
            column_config={
                "start_price": st.column_config.NumberColumn("Startpreis", format="%.2f"),
                "end_price": st.column_config.NumberColumn("Endpreis", format="%.2f"),
            },
        )

        labels = {
            row["id"]: f"{row['name']} | {pd.to_datetime(row['start_date']).date()}"
            for _, row in chart_lines.iterrows()
        }
        selected_line_id = st.selectbox(
            "Linie loeschen",
            chart_lines["id"].tolist(),
            format_func=lambda value: labels.get(value, value),
            key=make_key(safe_key, "delete_select"),
        )
        if st.button(
            "Ausgewaehlte Linie loeschen",
            key=make_key(safe_key, "delete_button"),
        ):
            store.delete_chart_line(email, selected_line_id)
            st.success("Linie geloescht.")
            st.rerun()


def chart_history(config: dict, result: dict, ticker: str, timeframe: str) -> pd.DataFrame:
    histories = result.get("histories", {})
    key = f"{ticker}|{timeframe}"
    history = histories.get(key)
    if history is not None and not history.empty:
        return normalize_chart_history(history)

    data_config = config.get("data", {})
    period = data_config.get("periods", {}).get(timeframe, "2y")
    cache_dir = data_config.get("cache_dir", "data/cache")
    try:
        provider = DataProvider(
            BASE_DIR / cache_dir if not Path(cache_dir).is_absolute() else cache_dir,
            cache_max_age_hours=data_config.get("cache_max_age_hours", {}),
            prefer_cache=data_config.get("prefer_cache", True),
        )
        return normalize_chart_history(
            add_indicators(provider.fetch_history(ticker, period=period, interval=timeframe))
        )
    except Exception as exc:
        logger.exception("Could not load chart history for %s %s", ticker, timeframe)
        st.error(f"Chartdaten konnten nicht geladen werden: {exc}")
        return pd.DataFrame()


def normalize_chart_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ema_20",
        "ema_50",
        "ema_100",
        "ema_200",
    ]:
        if column not in frame:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "open", "high", "low", "close"])


def chart_point_limit(timeframe: str) -> int:
    if timeframe == "1mo":
        return 240
    if timeframe == "1wk":
        return 260
    return 420


def render_collection_overview(
    config: dict,
    store: WorkspaceStore,
    email: str,
    key_prefix: str,
) -> None:
    st.markdown("### Gesammelte Daten")
    topics = store.list_topics(email)
    custom_symbols = store.list_watchlist_symbols(email)
    events = store.recent_events(email, limit=20)
    col1, col2, col3 = st.columns(3)
    col1.metric("Gespeicherte Themen", len(topics))
    col2.metric("Eigene Watchlist-Symbole", len(custom_symbols))
    col3.metric("Events", len(events))
    if not events.empty:
        st.dataframe(
            events[["event_type", "ticker", "timeframe", "detail", "created_at"]],
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "events_dataframe"),
        )
    else:
        render_empty_state(
            "Noch keine Aktivitaet",
            "Klicke Analysieren, Beobachten oder Speichern. Danach entsteht hier dein Verlauf.",
        )


def render_watchlist(config: dict, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    watchlist = result["watchlist"]
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    store.ensure_default_watchlists(email, watchlist_categories(config))

    render_section_title("Watchlist", f"Relative Staerke gegen {config.get('benchmark', 'QQQ')}")
    render_timeframe_buttons(
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        make_key(key_prefix, "timeframe"),
        make_key(key_prefix, "timeframe_buttons"),
    )
    timeframe = st.selectbox(
        "Timeframe",
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        key=make_key(key_prefix, "timeframe"),
    )
    filtered = watchlist[watchlist["timeframe"] == timeframe]
    if filtered.empty:
        render_empty_state(
            "Keine Watchlist-Daten",
            "Klicke Analysieren, damit die Mag7-Werte fuer diesen Timeframe geladen werden.",
        )
    else:
        render_section_title("Schnellueberblick", "Beste Kandidaten als Karten.")
        render_today_cards(
            filtered.sort_values("score", ascending=False).head(6),
            store,
            email,
            timeframe,
            key_prefix=make_key(key_prefix, "quick_cards"),
        )
        render_section_title("Sortierte Tabelle", "Score, Trend, Risk State und Relative Staerke.")
        render_watchlist_badge_table(
            filtered.sort_values("score", ascending=False),
            key_prefix=make_key(key_prefix, "badge_table"),
            compact=False,
        )
        with st.expander(f"Rohdaten anzeigen ({key_prefix})", expanded=False):
            render_analysis_table(filtered, key_prefix=make_key(key_prefix, "analysis_table"))
        with st.expander(f"Charts anzeigen ({key_prefix})", expanded=False):
            render_score_chart(
                filtered,
                f"Mag7 Scores {timeframe}",
                key_prefix=make_key(key_prefix, "score_chart"),
            )
            render_relative_strength_chart(filtered, key_prefix=make_key(key_prefix, "relative_strength_chart"))
    st.divider()
    render_section_title("Eigene Watchlists", "Kategorien, Pins und eigene Ideen.")
    render_custom_watchlists(
        config=config,
        store=store,
        email=email,
        result=result,
        key_prefix="watchlist",
        compact=False,
    )


def render_sector_rotation(config: dict, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    sectors = result.get("sector_rotation", pd.DataFrame())
    histories = result.get("histories", {})
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])

    render_section_title(
        "Sektorrotation",
        "Heatmap, Kapitalfluss und Veraenderung fuer Sektoren, Bau, Gold, Dollar und Treasuries.",
    )
    render_timeframe_buttons(
        timeframes,
        make_key(key_prefix, "timeframe"),
        make_key(key_prefix, "timeframe_buttons"),
    )
    timeframe = st.selectbox(
        "Timeframe",
        timeframes,
        key=make_key(key_prefix, "timeframe"),
    )

    if st.button(
        "Sektorrotation analysieren",
        key=make_key(key_prefix, "analyze"),
        type="primary",
        width="stretch",
    ):
        _run_update(config, generate_reports=True)

    if sectors.empty:
        render_empty_state(
            "Noch keine Sektor-Daten",
            "Starte Sektorrotation analysieren. Danach zeigt die App, welche Gruppen relative Staerke gegen SPY zeigen.",
        )
        render_sector_rotation_settings(config, key_prefix=make_key(key_prefix, "settings"))
        return

    filtered = sector_rotation_display_frame(config, sectors, timeframe, histories)
    if filtered.empty:
        render_empty_state(
            "Keine Sektor-Daten fuer diesen Timeframe",
            "Waehle einen anderen Timeframe oder starte die Analyse neu.",
        )
        return

    categories = ["Alle"] + sector_rotation_categories(config)
    selected_category = st.selectbox(
        "Kategorie",
        categories,
        key=make_key(key_prefix, "category"),
    )
    if selected_category != "Alle":
        filtered = filtered[filtered["category"] == selected_category]
    if filtered.empty:
        render_empty_state(
            "Keine Sektoren in dieser Kategorie",
            "Waehle Alle oder eine andere Kategorie.",
        )
        return

    render_sector_money_flow_summary(
        filtered,
        timeframe,
        key_prefix=make_key(key_prefix, "money_flow"),
    )

    render_section_title(
        "Vergleichsgruppen",
        "Tech, Finance, Bau, Energie, Gold, Dollar und Treasuries im direkten Vergleich.",
    )
    render_sector_group_comparison(filtered, key_prefix=make_key(key_prefix, "comparison"))

    col_left, col_right = st.columns([1.15, 0.85], gap="large")
    with col_left:
        render_section_title("Wo Geld hinwandert", "Sortiert nach relativer Staerke, Score und Veraenderung.")
        render_sector_rotation_table(filtered, key_prefix=make_key(key_prefix, "table"))
    with col_right:
        render_section_title("Dollar & Treasuries", "Defensiver Makro-Kontext.")
        render_macro_rotation_cards(filtered)

    render_section_title("Score-Heatmap", "Blockgroesse und Farbe zeigen den Score von 0 bis 100.")
    render_sector_rotation_heatmap(filtered, key_prefix=make_key(key_prefix, "heatmap"))

    render_section_title("Kapitalfluss-Map", "Relative Staerke gegen SPY vs Score. Pink markiert System-Auswertung.")
    render_sector_rotation_flow_map(filtered, key_prefix=make_key(key_prefix, "flow_map"))

    render_section_title("Sektor-Watchlist einstellen", "Nur Sektoren und Makro-Proxies, keine Einzelaktien.")
    render_sector_rotation_settings(config, key_prefix=make_key(key_prefix, "settings"))


def sector_rotation_display_frame(
    config: dict,
    sectors: pd.DataFrame,
    timeframe: str,
    histories: Optional[dict] = None,
) -> pd.DataFrame:
    frame = sectors[sectors["timeframe"] == timeframe].copy()
    if frame.empty:
        return frame
    category_map = {
        str(entry.get("ticker", "")).upper(): str(entry.get("category", "Eigene Sektoren"))
        for entry in config.get("sector_rotation_symbols", [])
        if isinstance(entry, dict)
    }
    frame["ticker_lookup"] = frame["ticker"].astype(str).str.upper()
    frame["category"] = frame["ticker_lookup"].map(category_map).fillna("Eigene Sektoren")
    frame["score_numeric"] = numeric_frame_column(frame, "score")
    frame["relative_strength_numeric"] = numeric_frame_column(frame, "relative_strength")
    frame["return_1_numeric"] = numeric_frame_column(frame, "return_1")
    frame["return_5_numeric"] = numeric_frame_column(frame, "return_5")
    frame["return_20_numeric"] = numeric_frame_column(frame, "return_20")
    change_rows = [
        sector_history_changes(histories or {}, str(row.get("ticker", "")), timeframe)
        for _, row in frame.iterrows()
    ]
    changes = pd.DataFrame(change_rows, index=frame.index)
    for column, fallback_column in {
        "change_1p_pct": "return_1_numeric",
        "change_5p_pct": "return_5_numeric",
        "change_20p_pct": "return_20_numeric",
    }.items():
        if column in changes:
            frame[column] = pd.to_numeric(changes[column], errors="coerce").fillna(frame[fallback_column])
        else:
            frame[column] = frame[fallback_column]
    frame["money_flow"] = frame.apply(classify_money_flow, axis=1)
    return frame.sort_values(
        ["relative_strength_numeric", "score_numeric", "change_5p_pct"],
        ascending=False,
    )


def numeric_frame_column(frame: pd.DataFrame, column: str, fallback: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(fallback, index=frame.index, dtype="float")
    return pd.to_numeric(frame[column], errors="coerce").fillna(fallback)


def sector_history_changes(histories: dict, ticker: str, timeframe: str) -> dict:
    history = histories.get(f"{ticker}|{timeframe}")
    if history is None or history.empty or "close" not in history:
        return {}
    frame = history.copy()
    if "date" in frame:
        frame = frame.sort_values("date")
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    return {
        "change_1p_pct": period_change_pct(closes, 1),
        "change_5p_pct": period_change_pct(closes, 5),
        "change_20p_pct": period_change_pct(closes, 20),
    }


def period_change_pct(closes: pd.Series, periods: int) -> float:
    if len(closes) <= periods:
        return 0.0
    latest = float(closes.iloc[-1])
    base = float(closes.iloc[-1 - periods])
    if base == 0:
        return 0.0
    return round((latest / base - 1) * 100, 2)


def classify_money_flow(row) -> str:
    trend = str(row.get("trend", "")).lower()
    rs = safe_float(row.get("relative_strength_numeric"), 0)
    score = safe_float(row.get("score_numeric"), 0)
    week_change = safe_float(row.get("change_5p_pct"), 0)
    category = str(row.get("category", ""))
    if trend == "bullish" and rs > 0 and score >= 60 and week_change >= 0:
        return "Zufluss"
    if category in ["Treasuries", "Treasury Yields", "Waehrung"] and trend == "bullish":
        return "Defensiv Watch"
    if trend == "bearish" or rs < 0:
        return "Abfluss"
    return "Neutral"


def render_sector_money_flow_summary(df: pd.DataFrame, timeframe: str, key_prefix: str) -> None:
    if df.empty:
        return
    strongest = df.iloc[0]
    weakest = df.sort_values(["relative_strength_numeric", "score_numeric"], ascending=True).iloc[0]
    inflow = int((df["money_flow"] == "Zufluss").sum())
    outflow = int((df["money_flow"] == "Abfluss").sum())
    flow_state = sector_capital_flow_state(df)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Timeframe", timeframe)
    col2.metric("Kapitalfluss", flow_state["label"], delta=f"{flow_state['spread']:.1f} Spread")
    col3.metric("Risk-On", f"{flow_state['risk_on_score']:.1f}")
    col4.metric("Risk-Off", f"{flow_state['risk_off_score']:.1f}")
    col5.metric("Zufluss / Abfluss", f"{inflow} / {outflow}")
    st.markdown(
        f"""
        <div class="sensei-alert-panel">
            <strong>Pink System-Auswertung:</strong>
            {status_badge_html(flow_state["label"], flow_state["badge"])}
            Leader: {escape(str(strongest.get("label", strongest.get("ticker", ""))))}.
            Schwach: {escape(str(weakest.get("label", weakest.get("ticker", "offen"))))}.
            Keine Order, nur Marktanalyse.
        </div>
        """,
        unsafe_allow_html=True,
    )
    flow_frame = sector_group_comparison_frame(df)
    if not flow_frame.empty:
        fig = px.bar(
            flow_frame.sort_values("rotation_strength", ascending=True),
            x="rotation_strength",
            y="group",
            color="flow_state",
            orientation="h",
            text="rotation_strength",
            title="Kapitalfluss-Staerke nach Vergleichsgruppe",
        )
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside", cliponaxis=False)
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
        style_plotly_figure(fig)
        render_plotly_chart(fig, key=make_key(key_prefix, "strength_plotly"))
    st.caption(
        "Risk-On wird aus Tech, Finance, Bau, Energie und zyklischen Maerkten gelesen. "
        "Risk-Off nutzt Gold, Dollar, defensive Sektoren und Treasury-Proxies."
    )


def sector_capital_flow_state(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "label": "Neutral",
            "badge": "gray",
            "risk_on_score": 0.0,
            "risk_off_score": 0.0,
            "spread": 0.0,
        }
    risk_on = df[df["ticker_lookup"].isin(RISK_ON_ROTATION_TICKERS)].copy()
    risk_off = df[df["ticker_lookup"].isin(RISK_OFF_ROTATION_TICKERS)].copy()
    risk_on_score = rotation_strength_score(risk_on)
    risk_off_score = rotation_strength_score(risk_off)
    spread = risk_on_score - risk_off_score
    if spread >= 8:
        label = "Risk-On"
        badge = "green"
    elif spread <= -8:
        label = "Risk-Off"
        badge = "pink"
    else:
        label = "Uebergang"
        badge = "yellow"
    return {
        "label": label,
        "badge": badge,
        "risk_on_score": round(risk_on_score, 1),
        "risk_off_score": round(risk_off_score, 1),
        "spread": round(spread, 1),
    }


def rotation_strength_score(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    score = pd.to_numeric(df.get("score_numeric", 0), errors="coerce").fillna(0).mean()
    rs = pd.to_numeric(df.get("relative_strength_numeric", 0), errors="coerce").fillna(0).clip(-10, 10).mean()
    week = pd.to_numeric(df.get("change_5p_pct", 0), errors="coerce").fillna(0).clip(-12, 12).mean()
    month = pd.to_numeric(df.get("change_20p_pct", 0), errors="coerce").fillna(0).clip(-20, 20).mean()
    flows = df.get("money_flow", pd.Series("", index=df.index)).astype(str)
    flow_bonus = ((flows == "Zufluss").sum() - (flows == "Abfluss").sum()) * 3 / max(1, len(df))
    return float(score + rs * 1.5 + week + month * 0.5 + flow_bonus)


def sector_group_comparison_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group in SECTOR_ROTATION_COMPARISON_GROUPS:
        tickers = {str(ticker).upper() for ticker in group["tickers"]}
        group_df = df[df["ticker_lookup"].isin(tickers)].copy()
        if group_df.empty:
            continue
        sorted_group = group_df.sort_values(
            ["relative_strength_numeric", "score_numeric", "change_5p_pct"],
            ascending=False,
        )
        leader = sorted_group.iloc[0]
        strength = rotation_strength_score(group_df)
        inflows = int((group_df["money_flow"] == "Zufluss").sum())
        outflows = int((group_df["money_flow"] == "Abfluss").sum())
        if inflows > outflows and strength >= 60:
            flow_state = "Zufluss"
        elif outflows > inflows or strength < 45:
            flow_state = "Abfluss"
        elif str(group.get("risk_profile")) == "risk_off" and strength >= 55:
            flow_state = "Defensiv Watch"
        else:
            flow_state = "Neutral"
        rows.append(
            {
                "group": group["name"],
                "risk_profile": group["risk_profile"],
                "flow_state": flow_state,
                "score": round(float(group_df["score_numeric"].mean()), 1),
                "relative_strength": round(float(group_df["relative_strength_numeric"].mean()), 2),
                "change_1p_pct": round(float(group_df["change_1p_pct"].mean()), 2),
                "change_5p_pct": round(float(group_df["change_5p_pct"].mean()), 2),
                "change_20p_pct": round(float(group_df["change_20p_pct"].mean()), 2),
                "rotation_strength": round(strength, 1),
                "leader": str(leader.get("label", leader.get("ticker", ""))),
                "tickers": ", ".join(sorted(group_df["ticker"].astype(str).unique())),
            }
        )
    return pd.DataFrame(rows).sort_values("rotation_strength", ascending=False) if rows else pd.DataFrame()


def render_sector_group_comparison(df: pd.DataFrame, key_prefix: str) -> None:
    comparison = sector_group_comparison_frame(df)
    if comparison.empty:
        render_empty_state("Vergleichsgruppen fehlen", "Fuer die festen Gruppen liegen noch keine Daten vor.")
        return

    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        display = comparison[
            [
                "group",
                "flow_state",
                "score",
                "relative_strength",
                "change_1p_pct",
                "change_5p_pct",
                "change_20p_pct",
                "leader",
                "tickers",
            ]
        ].copy()
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "dataframe"),
            column_config={
                "group": "Gruppe",
                "flow_state": "Geldfluss",
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
                "relative_strength": st.column_config.NumberColumn("RS vs SPY", format="%.2f"),
                "change_1p_pct": st.column_config.NumberColumn("Gestern %", format="%.2f"),
                "change_5p_pct": st.column_config.NumberColumn("Woche %", format="%.2f"),
                "change_20p_pct": st.column_config.NumberColumn("Monat %", format="%.2f"),
                "leader": "Leader",
                "tickers": "Ticker",
            },
        )
    with col2:
        change_frame = comparison.melt(
            id_vars=["group"],
            value_vars=["change_1p_pct", "change_5p_pct", "change_20p_pct"],
            var_name="period",
            value_name="change_pct",
        )
        change_frame["period"] = change_frame["period"].map(
            {
                "change_1p_pct": "Gestern",
                "change_5p_pct": "Woche",
                "change_20p_pct": "Monat",
            }
        )
        fig = px.bar(
            change_frame,
            x="group",
            y="change_pct",
            color="period",
            barmode="group",
            title="Veraenderung: gestern / woechentlich / monatlich",
        )
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.35)")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=45, b=10))
        style_plotly_figure(fig)
        render_plotly_chart(fig, key=make_key(key_prefix, "change_plotly"))


def render_sector_rotation_table(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        render_empty_state("Keine Sektoren", "Fuer diese Kategorie liegen keine Daten vor.")
        return
    display = df[
        [
            "category",
            "label",
            "ticker",
            "money_flow",
            "trend",
            "score",
            "relative_strength",
            "change_1p_pct",
            "change_5p_pct",
            "change_20p_pct",
            "return_5",
            "return_20",
            "close",
        ]
    ].copy()
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe"),
        column_config={
            "category": "Kategorie",
            "label": "Markt",
            "ticker": "Ticker",
            "money_flow": "Geldfluss",
            "trend": "Trend",
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "relative_strength": st.column_config.NumberColumn("RS vs SPY", format="%.2f"),
            "change_1p_pct": st.column_config.NumberColumn("Gestern %", format="%.2f"),
            "change_5p_pct": st.column_config.NumberColumn("Woche %", format="%.2f"),
            "change_20p_pct": st.column_config.NumberColumn("Monat %", format="%.2f"),
            "return_5": st.column_config.NumberColumn("5 Perioden %", format="%.2f"),
            "return_20": st.column_config.NumberColumn("20 Perioden %", format="%.2f"),
            "close": st.column_config.NumberColumn("Close", format="%.2f"),
        },
    )


def render_macro_rotation_cards(df: pd.DataFrame) -> None:
    macro_categories = ["Waehrung", "Treasuries", "Treasury Yields"]
    macro = df[df["category"].isin(macro_categories)].copy()
    if macro.empty:
        render_empty_state("Makro-Proxies fehlen", "Dollar und Treasury-Proxies werden nach der Analyse angezeigt.")
        return
    for _, row in macro.sort_values("category").iterrows():
        render_score_card(row.to_dict(), title=str(row.get("label", row.get("ticker", ""))))


def render_sector_rotation_heatmap(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        return
    heatmap = df.copy()
    heatmap["heat_size"] = heatmap["score_numeric"].clip(lower=5)
    heatmap["score_label"] = heatmap["score_numeric"].round(0).astype(int).astype(str) + "/100"
    fig = px.treemap(
        heatmap,
        path=["category", "label"],
        values="heat_size",
        color="score_numeric",
        color_continuous_scale=[
            (0.00, "#475569"),
            (0.69, "#64748b"),
            (0.70, "#facc15"),
            (0.79, "#facc15"),
            (0.80, "#38bdf8"),
            (0.89, "#38bdf8"),
            (0.90, "#22c55e"),
            (1.00, "#22c55e"),
        ],
        range_color=(0, 100),
        hover_data={
            "ticker": True,
            "score_numeric": ":.0f",
            "relative_strength_numeric": ":.2f",
            "change_1p_pct": ":.2f",
            "change_5p_pct": ":.2f",
            "change_20p_pct": ":.2f",
            "heat_size": False,
        },
        title="Score-Heatmap nach Marktgruppe",
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{color:.0f}/100",
        marker=dict(line=dict(width=1, color="rgba(15,23,42,0.9)")),
    )
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "treemap"))


def render_sector_rotation_flow_map(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        return
    fig = px.scatter(
        df,
        x="relative_strength_numeric",
        y="score_numeric",
        color="money_flow",
        size=df["change_20p_pct"].abs().clip(lower=1),
        hover_name="label",
        hover_data=["ticker", "category", "trend", "change_1p_pct", "change_5p_pct", "change_20p_pct"],
        title="Kapitalfluss: Relative Staerke vs Score",
    )
    fig.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.35)")
    fig.add_hline(y=70, line_dash="dot", line_color="rgba(255,255,255,0.22)")
    fig.update_layout(height=460, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "plotly"))


def render_sector_rotation_settings(config: dict, key_prefix: str) -> None:
    with st.expander(f"Sektor-Watchlist bearbeiten ({key_prefix})", expanded=False):
        entries = config.get("sector_rotation_symbols", DEFAULT_SECTOR_ROTATION_SYMBOLS)
        categories = sector_rotation_categories(config)
        st.caption("Nur Analyse-Symbole. Keine Orders, keine Broker-Aktion.")
        with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
            label = st.text_input(
                "Name",
                placeholder="z.B. Biotech",
                key=make_key(key_prefix, "label"),
            )
            ticker = st.text_input(
                "Ticker",
                placeholder="z.B. XBI",
                key=make_key(key_prefix, "ticker"),
            )
            category = st.selectbox(
                "Kategorie",
                categories + ["Eigene Sektoren"],
                key=make_key(key_prefix, "category"),
            )
            submitted = st.form_submit_button(
                "Sektor speichern",
                key=make_key(key_prefix, "submit"),
                width="stretch",
            )
            if submitted:
                cleaned_ticker = ticker.strip().upper()
                if not cleaned_ticker:
                    st.error("Bitte Ticker eintragen.")
                else:
                    new_entry = {
                        "label": label.strip() or cleaned_ticker,
                        "ticker": cleaned_ticker,
                        "category": category,
                    }
                    config["sector_rotation_symbols"] = merge_sector_entries(
                        entries,
                        [new_entry],
                    )
                    if category not in config.get("sector_rotation_categories", []):
                        config.setdefault("sector_rotation_categories", []).append(category)
                    save_config(config, CONFIG_PATH)
                    st.success("Sektor gespeichert. Danach Sektorrotation analysieren.")
                    st.rerun()

        st.dataframe(
            pd.DataFrame(entries),
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "current_symbols"),
        )


def sector_rotation_categories(config: dict) -> list[str]:
    categories = config.get("sector_rotation_categories") or DEFAULT_SECTOR_ROTATION_CATEGORIES
    cleaned = []
    for category in categories:
        text = str(category).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned or DEFAULT_SECTOR_ROTATION_CATEGORIES


def render_market_regime(config: dict, key_prefix: str) -> None:
    result = st.session_state.get("analysis_result", {})
    render_section_title(
        "Market Regime",
        "Regime-Erkennung ueber Monthly, Weekly und Daily. Nur Marktanalyse, keine Signale.",
    )
    st.info(
        "Dies ist keine Handelsentscheidung, kein Kaufsignal und kein Verkaufssignal. "
        "Die Engine analysiert nur das aktuelle Marktumfeld und ordnet passende Strategie-Typen zu."
    )
    if MARKET_REGIME_IMPORT_ERROR is not None:
        st.error(
            "Market-Regime-Modul wurde nicht geladen. "
            "Bitte pruefen, ob `modules/market_regime.py` im GitHub-Repo vorhanden ist."
        )
        st.caption(f"Import-Hinweis: {MARKET_REGIME_IMPORT_ERROR}")

    col_action, col_report = st.columns(2)
    with col_action:
        if st.button(
            "Regime neu berechnen",
            key=make_key(key_prefix, "refresh"),
            type="primary",
            width="stretch",
        ):
            _run_update(config, generate_reports=True, include_sector_rotation=True)
            result = st.session_state.get("analysis_result", {})
    with col_report:
        if st.button(
            "Regime-Reports speichern",
            key=make_key(key_prefix, "save_reports"),
            width="stretch",
        ):
            evaluation = evaluate_market_regime(config, result)
            paths = write_market_regime_reports(evaluation, Path(config.get("reports_dir", "reports")))
            st.success("Regime-Reports gespeichert: " + ", ".join(path.name for path in paths))

    evaluation = evaluate_market_regime(config, result)
    for issue in evaluation.get("issues", []):
        st.warning(issue)

    contexts = evaluation.get("contexts", {})
    if any(not context.get("sectors") for context in contexts.values()):
        st.warning(
            "Sektor-Daten sind noch nicht voll geladen. Klicke Regime neu berechnen, "
            "damit Sektor-Rotation und Risk-On/Risk-Off voll bewertet werden."
        )

    summary = evaluation.get("summary", pd.DataFrame())
    if summary.empty:
        render_empty_state(
            "Keine Regime-Auswertung verfuegbar",
            "Starte Regime neu berechnen. Wenn Kernmarktdaten fehlen, zeigt die App hier eine saubere Meldung.",
        )
        return

    timeframes = summary["Timeframe"].tolist()
    selected_timeframe = st.selectbox(
        "Zeitebene",
        timeframes,
        key=make_key(key_prefix, "timeframe"),
    )
    selected_row = summary[summary["Timeframe"] == selected_timeframe].iloc[0].to_dict()
    ranking = evaluation.get("rankings", {}).get(selected_timeframe, pd.DataFrame())

    active_regime = str(selected_row.get("Active Regime", "n/a"))
    confidence = safe_float(selected_row.get("Confidence Score"), 0)
    volatility = str(selected_row.get("Volatility Status", "Normal"))
    strongest_sector = str(selected_row.get("Strongest Sector", "nicht verfuegbar"))
    strategy = str(selected_row.get("Recommended Strategy", "Analyse beobachten"))
    explanation = str(selected_row.get("Explanation", "Keine Erklaerung verfuegbar."))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Aktives Regime", active_regime)
    col2.metric("Vertrauen", f"{confidence:.0f}%")
    col3.metric("Volatilitaet", volatility)
    col4.metric("Staerkster Sektor", strongest_sector)

    st.markdown(
        f"""
        <div class="sensei-callout sensei-alert-callout">
            <strong>Analyse:</strong> {escape(explanation)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_section_title("Status", "SPY, QQQ, GLD und Strategie-Zuordnung.")
    status_cols = st.columns(4)
    status_items = [
        ("SPY", selected_row.get("SPY Status", "Daten fehlen"), "blue"),
        ("QQQ", selected_row.get("QQQ Status", "Daten fehlen"), "blue"),
        ("GLD", selected_row.get("GLD Status", "Daten fehlen"), "yellow"),
        ("Strategie-Typ", strategy, "pink"),
    ]
    for column, (title, value, color) in zip(status_cols, status_items):
        with column:
            st.markdown(
                f"""
                <div class="sensei-mini-card">
                    <div class="sensei-card-label">{escape(title)}</div>
                    <div class="sensei-card-value">{status_badge_html(value, color)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if not ranking.empty:
        render_section_title("Regime Ranking", "Alle Regime werden bewertet und nach Score sortiert.")
        fig = px.bar(
            ranking,
            x="Score",
            y="Regime",
            orientation="h",
            color="Score",
            color_continuous_scale=["#5f6673", "#f5c542", "#4aa3ff", "#22c55e"],
            range_x=[0, 100],
            title=f"Regime Scores - {selected_timeframe}",
        )
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=45, b=10), yaxis={"categoryorder": "total ascending"})
        style_plotly_figure(fig)
        render_plotly_chart(fig, key=make_key(key_prefix, "ranking_plotly", selected_timeframe))
        st.dataframe(
            ranking,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "ranking_dataframe", selected_timeframe),
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "Strategy Type": "Strategie-Typ",
                "Description": "Beschreibung",
            },
        )

    with st.expander(f"Strategie-Zuordnung anzeigen ({key_prefix})", expanded=False):
        st.dataframe(
            evaluation.get("strategy_map", pd.DataFrame()),
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "strategy_map"),
        )


def render_backtesting(config: dict, key_prefix: str) -> None:
    result = st.session_state.analysis_result
    histories = result.get("histories", {})
    timeframes = config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"])

    render_section_title(
        "Backtesting",
        "Einfache Setup-Regeln, historischer Score und Signal-Auswertung. Keine Orders.",
    )
    st.info(
        "Backtesting ist reine Auswertung. Die App simuliert nur historische Signale aus geladenen Daten "
        "und fuehrt nichts aus."
    )
    render_system_alert_panel(
        "Pink Alert: Backtest-Signale",
        "Pink markiert erkannte historische Setup-Signale und Score-Filter. Keine echte Ausfuehrung.",
    )

    timeframe = st.selectbox(
        "Timeframe",
        timeframes,
        key=make_key(key_prefix, "timeframe"),
    )
    available_symbols = backtest_available_symbols(config, histories, timeframe)
    if not available_symbols:
        render_empty_state(
            "Keine Backtest-Daten geladen",
            "Starte zuerst eine Analyse fuer Dashboard oder Watchlist. Danach nutzt Backtesting die vorhandenen Historiendaten.",
        )
        return

    result_key = make_key(key_prefix, "result")
    with st.form(make_key(key_prefix, "form")):
        default_symbols = [symbol for symbol in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA"] if symbol in available_symbols]
        selected_symbols = st.multiselect(
            "Symbole",
            available_symbols,
            default=default_symbols[:6] or available_symbols[:4],
            key=make_key(key_prefix, "symbols"),
        )
        selected_setups = st.multiselect(
            "Setup-Kategorien testen",
            BACKTEST_SETUPS,
            default=BACKTEST_SETUPS,
            key=make_key(key_prefix, "setups"),
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            benchmark_options = [symbol for symbol in ["QQQ", "SPY"] if f"{symbol}|{timeframe}" in histories]
            benchmark = st.selectbox(
                "Benchmark fuer Relative Staerke",
                benchmark_options or ["QQQ"],
                key=make_key(key_prefix, "benchmark"),
            )
            min_score = st.slider(
                "Mindestscore",
                min_value=0,
                max_value=100,
                value=60,
                step=5,
                key=make_key(key_prefix, "min_score"),
            )
        with col2:
            hold_period = st.number_input(
                "Max. Haltedauer in Kerzen",
                min_value=1,
                max_value=260,
                value=20,
                step=1,
                key=make_key(key_prefix, "hold_period"),
            )
            max_signals = st.number_input(
                "Max. Signale je Symbol/Setup",
                min_value=10,
                max_value=1000,
                value=200,
                step=10,
                key=make_key(key_prefix, "max_signals"),
            )
        with col3:
            stop_loss_pct = st.number_input(
                "Stop-Simulation %",
                min_value=0.0,
                max_value=80.0,
                value=5.0,
                step=0.5,
                key=make_key(key_prefix, "stop_loss_pct"),
            )
            target_pct = st.number_input(
                "Ziel-Simulation %",
                min_value=0.0,
                max_value=200.0,
                value=10.0,
                step=0.5,
                key=make_key(key_prefix, "target_pct"),
            )
        submitted = st.form_submit_button(
            "Backtest starten",
            key=make_key(key_prefix, "submit"),
            width="stretch",
        )

    if submitted:
        settings = BacktestSettings(
            timeframe=timeframe,
            benchmark=benchmark,
            min_score=int(min_score),
            hold_period=int(hold_period),
            stop_loss_pct=float(stop_loss_pct),
            target_pct=float(target_pct),
            max_signals_per_symbol_setup=int(max_signals),
        )
        backtester = Backtester(histories)
        with st.spinner("Backtest laeuft..."):
            st.session_state[result_key] = backtester.run(selected_symbols, selected_setups, settings)
        st.success("Backtest berechnet.")

    backtest_result = st.session_state.get(result_key)
    if not backtest_result:
        render_empty_state(
            "Noch kein Backtest gestartet",
            "Waehle Symbole, Setups und Score-Filter. Danach zeigt die App, welche Signale historisch funktioniert haetten.",
        )
        return
    render_backtest_results(backtest_result, key_prefix=make_key(key_prefix, "results"))


def backtest_available_symbols(config: dict, histories: dict, timeframe: str) -> list[str]:
    candidates = tracking_symbols(config)
    candidates.extend(key.split("|", 1)[0] for key in histories if key.endswith(f"|{timeframe}"))
    cleaned = []
    for symbol in candidates:
        text = str(symbol).strip().upper()
        if text and f"{text}|{timeframe}" in histories and text not in cleaned:
            cleaned.append(text)
    return cleaned


def render_backtest_results(result: dict, key_prefix: str) -> None:
    trades = result.get("trades", pd.DataFrame())
    if result.get("message"):
        st.warning(result["message"])
    if trades.empty:
        render_empty_state(
            "Keine historischen Signale",
            "Lockere den Mindestscore, waehle mehr Symbole oder einen anderen Timeframe.",
        )
        skipped = result.get("skipped", pd.DataFrame())
        if skipped is not None and not skipped.empty:
            st.dataframe(
                skipped,
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "skipped"),
            )
        return

    render_backtest_summary(result.get("summary", {}))
    render_backtest_equity_curve(
        result.get("equity_curve", pd.DataFrame()),
        key_prefix=make_key(key_prefix, "equity"),
    )

    col1, col2 = st.columns(2)
    with col1:
        render_backtest_setup_summary(
            result.get("setup_summary", pd.DataFrame()),
            key_prefix=make_key(key_prefix, "setup_summary"),
        )
    with col2:
        render_backtest_score_summary(
            result.get("score_summary", pd.DataFrame()),
            key_prefix=make_key(key_prefix, "score_summary"),
        )

    render_section_title("Welche Signale funktioniert haetten", "Gewinner, Verlierer und alle historischen Signale.")
    render_backtest_signal_tables(trades, key_prefix=make_key(key_prefix, "signals"))


def render_backtest_summary(summary: dict) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Signale", int(summary.get("signals", 0)))
    col2.metric("Trefferquote", f"{safe_float(summary.get('win_rate')):.1f}%")
    col3.metric("Ø Return", f"{safe_float(summary.get('average_return')):.2f}%")
    col4.metric("Max Drawdown", f"{safe_float(summary.get('max_drawdown')):.2f}%")
    col5.metric("Ø Score", f"{safe_float(summary.get('average_score')):.0f}/100")
    col6, col7, col8, col9 = st.columns(4)
    col6.metric("Ø Gewinn", f"{safe_float(summary.get('average_win')):.2f}%")
    col7.metric("Ø Verlust", f"{safe_float(summary.get('average_loss')):.2f}%")
    col8.metric("Bestes Signal", f"{safe_float(summary.get('best_return')):.2f}%")
    col9.metric("Profit Factor", f"{safe_float(summary.get('profit_factor')):.2f}")


def render_backtest_equity_curve(curve: pd.DataFrame, key_prefix: str) -> None:
    if curve.empty:
        return
    fig = px.line(
        curve,
        x="exit_date",
        y="equity_pct",
        markers=True,
        title="Backtest Equity Curve",
        hover_data=["ticker", "setup_category", "return_pct", "drawdown_pct"],
    )
    fig.add_bar(
        x=curve["exit_date"],
        y=curve["drawdown_pct"],
        name="Drawdown %",
        marker_color="#b42318",
        opacity=0.35,
    )
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=45, b=10), hovermode="x unified")
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "plotly"))


def render_backtest_setup_summary(summary: pd.DataFrame, key_prefix: str) -> None:
    st.markdown("#### Ergebnis pro Setup")
    if summary.empty:
        render_empty_state("Keine Setup-Ergebnisse", "Fuer die gewaehlten Regeln gab es keine Signale.")
        return
    st.dataframe(
        summary,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe"),
        column_config={
            "setup_category": "Setup",
            "signals": "Signale",
            "win_rate": st.column_config.NumberColumn("Trefferquote %", format="%.1f"),
            "average_return": st.column_config.NumberColumn("Ø Return %", format="%.2f"),
            "best_return": st.column_config.NumberColumn("Best %", format="%.2f"),
            "worst_return": st.column_config.NumberColumn("Worst %", format="%.2f"),
            "average_score": st.column_config.NumberColumn("Ø Score", format="%.0f"),
        },
    )


def render_backtest_score_summary(summary: pd.DataFrame, key_prefix: str) -> None:
    st.markdown("#### Score-System rueckwirkend")
    if summary.empty:
        render_empty_state("Keine Score-Auswertung", "Fuer die gewaehlten Regeln gab es keine Score-Buckets.")
        return
    st.dataframe(
        summary,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe"),
        column_config={
            "score_bucket": "Score",
            "signals": "Signale",
            "win_rate": st.column_config.NumberColumn("Trefferquote %", format="%.1f"),
            "average_return": st.column_config.NumberColumn("Ø Return %", format="%.2f"),
            "best_return": st.column_config.NumberColumn("Best %", format="%.2f"),
            "worst_return": st.column_config.NumberColumn("Worst %", format="%.2f"),
        },
    )
    fig = px.bar(
        summary,
        x="score_bucket",
        y="average_return",
        color="win_rate",
        title="Historischer Score vs. Ergebnis",
        hover_data=["signals", "best_return", "worst_return"],
    )
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "plotly"))


def render_backtest_signal_tables(trades: pd.DataFrame, key_prefix: str) -> None:
    winners = trades[trades["worked"]].sort_values("return_pct", ascending=False).head(20)
    losers = trades[~trades["worked"]].sort_values("return_pct", ascending=True).head(20)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Funktioniert")
        render_backtest_trade_table(winners, key_prefix=make_key(key_prefix, "winners"))
    with col2:
        st.markdown("#### Nicht funktioniert")
        render_backtest_trade_table(losers, key_prefix=make_key(key_prefix, "losers"))

    with st.expander("Alle Backtest-Signale", expanded=False):
        render_backtest_trade_table(
            trades.sort_values(["entry_date", "ticker", "setup_category"], ascending=[False, True, True]),
            key_prefix=make_key(key_prefix, "all"),
        )
        csv_data = trades.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Backtest CSV herunterladen",
            data=csv_data,
            file_name="backtest_signals.csv",
            mime="text/csv",
            key=make_key(key_prefix, "download"),
            width="stretch",
        )


def render_backtest_trade_table(trades: pd.DataFrame, key_prefix: str) -> None:
    if trades.empty:
        render_empty_state("Keine Signale", "In dieser Ansicht gibt es keine Treffer.")
        return
    display = trades[
        [
            "ticker",
            "setup_category",
            "timeframe",
            "signal_date",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "return_pct",
            "exit_reason",
            "signal_score",
            "score_bucket",
            "relative_strength",
        ]
    ].copy()
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe"),
        column_config={
            "ticker": "Symbol",
            "setup_category": "Setup",
            "timeframe": "TF",
            "signal_date": "Signal",
            "entry_date": "Entry",
            "exit_date": "Exit",
            "entry_price": st.column_config.NumberColumn("Entry", format="%.2f"),
            "exit_price": st.column_config.NumberColumn("Exit", format="%.2f"),
            "return_pct": st.column_config.NumberColumn("Return %", format="%.2f"),
            "exit_reason": "Exit-Grund",
            "signal_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "score_bucket": "Score-Bucket",
            "relative_strength": st.column_config.NumberColumn("RS", format="%.2f"),
        },
    )


def render_mobile_analysis_cards(
    df: pd.DataFrame,
    key_prefix: str,
    limit: int = 12,
    selected_ticker: str = "",
) -> None:
    if df.empty:
        return
    rows = df.head(limit).to_dict("records")
    cards = ["<div class='sensei-mobile-card-grid'>"]
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        label = str(row.get("label") or ticker)
        score = int(safe_float(row.get("score"), 0))
        trend = str(row.get("trend", "neutral"))
        risk = str(row.get("risk_state", "offen"))
        rs = safe_float(row.get("relative_strength"), 0)
        close = safe_float(row.get("close"), 0)
        active_class = " sensei-mobile-card-active" if ticker and ticker == selected_ticker else ""
        cards.append(
            f"""
            <div class="sensei-mobile-card{active_class}">
                <div class="sensei-mobile-card-top">
                    <div>
                        <div class="sensei-mobile-card-symbol">{escape(ticker)}</div>
                        <div class="sensei-mobile-card-meta">{escape(label)}</div>
                    </div>
                    <div>{status_badge_html(f"{score}/100", score_tier(score)[2])}</div>
                </div>
                <div class="sensei-mobile-kpi-row" style="margin-top:.65rem;">
                    <div class="sensei-mobile-kpi">
                        <div class="sensei-mobile-kpi-label">Trend</div>
                        <div class="sensei-mobile-kpi-value">{status_badge_html(trend, status_color(trend))}</div>
                    </div>
                    <div class="sensei-mobile-kpi">
                        <div class="sensei-mobile-kpi-label">Risk</div>
                        <div class="sensei-mobile-kpi-value">{status_badge_html(risk, status_color(risk))}</div>
                    </div>
                    <div class="sensei-mobile-kpi">
                        <div class="sensei-mobile-kpi-label">RS</div>
                        <div class="sensei-mobile-kpi-value">{rs:.2f}</div>
                    </div>
                    <div class="sensei-mobile-kpi">
                        <div class="sensei-mobile-kpi-label">Close</div>
                        <div class="sensei-mobile-kpi-value">{close:.2f}</div>
                    </div>
                </div>
            </div>
            """
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)


def render_mobile_record_cards(
    records: list[dict],
    title_key: str,
    fields: list[tuple[str, str]],
    limit: int = 12,
) -> None:
    if not records:
        return
    cards = ["<div class='sensei-mobile-card-grid'>"]
    for row in records[:limit]:
        title = str(row.get(title_key, "-"))
        kpis = []
        for label, field in fields:
            value = row.get(field, "-")
            if isinstance(value, float):
                value = f"{value:.2f}"
            kpis.append(
                f"""
                <div class="sensei-mobile-kpi">
                    <div class="sensei-mobile-kpi-label">{escape(label)}</div>
                    <div class="sensei-mobile-kpi-value">{escape(str(value))}</div>
                </div>
                """
            )
        cards.append(
            f"""
            <div class="sensei-mobile-card">
                <div class="sensei-mobile-card-top">
                    <div class="sensei-mobile-card-symbol">{escape(title)}</div>
                    {status_badge_html('Details', 'pink')}
                </div>
                <div class="sensei-mobile-kpi-row" style="margin-top:.65rem;">{''.join(kpis)}</div>
            </div>
            """
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)


def render_watchlist_badge_table(df: pd.DataFrame, key_prefix: str, compact: bool = False) -> None:
    if df.empty:
        render_empty_state("Keine Tabellenwerte", "Noch keine Watchlist-Daten fuer diesen Timeframe.")
        return
    rows = df.head(5 if compact else 25).to_dict("records")
    render_mobile_analysis_cards(
        df.head(5 if compact else 12),
        key_prefix=make_key(key_prefix, "mobile_cards"),
        limit=5 if compact else 12,
    )
    header = (
        "<tr><th>Symbol</th><th>Score</th><th>Trend</th><th>Risk</th>"
        "<th>RS gegen QQQ</th><th>Close</th></tr>"
    )
    body = []
    for row in rows:
        score = int(safe_float(row.get("score"), 0))
        tier_label, _, tier_color = score_tier(score)
        trend = str(row.get("trend", "neutral"))
        risk = str(row.get("risk_state", "offen"))
        rs = safe_float(row.get("relative_strength"), 0)
        rs_kind = "green" if rs > 0 else "red" if rs < 0 else "gray"
        body.append(
            "<tr>"
            f"<td><strong>{escape(str(row.get('ticker', '')))}</strong><br>"
            f"<span class='sensei-muted'>{escape(str(row.get('label', '')))}</span></td>"
            f"<td>{status_badge_html(f'{score}/100 {tier_label}', tier_color)}</td>"
            f"<td>{status_badge_html(trend, status_color(trend))}</td>"
            f"<td>{status_badge_html(risk, status_color(risk))}</td>"
            f"<td>{status_badge_html(f'{rs:.2f}', rs_kind)}</td>"
            f"<td>{safe_float(row.get('close'), 0):.2f}</td>"
            "</tr>"
        )
    st.markdown(
        f"""
        <div class="sensei-table-card sensei-desktop-table">
            <table class="sensei-table">
                <thead>{header}</thead>
                <tbody>{''.join(body)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_papertrading(config: dict, key_prefix: str) -> None:
    render_tracking_area(
        config=config,
        account_type="papertrading",
        title="Papertrading",
        description=(
            "Simuliertes Analyse-Journal. Paper laeuft parallel mit und speichert "
            "bei jeder Analyse Snapshots deiner offenen Eintraege."
        ),
        key_prefix=key_prefix,
    )


def render_real_money(config: dict, key_prefix: str) -> None:
    render_tracking_area(
        config=config,
        account_type="real_money",
        title="Real Money",
        description=(
            "Manuelles Spiegel-Depot fuer echte Positionen. Keine Orders, keine "
            "Broker-Anbindung, keine automatische Ausfuehrung."
        ),
        key_prefix=key_prefix,
    )


def render_tracking_area(
    config: dict,
    account_type: str,
    title: str,
    description: str,
    key_prefix: str,
) -> None:
    tracker = _tracker(config)

    st.subheader(title)
    st.caption(description)
    st.info("Analyse-only: Eintraege werden nur lokal gespeichert und niemals ausgefuehrt.")
    if account_type == "real_money":
        render_trading_safety_banner(config, key_prefix=make_key(key_prefix, "trading_safety"))

    notice = st.session_state.pop(f"{account_type}_notice", None)
    if notice:
        st.success(notice)

    render_tracking_metrics(tracker, account_type)
    render_tracking_learning_panel(tracker, account_type)
    render_tracking_performance(
        tracker,
        account_type,
        expanded=False,
        key_prefix=make_key(key_prefix, "performance"),
    )
    with st.expander(f"Eintrag erfassen ({key_prefix})", expanded=False):
        render_tracking_entry_form(config, tracker, account_type, key_prefix=make_key(key_prefix, "entry"))
    with st.expander(f"Eintrag schliessen ({key_prefix})", expanded=False):
        render_tracking_close_form(config, tracker, account_type, key_prefix=make_key(key_prefix, "close"))
    with st.expander(f"Journal anzeigen ({key_prefix})", expanded=False):
        render_tracking_history(tracker, account_type, key_prefix=make_key(key_prefix, "history"))
    render_paper_real_comparison(tracker, key_prefix=make_key(key_prefix, "comparison"))


def render_tracking_metrics(tracker: PortfolioTracker, account_type: str) -> None:
    summary = tracker.summary(account_type)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Offen", summary["open_count"])
    col2.metric("Geschlossen", summary["closed_count"])
    col3.metric("Marktwert", format_money(summary["market_value"]))
    col4.metric("Offener P/L", format_money(summary["unrealized_pnl"]))
    col5.metric("Realisiert", format_money(summary["realized_pnl"]))
    col6, col7, col8, col9, col10 = st.columns(5)
    col6.metric("Trefferquote", f"{summary['win_rate']:.1f}%")
    col7.metric("Ø Gewinn", format_money(summary["average_win"]))
    col8.metric("Ø Verlust", format_money(summary["average_loss"]))
    col9.metric("Max Drawdown", format_money(summary["max_drawdown"]))
    col10.metric("Regelbrueche", summary["rule_violation_count"])


def render_trading_safety_banner(config: dict, key_prefix: str) -> None:
    safety = trading_safety_config(config)
    decision = evaluate_trading_request(config)
    st.markdown(
        f"""
        <div class="sensei-alert-panel">
            <strong>Trading Safety Gate</strong><br>
            {status_badge_html('Live aus', 'green')}
            {status_badge_html('Kill-Switch aktiv' if safety.get('kill_switch_active') else 'Kill-Switch pruefen', 'pink')}
            {status_badge_html('Sandbox zuerst', 'blue')}
            {status_badge_html('Auto-Orders gesperrt', 'green')}
            <div class="sensei-guidance-detail">
                Status: {escape(decision.status)}. Spaetere Broker-Anbindung muss erst Sandbox/Paper-API,
                Order-Vorschau, 2-Klick-Bestaetigung, Tagesverlustlimit und Audit-Log bestehen.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        "Trading-Safety-Audit markieren",
        key=make_key(key_prefix, "audit_marker"),
        width="stretch",
    ):
        path = write_audit_event(
            BASE_DIR,
            config,
            "real_money_safety_viewed",
            payload={"status": decision.status, "reasons": decision.reasons},
            actor=st.session_state.get("authenticated_email", "local"),
        )
        st.success(f"Audit-Eintrag geschrieben: {path.relative_to(BASE_DIR)}")


def render_tracking_learning_panel(tracker: PortfolioTracker, account_type: str) -> None:
    summary = tracker.summary(account_type)
    violations = tracker.rule_violation_breakdown(account_type)
    setups = tracker.setup_breakdown(account_type)
    worst_rule = "-"
    if not violations.empty:
        worst_rule = str(violations.iloc[0].get("rule_violation", "-"))
    best_setup = "-"
    if not setups.empty and "realized_pnl" in setups:
        best_setup = str(setups.sort_values("realized_pnl", ascending=False).iloc[0].get("setup_category", "-"))

    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html('Lernsystem', 'pink')}
            {status_badge_html(f"Trefferquote {summary['win_rate']:.1f}%", 'blue')}
            {status_badge_html(f"Max DD {format_money(summary['max_drawdown'])}", 'gray')}
            <div class="sensei-score-label" style="margin-top:.55rem;">
                Gespeichert werden Entry, Stop, Ziel, Setup, These, Analyse-Snapshot und automatische Regelverletzungen.
                Bester Setup-Stand: {escape(best_setup)}. Hauefigste Regel: {escape(worst_rule)}.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_tracking_performance(
    tracker: PortfolioTracker,
    account_type: str,
    expanded: bool = False,
    key_prefix: str = "tracking_performance",
) -> None:
    with st.expander(f"Performance auswerten ({key_prefix})", expanded=expanded):
        render_tracking_equity_curve(
            tracker,
            account_type,
            key_prefix=make_key(key_prefix, "equity_curve"),
        )
        col1, col2 = st.columns(2)
        with col1:
            render_tracking_setup_breakdown(
                tracker,
                account_type,
                key_prefix=make_key(key_prefix, "setup_breakdown"),
            )
        with col2:
            render_tracking_rule_violations(
                tracker,
                account_type,
                key_prefix=make_key(key_prefix, "rule_violations"),
            )


def render_tracking_equity_curve(
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    curve = tracker.equity_curve(account_type)
    if curve.empty:
        render_empty_state(
            "Noch keine Equity Curve",
            "Schliesse Paper- oder Real-Eintraege oder starte Analysen mit offenen Eintraegen. Danach entsteht hier der Verlauf.",
        )
        return

    fig = px.line(
        curve,
        x="date",
        y="equity",
        markers=True,
        title="Equity Curve",
        hover_data=["ticker", "realized_pnl", "source"],
    )
    fig.add_bar(
        x=curve["date"],
        y=curve["drawdown"],
        name="Drawdown",
        marker_color="#b42318",
        opacity=0.35,
    )
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=45, b=10), hovermode="x unified")
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "plotly", account_type))


def render_tracking_setup_breakdown(
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    st.markdown("#### Setup-Kategorien")
    breakdown = tracker.setup_breakdown(account_type)
    if breakdown.empty:
        render_empty_state(
            "Noch keine Setups",
            "Waehle beim Erfassen eines Eintrags eine Setup-Kategorie. Danach siehst du, welche Setups funktionieren.",
        )
        return
    render_mobile_record_cards(
        breakdown.to_dict("records"),
        title_key="setup_category",
        fields=[
            ("Einträge", "entries"),
            ("Treffer", "win_rate"),
            ("Realisiert", "realized_pnl"),
            ("Ø P/L", "average_pnl"),
        ],
    )
    with st.expander(f"Setup-Tabelle anzeigen ({key_prefix})", expanded=False):
        st.dataframe(
            breakdown,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "dataframe", account_type),
            column_config={
                "setup_category": "Setup",
                "entries": "Eintraege",
                "closed": "Geschlossen",
                "win_rate": st.column_config.NumberColumn("Trefferquote %", format="%.1f"),
                "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
                "average_pnl": st.column_config.NumberColumn("Ø P/L", format="%.2f"),
            },
        )


def render_tracking_rule_violations(
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    st.markdown("#### Regelverletzungen")
    violations = tracker.rule_violation_breakdown(account_type)
    if violations.empty:
        render_empty_state(
            "Keine Regelverletzungen erfasst",
            "Gut. Falls du bewusst gegen eine Regel testest, markiere sie beim Speichern des Eintrags.",
        )
        return
    render_mobile_record_cards(
        violations.to_dict("records"),
        title_key="rule_violation",
        fields=[
            ("Vorkommen", "entries"),
            ("Geschlossen", "closed"),
            ("Realisiert", "realized_pnl"),
        ],
    )
    with st.expander(f"Regel-Tabelle anzeigen ({key_prefix})", expanded=False):
        st.dataframe(
            violations,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "dataframe", account_type),
            column_config={
                "rule_violation": "Regelverletzung",
                "entries": "Vorkommen",
                "closed": "Geschlossen",
                "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
            },
        )


def render_tracking_entry_form(
    config: dict,
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    result = st.session_state.analysis_result
    symbols = tracking_symbols(config)
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])
    setup_categories = tracking_setup_categories(config)
    rule_options = tracking_rule_options(config)

    st.markdown("### Neuen Eintrag erfassen")
    col1, col2 = st.columns(2)
    with col1:
        ticker = st.selectbox(
            "Ticker",
            symbols,
            key=make_key(key_prefix, "ticker"),
        )
    with col2:
        timeframe = st.selectbox(
            "Analyse-Timeframe",
            timeframes,
            key=make_key(key_prefix, "timeframe"),
        )

    analysis_row = analysis_row_for_ticker(result, ticker, timeframe)
    default_price = safe_float(analysis_row.get("close"), fallback=1.0)
    render_tracking_analysis_snapshot(analysis_row)
    market_status = market_traffic_light(result, timeframe)

    with st.form(make_key(key_prefix, "form"), clear_on_submit=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            direction = st.selectbox(
                "Richtung",
                ["long", "short"],
                format_func=lambda value: value.upper(),
                key=make_key(key_prefix, "direction"),
            )
        with col_b:
            quantity = st.number_input(
                "Anzahl",
                min_value=0.0001,
                value=float(config.get("tracking", {}).get("default_quantity", 1.0)),
                step=1.0,
                key=make_key(key_prefix, "quantity"),
            )
        with col_c:
            entry_price = st.number_input(
                "Referenzpreis",
                min_value=0.01,
                value=max(default_price, 0.01),
                step=0.01,
                key=make_key(key_prefix, "entry_price", ticker, timeframe),
            )

        col_d, col_e, col_f = st.columns(3)
        with col_d:
            entry_date = st.date_input(
                "Datum",
                value=pd.Timestamp.today().date(),
                key=make_key(key_prefix, "entry_date"),
            )
        with col_e:
            stop_price = st.number_input(
                "Stop-Referenz optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=make_key(key_prefix, "stop_price"),
            )
        with col_f:
            target_price = st.number_input(
                "Ziel-Referenz optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=make_key(key_prefix, "target_price"),
            )

        setup_category = st.selectbox(
            "Setup-Kategorie",
            setup_categories,
            index=safe_index(setup_categories, "Trendfolge"),
            key=make_key(key_prefix, "setup_category"),
        )

        thesis = st.text_area(
            "Notiz / These",
            key=make_key(key_prefix, "thesis"),
            placeholder="Warum wird dieser Eintrag beobachtet?",
        )
        automatic_violations = auto_rule_violations(
            config=config,
            analysis_row=analysis_row,
            market_status=market_status,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            thesis=thesis,
        )
        render_auto_rule_violations(automatic_violations)
        rule_violations = st.multiselect(
            "Zusaetzliche Regelverletzungen",
            merge_rule_options(rule_options, automatic_violations),
            key=make_key(key_prefix, "rule_violations"),
            help="Automatische Regelverletzungen werden immer gespeichert. Hier kannst du bewusst weitere markieren.",
        )

        submitted = st.form_submit_button(
            "Eintrag speichern",
            key=make_key(key_prefix, "submit"),
            width="stretch",
        )
        if submitted:
            try:
                entry_id = tracker.add_entry(
                    account_type=account_type,
                    ticker=ticker,
                    direction=direction,
                    quantity=quantity,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    stop_price=stop_price,
                    target_price=target_price,
                    timeframe=timeframe,
                    thesis=thesis,
                    setup_category=setup_category,
                    rule_violations=merge_rule_options(automatic_violations, rule_violations),
                    analysis_row=analysis_row,
                )
                tracker.record_snapshots(account_type, result, result["updated_at"])
                st.session_state[f"{account_type}_notice"] = (
                    f"Eintrag gespeichert: {ticker} ({entry_id[:8]})."
                )
                st.rerun()
            except Exception as exc:
                logger.exception("Could not save tracking entry")
                st.error(f"Eintrag konnte nicht gespeichert werden: {exc}")


def render_tracking_close_form(
    config: dict,
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    entries = tracker.enriched_entries(account_type)
    open_entries = entries[entries["status"] == "open"].copy() if not entries.empty else entries
    if open_entries.empty:
        st.info("Keine offenen Eintraege vorhanden.")
        return

    result = st.session_state.analysis_result
    st.markdown("### Offenen Eintrag schliessen")
    options = open_entries["id"].tolist()
    labels = {
        row["id"]: (
            f"{row['ticker']} | {row['direction'].upper()} | "
            f"{float(row['quantity']):.4g} Stk. | {str(row['id'])[:8]}"
        )
        for _, row in open_entries.iterrows()
    }
    selected_id = st.selectbox(
        "Eintrag waehlen",
        options,
        format_func=lambda value: labels.get(value, value),
        key=make_key(key_prefix, "select"),
    )
    selected = open_entries[open_entries["id"] == selected_id].iloc[0]
    analysis_row = analysis_row_for_ticker(
        result,
        selected["ticker"],
        selected.get("timeframe") or "1d",
    )
    default_exit = safe_float(
        selected.get("last_price"),
        fallback=safe_float(analysis_row.get("close"), fallback=float(selected["entry_price"])),
    )

    with st.form(make_key(key_prefix, "form")):
        col1, col2 = st.columns(2)
        with col1:
            exit_price = st.number_input(
                "Schluss-Referenzpreis",
                min_value=0.01,
                value=max(default_exit, 0.01),
                step=0.01,
                key=make_key(key_prefix, "exit_price", selected_id),
            )
        with col2:
            exit_date = st.date_input(
                "Schlussdatum",
                value=pd.Timestamp.today().date(),
                key=make_key(key_prefix, "exit_date", selected_id),
            )
        exit_note = st.text_area(
            "Schlussnotiz",
            key=make_key(key_prefix, "exit_note", selected_id),
        )
        submitted = st.form_submit_button(
            "Schliessung speichern",
            key=make_key(key_prefix, "submit", selected_id),
            width="stretch",
        )
        if submitted:
            try:
                tracker.close_entry(selected_id, exit_price, exit_date, exit_note)
                tracker.record_snapshots(account_type, result, result["updated_at"])
                st.session_state[f"{account_type}_notice"] = (
                    f"Eintrag geschlossen: {selected['ticker']} ({selected_id[:8]})."
                )
                st.rerun()
            except Exception as exc:
                logger.exception("Could not close tracking entry")
                st.error(f"Eintrag konnte nicht geschlossen werden: {exc}")


def render_tracking_history(
    tracker: PortfolioTracker,
    account_type: str,
    key_prefix: str,
) -> None:
    st.markdown("### Journal und Daten")
    entries = tracker.enriched_entries(account_type)
    if entries.empty:
        render_empty_state(
            "Noch keine Journal-Eintraege",
            "Erfasse einen Paper- oder Real-Eintrag. Danach misst die App Trefferquote, P/L, Setups und Regelverletzungen.",
        )
        return

    display = build_tracking_display(entries)
    render_mobile_record_cards(
        display.to_dict("records"),
        title_key="ticker",
        fields=[
            ("Status", "status"),
            ("Richtung", "direction"),
            ("Entry", "entry_price"),
            ("Offen P/L", "unrealized_pnl"),
            ("Realisiert", "realized_pnl"),
            ("Setup", "setup_category"),
        ],
    )
    with st.expander(f"Große Journal-Tabelle anzeigen ({key_prefix})", expanded=False):
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "entries_dataframe", account_type),
            column_config={
                "id_short": "ID",
                "status": "Status",
                "ticker": "Ticker",
                "direction": "Richtung",
                "quantity": st.column_config.NumberColumn("Anzahl", format="%.4f"),
                "entry_price": st.column_config.NumberColumn("Einstieg", format="%.2f"),
                "stop_price": st.column_config.NumberColumn("Stop", format="%.2f"),
                "target_price": st.column_config.NumberColumn("Ziel", format="%.2f"),
                "last_price": st.column_config.NumberColumn("Letzter Preis", format="%.2f"),
                "market_value": st.column_config.NumberColumn("Marktwert", format="%.2f"),
                "unrealized_pnl": st.column_config.NumberColumn("Offener P/L", format="%.2f"),
                "unrealized_pnl_pct": st.column_config.NumberColumn("Offener P/L %", format="%.2f"),
                "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
                "setup_category": "Setup",
                "rule_violations": "Regelverletzungen",
                "score_at_entry": "Score Entry",
                "risk_state_at_entry": "Risk Entry",
                "snapshot_score": "Score Jetzt",
                "snapshot_risk_state": "Risk Jetzt",
            },
        )

    history = tracker.snapshot_history(account_type)
    if not history.empty:
        grouped = (
            history.groupby("analysis_updated_at", as_index=False)
            .agg({"market_value": "sum", "unrealized_pnl": "sum"})
            .sort_values("analysis_updated_at")
        )
        fig = px.line(
            grouped,
            x="analysis_updated_at",
            y=["market_value", "unrealized_pnl"],
            title="Snapshot-Verlauf offener Eintraege",
        )
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
        style_plotly_figure(fig)
        render_plotly_chart(
            fig,
            key=make_key(key_prefix, "snapshot_plotly", account_type),
        )

    csv_data = entries.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Journal CSV herunterladen",
        data=csv_data,
        file_name=f"{account_type}_journal.csv",
        mime="text/csv",
        key=make_key(key_prefix, "download", account_type),
        width="stretch",
    )
    if st.button(
        "CSV Export in reports/ aktualisieren",
        key=make_key(key_prefix, "export_report", account_type),
        width="stretch",
    ):
        path = tracker.export_journal(account_type, BASE_DIR / "reports")
        st.success(f"Export aktualisiert: {path.name}")


def render_paper_real_comparison(tracker: PortfolioTracker, key_prefix: str) -> None:
    with st.expander(f"Paper vs Real vergleichen ({key_prefix})", expanded=False):
        comparison = tracker.account_comparison()
        if comparison.empty:
            render_empty_state(
                "Noch kein Vergleich",
                "Sobald Papertrading oder Real Money Eintraege enthalten, zeigt die App hier die Unterschiede.",
            )
            return
        render_mobile_record_cards(
            comparison.to_dict("records"),
            title_key="account_type",
            fields=[
                ("Offen", "open_count"),
                ("Treffer", "win_rate"),
                ("Realisiert", "realized_pnl"),
                ("Drawdown", "max_drawdown"),
            ],
        )
        with st.expander(f"Vergleichstabelle anzeigen ({key_prefix})", expanded=False):
            st.dataframe(
                comparison,
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "dataframe"),
                column_config={
                    "account_type": "Bereich",
                    "open_count": "Offen",
                    "closed_count": "Geschlossen",
                    "win_rate": st.column_config.NumberColumn("Trefferquote %", format="%.1f"),
                    "average_win": st.column_config.NumberColumn("Ø Gewinn", format="%.2f"),
                    "average_loss": st.column_config.NumberColumn("Ø Verlust", format="%.2f"),
                    "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
                    "unrealized_pnl": st.column_config.NumberColumn("Offen P/L", format="%.2f"),
                    "max_drawdown": st.column_config.NumberColumn("Max Drawdown", format="%.2f"),
                    "rule_violation_count": "Regelbrueche",
                },
            )
        fig = px.bar(
            comparison,
            x="account_type",
            y=["realized_pnl", "unrealized_pnl", "max_drawdown"],
            barmode="group",
            title="Paper vs Real P/L und Drawdown",
        )
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
        style_plotly_figure(fig)
        render_plotly_chart(fig, key=make_key(key_prefix, "plotly"))


def render_reports(config: dict, key_prefix: str) -> None:
    render_section_title("Reports", "CSV und Abendzusammenfassung manuell erzeugen.")
    render_action_button_area(
        config,
        get_app_env(st.secrets),
        key_prefix=make_key(key_prefix, "actions"),
    )

    result = st.session_state.get("analysis_result", {})
    timeframes = config.get("data", {}).get("timeframes", ["1d", "1wk", "1mo"])
    summary_timeframe = st.selectbox(
        "Summary-Timeframe",
        timeframes,
        key=make_key(key_prefix, "summary_timeframe"),
    )
    render_market_watchlist_summaries(
        result,
        summary_timeframe,
        key_prefix=make_key(key_prefix, "summaries"),
    )

    report_paths = list_report_files(Path(config.get("reports_dir", "reports")))
    if not report_paths:
        render_empty_state(
            "Noch keine CSV-Reports",
            "Klicke Analysieren. Danach werden market_summary.csv und watchlist.csv erstellt.",
        )
        return

    render_report_previews(config, compact=False, key_prefix=make_key(key_prefix, "previews"))

    render_section_title("Downloads", "Export-Dateien aus dem Reports-Ordner.")
    for path in report_paths:
        data = path.read_bytes()
        mime = "text/csv" if path.suffix == ".csv" else "text/plain"
        st.download_button(
            label=f"Download {path.name}",
            data=data,
            file_name=path.name,
            mime=mime,
            key=make_key(key_prefix, "download", path.name),
        )


def render_updates(config: dict, app_env: str, key_prefix: str) -> None:
    st.subheader("Updates")
    version_info = get_current_version(BASE_DIR)
    st.write(f"Aktuelle Version: `{version_info.get('version', '0.1.0')}`")

    if is_cloud_env(app_env):
        st.info(
            "Updates sind im Cloud-Modus deaktiviert. "
            "Bitte Änderungen über GitHub deployen."
        )
        result = st.session_state.get("analysis_result")
        st.markdown("### Analyse-Status")
        if result:
            st.write(f"Letzte Datenanalyse: `{result['updated_at']}`")
        else:
            st.write("Noch keine Analyse in dieser Cloud-Session geladen.")
        st.write("Reports werden im Cloud-Modus bei Bedarf neu erzeugt.")
        st.markdown("### App-Log")
        st.code(read_safe_log(LOG_DIR / "app.log"))
        return

    if not require_sensitive_access(config, "updates"):
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Backup erstellen",
            key=make_key(key_prefix, "create_backup"),
            width="stretch",
        ):
            backup_dir = create_backup(BASE_DIR)
            st.success(f"Backup erstellt: {backup_dir.name}")
    with col2:
        if st.button(
            "Update-Dateien prüfen",
            key=make_key(key_prefix, "inspect_update_files"),
            width="stretch",
        ):
            result = inspect_update_files(BASE_DIR)
            st.session_state.update_inspection = result
            if result["ok"]:
                st.success(f"Update-Dateien ok: {len(result['files'])}")
            else:
                st.error("Update-Dateien enthalten Fehler.")

    col3, col4 = st.columns(2)
    with col3:
        if st.button(
            "Update anwenden",
            key=make_key(key_prefix, "apply_update"),
            width="stretch",
        ):
            result = apply_code_update(BASE_DIR)
            if result["ok"]:
                st.success(result["message"])
                st.info("Bitte Streamlit neu starten, falls Änderungen nicht sichtbar sind.")
            else:
                st.error(result["message"])
    with col4:
        if st.button(
            "Letztes Backup wiederherstellen",
            key=make_key(key_prefix, "restore_latest_backup"),
            width="stretch",
        ):
            result = restore_latest_backup(BASE_DIR)
            if result["ok"]:
                st.success(result["message"])
            else:
                st.error(result["message"])

    st.markdown("### Update-Dateien")
    inspection = st.session_state.get("update_inspection") or inspect_update_files(BASE_DIR)
    st.write(f"Ordner: `{inspection['updates_dir']}`")
    if inspection["files"]:
        st.write("Erlaubte Dateien:")
        st.write(inspection["files"])
    else:
        st.info("Keine erlaubten Update-Dateien gefunden.")
    if inspection["errors"]:
        st.error("\n".join(inspection["errors"]))

    result = st.session_state.analysis_result
    st.markdown("### Analyse-Status")
    st.write(f"Letzte Datenanalyse: `{result['updated_at']}`")
    st.write(f"Datenbank: `{config['data']['database_path']}`")
    st.write(f"Reports: `{config.get('reports_dir', 'reports')}`")

    update_file = LOG_DIR / "last_update.json"
    if update_file.exists():
        st.code(update_file.read_text(encoding="utf-8"), language="json")

    st.markdown("### Backups")
    backups = list_backups(BASE_DIR)
    if backups:
        st.write([backup.name for backup in backups])
    else:
        st.info("Noch keine Backups vorhanden.")

    st.markdown("### Update-Log")
    st.code(read_update_log(BASE_DIR))

    st.markdown("### Changelog")
    st.code(read_changelog(BASE_DIR))

    log_file = LOG_DIR / "app.log"
    if log_file.exists():
        st.markdown("### App-Log")
        st.code("\n".join(log_file.read_text(encoding="utf-8").splitlines()[-20:]))


def render_online_operations(config: dict, app_env: str, key_prefix: str) -> None:
    st.subheader("Online-Betrieb")
    if not require_sensitive_access(config, "online_ops"):
        return

    version_info = get_current_version(BASE_DIR)
    render_section_title(
        "Betriebsstatus",
        "Cloud-ready Status, Monitoring und sichere Betriebsregeln.",
    )
    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html(f"APP_ENV {app_env}", "blue")}
            {status_badge_html("Updates in Cloud aus", "green" if is_cloud_env(app_env) else "yellow")}
            {status_badge_html("Shell in Cloud aus", "green")}
            {status_badge_html("Secrets verdeckt", "green")}
            {status_badge_html("Keine Orders", "pink")}
            <div class="sensei-muted" style="margin-top:.5rem;">
                Version {escape(str(version_info.get("version", "unbekannt")))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    health_rows = build_health_report(BASE_DIR, config, app_env, version_info)
    st.dataframe(
        pd.DataFrame(health_rows),
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "health_table"),
    )

    render_section_title(
        "Secrets",
        "Nur Status. Echte Werte werden nicht angezeigt und nicht in config.json gespeichert.",
    )
    ops_config = config.get("online_operations", {})
    secret_rows = secret_status_rows(
        get_secret,
        app_env,
        optional_names=ops_config.get("optional_cloud_secrets"),
    )
    secrets_df = pd.DataFrame(secret_rows)
    st.dataframe(
        secrets_df[["secret", "level", "status", "value"]],
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "secrets_table"),
        column_config={
            "status": "Status",
            "value": "Wert",
        },
    )
    missing_required = secrets_df[
        (secrets_df["level"] == "Pflicht")
        & (secrets_df["present"] == False)  # noqa: E712
    ]
    if is_cloud_env(app_env) and not missing_required.empty:
        st.warning("Cloud-Secrets unvollstaendig: " + ", ".join(missing_required["secret"].tolist()))
    else:
        st.success("Pflicht-Secrets fuer den aktuellen Modus sind sauber vorbereitet.")

    render_section_title(
        "Monitoring / Fehlerlog",
        "Letzte Betriebsereignisse und Fehlerhinweise aus lokalen Laufzeitlogs.",
    )
    error_summary = summarize_error_logs(BASE_DIR)
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Fehlerhinweise in Logs", int(error_summary.get("error_count", 0)))
    with col2:
        if st.button(
            "Monitoring-Test schreiben",
            key=make_key(key_prefix, "write_monitoring_test"),
            width="stretch",
        ):
            path = write_monitoring_event(
                BASE_DIR,
                "manual_monitoring_test",
                {"app_env": app_env},
                actor=st.session_state.get("authenticated_email", "local"),
            )
            st.success(f"Monitoring-Event geschrieben: {path.name}")

    with st.expander(f"Online-Betrieb-Log ({key_prefix})", expanded=False):
        st.code(read_monitoring_log(BASE_DIR))
    with st.expander(f"Fehlerlog-Auszug ({key_prefix})", expanded=False):
        st.code(str(error_summary.get("recent", "")))

    render_section_title(
        "Cloud-Backup",
        "Export und Restore fuer Konfig-Auswahl, Watchlists und gespeicherte Themen.",
    )
    email = st.session_state.get("authenticated_email", "local")
    store = _workspace_store(config)
    backup = build_cloud_backup(BASE_DIR, config, store, email, app_env)
    backup_json = json.dumps(backup, indent=2, ensure_ascii=False)
    st.download_button(
        "Cloud-Backup herunterladen",
        data=backup_json.encode("utf-8"),
        file_name=f"analyse_market_sensei_cut_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        key=make_key(key_prefix, "download_cloud_backup"),
        width="stretch",
    )
    st.caption(
        "Das Backup enthaelt keine Secret-Werte. Streamlit Cloud-Speicher kann bei Redeploys verloren gehen, "
        "deshalb ist dieser JSON-Export dein schneller Fallschirm."
    )

    uploaded_backup = st.file_uploader(
        "Cloud-Backup wiederherstellen",
        type=["json"],
        key=make_key(key_prefix, "backup_uploader"),
    )
    if uploaded_backup is not None:
        try:
            uploaded_payload = json.loads(uploaded_backup.getvalue().decode("utf-8"))
            st.success(f"Backup erkannt: {uploaded_payload.get('created_at', 'ohne Datum')}")
            replace_watchlists = st.checkbox(
                "Bestehende Custom-Watchlists vorher entfernen",
                value=False,
                key=make_key(key_prefix, "replace_watchlists"),
            )
            restore_config = st.checkbox(
                "Konfig-Auswahl aus Backup uebernehmen",
                value=False,
                key=make_key(key_prefix, "restore_config"),
            )
            if st.button(
                "Backup jetzt wiederherstellen",
                key=make_key(key_prefix, "restore_backup"),
                width="stretch",
            ):
                restore_result = restore_cloud_backup(
                    uploaded_payload,
                    store,
                    email,
                    replace_watchlists=replace_watchlists,
                )
                if restore_config:
                    latest = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
                    latest.update(select_config_backup_fields(uploaded_payload))
                    save_config(enforce_security_defaults(latest, app_env), CONFIG_PATH)
                write_monitoring_event(
                    BASE_DIR,
                    "cloud_backup_restored",
                    restore_result | {"restore_config": restore_config},
                    actor=email,
                )
                st.success(
                    f"Backup wiederhergestellt: {restore_result['watchlists']} Watchlists, "
                    f"{restore_result['symbols']} Symbole."
                )
                st.info("Falls Konfig uebernommen wurde: App neu laden, damit alles sichtbar ist.")
        except Exception as exc:
            logger.exception("Could not restore cloud backup")
            st.error(f"Backup konnte nicht gelesen werden: {exc}")

    render_section_title(
        "Deploy-Routine",
        "Ein Klick lokal, in Cloud nur Anleitung. Keine lokalen Skripte im Cloud-Modus.",
    )
    st.code("\n".join(ops_config.get("deploy_routine", [])))
    if is_cloud_env(app_env):
        st.info("Cloud-Modus: lokale Deploy- und Update-Skripte sind deaktiviert. Änderungen laufen über GitHub.")
    else:
        if st.button(
            "Lokalen Deploy-Check ausfuehren",
            key=make_key(key_prefix, "run_deploy_check"),
            width="stretch",
        ):
            result = run_local_script(BASE_DIR / "scripts" / "prepare_cloud_deploy.sh")
            if result["ok"]:
                st.success(result["output"])
            else:
                st.error(result["output"])


def render_settings(app_env: str, key_prefix: str) -> None:
    st.subheader("Settings")
    config = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
    if not require_sensitive_access(config, "settings"):
        return

    st.write(f"APP_ENV: `{app_env}`")
    render_account_settings(config, app_env, key_prefix=make_key(key_prefix, "account"))
    render_runtime_mode_settings(config, key_prefix=make_key(key_prefix, "runtime_mode"))
    render_broker_planning_settings(config, key_prefix=make_key(key_prefix, "broker_planning"))
    render_trading_safety_settings(config, key_prefix=make_key(key_prefix, "trading_safety"))
    render_ports_and_integrations_settings(config, key_prefix=make_key(key_prefix, "ports_integrations"))
    if is_cloud_env(app_env):
        st.info("macOS Evening Job ist im Cloud-Modus ausgeblendet.")
    else:
        render_evening_job_settings(key_prefix=make_key(key_prefix, "evening_job"))

    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    edited = st.text_area(
        "config.json",
        value=config_text,
        height=420,
        key=make_key(key_prefix, "config_editor"),
    )
    if st.button(
        "Config speichern",
        key=make_key(key_prefix, "save_config"),
        width="stretch",
    ):
        try:
            parsed = enforce_security_defaults(json.loads(edited), app_env)
            save_config(parsed, CONFIG_PATH)
            st.success("Config gespeichert. Neue Daten werden erst beim naechsten Klick auf Analysieren geladen.")
        except json.JSONDecodeError as exc:
            st.error(f"config.json ist kein gueltiges JSON: {exc}")
        except Exception as exc:
            logger.exception("Could not save config")
            st.error(f"Config konnte nicht gespeichert werden: {exc}")


def render_account_settings(config: dict, app_env: str, key_prefix: str) -> None:
    st.markdown("### Account")
    email = st.session_state.get("authenticated_email")
    if not email:
        st.info("Nicht mit E-Mail angemeldet.")
        return

    st.write(f"E-Mail-Identitaet: `{email}`")
    two_factor = config.get("auth", {}).get("two_factor", {})
    two_factor_enabled = bool(two_factor.get("enabled", True))
    st.write(f"Zwei-Faktor-Login aktiv: `{two_factor_enabled}`")
    if is_cloud_env(app_env):
        st.info("Cloud-Modus: 2FA bleibt fuer den Online-Betrieb fest aktiv.")
    else:
        with st.form(make_key(key_prefix, "two_factor_form")):
            selected = st.toggle(
                "2FA im lokalen Entwicklungsmodus aktiv",
                value=two_factor_enabled,
                key=make_key(key_prefix, "two_factor_enabled"),
            )
            st.caption(
                "Nur lokal fuer Entwicklung. In APP_ENV=cloud wird 2FA automatisch wieder erzwungen."
            )
            submitted = st.form_submit_button(
                "2FA-Einstellung speichern",
                key=make_key(key_prefix, "two_factor_save"),
                width="stretch",
            )
        if submitted:
            latest = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
            latest_two_factor = latest.setdefault("auth", {}).setdefault("two_factor", {})
            latest_two_factor["enabled"] = bool(selected)
            latest_two_factor["required_for_login"] = bool(selected)
            save_config(latest, CONFIG_PATH)
            st.session_state.pop("pending_2fa_email", None)
            st.session_state.pop("local_2fa_code", None)
            st.success("2FA-Einstellung gespeichert. Der naechste Login nutzt diese Einstellung.")
            st.rerun()

    store = AuthStore(BASE_DIR / config.get("auth", {}).get("database_path", "data/auth.duckdb"))
    passkey = store.passkey_status(email)
    st.write(f"Passkey vorbereitet: `{passkey['prepared']}`")
    st.write(f"Aktive Passkeys: `{passkey['enabled_credentials']}`")
    st.caption(passkey["message"])


def require_sensitive_access(config: dict, area: str) -> bool:
    security = config.get("security", {})
    if not security.get("require_password_for_sensitive_settings", True):
        return True
    if dev_login_available(get_app_env(st.secrets)) and st.session_state.get("dev_login_active"):
        return True
    unlock_until = float(st.session_state.get("sensitive_unlocked_until", 0))
    if st.session_state.get("sensitive_unlocked") and time.time() < unlock_until:
        return True
    if st.session_state.get("sensitive_unlocked"):
        st.session_state.pop("sensitive_unlocked", None)
        st.session_state.pop("sensitive_unlocked_until", None)

    email = st.session_state.get("authenticated_email")
    if not email:
        st.error("Dieser Bereich braucht eine bestaetigte E-Mail-Anmeldung.")
        return False

    st.warning(
        "Geschuetzter Bereich. Bitte bestaetige dein Account-Passwort erneut, "
        "bevor Einstellungen, APIs, Ports oder Updates angezeigt werden."
    )
    password = st.text_input(
        "Account-Passwort erneut eingeben",
        type="password",
        key=make_key(area, "sensitive_password"),
    )
    if st.button(
        "Geschuetzten Bereich entsperren",
        key=make_key(area, "unlock"),
        width="stretch",
    ):
        store = AuthStore(BASE_DIR / config.get("auth", {}).get("database_path", "data/auth.duckdb"))
        result = store.verify_password(
            email,
            password,
            rate_limit=config.get("auth", {}).get("rate_limit", {}),
        )
        if result.ok:
            minutes = int(security.get("sensitive_unlock_minutes", 15))
            st.session_state.sensitive_unlocked = True
            st.session_state.sensitive_unlocked_until = time.time() + max(1, minutes) * 60
            st.success("Bereich entsperrt.")
            st.rerun()
        else:
            st.error(result.message)
    return False


def render_ports_and_integrations_settings(config: dict, key_prefix: str) -> None:
    st.markdown("### Ports, Seitenlinks und APIs")
    st.caption(
        "Vorbereiteter, passwortgeschuetzter Bereich. Hier werden nur Konfigurationen "
        "gespeichert; es werden keine API-Aufrufe und keine Broker-Aktionen ausgefuehrt."
    )

    settings = config.setdefault("ports_and_integrations", {})
    links = settings.get("protected_links") or [
        {
            "enabled": False,
            "name": "Beispiel Dashboard",
            "url": "https://example.com",
            "category": "seite",
            "note": "Hier spaeter Link eintragen",
        }
    ]
    apis = settings.get("protected_apis") or [
        {
            "enabled": False,
            "name": "Beispiel API",
            "base_url": "https://api.example.com",
            "port": "",
            "path": "/v1/status",
            "method": "GET",
            "auth_type": "api_key",
            "api_key_secret_ref": "EXAMPLE_API_KEY",
            "note": "Secret-Wert in Streamlit Secrets oder ENV ablegen",
        }
    ]

    with st.form(make_key(key_prefix, "form")):
        col1, col2, col3 = st.columns(3)
        with col1:
            streamlit_port = st.number_input(
                "Streamlit Port",
                min_value=1,
                max_value=65535,
                value=int(settings.get("streamlit_port", 8501)),
                step=1,
                key=make_key(key_prefix, "streamlit_port"),
            )
        with col2:
            local_api_port = st.text_input(
                "Lokaler API-Port optional",
                value=str(settings.get("local_api_port", "")),
                placeholder="z.B. 8000",
                key=make_key(key_prefix, "local_api_port"),
            )
        with col3:
            webhook_port = st.text_input(
                "Webhook-Port optional",
                value=str(settings.get("webhook_port", "")),
                placeholder="z.B. 9000",
                key=make_key(key_prefix, "webhook_port"),
            )

        st.caption(
            "Port-Aenderungen sind vorbereitet und werden gespeichert. Der Streamlit-"
            "Starter muss danach passend gestartet werden, damit ein neuer Port aktiv ist."
        )

        st.markdown("#### Geschuetzte Seitenlinks")
        links_df = st.data_editor(
            pd.DataFrame(links),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "protected_links_editor"),
            column_config={
                "enabled": st.column_config.CheckboxColumn("Aktiv"),
                "name": "Name",
                "url": st.column_config.LinkColumn("URL"),
                "category": "Kategorie",
                "note": "Notiz",
            },
        )

        st.markdown("#### Geschuetzte APIs")
        st.caption(
            "API-Keys nicht im Klartext speichern. Trage bei `api_key_secret_ref` "
            "nur den Namen des Secrets ein, z.B. `OPENAI_API_KEY` oder `MY_DATA_API_KEY`."
        )
        apis_df = st.data_editor(
            pd.DataFrame(apis),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=make_key(key_prefix, "protected_apis_editor"),
            column_config={
                "enabled": st.column_config.CheckboxColumn("Aktiv"),
                "name": "Name",
                "base_url": st.column_config.LinkColumn("Base URL"),
                "port": "Port",
                "path": "Pfad",
                "method": st.column_config.SelectboxColumn(
                    "Methode",
                    options=["GET", "POST", "PUT", "PATCH", "DELETE"],
                ),
                "auth_type": st.column_config.SelectboxColumn(
                    "Auth",
                    options=["none", "api_key", "bearer", "basic", "custom"],
                ),
                "api_key_secret_ref": "Secret-Name",
                "note": "Notiz",
            },
        )

        submitted = st.form_submit_button(
            "Ports, Links und APIs speichern",
            key=make_key(key_prefix, "submit"),
            width="stretch",
        )
        if submitted:
            settings["streamlit_port"] = int(streamlit_port)
            settings["local_api_port"] = local_api_port.strip()
            settings["webhook_port"] = webhook_port.strip()
            settings["protected"] = True
            settings["execute_api_calls"] = False
            settings["protected_links"] = clean_editor_records(
                links_df,
                ["enabled", "name", "url", "category", "note"],
            )
            settings["protected_apis"] = clean_editor_records(
                apis_df,
                [
                    "enabled",
                    "name",
                    "base_url",
                    "port",
                    "path",
                    "method",
                    "auth_type",
                    "api_key_secret_ref",
                    "note",
                ],
            )
            config["ports_and_integrations"] = settings
            save_config(config, CONFIG_PATH)
            st.success("Ports, Seitenlinks und API-Platzhalter gespeichert.")


def render_mode_banner(config: dict, app_env: str) -> None:
    runtime = config.get("runtime_mode", {})
    active = runtime.get("active", "papertrading")
    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html(f"APP_ENV {app_env}", "blue")}
            {status_badge_html(f"Modus {active}", "pink")}
            {status_badge_html("Analyse-only", "green")}
            <span class="sensei-muted" style="margin-left:.35rem;">Keine Orders. Keine Broker-Funktion.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def authenticate(app_env: str, config: dict) -> bool:
    auth_config = config.get("auth", {})
    if not auth_config.get("enabled", True):
        return legacy_password_auth(app_env)

    if st.session_state.get("authenticated_email"):
        return True

    store = AuthStore(BASE_DIR / auth_config.get("database_path", "data/auth.duckdb"))
    rate_limit = auth_config.get("rate_limit", {})
    st.subheader("Anmeldung")
    st.caption("Login mit bestaetigter E-Mail-Identitaet. Keine Trading-Funktionen.")
    render_dev_login_button(app_env, key_prefix=make_key("auth", "login"))

    login_tab, register_tab, confirm_tab, reset_tab, passkey_tab = st.tabs(
        ["Login", "Registrieren", "E-Mail bestaetigen", "Passwort vergessen", "Passkey"]
    )

    with login_tab:
        pending_email = st.session_state.get("pending_2fa_email")
        if pending_email:
            render_two_factor_login_step(store, pending_email, rate_limit=rate_limit)
        else:
            email = st.text_input("E-Mail", key=make_key("auth", "login", "email"))
            password = st.text_input(
                "Passwort",
                type="password",
                key=make_key("auth", "login", "password"),
            )
            if st.button(
                "Einloggen",
                key=make_key("auth", "login", "submit"),
                width="stretch",
            ):
                two_factor_config = auth_config.get("two_factor", {})
                if two_factor_config.get("enabled", True):
                    result = store.verify_password(email, password, rate_limit=rate_limit)
                    if not result.ok:
                        st.error(result.message)
                    else:
                        start_two_factor_challenge(
                            store=store,
                            email=result.email or email,
                            app_env=app_env,
                            auth_config=auth_config,
                        )
                else:
                    result = store.login(email, password, rate_limit=rate_limit)
                    if result.ok:
                        st.session_state.authenticated_email = result.email
                        st.success("Login erfolgreich.")
                        st.rerun()
                    else:
                        st.error(result.message)

    with register_tab:
        if not auth_config.get("allow_registration", True):
            st.info("Registrierung ist deaktiviert.")
        else:
            reg_email = st.text_input("E-Mail", key=make_key("auth", "register", "email"))
            reg_password = st.text_input(
                "Passwort",
                type="password",
                key=make_key("auth", "register", "password"),
            )
            reg_password_2 = st.text_input(
                "Passwort wiederholen",
                type="password",
                key=make_key("auth", "register", "password_repeat"),
            )
            if st.button(
                "Registrieren und Code senden",
                key=make_key("auth", "register", "submit"),
                width="stretch",
            ):
                if reg_password != reg_password_2:
                    st.error("Die Passwoerter stimmen nicht ueberein.")
                else:
                    allowed_emails = auth_config.get("allowed_emails", []) + read_allowed_email_secrets()
                    if (
                        is_cloud_env(app_env)
                        and auth_config.get("require_allowed_emails_in_cloud", True)
                        and not allowed_emails
                    ):
                        st.error(
                            "Cloud-Registrierung ist blockiert, bis AUTH_ALLOWED_EMAILS "
                            "oder auth.allowed_emails gesetzt ist."
                        )
                    elif is_cloud_env(app_env) and not smtp_config_complete():
                        st.error(
                            "Cloud-Registrierung ist blockiert, bis SMTP-Secrets vollstaendig gesetzt sind."
                        )
                    else:
                        result = store.register_user(
                            reg_email,
                            reg_password,
                            allowed_emails=allowed_emails,
                            code_minutes=int(auth_config.get("verification_code_minutes", 30)),
                            rate_limit=rate_limit,
                        )
                        if not result.ok:
                            st.error(result.message)
                        else:
                            smtp_result = send_verification_email(
                                result.email or reg_email,
                                result.verification_code or "",
                                smtp_settings(),
                            )
                            if smtp_result.ok:
                                st.success("Registrierung erstellt. Bitte pruefe deine E-Mail.")
                            elif is_cloud_env(app_env):
                                st.error(smtp_result.message)
                                st.info("In Streamlit Secrets muessen SMTP_* Werte gesetzt sein.")
                            else:
                                st.warning(
                                    "SMTP ist nicht konfiguriert. Nur lokal wird der Code angezeigt."
                                )
                                st.code(result.verification_code or "")

    with confirm_tab:
        confirm_email = st.text_input("E-Mail", key=make_key("auth", "confirm", "email"))
        confirm_code = st.text_input(
            "Bestaetigungscode",
            key=make_key("auth", "confirm", "code"),
        )
        if st.button(
            "E-Mail bestaetigen",
            key=make_key("auth", "confirm", "submit"),
            width="stretch",
        ):
            result = store.verify_email(
                confirm_email,
                confirm_code,
                rate_limit=rate_limit,
            )
            if result.ok:
                st.success(result.message)
            else:
                st.error(result.message)

    with reset_tab:
        st.caption("Reset-Code anfordern und danach ein neues Passwort setzen.")
        reset_backend_supported = ensure_password_reset_backend(store)
        if not reset_backend_supported:
            st.warning(
                "Passwort-Reset ist in dieser Version noch nicht vollstaendig geladen. "
                "Bitte `modules/auth.py` zusammen mit `app.py` deployen."
            )
        reset_email = st.text_input(
            "E-Mail fuer Reset-Code",
            key=make_key("auth", "password_reset", "request_email"),
        )
        if st.button(
            "Reset-Code senden",
            key=make_key("auth", "password_reset", "request_submit"),
            width="stretch",
        ):
            if not reset_backend_supported:
                st.error("Passwort-Reset Backend fehlt. Bitte `modules/auth.py` aktualisieren.")
            elif is_cloud_env(app_env) and not smtp_config_complete():
                st.error("Passwort-Reset ist im Cloud-Modus blockiert, bis SMTP-Secrets vollstaendig gesetzt sind.")
            else:
                code_minutes = int(auth_config.get("password_reset_code_minutes", 15))
                result = store.create_password_reset_code(
                    reset_email,
                    code_minutes=code_minutes,
                    rate_limit=rate_limit,
                )
                if not result.ok:
                    st.error(result.message)
                elif not result.verification_code:
                    st.success("Wenn die E-Mail registriert ist, wurde ein Reset-Code gesendet.")
                elif send_password_reset_email is None:
                    if is_cloud_env(app_env):
                        st.error(
                            "Passwort-Reset-Mailfunktion fehlt. Bitte `modules/auth.py` neu deployen."
                        )
                    else:
                        st.warning(
                            "Mailfunktion ist nicht geladen. Nur lokal wird der Reset-Code angezeigt."
                        )
                        st.code(result.verification_code)
                else:
                    smtp_result = send_password_reset_email(
                        result.email or reset_email,
                        result.verification_code or "",
                        smtp_settings(),
                    )
                    if smtp_result.ok:
                        st.success("Wenn die E-Mail registriert ist, wurde ein Reset-Code gesendet.")
                    elif is_cloud_env(app_env):
                        st.error(smtp_result.message)
                        st.info("In Streamlit Secrets muessen SMTP_* Werte gesetzt sein.")
                    else:
                        st.warning("SMTP ist nicht konfiguriert. Nur lokal wird der Reset-Code angezeigt.")
                        if result.verification_code:
                            st.code(result.verification_code)
                        else:
                            st.info("Wenn die E-Mail registriert ist, wurde ein Reset-Code vorbereitet.")

        st.divider()
        reset_confirm_email = st.text_input(
            "E-Mail",
            key=make_key("auth", "password_reset", "confirm_email"),
        )
        reset_code = st.text_input(
            "Reset-Code",
            key=make_key("auth", "password_reset", "code"),
        )
        new_password = st.text_input(
            "Neues Passwort",
            type="password",
            key=make_key("auth", "password_reset", "new_password"),
        )
        new_password_repeat = st.text_input(
            "Neues Passwort wiederholen",
            type="password",
            key=make_key("auth", "password_reset", "new_password_repeat"),
        )
        if st.button(
            "Passwort neu setzen",
            key=make_key("auth", "password_reset", "confirm_submit"),
            width="stretch",
        ):
            if not reset_backend_supported:
                st.error("Passwort-Reset Backend fehlt. Bitte `modules/auth.py` aktualisieren.")
            elif new_password != new_password_repeat:
                st.error("Die Passwoerter stimmen nicht ueberein.")
            else:
                result = store.reset_password(
                    reset_confirm_email,
                    reset_code,
                    new_password,
                    rate_limit=rate_limit,
                )
                if result.ok:
                    st.success(result.message)
                else:
                    st.error(result.message)

    with passkey_tab:
        st.info(
            "Passkey/WebAuthn ist vorbereitet, aber noch nicht aktiv. "
            "Fuer echte Passkeys braucht die App eine HTTPS-Domain und eine WebAuthn-Komponente."
        )
        st.write("Vorbereitet: Auth-Tabelle `passkey_credentials` und UI-Platzhalter.")

    return False


def start_two_factor_challenge(
    store: AuthStore,
    email: str,
    app_env: str,
    auth_config: dict,
) -> None:
    two_factor_config = auth_config.get("two_factor", {})
    code_minutes = int(two_factor_config.get("code_minutes", 10))
    code_result = store.create_two_factor_code(
        email,
        code_minutes,
        purpose="login",
        rate_limit=auth_config.get("rate_limit", {}),
    )
    if not code_result.ok:
        st.error(code_result.message)
        return

    smtp_result = send_two_factor_email(
        code_result.email or email,
        code_result.verification_code or "",
        smtp_settings(),
    )
    if smtp_result.ok:
        st.session_state.pending_2fa_email = code_result.email or email
        st.session_state.pop("local_2fa_code", None)
        st.success("Passwort bestaetigt. Bitte pruefe deine E-Mail fuer den 2FA-Code.")
        st.rerun()
        return

    if is_cloud_env(app_env):
        st.error(smtp_result.message)
        st.info("Fuer 2FA im Cloud-Modus muessen SMTP-Secrets gesetzt sein.")
        return

    st.session_state.pending_2fa_email = code_result.email or email
    st.session_state.local_2fa_code = code_result.verification_code
    st.rerun()


def render_two_factor_login_step(store: AuthStore, email: str, rate_limit: Optional[dict] = None) -> None:
    st.info(f"2FA erforderlich fuer `{email}`.")
    local_code = st.session_state.get("local_2fa_code")
    if local_code:
        st.caption("Lokaler Entwicklungsmodus: Code wird angezeigt, weil kein SMTP gesetzt ist.")
        st.code(local_code)

    code = st.text_input("Zwei-Faktor-Code", key=make_key("auth", "login", "2fa_code"))
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "2FA bestaetigen",
            key=make_key("auth", "login", "2fa_confirm"),
            width="stretch",
        ):
            result = store.verify_two_factor_code(
                email,
                code,
                purpose="login",
                rate_limit=rate_limit,
            )
            if result.ok:
                store.mark_login_success(result.email or email)
                st.session_state.authenticated_email = result.email or email
                st.session_state.pop("pending_2fa_email", None)
                st.session_state.pop("local_2fa_code", None)
                st.success("Login erfolgreich.")
                st.rerun()
            else:
                st.error(result.message)
    with col2:
        if st.button(
            "Login abbrechen",
            key=make_key("auth", "login", "cancel"),
            width="stretch",
        ):
            st.session_state.pop("pending_2fa_email", None)
            st.session_state.pop("local_2fa_code", None)
            st.rerun()


def legacy_password_auth(app_env: str) -> bool:
    return require_app_password_gate(app_env)


def require_app_password_gate(app_env: str) -> bool:
    password = get_secret("APP_PASSWORD") or os.getenv("APP_PASSWORD")
    if not password:
        if not is_cloud_env(app_env):
            return True
        st.subheader("App-Schutz")
        st.error("Cloud-Modus ist aktiv, aber `APP_PASSWORD` ist nicht gesetzt.")
        st.info(
            "Setze in Streamlit Community Cloud unter Secrets zum Beispiel: "
            '`APP_PASSWORD = "dein-starkes-passwort"`.'
        )
        return False

    if st.session_state.get("app_password_ok") or st.session_state.get("authenticated"):
        return True

    st.subheader("App-Schutz")
    st.caption(
        "Erster Zugriffsschutz vor dem Benutzer-Login. "
        "Danach folgt die E-Mail-Anmeldung mit 2FA."
    )
    render_dev_login_button(app_env, key_prefix=make_key("auth", "app_password_gate"))
    entered = st.text_input(
        "App-Passwort",
        type="password",
        key=make_key("auth", "app_password_gate", "input"),
    )
    if st.button(
        "App entsperren",
        width="stretch",
        key=make_key("auth", "app_password_gate", "button"),
    ):
        if hmac.compare_digest(entered or "", password):
            st.session_state.app_password_ok = True
            st.session_state.authenticated = True
            st.success("App entsperrt.")
            st.rerun()
        else:
            st.error("App-Passwort ist falsch.")
    return False


def render_account_bar() -> None:
    email = st.session_state.get("authenticated_email")
    if not email:
        return
    st.markdown("<div class='sensei-account-strip'>", unsafe_allow_html=True)
    account_col, action_col = st.columns([0.78, 0.22], gap="small")
    with account_col:
        st.caption(f"Angemeldet als {email}")
    with action_col:
        if st.button(
            "Logout",
            key=make_key("auth", "logout"),
            width="stretch",
        ):
            for key in [
                "authenticated_email",
                "authenticated",
                "app_password_ok",
                "dev_login_active",
                "pending_2fa_email",
                "local_2fa_code",
                "sensitive_unlocked",
                "sensitive_unlocked_until",
            ]:
                st.session_state.pop(key, None)
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def read_allowed_email_secrets() -> list[str]:
    raw = get_secret("AUTH_ALLOWED_EMAILS") or os.getenv("AUTH_ALLOWED_EMAILS", "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def smtp_settings() -> dict:
    return {
        "host": get_secret("SMTP_HOST") or os.getenv("SMTP_HOST"),
        "port": get_secret("SMTP_PORT") or os.getenv("SMTP_PORT", "587"),
        "username": get_secret("SMTP_USERNAME") or os.getenv("SMTP_USERNAME"),
        "password": get_secret("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD"),
        "sender": get_secret("SMTP_FROM") or os.getenv("SMTP_FROM"),
        "use_tls": (get_secret("SMTP_USE_TLS") or os.getenv("SMTP_USE_TLS", "true")).lower()
        != "false",
    }


def smtp_config_complete() -> bool:
    settings = smtp_settings()
    return all(settings.get(key) for key in ["host", "port", "username", "password", "sender"])


def get_secret(key: str) -> Optional[str]:
    try:
        value = st.secrets.get(key)
    except Exception:
        return None
    if value is None:
        return None
    return str(value)


def render_runtime_mode_settings(config: dict, key_prefix: str) -> None:
    st.markdown("### Vorbereiteter Modus")
    runtime = config.setdefault("runtime_mode", {})
    available = runtime.get("available", ["papertrading", "real"])
    active = runtime.get("active", "papertrading")
    selected = st.selectbox(
        "Modus auswaehlen",
        available,
        index=available.index(active) if active in available else 0,
        key=make_key(key_prefix, "select"),
    )
    st.caption(
        "Zwei Schritte: Modus auswaehlen, dann speichern. "
        "Auch Real aktiviert keine Orders und keine Broker-Funktion."
    )
    if st.button(
        "Modus speichern",
        key=make_key(key_prefix, "save"),
        width="stretch",
    ):
        runtime["active"] = selected
        runtime["orders_enabled"] = False
        runtime["broker_enabled"] = False
        config["runtime_mode"] = runtime
        save_config(config, CONFIG_PATH)
        st.success(f"Modus gespeichert: {selected}. Analyse-only bleibt aktiv. Keine neue Analyse gestartet.")


def render_broker_planning_settings(config: dict, key_prefix: str) -> None:
    st.markdown("### Broker-Planung")
    status = broker_status(config)
    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html('Prepared only', 'pink')}
            {status_badge_html(f"Default {status['default_provider']}", 'blue')}
            {status_badge_html('Execution aus', 'green')}
            {status_badge_html('API aus', 'green')}
            <span class="sensei-muted" style="margin-left:.35rem;">
                Provider werden nur als Routing-Plan gespeichert.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Die Matrix kombiniert grosse Anbieter nach Asset-Klassen. "
        "Spaeter kann daraus eine saubere Adapter-Schicht entstehen; heute gibt es keine Ausfuehrung."
    )
    matrix = provider_matrix(config)
    st.dataframe(
        matrix,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "provider_matrix"),
        column_config={
            "provider": "Provider",
            "asset_classes": "Asset-Klassen",
            "strengths": "Staerken",
            "best_for": "Sinnvoll fuer",
            "connection_status": "Status",
            "execution_enabled": st.column_config.CheckboxColumn("Ausfuehrung aktiv"),
        },
    )
    st.info(
        "Naechster sicherer Schritt waere ein Paper-Adapter mit Mock-Fills. "
        "Erst danach sollte eine echte Provider-API angeschlossen werden."
    )


def render_trading_safety_settings(config: dict, key_prefix: str) -> None:
    st.markdown("### Trading Safety")
    safety = trading_safety_config(config)
    decision = evaluate_trading_request(config)
    st.markdown(
        f"""
        <div class="sensei-card">
            {status_badge_html('Safety Gate aktiv', 'pink')}
            {status_badge_html('Live-Trading aus', 'green')}
            {status_badge_html('Sandbox/Paper zuerst', 'blue')}
            {status_badge_html('Keine Auto-Orders', 'green')}
            <div class="sensei-score-label" style="margin-top:.55rem;">
                Spaetere Broker-Anbindung darf erst nach Order-Vorschau, 2-Klick-Bestaetigung,
                Kill-Switch-Pruefung, Tagesverlustlimit und Audit-Log weiterlaufen.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    checklist = pd.DataFrame(safety_checklist(config))
    st.dataframe(
        checklist,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "checklist"),
        column_config={
            "check": "Sicherheitsregel",
            "required": st.column_config.CheckboxColumn("Pflicht"),
            "active": st.column_config.CheckboxColumn("Aktiv"),
            "status": "Status",
        },
    )

    with st.form(make_key(key_prefix, "limits_form")):
        col1, col2 = st.columns(2)
        with col1:
            daily_loss_pct = st.number_input(
                "Tagesverlustlimit %",
                min_value=0.1,
                max_value=20.0,
                value=float(safety.get("daily_loss_limit_pct", 1.0)),
                step=0.1,
                key=make_key(key_prefix, "daily_loss_pct"),
            )
        with col2:
            daily_loss_amount = st.number_input(
                "Tagesverlustlimit Betrag optional",
                min_value=0.0,
                max_value=1_000_000.0,
                value=float(safety.get("daily_loss_limit_amount", 0.0)),
                step=50.0,
                key=make_key(key_prefix, "daily_loss_amount"),
            )
        submitted = st.form_submit_button(
            "Safety-Limits speichern",
            key=make_key(key_prefix, "save_limits"),
            width="stretch",
        )
        if submitted:
            safety["daily_loss_limit_pct"] = float(daily_loss_pct)
            safety["daily_loss_limit_amount"] = float(daily_loss_amount)
            safety["enabled"] = True
            safety["live_trading_enabled"] = False
            safety["automatic_orders_allowed"] = False
            safety["kill_switch_active"] = True
            safety["sandbox_required"] = True
            safety["paper_api_first"] = True
            safety["order_preview_required"] = True
            safety["two_click_confirmation_required"] = True
            safety["hard_approval_required"] = True
            safety["daily_loss_limit_enabled"] = True
            safety["audit_log_enabled"] = True
            safety["allowed_connection_modes"] = ["sandbox_paper"]
            safety["default_connection_mode"] = "sandbox_paper"
            config["trading_safety"] = safety
            save_config(config, CONFIG_PATH)
            write_audit_event(
                BASE_DIR,
                config,
                "safety_limits_saved",
                payload={
                    "daily_loss_limit_pct": daily_loss_pct,
                    "daily_loss_limit_amount": daily_loss_amount,
                },
                actor=st.session_state.get("authenticated_email", "local"),
            )
            st.success("Safety-Limits gespeichert. Live-Trading bleibt aus.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Kill-Switch aktivieren",
            key=make_key(key_prefix, "activate_kill_switch"),
            width="stretch",
        ):
            safety["kill_switch_active"] = True
            safety["live_trading_enabled"] = False
            safety["automatic_orders_allowed"] = False
            config["trading_safety"] = safety
            save_config(config, CONFIG_PATH)
            write_audit_event(
                BASE_DIR,
                config,
                "kill_switch_activated",
                payload={"source": "settings"},
                actor=st.session_state.get("authenticated_email", "local"),
            )
            st.success("Kill-Switch ist aktiv. Ausfuehrung bleibt blockiert.")
    with col2:
        if st.button(
            "Safety-Test-Vorschau erzeugen",
            key=make_key(key_prefix, "preview_test"),
            width="stretch",
        ):
            preview = build_order_preview(
                ticker="SPY",
                side="buy",
                quantity=1,
                order_type="market",
                account_type="papertrading",
            )
            blocked_decision = evaluate_trading_request(
                config,
                request={
                    **preview,
                    "connection_mode": "sandbox_paper",
                    "preview_created": True,
                    "daily_loss_checked": True,
                    "audit_logged": False,
                    "automatic": False,
                },
                confirmation_step_1=True,
                confirmation_step_2=False,
                hard_approval=False,
            )
            path = write_audit_event(
                BASE_DIR,
                config,
                "order_preview_test_blocked",
                payload={
                    "preview": preview,
                    "decision": blocked_decision.to_dict(),
                },
                actor=st.session_state.get("authenticated_email", "local"),
            )
            st.info("Test-Vorschau wurde blockiert. Das ist korrekt.")
            st.code(json.dumps({"preview": preview, "decision": blocked_decision.to_dict()}, indent=2))
            st.caption(f"Audit: {path.relative_to(BASE_DIR)}")

    audit_path = BASE_DIR / str(safety.get("audit_log_path", "logs/trading_safety_audit.jsonl"))
    with st.expander(f"Trading-Safety Audit-Log ({key_prefix})", expanded=False):
        st.code(read_audit_log(audit_path, max_lines=25))
    if decision.reasons:
        st.caption("Aktuelle Blockgruende: " + " | ".join(decision.reasons[:8]))


def render_evening_job_settings(key_prefix: str) -> None:
    st.markdown("### Evening Job")
    st.caption(
        "Installiert einen macOS LaunchAgent fuer 22:30 Uhr. "
        "Der Job startet nur die Analyse und bricht ab, wenn der Mac nicht am Netzteil haengt."
    )
    st.code(
        "python main.py --mode evening-analysis\n"
        "./install_evening_job.sh\n"
        "./uninstall_evening_job.sh"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Evening Job installieren",
            key=make_key(key_prefix, "install"),
            width="stretch",
        ):
            result = run_local_script(BASE_DIR / "install_evening_job.sh")
            if result["ok"]:
                st.success(result["output"])
            else:
                st.error(result["output"])
    with col2:
        if st.button(
            "Evening Job entfernen",
            key=make_key(key_prefix, "uninstall"),
            width="stretch",
        ):
            result = run_local_script(BASE_DIR / "uninstall_evening_job.sh")
            if result["ok"]:
                st.success(result["output"])
            else:
                st.error(result["output"])


def run_local_script(path: Path) -> dict:
    if is_cloud_env(get_app_env(st.secrets)):
        return {
            "ok": False,
            "output": "Lokale Shell-Skripte sind im Cloud-Modus deaktiviert.",
        }
    try:
        completed = subprocess.run(
            [str(path)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "output": f"Skript konnte nicht gestartet werden: {exc}"}

    output = "\n".join(
        part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
    )
    if not output:
        output = f"Skript beendet mit Code {completed.returncode}."
    return {"ok": completed.returncode == 0, "output": output}


def render_footer() -> None:
    st.divider()
    st.caption(
        "Keine Anlageberatung. Keine Kauf- oder Verkaufsempfehlung. "
        "Daten können verzögert oder fehlerhaft sein."
    )


def read_safe_log(path: Path, max_lines: int = 40) -> str:
    if not path.exists():
        return "Noch kein Log vorhanden."
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[-max_lines:])


def tracking_symbols(config: dict) -> list[str]:
    symbols = []
    for entry in config.get("dashboard_symbols", []):
        ticker = entry.get("ticker") if isinstance(entry, dict) else entry
        symbols.append(str(ticker))
    symbols.extend(str(item) for item in config.get("watchlist", []))
    benchmark = config.get("benchmark")
    if benchmark:
        symbols.append(str(benchmark))

    unique = []
    for symbol in symbols:
        if symbol and symbol not in unique:
            unique.append(symbol)
    return unique or ["SPY"]


def analysis_combined_frame(result: dict) -> pd.DataFrame:
    frames = [
        result.get("dashboard", pd.DataFrame()),
        result.get("watchlist", pd.DataFrame()),
        result.get("sector_rotation", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def exact_analysis_row_for_ticker(result: dict, ticker: str, timeframe: str) -> dict:
    combined = analysis_combined_frame(result)
    if combined.empty or not {"ticker", "timeframe"}.issubset(combined.columns):
        return {}

    combined["ticker_lookup"] = combined["ticker"].astype(str).str.upper()
    combined["timeframe_lookup"] = combined["timeframe"].astype(str)
    ticker_lookup = str(ticker).upper()
    exact = combined[
        (combined["ticker_lookup"] == ticker_lookup) & (combined["timeframe_lookup"] == str(timeframe))
    ]
    if exact.empty:
        return {}
    row = exact.iloc[0].drop(labels=["ticker_lookup", "timeframe_lookup"], errors="ignore")
    return row.to_dict()


def analysis_row_for_ticker(result: dict, ticker: str, timeframe: str) -> dict:
    combined = analysis_combined_frame(result)
    if combined.empty:
        return {}

    combined["ticker_lookup"] = combined["ticker"].astype(str).str.upper()
    combined["timeframe_lookup"] = combined["timeframe"].astype(str)
    ticker_lookup = str(ticker).upper()
    exact = combined[
        (combined["ticker_lookup"] == ticker_lookup) & (combined["timeframe_lookup"] == str(timeframe))
    ]
    if exact.empty:
        exact = combined[combined["ticker_lookup"] == ticker_lookup]
    if exact.empty:
        return {}
    row = exact.iloc[0].drop(labels=["ticker_lookup", "timeframe_lookup"], errors="ignore")
    return row.to_dict()


def render_tracking_analysis_snapshot(row: dict) -> None:
    if not row:
        st.warning("Fuer diesen Ticker liegt noch keine Analysezeile vor.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Close", f"{safe_float(row.get('close')):.2f}")
    col2.metric("Score", f"{int(safe_float(row.get('score'), 0))}/100")
    col3.metric("Trend", str(row.get("trend", "n/a")))
    col4.metric("Risk", str(row.get("risk_state", "n/a")))
    st.caption(
        "Diese Werte werden beim Speichern als Analyse-Snapshot am Eintrag gesichert."
    )


def auto_rule_violations(
    config: dict,
    analysis_row: dict,
    market_status: dict,
    direction: str,
    quantity: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    thesis: str,
) -> list[str]:
    row = analysis_row or {}
    violations: list[str] = []
    risk_config = config.get("risk_management", {})
    thresholds = risk_config.get("thresholds", {})
    reduced_score_below = safe_float(thresholds.get("reduced_score_below"), 60)
    score = safe_float(row.get("score"), 0)
    risk_state = str(row.get("risk_state", "")).upper()
    trend = str(row.get("trend", "")).lower()
    close = safe_float(row.get("close"), 0)
    ema200 = safe_float(row.get("ema_200"), 0)
    direction = str(direction).lower()

    if score < reduced_score_below:
        violations.append("Score unter Mindestwert")
    if risk_state == "BLOCKED":
        violations.append("Risk State BLOCKED ignoriert")
    if (direction == "long" and trend == "bearish") or (direction == "short" and trend == "bullish"):
        violations.append("Trend gegen Richtung")
    if direction == "long" and close > 0 and ema200 > 0 and close < ema200:
        violations.append("Close unter EMA200")
    if safe_float(stop_price, 0) <= 0:
        violations.append("Stop fehlt")
    if safe_float(target_price, 0) <= 0:
        violations.append("Ziel fehlt")
    if str(market_status.get("level", "caution")) != "ok":
        violations.append("Marktampel nicht OK")
    if len(str(thesis or "").strip()) < 12:
        violations.append("Keine klare These")

    max_entry_value = safe_float(config.get("tracking", {}).get("max_entry_value"), 0)
    entry_value = safe_float(quantity, 0) * safe_float(entry_price, 0)
    if max_entry_value > 0 and entry_value > max_entry_value:
        violations.append("Positionsgroesse zu hoch")

    return merge_rule_options([], violations)


def render_auto_rule_violations(violations: list[str]) -> None:
    if not violations:
        st.markdown(
            f"{status_badge_html('Auto-Regelcheck OK', 'green')}",
            unsafe_allow_html=True,
        )
        return
    chips = " ".join(status_badge_html(violation, "pink") for violation in violations)
    st.markdown(
        (
            "<div class='sensei-alert-panel'>"
            "<strong>Automatisch markierte Regelverletzungen</strong><br>"
            f"{chips}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def merge_rule_options(*groups) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group or []:
            text = str(value).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def build_tracking_display(entries: pd.DataFrame) -> pd.DataFrame:
    display = entries.copy()
    display["id_short"] = display["id"].astype(str).str[:8]
    columns = [
        "id_short",
        "status",
        "ticker",
        "direction",
        "quantity",
        "entry_date",
        "entry_price",
        "stop_price",
        "target_price",
        "last_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "exit_date",
        "exit_price",
        "realized_pnl",
        "setup_category",
        "rule_violations",
        "score_at_entry",
        "trend_at_entry",
        "risk_state_at_entry",
        "snapshot_score",
        "snapshot_trend",
        "snapshot_risk_state",
        "thesis",
    ]
    return display[[column for column in columns if column in display.columns]]


def tracking_setup_categories(config: dict) -> list[str]:
    defaults = [
        "Trendfolge",
        "Breakout",
        "Pullback",
        "Mean Reversion",
        "Relative Staerke",
        "Defensiv Beobachtung",
        "Sonstiges",
    ]
    return clean_string_list(config.get("tracking", {}).get("setup_categories"), defaults)


def tracking_rule_options(config: dict) -> list[str]:
    defaults = [
        "Score unter Mindestwert",
        "Risk State BLOCKED ignoriert",
        "Trend gegen Richtung",
        "Close unter EMA200",
        "Stop fehlt",
        "Ziel fehlt",
        "Positionsgroesse zu hoch",
        "Marktampel nicht OK",
        "Keine klare These",
    ]
    return clean_string_list(config.get("tracking", {}).get("rule_violation_options"), defaults)


def clean_string_list(values, defaults: list[str]) -> list[str]:
    cleaned = []
    for value in values or defaults:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned or defaults


def watchlist_categories(config: dict) -> list[str]:
    categories = config.get("watchlist_categories") or DEFAULT_WATCHLIST_CATEGORIES
    cleaned = []
    for category in categories:
        text = str(category).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned or DEFAULT_WATCHLIST_CATEGORIES


def trend_sort_rank(value) -> int:
    return {
        "bullish": 0,
        "neutral": 1,
        "bearish": 2,
        "nicht analysiert": 3,
    }.get(str(value).lower(), 9)


def risk_sort_rank(value) -> int:
    return {
        "OK": 0,
        "REDUCED": 1,
        "BLOCKED": 2,
        "offen": 3,
    }.get(str(value), 9)


def safe_float(value, fallback: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return float(fallback)
    return float(value)


def style_plotly_figure(fig):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(17,17,19,0.96)",
        font=dict(color="#f5f5f7"),
        title_font=dict(color="#f5f5f7"),
        legend=dict(font=dict(color="#f5f5f7")),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.10)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.10)")
    return fig


def safe_optional_float(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_index(options: list, value, default: int = 0) -> int:
    normalized = str(value)
    try:
        return [str(option) for option in options].index(normalized)
    except ValueError:
        return default


def safe_widget_key(value) -> str:
    return "".join(character if character.isalnum() else "_" for character in str(value))


def format_money(value: float) -> str:
    return f"{float(value):,.2f} USD"


def clean_editor_records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    if df is None or df.empty:
        return []

    records = []
    for raw in df.reindex(columns=columns).to_dict("records"):
        cleaned = {}
        has_content = False
        for column in columns:
            value = raw.get(column)
            if column == "enabled":
                cleaned[column] = bool(value) if not pd.isna(value) else False
                continue
            if value is None or pd.isna(value):
                text = ""
            else:
                text = str(value).strip()
            cleaned[column] = text
            if text:
                has_content = True
        if has_content:
            records.append(cleaned)
    return records


def render_empty_state(title: str, body: str) -> None:
    st.info(f"**{title}**\n\n{body}")


def render_summary_metrics(df: pd.DataFrame) -> None:
    if df.empty:
        render_empty_state(
            "Keine Daten fuer diesen Timeframe",
            "Klicke Analysieren oder waehle einen anderen Timeframe.",
        )
        return
    columns = st.columns(len(df))
    for col, (_, row) in zip(columns, df.iterrows()):
        with col:
            st.metric(
                label=row["label"],
                value=f"{int(row['score'])}/100",
                delta=row["trend"],
            )


def render_analysis_table(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        render_empty_state(
            "Keine Analysezeilen",
            "Sobald eine Analyse erfolgreich war, erscheinen hier Score, Trend, Risk State und EMAs.",
        )
        return
    columns = [
        "label",
        "ticker",
        "timeframe",
        "trend",
        "score",
        "risk_state",
        "risk_score",
        "data_status",
        "data_source",
        "last_clean_date",
        "data_rows",
        "max_risk_pct",
        "max_position_pct",
        "close",
        "ema_20",
        "ema_50",
        "ema_100",
        "ema_200",
        "return_5",
        "return_20",
        "relative_strength",
        "last_updated",
        "data_message",
    ]
    working = df.copy()
    for column in columns:
        if column not in working:
            working[column] = "" if column != "data_rows" else 0
    display = working[columns].copy()
    render_mobile_analysis_cards(
        display.sort_values("score", ascending=False) if "score" in display else display,
        key_prefix=make_key(key_prefix, "mobile_cards"),
        limit=12,
    )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        key=make_key(key_prefix, "dataframe"),
        column_config={
            "label": "Name",
            "ticker": "Ticker",
            "trend": "Trend",
            "risk_state": "Risk State",
            "data_status": "Datenstatus",
            "data_source": "Quelle",
            "last_clean_date": "Letzter sauberer Stand",
            "data_rows": st.column_config.NumberColumn("Datenzeilen", format="%d"),
            "score": st.column_config.ProgressColumn(
                "Score",
                min_value=0,
                max_value=100,
                format="%d",
            ),
            "risk_score": st.column_config.ProgressColumn(
                "Risk Score",
                min_value=0,
                max_value=100,
                format="%d",
            ),
            "max_risk_pct": st.column_config.NumberColumn("Max Risk %", format="%.2f"),
            "max_position_pct": st.column_config.NumberColumn("Max Size %", format="%.2f"),
            "close": st.column_config.NumberColumn("Close", format="%.2f"),
            "ema_20": st.column_config.NumberColumn("EMA20", format="%.2f"),
            "ema_50": st.column_config.NumberColumn("EMA50", format="%.2f"),
            "ema_100": st.column_config.NumberColumn("EMA100", format="%.2f"),
            "ema_200": st.column_config.NumberColumn("EMA200", format="%.2f"),
            "return_5": st.column_config.NumberColumn("5 Perioden %", format="%.2f"),
            "return_20": st.column_config.NumberColumn("20 Perioden %", format="%.2f"),
            "relative_strength": st.column_config.NumberColumn("RS vs QQQ", format="%.2f"),
            "last_updated": "Letzte Aktualisierung",
            "data_message": "Datenmeldung",
        },
    )


def render_score_chart(df: pd.DataFrame, title: str, key_prefix: str) -> None:
    if df.empty:
        return
    fig = px.bar(
        df,
        x="label",
        y="score",
        color="trend",
        range_y=[0, 100],
        title=title,
    )
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "score_plotly"))
    risk_fig = px.bar(
        df,
        x="label",
        y="risk_score",
        color="risk_state",
        range_y=[0, 100],
        title=f"{title} - Risk Score",
    )
    risk_fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(risk_fig)
    render_plotly_chart(risk_fig, key=make_key(key_prefix, "risk_plotly"))


def render_relative_strength_chart(df: pd.DataFrame, key_prefix: str) -> None:
    if df.empty:
        return
    fig = px.bar(
        df,
        x="label",
        y="relative_strength",
        title="Relative Staerke gegen QQQ",
    )
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
    style_plotly_figure(fig)
    render_plotly_chart(fig, key=make_key(key_prefix, "plotly"))


def render_report_previews(config: dict, compact: bool, key_prefix: str) -> None:
    reports_dir = Path(config.get("reports_dir", "reports"))
    market_path = reports_dir / "market_summary.csv"
    watchlist_path = reports_dir / "watchlist.csv"
    sector_rotation_path = reports_dir / "sector_rotation.csv"
    market_regime_path = reports_dir / "market_regime_report.csv"
    regime_history_path = reports_dir / "regime_history.csv"
    regime_strategy_path = reports_dir / "regime_strategy_map.csv"
    evening_path = reports_dir / "evening_summary.txt"

    if not any(
        path.exists()
        for path in [
            market_path,
            watchlist_path,
            sector_rotation_path,
            market_regime_path,
            regime_history_path,
            regime_strategy_path,
            evening_path,
        ]
    ):
        if not compact:
            render_empty_state(
                "Noch keine Reports",
                "Klicke Analysieren oder Reports aktualisieren. Danach kannst du CSV-Dateien herunterladen.",
            )
        return

    with st.expander(f"Reports aus letzter Analyse ({key_prefix})", expanded=not compact):
        if market_path.exists():
            st.markdown("**market_summary.csv**")
            st.dataframe(
                pd.read_csv(market_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "market_summary_dataframe"),
            )
        if watchlist_path.exists():
            st.markdown("**watchlist.csv**")
            st.dataframe(
                pd.read_csv(watchlist_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "watchlist_dataframe"),
            )
        if sector_rotation_path.exists():
            st.markdown("**sector_rotation.csv**")
            st.dataframe(
                pd.read_csv(sector_rotation_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "sector_rotation_dataframe"),
            )
        if market_regime_path.exists():
            st.markdown("**market_regime_report.csv**")
            st.dataframe(
                pd.read_csv(market_regime_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "market_regime_dataframe"),
            )
        if regime_history_path.exists():
            st.markdown("**regime_history.csv**")
            st.dataframe(
                pd.read_csv(regime_history_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "regime_history_dataframe"),
            )
        if regime_strategy_path.exists():
            st.markdown("**regime_strategy_map.csv**")
            st.dataframe(
                pd.read_csv(regime_strategy_path),
                width="stretch",
                hide_index=True,
                key=make_key(key_prefix, "regime_strategy_dataframe"),
            )
        if evening_path.exists():
            st.markdown("**evening_summary.txt**")
            st.code(evening_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            write_monitoring_event(
                BASE_DIR,
                "app_exception",
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                },
                actor="system",
            )
        except Exception:
            pass
        raise
