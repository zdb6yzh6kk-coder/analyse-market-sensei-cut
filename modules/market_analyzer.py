from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from .data_provider import DataProvider
from .indicators import add_indicators, classify_trend, latest_snapshot, relative_strength
from .risk_management import RiskManager
from .score_engine import ScoreEngine


logger = logging.getLogger(__name__)


class MarketAnalyzer:
    def __init__(self, config: dict, data_provider: Optional[DataProvider] = None) -> None:
        self.config = config
        data_config = config.get("data", {})
        self.provider = data_provider or DataProvider(
            data_config.get("cache_dir", "data/cache"),
            cache_max_age_hours=data_config.get("cache_max_age_hours", {}),
            prefer_cache=data_config.get("prefer_cache", True),
        )
        self.scorer = ScoreEngine()
        self.risk_manager = RiskManager(config)
        self.histories: dict[str, pd.DataFrame] = {}

    def analyze_symbols(self, symbols: list, benchmark_ticker: Optional[str] = None) -> pd.DataFrame:
        data_config = self.config.get("data", {})
        timeframes = data_config.get("timeframes", ["1d", "1wk", "1mo"])
        periods = data_config.get("periods", {})
        market_context = self.market_context(timeframes)

        rows = []
        for entry in symbols:
            label, ticker = _parse_symbol(entry)
            for timeframe in timeframes:
                period = periods.get(timeframe, "2y")
                history = self._get_history(ticker, period, timeframe)
                trend = classify_trend(history)
                snapshot = latest_snapshot(history)
                benchmark_data = self._get_history(benchmark_ticker, period, timeframe) if benchmark_ticker else None
                rel_strength = 0.0
                if benchmark_data is not None and ticker != benchmark_ticker:
                    rel_strength = relative_strength(history, benchmark_data)

                score_parts = self.scorer.score(
                    snapshot=snapshot,
                    market_context=market_context.get(timeframe, {}),
                    relative_strength=rel_strength,
                )
                base_row = {
                    "trend": trend,
                    "score": score_parts["score"],
                    "close": round(snapshot["close"], 2),
                    "ema_20": round(snapshot["ema_20"], 2),
                    "ema_50": round(snapshot["ema_50"], 2),
                    "ema_100": round(snapshot["ema_100"], 2),
                    "ema_200": round(snapshot["ema_200"], 2),
                    "relative_strength": rel_strength,
                }
                risk = self.risk_manager.evaluate(
                    base_row,
                    market_context.get(timeframe, {}),
                )

                rows.append(
                    {
                        "label": label,
                        "ticker": ticker,
                        "timeframe": timeframe,
                        "trend": trend,
                        "score": score_parts["score"],
                        "close": round(snapshot["close"], 2),
                        "ema_20": round(snapshot["ema_20"], 2),
                        "ema_50": round(snapshot["ema_50"], 2),
                        "ema_100": round(snapshot["ema_100"], 2),
                        "ema_200": round(snapshot["ema_200"], 2),
                        "return_5": round(snapshot["return_5"], 2),
                        "return_20": round(snapshot["return_20"], 2),
                        "relative_strength": rel_strength,
                        "risk_state": risk["risk_state"],
                        "risk_score": risk["risk_score"],
                        "max_risk_pct": risk["max_risk_pct"],
                        "max_position_pct": risk["max_position_pct"],
                        "technical_stop_distance_pct": risk["technical_stop_distance_pct"],
                        "portfolio_daily_loss_limit_pct": risk["portfolio_daily_loss_limit_pct"],
                        "portfolio_weekly_loss_limit_pct": risk["portfolio_weekly_loss_limit_pct"],
                        "max_correlation_group_pct": risk["max_correlation_group_pct"],
                        "risk_rule_hits": risk["risk_rule_hits"],
                        "spy_trend_points": score_parts["spy_trend_points"],
                        "qqq_trend_points": score_parts["qqq_trend_points"],
                        "market_alignment_points": score_parts["market_alignment_points"],
                        "ema20_points": score_parts["ema20_points"],
                        "ema50_points": score_parts["ema50_points"],
                        "ema100_points": score_parts["ema100_points"],
                        "ema200_points": score_parts["ema200_points"],
                        "relative_strength_points": score_parts["relative_strength_points"],
                        "last_updated": snapshot["last_updated"],
                        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )

        return pd.DataFrame(rows)

    def market_context(self, timeframes: list[str]) -> dict[str, dict]:
        data_config = self.config.get("data", {})
        periods = data_config.get("periods", {})
        context = {}
        for timeframe in timeframes:
            period = periods.get(timeframe, "2y")
            spy = self._get_history("SPY", period, timeframe)
            qqq = self._get_history("QQQ", period, timeframe)
            context[timeframe] = {
                "spy_trend": classify_trend(spy),
                "qqq_trend": classify_trend(qqq),
                "same_direction": classify_trend(spy) == classify_trend(qqq),
            }
        return context

    def _get_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        key = f"{ticker}|{interval}"
        if key in self.histories:
            return self.histories[key]
        raw = self.provider.fetch_history(ticker, period=period, interval=interval)
        history = add_indicators(raw)
        history["timeframe"] = interval
        self.histories[key] = history
        return history


def _parse_symbol(entry) -> tuple[str, str]:
    if isinstance(entry, dict):
        return entry.get("label", entry["ticker"]), entry["ticker"]
    return str(entry), str(entry)
