from __future__ import annotations

import logging
from pathlib import Path
from typing import Union
from uuid import uuid4

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)


class MarketDatabase:
    def __init__(self, path: Union[str, Path] = "data/market.duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_prices (
                    date TIMESTAMP,
                    ticker VARCHAR,
                    timeframe VARCHAR,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    updated_at TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_results (
                    run_id VARCHAR,
                    created_at TIMESTAMP,
                    group_name VARCHAR,
                    label VARCHAR,
                    ticker VARCHAR,
                    timeframe VARCHAR,
                    trend VARCHAR,
                    score INTEGER,
                    close DOUBLE,
                    ema_20 DOUBLE,
                    ema_50 DOUBLE,
                    ema_100 DOUBLE,
                    ema_200 DOUBLE,
                    return_1 DOUBLE,
                    return_5 DOUBLE,
                    return_20 DOUBLE,
                    relative_strength DOUBLE,
                    risk_state VARCHAR,
                    risk_score INTEGER,
                    max_risk_pct DOUBLE,
                    max_position_pct DOUBLE,
                    technical_stop_distance_pct DOUBLE,
                    portfolio_daily_loss_limit_pct DOUBLE,
                    portfolio_weekly_loss_limit_pct DOUBLE,
                    max_correlation_group_pct DOUBLE,
                    risk_rule_hits VARCHAR,
                    spy_trend_points INTEGER,
                    qqq_trend_points INTEGER,
                    market_alignment_points INTEGER,
                    mag7_points INTEGER,
                    sector_strength_points INTEGER,
                    ema20_points INTEGER,
                    ema50_points INTEGER,
                    ema100_points INTEGER,
                    ema200_points INTEGER,
                    relative_strength_points INTEGER,
                    trend_following_points INTEGER,
                    score_model VARCHAR,
                    sector_ticker VARCHAR,
                    sector_trend VARCHAR,
                    sector_relative_strength DOUBLE,
                    mag7_bullish_count INTEGER,
                    mag7_bearish_count INTEGER,
                    last_updated VARCHAR,
                    data_status VARCHAR,
                    data_source VARCHAR,
                    data_message VARCHAR,
                    data_rows INTEGER,
                    last_clean_date VARCHAR,
                    data_fetched_at VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    path VARCHAR,
                    kind VARCHAR,
                    row_count INTEGER,
                    created_at TIMESTAMP
                )
                """
            )
            self._ensure_column(con, "market_prices", "timeframe", "VARCHAR")
            for column, column_type in {
                "timeframe": "VARCHAR",
                "ema_20": "DOUBLE",
                "ema_50": "DOUBLE",
                "ema_100": "DOUBLE",
                "ema_200": "DOUBLE",
                "return_1": "DOUBLE",
                "return_5": "DOUBLE",
                "return_20": "DOUBLE",
                "spy_trend_points": "INTEGER",
                "qqq_trend_points": "INTEGER",
                "market_alignment_points": "INTEGER",
                "mag7_points": "INTEGER",
                "sector_strength_points": "INTEGER",
                "ema20_points": "INTEGER",
                "ema50_points": "INTEGER",
                "ema100_points": "INTEGER",
                "ema200_points": "INTEGER",
                "relative_strength_points": "INTEGER",
                "trend_following_points": "INTEGER",
                "score_model": "VARCHAR",
                "sector_ticker": "VARCHAR",
                "sector_trend": "VARCHAR",
                "sector_relative_strength": "DOUBLE",
                "mag7_bullish_count": "INTEGER",
                "mag7_bearish_count": "INTEGER",
                "risk_state": "VARCHAR",
                "risk_score": "INTEGER",
                "max_risk_pct": "DOUBLE",
                "max_position_pct": "DOUBLE",
                "technical_stop_distance_pct": "DOUBLE",
                "portfolio_daily_loss_limit_pct": "DOUBLE",
                "portfolio_weekly_loss_limit_pct": "DOUBLE",
                "max_correlation_group_pct": "DOUBLE",
                "risk_rule_hits": "VARCHAR",
                "data_status": "VARCHAR",
                "data_source": "VARCHAR",
                "data_message": "VARCHAR",
                "data_rows": "INTEGER",
                "last_clean_date": "VARCHAR",
                "data_fetched_at": "VARCHAR",
            }.items():
                self._ensure_column(con, "analysis_results", column, column_type)
        finally:
            con.close()

    def save_prices(self, histories: dict[str, pd.DataFrame]) -> None:
        con = duckdb.connect(str(self.path))
        try:
            for _, frame in histories.items():
                if frame.empty:
                    continue
                data = frame[
                    ["date", "ticker", "timeframe", "open", "high", "low", "close", "volume"]
                ].copy()
                ticker = str(data["ticker"].iloc[0])
                timeframe = str(data["timeframe"].iloc[0])
                min_date = data["date"].min()
                max_date = data["date"].max()
                con.execute(
                    """
                    DELETE FROM market_prices
                    WHERE ticker = ? AND timeframe = ? AND date BETWEEN ? AND ?
                    """,
                    [ticker, timeframe, min_date, max_date],
                )
                con.register("price_df", data)
                con.execute(
                    """
                    INSERT INTO market_prices (
                        date, ticker, timeframe, open, high, low, close, volume, updated_at
                    )
                    SELECT date, ticker, timeframe, open, high, low, close, volume, current_timestamp
                    FROM price_df
                    """
                )
                con.unregister("price_df")
        finally:
            con.close()

    def save_analysis(self, group_name: str, analysis: pd.DataFrame) -> str:
        run_id = str(uuid4())
        if analysis.empty:
            return run_id

        data = analysis.copy()
        data.insert(0, "group_name", group_name)
        data.insert(0, "created_at", pd.Timestamp.utcnow().to_pydatetime())
        data.insert(0, "run_id", run_id)

        columns = [
            "run_id",
            "created_at",
            "group_name",
            "label",
            "ticker",
            "timeframe",
            "trend",
            "score",
            "close",
            "ema_20",
            "ema_50",
            "ema_100",
            "ema_200",
            "return_1",
            "return_5",
            "return_20",
            "relative_strength",
            "risk_state",
            "risk_score",
            "max_risk_pct",
            "max_position_pct",
            "technical_stop_distance_pct",
            "portfolio_daily_loss_limit_pct",
            "portfolio_weekly_loss_limit_pct",
            "max_correlation_group_pct",
            "risk_rule_hits",
            "spy_trend_points",
            "qqq_trend_points",
            "market_alignment_points",
            "mag7_points",
            "sector_strength_points",
            "ema20_points",
            "ema50_points",
            "ema100_points",
            "ema200_points",
            "relative_strength_points",
            "trend_following_points",
            "score_model",
            "sector_ticker",
            "sector_trend",
            "sector_relative_strength",
            "mag7_bullish_count",
            "mag7_bearish_count",
            "last_updated",
            "data_status",
            "data_source",
            "data_message",
            "data_rows",
            "last_clean_date",
            "data_fetched_at",
        ]
        for column in columns:
            if column not in data:
                data[column] = None
        con = duckdb.connect(str(self.path))
        try:
            con.register("analysis_df", data[columns])
            con.execute(
                f"INSERT INTO analysis_results ({', '.join(columns)}) SELECT * FROM analysis_df"
            )
            con.unregister("analysis_df")
        finally:
            con.close()
        return run_id

    def record_report(self, path: Path, kind: str, row_count: int) -> None:
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                "INSERT INTO reports VALUES (?, ?, ?, current_timestamp)",
                [str(path), kind, row_count],
            )
        finally:
            con.close()

    def _ensure_column(self, con, table: str, column: str, column_type: str) -> None:
        existing = {
            row[1]
            for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
        if column not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
