from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .trading_safety import evaluate_trading_request


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    asset_classes: tuple[str, ...]
    strengths: tuple[str, ...]
    best_for: str
    connection_status: str = "prepared"


DEFAULT_PROVIDERS: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        name="Interactive Brokers",
        asset_classes=("stock", "etf", "index", "future", "option", "forex"),
        strengths=("multi_asset", "global_markets", "professional_routing"),
        best_for="Zentrale Spaeter-Anbindung fuer Aktien, ETFs, Indizes, Futures und Optionen.",
    ),
    ProviderProfile(
        name="Alpaca",
        asset_classes=("stock", "etf", "crypto"),
        strengths=("paper_api", "simple_rest_api", "automation"),
        best_for="Schnelles Paper-/API-Prototyping fuer US-Aktien, ETFs und ausgewaehlte Krypto-Setups.",
    ),
    ProviderProfile(
        name="Tradier",
        asset_classes=("stock", "etf", "option"),
        strengths=("options_workflows", "simple_api"),
        best_for="Options-Workflows und US-Markt-Setups.",
    ),
    ProviderProfile(
        name="Saxo",
        asset_classes=("stock", "etf", "forex", "future", "option"),
        strengths=("multi_asset", "international_markets"),
        best_for="Alternative Multi-Asset-Anbindung neben Interactive Brokers.",
    ),
    ProviderProfile(
        name="Kraken",
        asset_classes=("crypto",),
        strengths=("crypto_spot", "risk_controls"),
        best_for="Krypto-Spot-Setups.",
    ),
    ProviderProfile(
        name="Coinbase Advanced",
        asset_classes=("crypto",),
        strengths=("crypto_spot", "simple_onboarding"),
        best_for="Krypto-Spot-Setups mit breiter Marktverfuegbarkeit.",
    ),
    ProviderProfile(
        name="Binance",
        asset_classes=("crypto",),
        strengths=("crypto_liquidity", "crypto_derivatives"),
        best_for="Krypto-Setups mit hoher Liquiditaet.",
    ),
    ProviderProfile(
        name="IG",
        asset_classes=("index", "forex", "commodity"),
        strengths=("indices", "cfds", "market_coverage"),
        best_for="Index-, Forex- und Rohstoff-Setups, falls CFD-Zugang spaeter bewusst erlaubt wird.",
    ),
)


def infer_asset_class(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "unknown"
    if symbol.startswith("^"):
        return "index"
    if symbol.endswith("-USD") or symbol.endswith("USDT") or symbol in {"BTC", "ETH", "SOL"}:
        return "crypto"
    if "=" in symbol:
        if symbol in {"GC=F", "SI=F", "CL=F"}:
            return "commodity"
        return "future"
    if symbol in {"SPY", "QQQ", "GLD", "IWM", "DIA", "TLT"}:
        return "etf"
    if symbol.replace(".", "").isalpha():
        return "stock"
    return "unknown"


def provider_profiles(config: dict | None = None) -> list[ProviderProfile]:
    config = config or {}
    planning = config.get("broker_planning", {})
    preferred = planning.get("preferred_providers") or []
    profiles = list(DEFAULT_PROVIDERS)
    if not preferred:
        return profiles

    rank = {str(name): index for index, name in enumerate(preferred)}
    return sorted(profiles, key=lambda profile: rank.get(profile.name, len(rank) + 99))


def recommend_providers(ticker: str, config: dict | None = None, limit: int = 3) -> list[ProviderProfile]:
    asset_class = infer_asset_class(ticker)
    matches = [
        profile
        for profile in provider_profiles(config)
        if asset_class in profile.asset_classes
    ]
    if not matches and asset_class == "commodity":
        matches = [
            profile
            for profile in provider_profiles(config)
            if "future" in profile.asset_classes or "commodity" in profile.asset_classes
        ]
    return matches[:limit]


def broker_status(config: dict | None = None) -> dict:
    planning = (config or {}).get("broker_planning", {})
    return {
        "planning_enabled": bool(planning.get("enabled", True)),
        "execution_enabled": False,
        "api_calls_enabled": False,
        "live_connection": False,
        "status": "prepared_only",
        "default_provider": planning.get("default_provider", "Interactive Brokers"),
    }


def execution_plan(ticker: str, account_type: str, config: dict | None = None) -> dict:
    recommendations = recommend_providers(ticker, config)
    preferred = recommendations[0].name if recommendations else "Noch offen"
    asset_class = infer_asset_class(ticker)
    safety = evaluate_trading_request(
        config,
        request={
            "ticker": str(ticker).upper(),
            "account_type": account_type,
            "connection_mode": "sandbox_paper",
            "preview_created": False,
            "daily_loss_checked": False,
            "audit_logged": False,
            "automatic": False,
        },
    )
    return {
        "ticker": str(ticker).upper(),
        "asset_class": asset_class,
        "account_type": account_type,
        "routing_state": "prepared_only",
        "recommended_provider": preferred,
        "execution_enabled": False,
        "api_calls_enabled": False,
        "safety_gate": safety.status,
        "safety_reasons": "; ".join(safety.reasons),
        "safety_note": "Nur Journal/Plan. Keine API-Verbindung und keine Ausfuehrung.",
    }


def provider_matrix(config: dict | None = None) -> pd.DataFrame:
    rows = []
    for profile in provider_profiles(config):
        rows.append(
            {
                "provider": profile.name,
                "asset_classes": ", ".join(profile.asset_classes),
                "strengths": ", ".join(profile.strengths),
                "best_for": profile.best_for,
                "connection_status": profile.connection_status,
                "execution_enabled": False,
            }
        )
    return pd.DataFrame(rows)


def covered_asset_classes(profiles: Iterable[ProviderProfile] | None = None) -> list[str]:
    seen = []
    for profile in profiles or DEFAULT_PROVIDERS:
        for asset_class in profile.asset_classes:
            if asset_class not in seen:
                seen.append(asset_class)
    return seen
