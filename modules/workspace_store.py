from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

import duckdb
import pandas as pd


DEFAULT_CATEGORIES = ["Markt", "Watchlist", "Paper", "Real", "Research"]
DEFAULT_WATCHLIST_CATEGORIES = ["Indizes", "Aktien", "Gold", "Krypto", "Eigene Ideen"]


class WorkspaceStore:
    def __init__(self, path: Union[str, Path] = "data/workspace.duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_topics (
                    id VARCHAR PRIMARY KEY,
                    email VARCHAR,
                    name VARCHAR NOT NULL,
                    ticker VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    note VARCHAR,
                    pinned BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    last_opened_at TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_events (
                    id VARCHAR PRIMARY KEY,
                    email VARCHAR,
                    event_type VARCHAR NOT NULL,
                    ticker VARCHAR,
                    timeframe VARCHAR,
                    detail VARCHAR,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_watchlists (
                    id VARCHAR PRIMARY KEY,
                    email VARCHAR,
                    name VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    pinned BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_watchlist_symbols (
                    id VARCHAR PRIMARY KEY,
                    watchlist_id VARCHAR NOT NULL,
                    email VARCHAR,
                    ticker VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    note VARCHAR,
                    pinned BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS chart_lines (
                    id VARCHAR PRIMARY KEY,
                    email VARCHAR,
                    ticker VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    start_date TIMESTAMP NOT NULL,
                    start_price DOUBLE NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    end_price DOUBLE NOT NULL,
                    color VARCHAR NOT NULL,
                    note VARCHAR,
                    pinned BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        finally:
            con.close()

    def ensure_default_watchlists(
        self,
        email: str,
        categories: Optional[list[str]] = None,
    ) -> None:
        normalized_email = self._email(email)
        if not self.list_watchlists(normalized_email).empty:
            return
        for category in categories or DEFAULT_WATCHLIST_CATEGORIES:
            self.save_watchlist(
                email=normalized_email,
                name=category,
                category=category,
                pinned=category in ["Indizes", "Aktien", "Eigene Ideen"],
            )

    def save_watchlist(
        self,
        email: str,
        name: str,
        category: str,
        pinned: bool = True,
        watchlist_id: Optional[str] = None,
    ) -> str:
        normalized_email = self._email(email)
        cleaned_name = name.strip()
        cleaned_category = category.strip() or "Eigene Ideen"
        if not cleaned_name:
            raise ValueError("Watchlist-Name fehlt.")

        now = datetime.now()
        con = duckdb.connect(str(self.path))
        try:
            if watchlist_id:
                con.execute(
                    """
                    UPDATE custom_watchlists
                    SET name = ?,
                        category = ?,
                        pinned = ?,
                        updated_at = ?
                    WHERE id = ? AND email = ?
                    """,
                    [
                        cleaned_name,
                        cleaned_category,
                        bool(pinned),
                        now,
                        watchlist_id,
                        normalized_email,
                    ],
                )
                return watchlist_id

            watchlist_id = str(uuid4())
            con.execute(
                """
                INSERT INTO custom_watchlists VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    watchlist_id,
                    normalized_email,
                    cleaned_name,
                    cleaned_category,
                    bool(pinned),
                    now,
                    now,
                ],
            )
        finally:
            con.close()
        return watchlist_id

    def list_watchlists(self, email: str) -> pd.DataFrame:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                """
                SELECT
                    w.*,
                    COUNT(s.id) AS symbol_count
                FROM custom_watchlists w
                LEFT JOIN custom_watchlist_symbols s
                    ON s.watchlist_id = w.id AND s.email = w.email
                WHERE w.email = ?
                GROUP BY
                    w.id, w.email, w.name, w.category, w.pinned,
                    w.created_at, w.updated_at
                ORDER BY w.pinned DESC, w.updated_at DESC, w.name ASC
                """,
                [normalized_email],
            ).df()
        finally:
            con.close()

    def delete_watchlist(self, email: str, watchlist_id: str) -> None:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                "DELETE FROM custom_watchlist_symbols WHERE watchlist_id = ? AND email = ?",
                [watchlist_id, normalized_email],
            )
            con.execute(
                "DELETE FROM custom_watchlists WHERE id = ? AND email = ?",
                [watchlist_id, normalized_email],
            )
        finally:
            con.close()

    def add_watchlist_symbol(
        self,
        email: str,
        watchlist_id: str,
        ticker: str,
        category: str,
        note: str = "",
        pinned: bool = False,
    ) -> str:
        normalized_email = self._email(email)
        cleaned_ticker = ticker.strip().upper()
        cleaned_category = category.strip() or "Eigene Ideen"
        if not cleaned_ticker:
            raise ValueError("Ticker fehlt.")

        now = datetime.now()
        con = duckdb.connect(str(self.path))
        try:
            existing = con.execute(
                """
                SELECT id
                FROM custom_watchlist_symbols
                WHERE email = ? AND watchlist_id = ? AND ticker = ?
                LIMIT 1
                """,
                [normalized_email, watchlist_id, cleaned_ticker],
            ).fetchone()
            if existing:
                symbol_id = existing[0]
                con.execute(
                    """
                    UPDATE custom_watchlist_symbols
                    SET category = ?,
                        note = ?,
                        pinned = ?,
                        updated_at = ?
                    WHERE id = ? AND email = ?
                    """,
                    [
                        cleaned_category,
                        note.strip(),
                        bool(pinned),
                        now,
                        symbol_id,
                        normalized_email,
                    ],
                )
                return symbol_id

            symbol_id = str(uuid4())
            con.execute(
                """
                INSERT INTO custom_watchlist_symbols
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    symbol_id,
                    watchlist_id,
                    normalized_email,
                    cleaned_ticker,
                    cleaned_category,
                    note.strip(),
                    bool(pinned),
                    now,
                    now,
                ],
            )
        finally:
            con.close()
        return symbol_id

    def list_watchlist_symbols(
        self,
        email: str,
        watchlist_id: Optional[str] = None,
    ) -> pd.DataFrame:
        normalized_email = self._email(email)
        watchlist_clause = "AND s.watchlist_id = ?" if watchlist_id else ""
        params = [normalized_email]
        if watchlist_id:
            params.append(watchlist_id)

        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                f"""
                SELECT
                    s.*,
                    w.name AS watchlist_name,
                    w.category AS watchlist_category,
                    w.pinned AS watchlist_pinned
                FROM custom_watchlist_symbols s
                LEFT JOIN custom_watchlists w
                    ON w.id = s.watchlist_id AND w.email = s.email
                WHERE s.email = ?
                {watchlist_clause}
                ORDER BY s.pinned DESC, s.updated_at DESC, s.ticker ASC
                """,
                params,
            ).df()
        finally:
            con.close()

    def delete_watchlist_symbol(self, email: str, symbol_id: str) -> None:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                "DELETE FROM custom_watchlist_symbols WHERE id = ? AND email = ?",
                [symbol_id, normalized_email],
            )
        finally:
            con.close()

    def save_chart_line(
        self,
        email: str,
        ticker: str,
        timeframe: str,
        name: str,
        start_date,
        start_price: float,
        end_date,
        end_price: float,
        color: str = "#ff2bd6",
        note: str = "",
        pinned: bool = True,
    ) -> str:
        normalized_email = self._email(email)
        cleaned_ticker = ticker.strip().upper()
        cleaned_timeframe = timeframe.strip()
        cleaned_name = name.strip() or f"{cleaned_ticker} Linie"
        if not cleaned_ticker:
            raise ValueError("Ticker fehlt.")
        if float(start_price) <= 0 or float(end_price) <= 0:
            raise ValueError("Preise muessen groesser als 0 sein.")

        now = datetime.now()
        line_id = str(uuid4())
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                INSERT INTO chart_lines
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    line_id,
                    normalized_email,
                    cleaned_ticker,
                    cleaned_timeframe,
                    cleaned_name,
                    pd.Timestamp(start_date).to_pydatetime(),
                    float(start_price),
                    pd.Timestamp(end_date).to_pydatetime(),
                    float(end_price),
                    color.strip() or "#ff2bd6",
                    note.strip(),
                    bool(pinned),
                    now,
                    now,
                ],
            )
        finally:
            con.close()
        return line_id

    def list_chart_lines(self, email: str, ticker: str, timeframe: str) -> pd.DataFrame:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                """
                SELECT *
                FROM chart_lines
                WHERE email = ?
                    AND ticker = ?
                    AND timeframe = ?
                ORDER BY pinned DESC, updated_at DESC, created_at DESC
                """,
                [normalized_email, ticker.strip().upper(), timeframe.strip()],
            ).df()
        finally:
            con.close()

    def delete_chart_line(self, email: str, line_id: str) -> None:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                "DELETE FROM chart_lines WHERE id = ? AND email = ?",
                [line_id, normalized_email],
            )
        finally:
            con.close()

    def save_topic(
        self,
        email: str,
        name: str,
        ticker: str,
        timeframe: str,
        category: str,
        note: str = "",
        pinned: bool = True,
        topic_id: Optional[str] = None,
    ) -> str:
        normalized_email = self._email(email)
        cleaned_name = name.strip() or f"{ticker.upper()} {timeframe}"
        cleaned_ticker = ticker.strip().upper()
        cleaned_timeframe = timeframe.strip()
        cleaned_category = category.strip() or "Research"
        now = datetime.now()
        if not cleaned_ticker:
            raise ValueError("Ticker fehlt.")

        con = duckdb.connect(str(self.path))
        try:
            if topic_id:
                con.execute(
                    """
                    UPDATE saved_topics
                    SET name = ?,
                        ticker = ?,
                        timeframe = ?,
                        category = ?,
                        note = ?,
                        pinned = ?,
                        updated_at = ?
                    WHERE id = ? AND email = ?
                    """,
                    [
                        cleaned_name,
                        cleaned_ticker,
                        cleaned_timeframe,
                        cleaned_category,
                        note.strip(),
                        bool(pinned),
                        now,
                        topic_id,
                        normalized_email,
                    ],
                )
                return topic_id

            topic_id = str(uuid4())
            con.execute(
                """
                INSERT INTO saved_topics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                [
                    topic_id,
                    normalized_email,
                    cleaned_name,
                    cleaned_ticker,
                    cleaned_timeframe,
                    cleaned_category,
                    note.strip(),
                    bool(pinned),
                    now,
                    now,
                ],
            )
        finally:
            con.close()
        return topic_id

    def list_topics(self, email: str, pinned_only: bool = False) -> pd.DataFrame:
        normalized_email = self._email(email)
        pinned_clause = "AND pinned = true" if pinned_only else ""
        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                f"""
                SELECT *
                FROM saved_topics
                WHERE email = ?
                {pinned_clause}
                ORDER BY pinned DESC, COALESCE(last_opened_at, updated_at) DESC, updated_at DESC
                """,
                [normalized_email],
            ).df()
        finally:
            con.close()

    def delete_topic(self, email: str, topic_id: str) -> None:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                "DELETE FROM saved_topics WHERE id = ? AND email = ?",
                [topic_id, normalized_email],
            )
        finally:
            con.close()

    def mark_opened(self, email: str, topic_id: str) -> None:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                UPDATE saved_topics
                SET last_opened_at = ?, updated_at = ?
                WHERE id = ? AND email = ?
                """,
                [datetime.now(), datetime.now(), topic_id, normalized_email],
            )
        finally:
            con.close()

    def record_event(
        self,
        email: str,
        event_type: str,
        ticker: str = "",
        timeframe: str = "",
        detail: str = "",
    ) -> str:
        normalized_email = self._email(email)
        event_id = str(uuid4())
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                INSERT INTO workspace_events VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    event_id,
                    normalized_email,
                    event_type.strip(),
                    ticker.strip().upper(),
                    timeframe.strip(),
                    detail.strip(),
                    datetime.now(),
                ],
            )
        finally:
            con.close()
        return event_id

    def recent_events(self, email: str, limit: int = 30) -> pd.DataFrame:
        normalized_email = self._email(email)
        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                """
                SELECT *
                FROM workspace_events
                WHERE email = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [normalized_email, int(limit)],
            ).df()
        finally:
            con.close()

    @staticmethod
    def _email(email: str) -> str:
        return (email or "local").strip().lower()
