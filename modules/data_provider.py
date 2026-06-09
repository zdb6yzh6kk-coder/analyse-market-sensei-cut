from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover - depends on local environment
    yf = None


logger = logging.getLogger(__name__)


class DataProvider:
    def __init__(
        self,
        cache_dir: Union[str, Path] = "data/cache",
        cache_max_age_hours: Optional[dict[str, float]] = None,
        prefer_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_max_age_hours = cache_max_age_hours or {}
        self.prefer_cache = bool(prefer_cache)

    def fetch_history(self, ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        cache_path = self.cache_dir / f"{_safe_name(ticker)}_{period}_{interval}.csv"
        if self.prefer_cache and self._cache_is_fresh(cache_path, interval):
            logger.info("Using fresh cached market data for %s %s", ticker, interval)
            data = pd.read_csv(cache_path, parse_dates=["date"])
            data = _normalize_schema(data, ticker)
            data["timeframe"] = interval
            return data

        data = self._download(ticker, period, interval)

        if data.empty and cache_path.exists():
            logger.info("Using cached market data for %s %s", ticker, interval)
            data = pd.read_csv(cache_path, parse_dates=["date"])

        if data.empty:
            logger.warning("Using generated fallback data for %s %s", ticker, interval)
            data = self._fallback_data(ticker, interval)

        data = _normalize_schema(data, ticker)
        data["timeframe"] = interval
        data.to_csv(cache_path, index=False)
        return data

    def _cache_is_fresh(self, cache_path: Path, interval: str) -> bool:
        if not cache_path.exists():
            return False
        max_age_hours = _max_age_for_interval(self.cache_max_age_hours, interval)
        if max_age_hours <= 0:
            return False
        modified_at = datetime.fromtimestamp(cache_path.stat().st_mtime)
        return datetime.now() - modified_at <= timedelta(hours=max_age_hours)

    def fetch_many(
        self,
        tickers: list[str],
        period: str = "6mo",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        return {
            ticker: self.fetch_history(ticker, period=period, interval=interval)
            for ticker in tickers
        }

    def _download(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        if yf is None:
            logger.warning("yfinance is not installed")
            return pd.DataFrame()

        try:
            raw = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception:
            logger.exception("Could not download market data for %s", ticker)
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        dates = pd.to_datetime(raw.index)
        try:
            dates = dates.tz_convert(None)
        except TypeError:
            pass

        normalized = pd.DataFrame(
            {
                "date": dates,
                "open": raw.get("Open", raw.get("Close")),
                "high": raw.get("High", raw.get("Close")),
                "low": raw.get("Low", raw.get("Close")),
                "close": raw.get("Close"),
                "volume": raw.get("Volume", 0),
                "ticker": ticker,
            }
        )
        return normalized.dropna(subset=["close"])

    def _fallback_data(self, ticker: str, interval: str) -> pd.DataFrame:
        seed = sum(ord(char) for char in ticker)
        rng = np.random.default_rng(seed)
        periods = _fallback_periods(interval)
        dates = _fallback_dates(interval, periods)
        base = 80 + seed % 220
        drift = rng.normal(0.04, 0.12, periods)
        noise = rng.normal(0, 1.4, periods)
        close = np.maximum(base + np.cumsum(drift + noise), 5)
        open_price = close * (1 + rng.normal(0, 0.004, periods))
        high = np.maximum(open_price, close) * (1 + rng.uniform(0, 0.012, periods))
        low = np.minimum(open_price, close) * (1 - rng.uniform(0, 0.012, periods))
        volume = rng.integers(1_000_000, 25_000_000, periods)
        return pd.DataFrame(
            {
                "date": dates,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "ticker": ticker,
            }
        )


def _normalize_schema(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    frame = data.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    frame["date"] = pd.to_datetime(frame["date"])
    frame["ticker"] = ticker
    for column in ["open", "high", "low", "close", "volume"]:
        if column not in frame:
            frame[column] = frame["close"] if column != "volume" else 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[["date", "ticker", "open", "high", "low", "close", "volume"]].dropna(
        subset=["close"]
    )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)


def _max_age_for_interval(cache_max_age_hours: dict[str, float], interval: str) -> float:
    value = cache_max_age_hours.get(interval, cache_max_age_hours.get("default", 0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fallback_periods(interval: str) -> int:
    if interval == "1mo":
        return 260
    if interval == "1wk":
        return 260
    return 520


def _fallback_dates(interval: str, periods: int) -> pd.DatetimeIndex:
    end = pd.Timestamp.now().normalize()
    if interval == "1mo":
        return pd.date_range(end=end, periods=periods, freq="MS")
    if interval == "1wk":
        return pd.date_range(end=end, periods=periods, freq="W-FRI")
    return pd.bdate_range(end=end, periods=periods)
