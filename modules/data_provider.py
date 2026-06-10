from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:  # pragma: no cover - depends on local environment
    yf = None


logger = logging.getLogger(__name__)


@dataclass
class DataQualityRecord:
    ticker: str
    timeframe: str
    status: str
    source: str
    message: str
    rows: int
    last_clean_date: str
    fetched_at: str
    cache_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class DataProvider:
    def __init__(
        self,
        cache_dir: Union[str, Path] = "data/cache",
        cache_max_age_hours: Optional[dict[str, float]] = None,
        prefer_cache: bool = True,
        secondary_sources: Optional[list[str]] = None,
        alpha_vantage_api_key: Optional[str] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_max_age_hours = cache_max_age_hours or {}
        self.prefer_cache = bool(prefer_cache)
        self.secondary_sources = secondary_sources or ["alpha_vantage"]
        self.alpha_vantage_api_key = alpha_vantage_api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.quality: dict[str, DataQualityRecord] = {}

    def fetch_history(self, ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        cache_path = self.cache_dir / f"{_safe_name(ticker)}_{period}_{interval}.csv"
        if self.prefer_cache and self._cache_is_fresh(cache_path, interval):
            logger.info("Using fresh cached market data for %s %s", ticker, interval)
            data = pd.read_csv(cache_path, parse_dates=["date"])
            data = _normalize_schema(data, ticker)
            data["timeframe"] = interval
            self._set_quality(
                ticker=ticker,
                interval=interval,
                status="cache",
                source=_cache_source(cache_path),
                message=_cache_message(cache_path, "Frischer Cache genutzt."),
                data=data,
                cache_path=cache_path,
            )
            return data

        data = self._download(ticker, period, interval)
        status = "delayed"
        source = "yfinance"
        message = "Verzoegerte Marktdaten ueber yfinance geladen."

        if data.empty and "alpha_vantage" in self.secondary_sources:
            data = self._download_alpha_vantage(ticker, period, interval)
            if not data.empty:
                status = "delayed"
                source = "alpha_vantage"
                message = "Verzoegerte EOD-Marktdaten ueber Alpha Vantage geladen."

        if data.empty and "stooq" in self.secondary_sources:
            data = self._download_stooq(ticker, period, interval)
            if not data.empty:
                status = "delayed"
                source = "stooq"
                message = "Verzoegerte Marktdaten ueber Stooq-Fallback geladen."

        if data.empty and cache_path.exists():
            logger.info("Using cached market data for %s %s", ticker, interval)
            data = pd.read_csv(cache_path, parse_dates=["date"])
            status = "cache"
            source = _cache_source(cache_path)
            message = "Live/Delayed-Download fehlgeschlagen. Letzter Cache wurde genutzt."

        if data.empty:
            logger.warning("Using generated fallback data for %s %s", ticker, interval)
            data = self._fallback_data(ticker, interval)
            status = "fehlerhaft"
            source = "synthetic_fallback"
            message = "Keine echten Marktdaten geladen. Synthetische Fallback-Daten nur fuer UI-Stabilitaet."

        data = _normalize_schema(data, ticker)
        data["timeframe"] = interval
        self._set_quality(
            ticker=ticker,
            interval=interval,
            status=status,
            source=source,
            message=message,
            data=data,
            cache_path=cache_path,
        )
        if status != "fehlerhaft":
            data.to_csv(cache_path, index=False)
            self._write_cache_metadata(cache_path, ticker, interval, status, source, message, data)
        return data

    def quality_for(self, ticker: str, interval: str) -> dict:
        key = _quality_key(ticker, interval)
        record = self.quality.get(key)
        if record is None:
            return DataQualityRecord(
                ticker=ticker,
                timeframe=interval,
                status="fehlerhaft",
                source="unknown",
                message="Keine Datenqualitaets-Metadaten vorhanden.",
                rows=0,
                last_clean_date="",
                fetched_at=datetime.now().isoformat(timespec="seconds"),
            ).to_dict()
        return record.to_dict()

    def quality_frame(self) -> pd.DataFrame:
        return pd.DataFrame([record.to_dict() for record in self.quality.values()])

    def _cache_is_fresh(self, cache_path: Path, interval: str) -> bool:
        if not cache_path.exists():
            return False
        if not cache_path.with_suffix(".json").exists():
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

    def _download_alpha_vantage(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        if not self.alpha_vantage_api_key:
            return pd.DataFrame()
        symbol = _alpha_vantage_symbol(ticker)
        if not symbol:
            return pd.DataFrame()

        try:
            response = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "TIME_SERIES_DAILY_ADJUSTED",
                    "symbol": symbol,
                    "outputsize": "full",
                    "apikey": self.alpha_vantage_api_key,
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.exception("Could not download Alpha Vantage fallback data for %s", ticker)
            return pd.DataFrame()

        series = payload.get("Time Series (Daily)")
        if not isinstance(series, dict):
            message = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
            if message:
                logger.warning("Alpha Vantage returned no usable data for %s: %s", ticker, message)
            return pd.DataFrame()

        rows = []
        for date, values in series.items():
            rows.append(
                {
                    "date": date,
                    "open": values.get("1. open"),
                    "high": values.get("2. high"),
                    "low": values.get("3. low"),
                    "close": values.get("5. adjusted close") or values.get("4. close"),
                    "volume": values.get("6. volume", 0),
                    "ticker": ticker,
                }
            )
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values("date")
        frame = _apply_period_filter(frame, period)
        if interval in {"1wk", "1mo"}:
            frame = _resample_ohlcv(frame, ticker, interval)
        return frame

    def _download_stooq(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        stooq_symbol = _stooq_symbol(ticker)
        if not stooq_symbol:
            return pd.DataFrame()

        url = "https://stooq.com/q/d/l/"
        try:
            response = requests.get(
                url,
                params={"s": stooq_symbol, "i": "d"},
                timeout=8,
                headers={"User-Agent": "Analyse Market Sensei Cut/1.0"},
            )
            response.raise_for_status()
        except Exception:
            logger.exception("Could not download Stooq fallback data for %s", ticker)
            return pd.DataFrame()

        text = response.text.strip()
        if not text or text.lower().startswith("no data"):
            return pd.DataFrame()

        try:
            data = pd.read_csv(StringIO(text))
        except Exception:
            logger.exception("Could not parse Stooq fallback data for %s", ticker)
            return pd.DataFrame()

        if data.empty or "Close" not in data:
            return pd.DataFrame()

        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(data["Date"], errors="coerce"),
                "open": pd.to_numeric(data.get("Open", data.get("Close")), errors="coerce"),
                "high": pd.to_numeric(data.get("High", data.get("Close")), errors="coerce"),
                "low": pd.to_numeric(data.get("Low", data.get("Close")), errors="coerce"),
                "close": pd.to_numeric(data["Close"], errors="coerce"),
                "volume": pd.to_numeric(data.get("Volume", 0), errors="coerce").fillna(0),
                "ticker": ticker,
            }
        ).dropna(subset=["date", "close"])
        frame = _apply_period_filter(frame, period)
        if interval in {"1wk", "1mo"}:
            frame = _resample_ohlcv(frame, ticker, interval)
        return frame

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

    def _set_quality(
        self,
        ticker: str,
        interval: str,
        status: str,
        source: str,
        message: str,
        data: pd.DataFrame,
        cache_path: Optional[Path] = None,
    ) -> None:
        last_clean_date = ""
        if status != "fehlerhaft" and source != "cache_unverified" and not data.empty:
            last_clean_date = str(pd.to_datetime(data["date"]).max().date())
        self.quality[_quality_key(ticker, interval)] = DataQualityRecord(
            ticker=ticker,
            timeframe=interval,
            status=status,
            source=source,
            message=message,
            rows=len(data),
            last_clean_date=last_clean_date,
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            cache_path=str(cache_path or ""),
        )

    def _write_cache_metadata(
        self,
        cache_path: Path,
        ticker: str,
        interval: str,
        status: str,
        source: str,
        message: str,
        data: pd.DataFrame,
    ) -> None:
        metadata = DataQualityRecord(
            ticker=ticker,
            timeframe=interval,
            status=status,
            source=source,
            message=message,
            rows=len(data),
            last_clean_date=str(pd.to_datetime(data["date"]).max().date()) if not data.empty else "",
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            cache_path=str(cache_path),
        )
        metadata_path = cache_path.with_suffix(".json")
        metadata_path.write_text(
            json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
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


def _quality_key(ticker: str, interval: str) -> str:
    return f"{str(ticker).upper()}|{interval}"


def _cache_message(cache_path: Path, default: str) -> str:
    metadata_path = cache_path.with_suffix(".json")
    if not metadata_path.exists():
        return f"{default} Quelle im Cache nicht verifiziert."
    return default


def _cache_source(cache_path: Path) -> str:
    return "cache" if cache_path.with_suffix(".json").exists() else "cache_unverified"


def _alpha_vantage_symbol(ticker: str) -> str:
    cleaned = str(ticker).strip().upper()
    if not cleaned:
        return ""
    if cleaned.startswith("^") or "=" in cleaned or "-USD" in cleaned:
        return ""
    if cleaned.endswith(".US"):
        return cleaned[:-3]
    return cleaned


def _stooq_symbol(ticker: str) -> str:
    cleaned = str(ticker).strip().lower()
    explicit = {
        "^gspc": "^spx",
        "^ndx": "^ndq",
        "^gdaxi": "^dax",
        "^fvx": "",
        "^tnx": "",
        "gc=f": "",
        "dx-y.nyb": "",
        "btc-usd": "",
    }
    if cleaned in explicit:
        return explicit[cleaned]
    if cleaned.endswith("=x") or cleaned.startswith("^"):
        return ""
    if "-" in cleaned:
        return ""
    if "." in cleaned:
        return cleaned
    return f"{cleaned}.us"


def _apply_period_filter(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    latest = pd.to_datetime(frame["date"]).max()
    period_map = {
        "1mo": pd.DateOffset(months=1),
        "3mo": pd.DateOffset(months=3),
        "6mo": pd.DateOffset(months=6),
        "1y": pd.DateOffset(years=1),
        "2y": pd.DateOffset(years=2),
        "5y": pd.DateOffset(years=5),
        "10y": pd.DateOffset(years=10),
        "20y": pd.DateOffset(years=20),
    }
    offset = period_map.get(str(period).lower())
    if offset is None:
        return frame
    cutoff = latest - offset
    return frame[pd.to_datetime(frame["date"]) >= cutoff].copy()


def _resample_ohlcv(frame: pd.DataFrame, ticker: str, interval: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    rule = "W-FRI" if interval == "1wk" else "MS"
    data = frame.sort_values("date").set_index("date")
    resampled = data.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    resampled = resampled.dropna(subset=["close"]).reset_index()
    resampled["ticker"] = ticker
    return resampled


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
