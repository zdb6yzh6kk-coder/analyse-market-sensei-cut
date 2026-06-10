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

DEFAULT_MAG7 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]
DEFAULT_SECTOR_MAP = {
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
}


class MarketAnalyzer:
    def __init__(self, config: dict, data_provider: Optional[DataProvider] = None) -> None:
        self.config = config
        data_config = config.get("data", {})
        self.provider = data_provider or DataProvider(
            data_config.get("cache_dir", "data/cache"),
            cache_max_age_hours=data_config.get("cache_max_age_hours", {}),
            prefer_cache=data_config.get("prefer_cache", True),
            secondary_sources=data_config.get("secondary_sources", ["alpha_vantage"]),
            alpha_vantage_api_key=data_config.get("alpha_vantage_api_key"),
        )
        self.scorer = ScoreEngine(config.get("score_model", {}).get("weights", {}))
        self.risk_manager = RiskManager(config)
        self.histories: dict[str, pd.DataFrame] = {}

    def analyze_symbols(self, symbols: list, benchmark_ticker: Optional[str] = None) -> pd.DataFrame:
        data_config = self.config.get("data", {})
        timeframes = data_config.get("timeframes", ["1d", "1wk", "1mo"])
        periods = data_config.get("periods", {})
        parsed_symbols = [_parse_symbol(entry) for entry in symbols]
        market_context = self.market_context(timeframes, [ticker for _, ticker in parsed_symbols])

        rows = []
        for label, ticker in parsed_symbols:
            for timeframe in timeframes:
                period = periods.get(timeframe, "2y")
                history = self._get_history(ticker, period, timeframe)
                data_quality = self.provider.quality_for(ticker, timeframe)
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
                    ticker=ticker,
                    trend=trend,
                    sector_ticker=self.sector_ticker_for(ticker),
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
                        "return_1": round(snapshot["return_1"], 2),
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
                        "mag7_points": score_parts["mag7_points"],
                        "sector_strength_points": score_parts["sector_strength_points"],
                        "ema20_points": score_parts["ema20_points"],
                        "ema50_points": score_parts["ema50_points"],
                        "ema100_points": score_parts["ema100_points"],
                        "ema200_points": score_parts["ema200_points"],
                        "relative_strength_points": score_parts["relative_strength_points"],
                        "trend_following_points": score_parts["trend_following_points"],
                        "score_model": score_parts["score_model"],
                        "sector_ticker": score_parts["sector_ticker"],
                        "sector_trend": score_parts["sector_trend"],
                        "sector_relative_strength": score_parts["sector_relative_strength"],
                        "mag7_bullish_count": score_parts["mag7_bullish_count"],
                        "mag7_bearish_count": score_parts["mag7_bearish_count"],
                        "last_updated": snapshot["last_updated"],
                        "data_status": data_quality.get("status", "fehlerhaft"),
                        "data_source": data_quality.get("source", "unknown"),
                        "data_message": data_quality.get("message", ""),
                        "data_rows": data_quality.get("rows", 0),
                        "last_clean_date": data_quality.get("last_clean_date", ""),
                        "data_fetched_at": data_quality.get("fetched_at", ""),
                        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )

        return pd.DataFrame(rows)

    def market_context(self, timeframes: list[str], symbols: Optional[list[str]] = None) -> dict[str, dict]:
        data_config = self.config.get("data", {})
        periods = data_config.get("periods", {})
        context = {}
        symbols = symbols or []
        for timeframe in timeframes:
            period = periods.get(timeframe, "2y")
            spy = self._get_history("SPY", period, timeframe)
            qqq = self._get_history("QQQ", period, timeframe)
            spy_trend = classify_trend(spy)
            qqq_trend = classify_trend(qqq)
            context[timeframe] = {
                "spy_trend": spy_trend,
                "qqq_trend": qqq_trend,
                "same_direction": spy_trend == qqq_trend,
                "mag7": self.mag7_context(period, timeframe),
                "sector_strength": self.sector_context(symbols, period, timeframe, spy),
            }
        return context

    def mag7_context(self, period: str, timeframe: str) -> dict:
        mag7_symbols = self.config.get("score_model", {}).get("mag7_symbols", DEFAULT_MAG7)
        trends = {}
        for ticker in mag7_symbols:
            history = self._get_history(str(ticker), period, timeframe)
            trends[str(ticker).upper()] = classify_trend(history)
        values = list(trends.values())
        return {
            "trends": trends,
            "total": len(values),
            "bullish_count": values.count("bullish"),
            "bearish_count": values.count("bearish"),
            "neutral_count": values.count("neutral"),
        }

    def sector_context(
        self,
        symbols: list[str],
        period: str,
        timeframe: str,
        spy_history: pd.DataFrame,
    ) -> dict:
        sector_tickers = []
        for ticker in symbols + self.config.get("score_model", {}).get("mag7_symbols", DEFAULT_MAG7):
            sector_ticker = self.sector_ticker_for(str(ticker))
            if sector_ticker and sector_ticker not in sector_tickers:
                sector_tickers.append(sector_ticker)

        sectors = {}
        relative_values = []
        bullish_count = 0
        for sector_ticker in sector_tickers:
            history = self._get_history(sector_ticker, period, timeframe)
            trend = classify_trend(history)
            rel_strength = 0.0 if sector_ticker == "SPY" else relative_strength(history, spy_history)
            sectors[sector_ticker] = {
                "trend": trend,
                "relative_strength": rel_strength,
            }
            relative_values.append(rel_strength)
            bullish_count += 1 if trend == "bullish" else 0

        sectors["average"] = {
            "trend": "bullish" if bullish_count >= max(1, len(sector_tickers) / 2) else "neutral",
            "relative_strength": round(sum(relative_values) / len(relative_values), 2) if relative_values else 0.0,
        }
        return sectors

    def sector_ticker_for(self, ticker: str) -> str:
        mapping = self.config.get("score_model", {}).get("sector_map", DEFAULT_SECTOR_MAP)
        cleaned = str(ticker).strip().upper()
        return str(mapping.get(cleaned, "")).strip().upper()

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
