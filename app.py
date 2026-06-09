from __future__ import annotations

import json
import hmac
import logging
import os
import subprocess
import time
from html import escape
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from main import run_evening_analysis
from modules.app_env import get_app_env, is_cloud_env
from modules.auth import AuthStore, send_two_factor_email, send_verification_email
from modules.data_provider import DataProvider
from modules.indicators import add_indicators
from modules.portfolio_tracker import PortfolioTracker
from modules.report_generator import list_report_files
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


def main() -> None:
    st.set_page_config(
        page_title="Analyse Market Sensei Cut",
        layout="wide",
    )
    st.title("Analyse Market Sensei Cut")
    st.caption("Lokale Marktdatenanalyse. Keine Orders. Kein Trading. Keine Broker-API.")
    apply_responsive_css()

    app_env = get_app_env(st.secrets)
    config = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
    if not require_app_password_gate(app_env):
        st.stop()
    if not authenticate(app_env, config):
        st.stop()

    _ensure_result(config, app_env)
    _refresh_tracking_snapshots(config)
    render_account_bar()
    render_mode_banner(config, app_env)

    tabs = st.tabs(
        [
            "Workspace",
            "Dashboard",
            "Watchlist",
            "Papertrading",
            "Real Money",
            "Reports",
            "Updates",
            "Settings",
        ]
    )
    with tabs[0]:
        render_workspace(config, app_env)
    with tabs[1]:
        render_dashboard(config, app_env)
    with tabs[2]:
        render_watchlist(config)
    with tabs[3]:
        render_papertrading(config)
    with tabs[4]:
        render_real_money(config)
    with tabs[5]:
        render_reports(config)
    with tabs[6]:
        render_updates(config, app_env)
    with tabs[7]:
        render_settings(app_env)
    render_footer()


def _ensure_result(config: dict, app_env: str) -> None:
    if "analysis_result" not in st.session_state:
        with st.spinner("Lade Marktdaten und berechne Analyse..."):
            st.session_state.analysis_result = run_full_update(
                config,
                generate_reports=False,
            )


def _run_update(config: dict, generate_reports: bool = False) -> None:
    with st.spinner("Analyse laeuft..."):
        st.session_state.analysis_result = run_full_update(
            config,
            generate_reports=generate_reports,
        )
        _refresh_tracking_snapshots(config, force=True)
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
        st.session_state.analysis_result = run_full_update(
            temporary_config,
            generate_reports=False,
        )
        _refresh_tracking_snapshots(temporary_config, force=True)
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


def apply_responsive_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sensei-alert: #ff2bd6;
            --sensei-alert-soft: rgba(255, 43, 214, 0.10);
            --sensei-alert-line: rgba(255, 43, 214, 0.42);
        }
        .sensei-terminal {
            border: 1px solid rgba(49, 51, 63, 0.14);
            border-radius: 8px;
            padding: 0.7rem 0.8rem;
            background: linear-gradient(180deg, rgba(250,250,250,0.92), rgba(245,245,247,0.76));
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
        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-top: 1rem;
            }
            [data-testid="stMetric"] {
                background: rgba(250, 250, 250, 0.7);
                border: 1px solid rgba(49, 51, 63, 0.12);
                border-radius: 8px;
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
        }
        </style>
        """,
        unsafe_allow_html=True,
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


def enforce_security_defaults(config: dict, app_env: str) -> dict:
    auth = config.setdefault("auth", {})
    auth["enabled"] = True
    auth["require_email_verification"] = True
    auth.setdefault("allow_registration", True)
    auth.setdefault("verification_code_minutes", 30)
    auth.setdefault("database_path", "data/auth.duckdb")
    if is_cloud_env(app_env):
        auth["require_allowed_emails_in_cloud"] = True

    two_factor = auth.setdefault("two_factor", {})
    two_factor["enabled"] = True
    two_factor["required_for_login"] = True
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

    security = config.setdefault("security", {})
    security["require_password_for_sensitive_settings"] = True
    security["settings_password_gate"] = True
    security["updates_password_gate"] = True
    security["ports_and_integrations_password_gate"] = True
    security["store_api_keys_in_config"] = False
    security.setdefault("sensitive_unlock_minutes", 15)

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
    data.setdefault(
        "cache_max_age_hours",
        {
            "1d": 6,
            "1wk": 24,
            "1mo": 72,
            "default": 24,
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
    config.setdefault("watchlist_categories", DEFAULT_WATCHLIST_CATEGORIES)

    runtime = config.setdefault("runtime_mode", {})
    runtime["orders_enabled"] = False
    runtime["broker_enabled"] = False
    return config


def render_dashboard(config: dict, app_env: str) -> None:
    result = st.session_state.analysis_result
    dashboard = result["dashboard"]

    st.subheader("Dashboard")
    if st.button("Abendanalyse jetzt starten", use_container_width=True):
        evening_result = run_evening_analysis(
            require_power=not is_cloud_env(app_env),
            allow_cloud=True,
        )
        if evening_result["ok"]:
            st.session_state.analysis_result = evening_result["analysis_result"]
            st.success("Abendanalyse abgeschlossen.")
            st.info("reports/evening_summary.txt wurde aktualisiert.")
            result = st.session_state.analysis_result
            dashboard = result["dashboard"]
        elif evening_result.get("skipped"):
            st.warning(evening_result["message"])
        else:
            st.error(evening_result["message"])

    st.write(f"Letzte Aktualisierung: `{result['updated_at']}`")
    render_timeframe_buttons(
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        "dashboard_timeframe",
        "dashboard",
    )
    timeframe = st.selectbox(
        "Timeframe",
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        key="dashboard_timeframe",
    )
    filtered = dashboard[dashboard["timeframe"] == timeframe]
    render_market_traffic_light(result, timeframe)
    render_summary_metrics(filtered)
    with st.expander("Details anzeigen", expanded=False):
        render_analysis_table(filtered)
    with st.expander("Score-Charts anzeigen", expanded=False):
        render_score_chart(filtered, f"Dashboard Scores {timeframe}")
    render_report_previews(config, compact=True)


def render_workspace(config: dict, app_env: str) -> None:
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
    render_mobile_quick_view(config, store, email, result, timeframes)
    render_today_overview(config, store, email, result, timeframes)
    st.divider()
    st.markdown("### Detailansicht")

    col_left, col_right = st.columns([1, 2])
    with col_left:
        st.markdown("### Fokus")
        selected_topic = render_saved_topics_picker(store, email)
        default_ticker = selected_topic.get("ticker") if selected_topic else symbols[0]
        default_timeframe = selected_topic.get("timeframe") if selected_topic else timeframes[0]
        if default_ticker and default_ticker not in symbols:
            symbols.insert(0, default_ticker)
        apply_selected_topic(selected_topic)
        render_quick_symbol_buttons(symbols)
        render_timeframe_buttons(timeframes, "workspace_timeframe", "workspace")
        ticker = st.selectbox(
            "Ticker",
            symbols,
            index=safe_index(symbols, default_ticker),
            key="workspace_ticker",
        )
        timeframe = st.selectbox(
            "Timeframe",
            timeframes,
            index=safe_index(timeframes, default_timeframe),
            key="workspace_timeframe",
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
            key="workspace_focus_mode",
        )

        col_action_1, col_action_2 = st.columns(2)
        with col_action_1:
            if st.button("Analysieren", key="workspace_analyze", type="primary", use_container_width=True):
                _run_update(config, generate_reports=True)
                store.record_event(email, "data_collection", ticker, timeframe, "manual")
        with col_action_2:
            if st.button("Beobachten", key="workspace_observe", use_container_width=True):
                observe_symbol(store, email, ticker, note=f"Fokus {timeframe}")
                st.success(f"{ticker} wurde beobachtet. Pink markiert den Alert-Datenpunkt.")
                st.rerun()

        render_save_topic_form(config, store, email, ticker, timeframe)
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
        render_workspace_focus_card(row, ticker, timeframe)
        if focus_mode in ["Chart", "Daten sammeln"]:
            render_symbol_chart(config, result, ticker, timeframe, store, email)
        if focus_mode == "Daten sammeln":
            render_collection_overview(config, store, email)


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
) -> None:
    with st.expander("Mobile Schnellansicht", expanded=True):
        st.caption("Watchlist zuerst, Chart direkt darunter. Tabellen bleiben in Details.")
        render_timeframe_buttons(timeframes, "mobile_timeframe", "mobile")
        timeframe = st.session_state.get("mobile_timeframe", timeframes[0])

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
        render_mobile_watchlist_cards(display, timeframe)

        tickers = display["ticker"].astype(str).str.upper().tolist()
        current_ticker = st.session_state.get("mobile_ticker", tickers[0])
        if current_ticker not in tickers:
            current_ticker = tickers[0]
        selected_ticker = st.selectbox(
            "Chart-Symbol",
            tickers,
            index=safe_index(tickers, current_ticker),
            key="mobile_ticker",
        )

        row = analysis_row_for_ticker(result, selected_ticker, timeframe)
        render_workspace_focus_card(row, selected_ticker, timeframe)
        render_symbol_chart(config, result, selected_ticker, timeframe, store, email)


def render_mobile_watchlist_cards(display: pd.DataFrame, timeframe: str) -> None:
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
                    key=f"mobile-chart-{safe_widget_key(ticker)}-{safe_widget_key(timeframe)}",
                    use_container_width=True,
                ):
                    st.session_state.mobile_ticker = ticker
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
) -> None:
    st.markdown("### Heute ansehen")
    st.caption("Erst Ampel lesen, dann Kandidaten ansehen. Details bleiben darunter.")
    render_timeframe_buttons(timeframes, "today_timeframe", "today")
    timeframe = st.session_state.get("today_timeframe", timeframes[0])

    render_market_traffic_light(result, timeframe)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Analysieren", key="today_analyze", type="primary", use_container_width=True):
            _run_update(config, generate_reports=True)
            store.record_event(email, "today_analyze", "", timeframe, "manual")
    with col2:
        selected_focus = st.session_state.get("workspace_ticker") or tracking_symbols(config)[0]
        if st.button("Beobachten", key="today_observe", use_container_width=True):
            observe_symbol(store, email, selected_focus, note=f"Heute ansehen {timeframe}")
            st.success(f"{selected_focus} wurde beobachtet. Pink markiert den Alert-Datenpunkt.")
            st.rerun()
    with col3:
        if st.button("Zum Chart", key="today_to_chart", use_container_width=True):
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
    render_today_cards(candidates.head(6), store, email, timeframe)


def render_market_traffic_light(result: dict, timeframe: str) -> None:
    status = market_traffic_light(result, timeframe)
    message = (
        f"{status['label']}: {status['summary']} "
        f"Regel: {status['rule']} Naechster Schritt: {status['next_step']}"
    )
    if status["level"] == "ok":
        st.success(message)
    elif status["level"] == "blocked":
        st.error(message)
    else:
        st.warning(message)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ampel", status["label"])
    col2.metric("SPY", status["spy"])
    col3.metric("QQQ", status["qqq"])
    col4.metric("Score", f"{status['average_score']:.0f}/100")


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
                    key=f"today-view-{safe_widget_key(ticker)}-{safe_widget_key(timeframe)}",
                    use_container_width=True,
                ):
                    st.session_state.workspace_ticker = ticker
                    st.session_state.workspace_timeframe = timeframe
                    st.session_state.workspace_focus_mode = "Chart"
                    st.rerun()
            with col_b:
                if st.button(
                    "Beobachten",
                    key=f"today-watch-{safe_widget_key(ticker)}-{safe_widget_key(timeframe)}",
                    use_container_width=True,
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


def render_saved_topics_picker(store: WorkspaceStore, email: str) -> dict:
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
        key="workspace_saved_topic",
    )
    if not selected_id:
        return {}

    store.mark_opened(email, selected_id)
    selected = topics[topics["id"] == selected_id].iloc[0].to_dict()
    if st.button("Thema loeschen", key=f"delete-topic-{selected_id}", use_container_width=True):
        store.delete_topic(email, selected_id)
        st.success("Thema geloescht.")
        st.rerun()
    return selected


def render_quick_symbol_buttons(symbols: list[str]) -> None:
    st.caption("Schnellwechsel")
    quick_symbols = symbols[:8]
    columns = st.columns(4)
    for index, symbol in enumerate(quick_symbols):
        with columns[index % 4]:
            if st.button(
                symbol,
                key=f"quick-symbol-{safe_widget_key(symbol)}",
                use_container_width=True,
            ):
                st.session_state.workspace_ticker = symbol
                st.rerun()


def render_timeframe_buttons(timeframes: list[str], state_key: str, key_prefix: str) -> None:
    st.caption("Timeframe")
    current = st.session_state.get(state_key, timeframes[0])
    columns = st.columns(max(1, len(timeframes)))
    for index, timeframe in enumerate(timeframes):
        with columns[index % len(columns)]:
            if st.button(
                timeframe,
                key=f"{key_prefix}-timeframe-{safe_widget_key(timeframe)}",
                type="primary" if timeframe == current else "secondary",
                use_container_width=True,
            ):
                st.session_state[state_key] = timeframe
                st.rerun()


def render_save_topic_form(
    config: dict,
    store: WorkspaceStore,
    email: str,
    ticker: str,
    timeframe: str,
) -> None:
    categories = config.get("workspace", {}).get("categories", DEFAULT_CATEGORIES)
    with st.expander("Speichern", expanded=False):
        render_system_alert_panel(
            "Pink Alert: Speicherung",
            "Alles, was fuer spaetere System-Erkennung, Beobachtung oder Bot-Vorbereitung gespeichert wird, ist pink markiert.",
        )
        with st.form("save_workspace_topic", clear_on_submit=True):
            name = st.text_input("Name", value=f"{ticker} {timeframe}")
            category = st.selectbox("Kategorie", categories, index=safe_index(categories, "Research"))
            note = st.text_area("Notiz", placeholder="Worauf willst du spaeter schnell zugreifen?")
            pinned = st.checkbox("Oben halten", value=True)
            if st.form_submit_button("Speichern", use_container_width=True):
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
        with st.expander("Eigene Watchlists", expanded=False):
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
        key=f"{key_prefix}_custom_watchlist_select",
    )
    selected_watchlist = watchlists[watchlists["id"] == selected_watchlist_id].iloc[0].to_dict()

    col_a, col_b = st.columns(2)
    with col_a:
        timeframe = st.selectbox(
            "Analyse-Timeframe",
            timeframes,
            index=safe_index(timeframes, st.session_state.get("workspace_timeframe", timeframes[0])),
            key=f"{key_prefix}_custom_watchlist_timeframe",
        )
    with col_b:
        sort_mode = st.selectbox(
            "Sortierung",
            ["Risk State", "Score hoch", "Trend", "Favoriten/Pins"],
            key=f"{key_prefix}_custom_watchlist_sort",
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
            use_container_width=True,
            hide_index=True,
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
                        key=f"{key_prefix}-custom-focus-{safe_widget_key(symbol)}",
                        use_container_width=True,
                    ):
                        st.session_state.workspace_ticker = symbol
                        st.session_state.workspace_timeframe = timeframe
                        st.rerun()

        if st.button(
            "Analysieren",
            key=f"{key_prefix}_analyze_custom_watchlist",
            type="primary",
            use_container_width=True,
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
            key=f"{key_prefix}_delete_watchlist",
            use_container_width=True,
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
        with st.expander("Neue Watchlist", expanded=False):
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
    with st.form(f"{key_prefix}_create_watchlist_form", clear_on_submit=True):
        name = st.text_input(
            "Name",
            placeholder="z.B. Breakout Ideen",
            key=f"{key_prefix}_create_watchlist_name",
        )
        category = st.selectbox(
            "Kategorie",
            categories,
            index=safe_index(categories, "Eigene Ideen"),
            key=f"{key_prefix}_create_watchlist_category",
        )
        pinned = st.checkbox(
            "Oben halten",
            value=True,
            key=f"{key_prefix}_create_watchlist_pinned",
        )
        if st.form_submit_button("Watchlist anlegen", use_container_width=True):
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
    with st.form(f"{key_prefix}_add_watchlist_symbol_form", clear_on_submit=True):
        symbol = st.text_input(
            "Symbol hinzufuegen",
            placeholder="z.B. BTC-USD",
            key=f"{key_prefix}_add_symbol_ticker",
        )
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(
                "Kategorie",
                categories,
                index=safe_index(categories, "Eigene Ideen"),
                key=f"{key_prefix}_add_symbol_category",
            )
        with col2:
            pinned = st.checkbox("Pin", value=False, key=f"{key_prefix}_add_symbol_pinned")
        note = st.text_input(
            "Notiz optional",
            placeholder="Warum ist das Symbol interessant?",
            key=f"{key_prefix}_add_symbol_note",
        )
        if st.form_submit_button("Beobachten", use_container_width=True):
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
        with st.expander("Symbol entfernen", expanded=False):
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
        key=f"{key_prefix}_delete_symbol_select",
    )
    if st.button(
        "Symbol entfernen",
        key=f"{key_prefix}_delete_symbol_button",
        use_container_width=True,
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


def render_workspace_focus_card(row: dict, ticker: str, timeframe: str) -> None:
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
            }
        ]
    )
    st.dataframe(compact, use_container_width=True, hide_index=True)


def render_symbol_chart(
    config: dict,
    result: dict,
    ticker: str,
    timeframe: str,
    store: Optional[WorkspaceStore] = None,
    email: str = "local",
) -> None:
    history = chart_history(config, result, ticker, timeframe)
    if history.empty:
        st.warning("Keine historischen Chartdaten fuer diesen Fokus vorhanden.")
        return

    row = analysis_row_for_ticker(result, ticker, timeframe)
    if row:
        render_system_alert_tags(row, compact=False)
    history = history.sort_values("date").tail(chart_point_limit(timeframe)).copy()
    chart_lines = (
        store.list_chart_lines(email, ticker, timeframe)
        if store is not None
        else pd.DataFrame()
    )
    up_color = "#16803c"
    down_color = "#b42318"
    volume_colors = [
        up_color if close >= open_price else down_color
        for close, open_price in zip(history["close"], history["open"])
    ]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
    )
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
        "ema_200": ("EMA200", "#111827"),
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

    add_chart_line_traces(fig, chart_lines)

    fig.add_trace(
        go.Bar(
            x=history["date"],
            y=history["volume"],
            name="Volumen",
            marker_color=volume_colors,
            opacity=0.45,
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        title=f"{ticker} Candlestick {timeframe}",
        height=660,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        dragmode="pan",
        newshape=dict(line_color=SYSTEM_ALERT_COLOR, line_width=2),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        uirevision=f"{ticker}-{timeframe}",
    )
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        row=1,
        col=1,
    )
    fig.update_yaxes(title_text="Preis", row=1, col=1)
    fig.update_yaxes(title_text="Volumen", row=2, col=1)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": ["drawline", "eraseshape"],
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        },
    )
    st.caption(
        "Zoom mit Mausrad, Pan ueber Ziehen. Pink markiert System-/Alert-Linien und gespeicherte Erkennungspunkte."
    )
    render_chart_line_tools(store, email, ticker, timeframe, history, chart_lines)


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


def render_chart_line_tools(
    store: Optional[WorkspaceStore],
    email: str,
    ticker: str,
    timeframe: str,
    history: pd.DataFrame,
    chart_lines: pd.DataFrame,
) -> None:
    if store is None:
        return

    safe_key = safe_widget_key(f"{ticker}-{timeframe}")
    last_row = history.iloc[-1]
    start_row = history.iloc[max(0, len(history) - 30)]
    default_start_date = pd.to_datetime(start_row["date"]).date()
    default_end_date = pd.to_datetime(last_row["date"]).date()
    default_start_price = float(start_row["close"])
    default_end_price = float(last_row["close"])

    with st.expander("Linien speichern und verwalten", expanded=False):
        render_system_alert_panel(
            "Pink Alert: Linien",
            "Gespeicherte Linien sind Alert- und Erkennungspunkte. Sie markieren keine Order und keine Ausfuehrung.",
        )
        with st.form(f"chart_line_form_{safe_key}", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Name", value=f"{ticker} Linie")
                start_date = st.date_input("Startdatum", value=default_start_date)
                start_price = st.number_input(
                    "Startpreis",
                    min_value=0.01,
                    value=max(default_start_price, 0.01),
                    step=0.01,
                )
            with col2:
                color = st.color_picker("Farbe", value=SYSTEM_ALERT_COLOR)
                end_date = st.date_input("Enddatum", value=default_end_date)
                end_price = st.number_input(
                    "Endpreis",
                    min_value=0.01,
                    value=max(default_end_price, 0.01),
                    step=0.01,
                )
            note = st.text_input("Notiz optional", placeholder="z.B. Widerstand oder Trendlinie")
            pinned = st.checkbox("Linie oben halten", value=True)
            submitted = st.form_submit_button("Linie speichern", use_container_width=True)
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
                "Zeichne erst im Chart oder trage Start und Ende unten ein. Gespeicherte Linien erscheinen beim naechsten Oeffnen wieder.",
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
            use_container_width=True,
            hide_index=True,
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
            key=f"delete_chart_line_{safe_key}",
        )
        if st.button("Ausgewaehlte Linie loeschen", key=f"delete_chart_line_btn_{safe_key}"):
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


def render_collection_overview(config: dict, store: WorkspaceStore, email: str) -> None:
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
            use_container_width=True,
            hide_index=True,
        )
    else:
        render_empty_state(
            "Noch keine Aktivitaet",
            "Klicke Analysieren, Beobachten oder Speichern. Danach entsteht hier dein Verlauf.",
        )


def render_watchlist(config: dict) -> None:
    result = st.session_state.analysis_result
    watchlist = result["watchlist"]
    store = _workspace_store(config)
    email = st.session_state.get("authenticated_email", "local")
    store.ensure_default_watchlists(email, watchlist_categories(config))

    st.subheader("Watchlist")
    st.caption(f"Relative Staerke gegen {config.get('benchmark', 'QQQ')}")
    render_timeframe_buttons(
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        "watchlist_timeframe",
        "watchlist",
    )
    timeframe = st.selectbox(
        "Timeframe",
        config["data"].get("timeframes", ["1d", "1wk", "1mo"]),
        key="watchlist_timeframe",
    )
    filtered = watchlist[watchlist["timeframe"] == timeframe]
    if filtered.empty:
        render_empty_state(
            "Keine Watchlist-Daten",
            "Klicke Analysieren, damit die Mag7-Werte fuer diesen Timeframe geladen werden.",
        )
    else:
        st.markdown("### Schnellueberblick")
        render_today_cards(
            filtered.sort_values("score", ascending=False).head(6),
            store,
            email,
            timeframe,
        )
        with st.expander("Tabelle anzeigen", expanded=False):
            render_analysis_table(filtered)
        with st.expander("Charts anzeigen", expanded=False):
            render_score_chart(filtered, f"Mag7 Scores {timeframe}")
            render_relative_strength_chart(filtered)
    st.divider()
    st.markdown("### Eigene Watchlists")
    render_custom_watchlists(
        config=config,
        store=store,
        email=email,
        result=result,
        key_prefix="watchlist",
        compact=False,
    )


def render_papertrading(config: dict) -> None:
    render_tracking_area(
        config=config,
        account_type="papertrading",
        title="Papertrading",
        description=(
            "Simuliertes Analyse-Journal. Paper laeuft parallel mit und speichert "
            "bei jeder Analyse Snapshots deiner offenen Eintraege."
        ),
    )


def render_real_money(config: dict) -> None:
    render_tracking_area(
        config=config,
        account_type="real_money",
        title="Real Money",
        description=(
            "Manuelles Spiegel-Depot fuer echte Positionen. Keine Orders, keine "
            "Broker-Anbindung, keine automatische Ausfuehrung."
        ),
    )


def render_tracking_area(config: dict, account_type: str, title: str, description: str) -> None:
    tracker = _tracker(config)

    st.subheader(title)
    st.caption(description)
    st.info("Analyse-only: Eintraege werden nur lokal gespeichert und niemals ausgefuehrt.")

    notice = st.session_state.pop(f"{account_type}_notice", None)
    if notice:
        st.success(notice)

    render_tracking_metrics(tracker, account_type)
    render_tracking_performance(tracker, account_type, expanded=False)
    with st.expander("Eintrag erfassen", expanded=False):
        render_tracking_entry_form(config, tracker, account_type)
    with st.expander("Eintrag schliessen", expanded=False):
        render_tracking_close_form(config, tracker, account_type)
    with st.expander("Journal anzeigen", expanded=False):
        render_tracking_history(tracker, account_type)
    render_paper_real_comparison(tracker)


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


def render_tracking_performance(
    tracker: PortfolioTracker,
    account_type: str,
    expanded: bool = False,
) -> None:
    with st.expander("Performance auswerten", expanded=expanded):
        render_tracking_equity_curve(tracker, account_type)
        col1, col2 = st.columns(2)
        with col1:
            render_tracking_setup_breakdown(tracker, account_type)
        with col2:
            render_tracking_rule_violations(tracker, account_type)


def render_tracking_equity_curve(tracker: PortfolioTracker, account_type: str) -> None:
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
    st.plotly_chart(fig, use_container_width=True)


def render_tracking_setup_breakdown(tracker: PortfolioTracker, account_type: str) -> None:
    st.markdown("#### Setup-Kategorien")
    breakdown = tracker.setup_breakdown(account_type)
    if breakdown.empty:
        render_empty_state(
            "Noch keine Setups",
            "Waehle beim Erfassen eines Eintrags eine Setup-Kategorie. Danach siehst du, welche Setups funktionieren.",
        )
        return
    st.dataframe(
        breakdown,
        use_container_width=True,
        hide_index=True,
        column_config={
            "setup_category": "Setup",
            "entries": "Eintraege",
            "closed": "Geschlossen",
            "win_rate": st.column_config.NumberColumn("Trefferquote %", format="%.1f"),
            "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
            "average_pnl": st.column_config.NumberColumn("Ø P/L", format="%.2f"),
        },
    )


def render_tracking_rule_violations(tracker: PortfolioTracker, account_type: str) -> None:
    st.markdown("#### Regelverletzungen")
    violations = tracker.rule_violation_breakdown(account_type)
    if violations.empty:
        render_empty_state(
            "Keine Regelverletzungen erfasst",
            "Gut. Falls du bewusst gegen eine Regel testest, markiere sie beim Speichern des Eintrags.",
        )
        return
    st.dataframe(
        violations,
        use_container_width=True,
        hide_index=True,
        column_config={
            "rule_violation": "Regelverletzung",
            "entries": "Vorkommen",
            "closed": "Geschlossen",
            "realized_pnl": st.column_config.NumberColumn("Realisiert", format="%.2f"),
        },
    )


def render_tracking_entry_form(config: dict, tracker: PortfolioTracker, account_type: str) -> None:
    result = st.session_state.analysis_result
    symbols = tracking_symbols(config)
    timeframes = config["data"].get("timeframes", ["1d", "1wk", "1mo"])
    setup_categories = tracking_setup_categories(config)
    rule_options = tracking_rule_options(config)

    st.markdown("### Neuen Eintrag erfassen")
    col1, col2 = st.columns(2)
    with col1:
        ticker = st.selectbox("Ticker", symbols, key=f"{account_type}_entry_ticker")
    with col2:
        timeframe = st.selectbox(
            "Analyse-Timeframe",
            timeframes,
            key=f"{account_type}_entry_timeframe",
        )

    analysis_row = analysis_row_for_ticker(result, ticker, timeframe)
    default_price = safe_float(analysis_row.get("close"), fallback=1.0)
    render_tracking_analysis_snapshot(analysis_row)

    with st.form(f"{account_type}_entry_form", clear_on_submit=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            direction = st.selectbox(
                "Richtung",
                ["long", "short"],
                format_func=lambda value: value.upper(),
                key=f"{account_type}_direction",
            )
        with col_b:
            quantity = st.number_input(
                "Anzahl",
                min_value=0.0001,
                value=float(config.get("tracking", {}).get("default_quantity", 1.0)),
                step=1.0,
                key=f"{account_type}_quantity",
            )
        with col_c:
            entry_price = st.number_input(
                "Referenzpreis",
                min_value=0.01,
                value=max(default_price, 0.01),
                step=0.01,
                key=f"{account_type}_{ticker}_{timeframe}_entry_price",
            )

        col_d, col_e, col_f = st.columns(3)
        with col_d:
            entry_date = st.date_input(
                "Datum",
                value=pd.Timestamp.today().date(),
                key=f"{account_type}_entry_date",
            )
        with col_e:
            stop_price = st.number_input(
                "Stop-Referenz optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=f"{account_type}_stop_price",
            )
        with col_f:
            target_price = st.number_input(
                "Ziel-Referenz optional",
                min_value=0.0,
                value=0.0,
                step=0.01,
                key=f"{account_type}_target_price",
            )

        col_g, col_h = st.columns(2)
        with col_g:
            setup_category = st.selectbox(
                "Setup-Kategorie",
                setup_categories,
                index=safe_index(setup_categories, "Trendfolge"),
                key=f"{account_type}_setup_category",
            )
        with col_h:
            rule_violations = st.multiselect(
                "Regelverletzungen",
                rule_options,
                key=f"{account_type}_rule_violations",
                help="Nur markieren, wenn der Eintrag bewusst gegen eine harte Regel laeuft.",
            )

        thesis = st.text_area(
            "Notiz / These",
            key=f"{account_type}_thesis",
            placeholder="Warum wird dieser Eintrag beobachtet?",
        )
        submitted = st.form_submit_button("Eintrag speichern", use_container_width=True)
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
                    rule_violations=rule_violations,
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


def render_tracking_close_form(config: dict, tracker: PortfolioTracker, account_type: str) -> None:
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
        key=f"{account_type}_close_select",
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

    with st.form(f"{account_type}_close_form"):
        col1, col2 = st.columns(2)
        with col1:
            exit_price = st.number_input(
                "Schluss-Referenzpreis",
                min_value=0.01,
                value=max(default_exit, 0.01),
                step=0.01,
                key=f"{account_type}_{selected_id}_exit_price",
            )
        with col2:
            exit_date = st.date_input(
                "Schlussdatum",
                value=pd.Timestamp.today().date(),
                key=f"{account_type}_{selected_id}_exit_date",
            )
        exit_note = st.text_area("Schlussnotiz", key=f"{account_type}_{selected_id}_exit_note")
        submitted = st.form_submit_button("Schliessung speichern", use_container_width=True)
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


def render_tracking_history(tracker: PortfolioTracker, account_type: str) -> None:
    st.markdown("### Journal und Daten")
    entries = tracker.enriched_entries(account_type)
    if entries.empty:
        render_empty_state(
            "Noch keine Journal-Eintraege",
            "Erfasse einen Paper- oder Real-Eintrag. Danach misst die App Trefferquote, P/L, Setups und Regelverletzungen.",
        )
        return

    display = build_tracking_display(entries)
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id_short": "ID",
            "status": "Status",
            "ticker": "Ticker",
            "direction": "Richtung",
            "quantity": st.column_config.NumberColumn("Anzahl", format="%.4f"),
            "entry_price": st.column_config.NumberColumn("Einstieg", format="%.2f"),
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
        st.plotly_chart(fig, use_container_width=True)

    csv_data = entries.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Journal CSV herunterladen",
        data=csv_data,
        file_name=f"{account_type}_journal.csv",
        mime="text/csv",
        key=f"{account_type}_download",
        use_container_width=True,
    )
    if st.button(
        "CSV Export in reports/ aktualisieren",
        key=f"{account_type}_export_report",
        use_container_width=True,
    ):
        path = tracker.export_journal(account_type, BASE_DIR / "reports")
        st.success(f"Export aktualisiert: {path.name}")


def render_paper_real_comparison(tracker: PortfolioTracker) -> None:
    with st.expander("Paper vs Real vergleichen", expanded=False):
        comparison = tracker.account_comparison()
        if comparison.empty:
            render_empty_state(
                "Noch kein Vergleich",
                "Sobald Papertrading oder Real Money Eintraege enthalten, zeigt die App hier die Unterschiede.",
            )
            return
        st.dataframe(
            comparison,
            use_container_width=True,
            hide_index=True,
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
        st.plotly_chart(fig, use_container_width=True)


def render_reports(config: dict) -> None:
    st.subheader("Reports")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Analysieren", key="reports_analyze", type="primary", use_container_width=True):
            _run_update(config, generate_reports=True)
    with col2:
        if st.button("Reports aktualisieren", key="reports_refresh", use_container_width=True):
            current = st.session_state.get("analysis_result")
            if current:
                _run_update(config, generate_reports=True)
            else:
                _run_update(config, generate_reports=True)

    report_paths = list_report_files(Path(config.get("reports_dir", "reports")))
    if not report_paths:
        render_empty_state(
            "Noch keine CSV-Reports",
            "Klicke Analysieren. Danach werden market_summary.csv und watchlist.csv erstellt.",
        )
        return

    render_report_previews(config, compact=False)

    st.write("Downloads")
    for path in report_paths:
        data = path.read_bytes()
        mime = "text/csv" if path.suffix == ".csv" else "text/plain"
        st.download_button(
            label=f"Download {path.name}",
            data=data,
            file_name=path.name,
            mime=mime,
            key=f"download-{path.name}",
        )


def render_updates(config: dict, app_env: str) -> None:
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
        if st.button("Backup erstellen", use_container_width=True):
            backup_dir = create_backup(BASE_DIR)
            st.success(f"Backup erstellt: {backup_dir.name}")
    with col2:
        if st.button("Update-Dateien prüfen", use_container_width=True):
            result = inspect_update_files(BASE_DIR)
            st.session_state.update_inspection = result
            if result["ok"]:
                st.success(f"Update-Dateien ok: {len(result['files'])}")
            else:
                st.error("Update-Dateien enthalten Fehler.")

    col3, col4 = st.columns(2)
    with col3:
        if st.button("Update anwenden", use_container_width=True):
            result = apply_code_update(BASE_DIR)
            if result["ok"]:
                st.success(result["message"])
                st.info("Bitte Streamlit neu starten, falls Änderungen nicht sichtbar sind.")
            else:
                st.error(result["message"])
    with col4:
        if st.button("Letztes Backup wiederherstellen", use_container_width=True):
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


def render_settings(app_env: str) -> None:
    st.subheader("Settings")
    config = enforce_security_defaults(load_config(CONFIG_PATH), app_env)
    if not require_sensitive_access(config, "settings"):
        return

    st.write(f"APP_ENV: `{app_env}`")
    render_account_settings(config)
    render_runtime_mode_settings(config)
    render_ports_and_integrations_settings(config)
    if is_cloud_env(app_env):
        st.info("macOS Evening Job ist im Cloud-Modus ausgeblendet.")
    else:
        render_evening_job_settings()

    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    edited = st.text_area(
        "config.json",
        value=config_text,
        height=420,
        key="config_editor",
    )
    if st.button("Config speichern", use_container_width=True):
        try:
            parsed = enforce_security_defaults(json.loads(edited), app_env)
            save_config(parsed, CONFIG_PATH)
            st.success("Config gespeichert. Neue Daten werden erst beim naechsten Klick auf Analysieren geladen.")
        except json.JSONDecodeError as exc:
            st.error(f"config.json ist kein gueltiges JSON: {exc}")
        except Exception as exc:
            logger.exception("Could not save config")
            st.error(f"Config konnte nicht gespeichert werden: {exc}")


def render_account_settings(config: dict) -> None:
    st.markdown("### Account")
    email = st.session_state.get("authenticated_email")
    if not email:
        st.info("Nicht mit E-Mail angemeldet.")
        return

    st.write(f"E-Mail-Identitaet: `{email}`")
    two_factor = config.get("auth", {}).get("two_factor", {})
    st.write(f"Zwei-Faktor-Login aktiv: `{two_factor.get('enabled', True)}`")
    store = AuthStore(BASE_DIR / config.get("auth", {}).get("database_path", "data/auth.duckdb"))
    passkey = store.passkey_status(email)
    st.write(f"Passkey vorbereitet: `{passkey['prepared']}`")
    st.write(f"Aktive Passkeys: `{passkey['enabled_credentials']}`")
    st.caption(passkey["message"])


def require_sensitive_access(config: dict, area: str) -> bool:
    security = config.get("security", {})
    if not security.get("require_password_for_sensitive_settings", True):
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
        key=f"{area}_sensitive_password",
    )
    if st.button("Geschuetzten Bereich entsperren", key=f"{area}_unlock", use_container_width=True):
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


def render_ports_and_integrations_settings(config: dict) -> None:
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

    with st.form("ports_and_integrations_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            streamlit_port = st.number_input(
                "Streamlit Port",
                min_value=1,
                max_value=65535,
                value=int(settings.get("streamlit_port", 8501)),
                step=1,
            )
        with col2:
            local_api_port = st.text_input(
                "Lokaler API-Port optional",
                value=str(settings.get("local_api_port", "")),
                placeholder="z.B. 8000",
            )
        with col3:
            webhook_port = st.text_input(
                "Webhook-Port optional",
                value=str(settings.get("webhook_port", "")),
                placeholder="z.B. 9000",
            )

        st.caption(
            "Port-Aenderungen sind vorbereitet und werden gespeichert. Der Streamlit-"
            "Starter muss danach passend gestartet werden, damit ein neuer Port aktiv ist."
        )

        st.markdown("#### Geschuetzte Seitenlinks")
        links_df = st.data_editor(
            pd.DataFrame(links),
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="protected_links_editor",
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
            use_container_width=True,
            hide_index=True,
            key="protected_apis_editor",
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

        submitted = st.form_submit_button("Ports, Links und APIs speichern", use_container_width=True)
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
    st.info(
        f"APP_ENV: {app_env}. Vorbereiteter Modus: {active}. "
        "Analyse-only: Orders, Broker und echte Ausfuehrung sind deaktiviert."
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

    login_tab, register_tab, confirm_tab, passkey_tab = st.tabs(
        ["Login", "Registrieren", "E-Mail bestaetigen", "Passkey"]
    )

    with login_tab:
        pending_email = st.session_state.get("pending_2fa_email")
        if pending_email:
            render_two_factor_login_step(store, pending_email, rate_limit=rate_limit)
        else:
            email = st.text_input("E-Mail", key="login_email")
            password = st.text_input("Passwort", type="password", key="login_password")
            if st.button("Einloggen", use_container_width=True):
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
            reg_email = st.text_input("E-Mail", key="register_email")
            reg_password = st.text_input("Passwort", type="password", key="register_password")
            reg_password_2 = st.text_input(
                "Passwort wiederholen",
                type="password",
                key="register_password_2",
            )
            if st.button("Registrieren und Code senden", use_container_width=True):
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
        confirm_email = st.text_input("E-Mail", key="confirm_email")
        confirm_code = st.text_input("Bestaetigungscode", key="confirm_code")
        if st.button("E-Mail bestaetigen", use_container_width=True):
            result = store.verify_email(
                confirm_email,
                confirm_code,
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

    code = st.text_input("Zwei-Faktor-Code", key="login_2fa_code")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("2FA bestaetigen", use_container_width=True):
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
        if st.button("Login abbrechen", use_container_width=True):
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
    entered = st.text_input("App-Passwort", type="password", key="app_password_gate_input")
    if st.button("App entsperren", use_container_width=True, key="app_password_gate_button"):
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
    with st.sidebar:
        st.caption(f"Angemeldet als {email}")
        if st.button("Logout", use_container_width=True):
            for key in [
                "authenticated_email",
                "authenticated",
                "app_password_ok",
                "pending_2fa_email",
                "local_2fa_code",
                "sensitive_unlocked",
                "sensitive_unlocked_until",
            ]:
                st.session_state.pop(key, None)
            st.rerun()


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


def render_runtime_mode_settings(config: dict) -> None:
    st.markdown("### Vorbereiteter Modus")
    runtime = config.setdefault("runtime_mode", {})
    available = runtime.get("available", ["papertrading", "real"])
    active = runtime.get("active", "papertrading")
    selected = st.selectbox(
        "Modus auswaehlen",
        available,
        index=available.index(active) if active in available else 0,
        key="runtime_mode_select",
    )
    st.caption(
        "Zwei Schritte: Modus auswaehlen, dann speichern. "
        "Auch Real aktiviert keine Orders und keine Broker-Funktion."
    )
    if st.button("Modus speichern", use_container_width=True):
        runtime["active"] = selected
        runtime["orders_enabled"] = False
        runtime["broker_enabled"] = False
        config["runtime_mode"] = runtime
        save_config(config, CONFIG_PATH)
        st.success(f"Modus gespeichert: {selected}. Analyse-only bleibt aktiv. Keine neue Analyse gestartet.")


def render_evening_job_settings() -> None:
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
        if st.button("Evening Job installieren", use_container_width=True):
            result = run_local_script(BASE_DIR / "install_evening_job.sh")
            if result["ok"]:
                st.success(result["output"])
            else:
                st.error(result["output"])
    with col2:
        if st.button("Evening Job entfernen", use_container_width=True):
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


def analysis_row_for_ticker(result: dict, ticker: str, timeframe: str) -> dict:
    frames = [
        result.get("dashboard", pd.DataFrame()),
        result.get("watchlist", pd.DataFrame()),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return {}

    combined = pd.concat(frames, ignore_index=True)
    combined["ticker_lookup"] = combined["ticker"].astype(str).str.upper()
    ticker_lookup = str(ticker).upper()
    exact = combined[
        (combined["ticker_lookup"] == ticker_lookup) & (combined["timeframe"] == timeframe)
    ]
    if exact.empty:
        exact = combined[combined["ticker_lookup"] == ticker_lookup]
    if exact.empty:
        return {}
    row = exact.iloc[0].drop(labels=["ticker_lookup"], errors="ignore")
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


def render_analysis_table(df: pd.DataFrame) -> None:
    if df.empty:
        render_empty_state(
            "Keine Analysezeilen",
            "Sobald eine Analyse erfolgreich war, erscheinen hier Score, Trend, Risk State und EMAs.",
        )
        return
    display = df[
        [
            "label",
            "ticker",
            "timeframe",
            "trend",
            "score",
            "risk_state",
            "risk_score",
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
        ]
    ].copy()
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "label": "Name",
            "ticker": "Ticker",
            "trend": "Trend",
            "risk_state": "Risk State",
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
        },
    )


def render_score_chart(df: pd.DataFrame, title: str) -> None:
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
    st.plotly_chart(fig, use_container_width=True)
    risk_fig = px.bar(
        df,
        x="label",
        y="risk_score",
        color="risk_state",
        range_y=[0, 100],
        title=f"{title} - Risk Score",
    )
    risk_fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
    st.plotly_chart(risk_fig, use_container_width=True)


def render_relative_strength_chart(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig = px.bar(
        df,
        x="label",
        y="relative_strength",
        title="Relative Staerke gegen QQQ",
    )
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=45, b=10))
    st.plotly_chart(fig, use_container_width=True)


def render_report_previews(config: dict, compact: bool) -> None:
    reports_dir = Path(config.get("reports_dir", "reports"))
    market_path = reports_dir / "market_summary.csv"
    watchlist_path = reports_dir / "watchlist.csv"
    evening_path = reports_dir / "evening_summary.txt"

    if not any(path.exists() for path in [market_path, watchlist_path, evening_path]):
        if not compact:
            render_empty_state(
                "Noch keine Reports",
                "Klicke Analysieren oder Reports aktualisieren. Danach kannst du CSV-Dateien herunterladen.",
            )
        return

    with st.expander("Reports aus letzter Analyse", expanded=not compact):
        if market_path.exists():
            st.markdown("**market_summary.csv**")
            st.dataframe(pd.read_csv(market_path), use_container_width=True, hide_index=True)
        if watchlist_path.exists():
            st.markdown("**watchlist.csv**")
            st.dataframe(pd.read_csv(watchlist_path), use_container_width=True, hide_index=True)
        if evening_path.exists():
            st.markdown("**evening_summary.txt**")
            st.code(evening_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
