from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)

ACCOUNT_TYPES = {"papertrading", "real_money"}
DIRECTION_MULTIPLIER = {"long": 1, "short": -1}


class PortfolioTracker:
    def __init__(self, path: Union[str, Path] = "data/portfolio_tracker.duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_entries (
                    id VARCHAR PRIMARY KEY,
                    account_type VARCHAR,
                    ticker VARCHAR,
                    direction VARCHAR,
                    quantity DOUBLE,
                    entry_price DOUBLE,
                    entry_date DATE,
                    stop_price DOUBLE,
                    target_price DOUBLE,
                    timeframe VARCHAR,
                    thesis VARCHAR,
                    status VARCHAR,
                    exit_price DOUBLE,
                    exit_date DATE,
                    exit_note VARCHAR,
                    score_at_entry INTEGER,
                    trend_at_entry VARCHAR,
                    risk_state_at_entry VARCHAR,
                    risk_score_at_entry INTEGER,
                    max_risk_pct DOUBLE,
                    relative_strength DOUBLE,
                    setup_category VARCHAR,
                    rule_violations VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
            _ensure_columns(
                con,
                "portfolio_entries",
                {
                    "setup_category": "VARCHAR",
                    "rule_violations": "VARCHAR",
                },
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id VARCHAR PRIMARY KEY,
                    account_type VARCHAR,
                    entry_id VARCHAR,
                    analysis_updated_at VARCHAR,
                    created_at TIMESTAMP,
                    ticker VARCHAR,
                    direction VARCHAR,
                    quantity DOUBLE,
                    entry_price DOUBLE,
                    last_price DOUBLE,
                    market_value DOUBLE,
                    unrealized_pnl DOUBLE,
                    unrealized_pnl_pct DOUBLE,
                    score INTEGER,
                    trend VARCHAR,
                    risk_state VARCHAR,
                    risk_score INTEGER
                )
                """
            )
        finally:
            con.close()

    def add_entry(
        self,
        account_type: str,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        entry_date: date,
        timeframe: str,
        thesis: str = "",
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        setup_category: str = "",
        rule_violations: Optional[list[str]] = None,
        analysis_row: Optional[dict] = None,
    ) -> str:
        account_type = _validate_account_type(account_type)
        direction = _validate_direction(direction)
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("Ticker fehlt.")
        if quantity <= 0:
            raise ValueError("Anzahl muss groesser als 0 sein.")
        if entry_price <= 0:
            raise ValueError("Referenzpreis muss groesser als 0 sein.")

        row = analysis_row or {}
        entry_id = str(uuid4())
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                INSERT INTO portfolio_entries (
                    id, account_type, ticker, direction, quantity, entry_price,
                    entry_date, stop_price, target_price, timeframe, thesis,
                    status, exit_price, exit_date, exit_note, score_at_entry,
                    trend_at_entry, risk_state_at_entry, risk_score_at_entry,
                    max_risk_pct, relative_strength, setup_category,
                    rule_violations, created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'open', NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?,
                    current_timestamp, current_timestamp
                )
                """,
                [
                    entry_id,
                    account_type,
                    ticker,
                    direction,
                    float(quantity),
                    float(entry_price),
                    entry_date,
                    _positive_or_none(stop_price),
                    _positive_or_none(target_price),
                    timeframe,
                    thesis.strip(),
                    _int_or_none(row.get("score")),
                    _text_or_none(row.get("trend")),
                    _text_or_none(row.get("risk_state")),
                    _int_or_none(row.get("risk_score")),
                    _float_or_none(row.get("max_risk_pct")),
                    _float_or_none(row.get("relative_strength")),
                    setup_category.strip() or "Nicht klassifiziert",
                    _join_rule_violations(rule_violations),
                ],
            )
        finally:
            con.close()
        return entry_id

    def close_entry(
        self,
        entry_id: str,
        exit_price: float,
        exit_date: date,
        exit_note: str = "",
    ) -> None:
        if exit_price <= 0:
            raise ValueError("Schlusspreis muss groesser als 0 sein.")

        con = duckdb.connect(str(self.path))
        try:
            existing = con.execute(
                "SELECT COUNT(*) FROM portfolio_entries WHERE id = ? AND status = 'open'",
                [entry_id],
            ).fetchone()[0]
            if existing == 0:
                raise ValueError("Offener Eintrag wurde nicht gefunden.")
            con.execute(
                """
                UPDATE portfolio_entries
                SET status = 'closed',
                    exit_price = ?,
                    exit_date = ?,
                    exit_note = ?,
                    updated_at = current_timestamp
                WHERE id = ? AND status = 'open'
                """,
                [float(exit_price), exit_date, exit_note.strip(), entry_id],
            )
        finally:
            con.close()

    def list_entries(self, account_type: str, include_closed: bool = True) -> pd.DataFrame:
        account_type = _validate_account_type(account_type)
        status_clause = "" if include_closed else "AND status = 'open'"
        con = duckdb.connect(str(self.path))
        try:
            df = con.execute(
                f"""
                SELECT *
                FROM portfolio_entries
                WHERE account_type = ?
                {status_clause}
                ORDER BY created_at DESC
                """,
                [account_type],
            ).df()
        finally:
            con.close()
        return _add_realized_pnl(df)

    def record_snapshots(
        self,
        account_type: str,
        analysis_result: dict,
        analysis_updated_at: str,
    ) -> pd.DataFrame:
        account_type = _validate_account_type(account_type)
        open_entries = self.list_entries(account_type, include_closed=False)
        if open_entries.empty:
            return pd.DataFrame()

        lookup = _analysis_lookup(analysis_result)
        rows = []
        for _, entry in open_entries.iterrows():
            ticker = entry["ticker"]
            current = lookup.get(ticker, {})
            last_price = _float_or_none(current.get("close")) or float(entry["entry_price"])
            quantity = float(entry["quantity"])
            entry_price = float(entry["entry_price"])
            direction = entry["direction"]
            multiplier = DIRECTION_MULTIPLIER.get(direction, 1)
            entry_value = quantity * entry_price
            market_value = quantity * last_price
            pnl = (last_price - entry_price) * quantity * multiplier
            pnl_pct = (pnl / entry_value * 100) if entry_value else 0.0
            rows.append(
                {
                    "id": str(uuid4()),
                    "account_type": account_type,
                    "entry_id": entry["id"],
                    "analysis_updated_at": analysis_updated_at,
                    "created_at": datetime.now(),
                    "ticker": ticker,
                    "direction": direction,
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "last_price": last_price,
                    "market_value": market_value,
                    "unrealized_pnl": pnl,
                    "unrealized_pnl_pct": pnl_pct,
                    "score": _int_or_none(current.get("score")),
                    "trend": _text_or_none(current.get("trend")),
                    "risk_state": _text_or_none(current.get("risk_state")),
                    "risk_score": _int_or_none(current.get("risk_score")),
                }
            )

        snapshots = pd.DataFrame(rows)
        con = duckdb.connect(str(self.path))
        try:
            con.execute(
                """
                DELETE FROM portfolio_snapshots
                WHERE account_type = ? AND analysis_updated_at = ?
                """,
                [account_type, analysis_updated_at],
            )
            con.register("snapshot_df", snapshots)
            con.execute(
                """
                INSERT INTO portfolio_snapshots
                SELECT * FROM snapshot_df
                """
            )
            con.unregister("snapshot_df")
        finally:
            con.close()
        return snapshots

    def latest_snapshots(self, account_type: str) -> pd.DataFrame:
        account_type = _validate_account_type(account_type)
        con = duckdb.connect(str(self.path))
        try:
            latest = con.execute(
                """
                SELECT MAX(analysis_updated_at)
                FROM portfolio_snapshots
                WHERE account_type = ?
                """,
                [account_type],
            ).fetchone()[0]
            if latest is None:
                return pd.DataFrame()
            return con.execute(
                """
                SELECT *
                FROM portfolio_snapshots
                WHERE account_type = ? AND analysis_updated_at = ?
                ORDER BY ticker
                """,
                [account_type, latest],
            ).df()
        finally:
            con.close()

    def snapshot_history(self, account_type: str) -> pd.DataFrame:
        account_type = _validate_account_type(account_type)
        con = duckdb.connect(str(self.path))
        try:
            return con.execute(
                """
                SELECT *
                FROM portfolio_snapshots
                WHERE account_type = ?
                ORDER BY analysis_updated_at, ticker
                """,
                [account_type],
            ).df()
        finally:
            con.close()

    def enriched_entries(self, account_type: str) -> pd.DataFrame:
        entries = self.list_entries(account_type, include_closed=True)
        if entries.empty:
            return entries

        snapshots = self.latest_snapshots(account_type)
        if snapshots.empty:
            for column in [
                "last_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "snapshot_score",
                "snapshot_trend",
                "snapshot_risk_state",
                "snapshot_risk_score",
            ]:
                entries[column] = pd.NA
            return entries

        latest = snapshots.drop(columns=["id"], errors="ignore").rename(
            columns={
                "entry_id": "id",
                "score": "snapshot_score",
                "trend": "snapshot_trend",
                "risk_state": "snapshot_risk_state",
                "risk_score": "snapshot_risk_score",
            }
        )
        keep = [
            "id",
            "last_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "snapshot_score",
            "snapshot_trend",
            "snapshot_risk_state",
            "snapshot_risk_score",
        ]
        return entries.merge(latest[keep], on="id", how="left")

    def summary(self, account_type: str) -> dict:
        entries = self.enriched_entries(account_type)
        if entries.empty:
            return {
                "open_count": 0,
                "closed_count": 0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "win_rate": 0.0,
                "average_win": 0.0,
                "average_loss": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "rule_violation_count": 0,
            }

        open_entries = entries[entries["status"] == "open"].copy()
        closed_entries = entries[entries["status"] == "closed"].copy()
        market_value = _sum_numeric(open_entries, "market_value")
        if market_value == 0:
            market_value = _sum_numeric(open_entries, "entry_value")
        realized = _sum_numeric(closed_entries, "realized_pnl")
        unrealized = _sum_numeric(open_entries, "unrealized_pnl")
        win_rate = 0.0
        average_win = 0.0
        average_loss = 0.0
        profit_factor = 0.0
        if not closed_entries.empty:
            pnl = pd.to_numeric(closed_entries["realized_pnl"], errors="coerce").fillna(0)
            wins = (pnl > 0).sum()
            losses = pnl[pnl < 0]
            gains = pnl[pnl > 0]
            win_rate = float(wins / len(closed_entries) * 100)
            average_win = float(gains.mean()) if not gains.empty else 0.0
            average_loss = float(losses.mean()) if not losses.empty else 0.0
            loss_sum = abs(float(losses.sum()))
            profit_factor = float(gains.sum() / loss_sum) if loss_sum else float(gains.sum() > 0)
        equity = self.equity_curve(account_type)
        max_drawdown = float(equity["drawdown"].min()) if not equity.empty else 0.0
        return {
            "open_count": int(len(open_entries)),
            "closed_count": int(len(closed_entries)),
            "market_value": float(market_value),
            "unrealized_pnl": float(unrealized),
            "realized_pnl": float(realized),
            "win_rate": win_rate,
            "average_win": average_win,
            "average_loss": average_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "rule_violation_count": int(_rule_violation_count(entries)),
        }

    def equity_curve(self, account_type: str) -> pd.DataFrame:
        account_type = _validate_account_type(account_type)
        entries = self.list_entries(account_type, include_closed=True)
        closed = entries[entries["status"] == "closed"].copy() if not entries.empty else entries
        rows = []
        if not closed.empty:
            closed["curve_date"] = pd.to_datetime(closed["exit_date"]).fillna(
                pd.to_datetime(closed["updated_at"])
            )
            closed["realized_pnl"] = pd.to_numeric(closed["realized_pnl"], errors="coerce").fillna(0)
            closed = closed.sort_values(["curve_date", "updated_at"])
            running = 0.0
            for _, row in closed.iterrows():
                running += float(row["realized_pnl"])
                rows.append(
                    {
                        "date": row["curve_date"],
                        "ticker": row["ticker"],
                        "equity": running,
                        "realized_pnl": float(row["realized_pnl"]),
                        "source": "closed_trade",
                    }
                )

        if not rows:
            history = self.snapshot_history(account_type)
            if not history.empty:
                grouped = (
                    history.groupby("analysis_updated_at", as_index=False)
                    .agg({"unrealized_pnl": "sum"})
                    .sort_values("analysis_updated_at")
                )
                rows = [
                    {
                        "date": pd.to_datetime(row["analysis_updated_at"]),
                        "ticker": "open_entries",
                        "equity": float(row["unrealized_pnl"]),
                        "realized_pnl": 0.0,
                        "source": "open_snapshot",
                    }
                    for _, row in grouped.iterrows()
                ]

        curve = pd.DataFrame(rows)
        if curve.empty:
            return curve
        curve["peak"] = curve["equity"].cummax()
        curve["drawdown"] = curve["equity"] - curve["peak"]
        curve["drawdown_pct"] = 0.0
        non_zero_peak = curve["peak"].abs() > 0
        curve.loc[non_zero_peak, "drawdown_pct"] = (
            curve.loc[non_zero_peak, "drawdown"] / curve.loc[non_zero_peak, "peak"].abs() * 100
        )
        return curve

    def setup_breakdown(self, account_type: str) -> pd.DataFrame:
        entries = self.enriched_entries(account_type)
        if entries.empty:
            return pd.DataFrame()
        frame = entries.copy()
        if "setup_category" not in frame.columns:
            frame["setup_category"] = "Nicht klassifiziert"
        frame["setup_category"] = frame["setup_category"].fillna("Nicht klassifiziert")
        if "realized_pnl" not in frame.columns:
            frame["realized_pnl"] = 0.0
        frame["realized_pnl"] = pd.to_numeric(frame["realized_pnl"], errors="coerce").fillna(0)
        closed = frame[frame["status"] == "closed"].copy()
        if closed.empty:
            grouped = frame.groupby("setup_category", as_index=False).agg({"id": "count"})
            grouped = grouped.rename(columns={"id": "entries"})
            grouped["closed"] = 0
            grouped["win_rate"] = 0.0
            grouped["realized_pnl"] = 0.0
            grouped["average_pnl"] = 0.0
            return grouped

        grouped = (
            closed.groupby("setup_category", as_index=False)
            .agg(
                entries=("id", "count"),
                realized_pnl=("realized_pnl", "sum"),
                average_pnl=("realized_pnl", "mean"),
            )
            .sort_values("realized_pnl", ascending=False)
        )
        wins = (
            closed.assign(win=closed["realized_pnl"] > 0)
            .groupby("setup_category", as_index=False)
            .agg(wins=("win", "sum"), closed=("id", "count"))
        )
        grouped = grouped.merge(wins, on="setup_category", how="left")
        grouped["win_rate"] = grouped["wins"] / grouped["closed"] * 100
        return grouped.drop(columns=["wins"])

    def rule_violation_breakdown(self, account_type: str) -> pd.DataFrame:
        entries = self.enriched_entries(account_type)
        if entries.empty or "rule_violations" not in entries:
            return pd.DataFrame()

        rows = []
        for _, entry in entries.iterrows():
            for violation in _split_rule_violations(entry.get("rule_violations")):
                rows.append(
                    {
                        "rule_violation": violation,
                        "ticker": entry.get("ticker"),
                        "status": entry.get("status"),
                        "realized_pnl": _float_or_zero(entry.get("realized_pnl")),
                    }
                )
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        return (
            frame.groupby("rule_violation", as_index=False)
            .agg(
                entries=("ticker", "count"),
                closed=("status", lambda values: int((values == "closed").sum())),
                realized_pnl=("realized_pnl", "sum"),
            )
            .sort_values(["entries", "realized_pnl"], ascending=[False, True])
        )

    def account_comparison(self) -> pd.DataFrame:
        rows = []
        for account_type in sorted(ACCOUNT_TYPES):
            summary = self.summary(account_type)
            rows.append(
                {
                    "account_type": account_type,
                    "open_count": summary["open_count"],
                    "closed_count": summary["closed_count"],
                    "win_rate": summary["win_rate"],
                    "average_win": summary["average_win"],
                    "average_loss": summary["average_loss"],
                    "realized_pnl": summary["realized_pnl"],
                    "unrealized_pnl": summary["unrealized_pnl"],
                    "max_drawdown": summary["max_drawdown"],
                    "rule_violation_count": summary["rule_violation_count"],
                }
            )
        return pd.DataFrame(rows)

    def export_journal(self, account_type: str, reports_dir: Union[str, Path]) -> Path:
        account_type = _validate_account_type(account_type)
        reports_path = Path(reports_dir)
        reports_path.mkdir(parents=True, exist_ok=True)
        filename = "papertrading_journal.csv" if account_type == "papertrading" else "real_money_journal.csv"
        path = reports_path / filename
        self.enriched_entries(account_type).to_csv(path, index=False)
        return path


def _validate_account_type(account_type: str) -> str:
    if account_type not in ACCOUNT_TYPES:
        raise ValueError(f"Unbekanntes Konto: {account_type}")
    return account_type


def _validate_direction(direction: str) -> str:
    direction = direction.lower().strip()
    if direction not in DIRECTION_MULTIPLIER:
        raise ValueError("Richtung muss long oder short sein.")
    return direction


def _positive_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return value if value > 0 else None


def _float_or_none(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _int_or_none(value) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _text_or_none(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _analysis_lookup(analysis_result: dict) -> dict[str, dict]:
    frames = [
        analysis_result.get("dashboard", pd.DataFrame()),
        analysis_result.get("watchlist", pd.DataFrame()),
    ]
    combined = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    if combined.empty:
        return {}
    daily = combined[combined["timeframe"] == "1d"].copy()
    if daily.empty:
        daily = combined.copy()
    lookup = {}
    for _, row in daily.iterrows():
        lookup[str(row["ticker"]).upper()] = row.to_dict()
    return lookup


def _add_realized_pnl(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    result = df.copy()
    multiplier = result["direction"].map(DIRECTION_MULTIPLIER).fillna(1)
    result["entry_value"] = result["quantity"] * result["entry_price"]
    result["realized_pnl"] = pd.NA
    closed = result["status"] == "closed"
    result.loc[closed, "realized_pnl"] = (
        (result.loc[closed, "exit_price"] - result.loc[closed, "entry_price"])
        * result.loc[closed, "quantity"]
        * multiplier.loc[closed]
    )
    return result


def _sum_numeric(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _ensure_columns(con: duckdb.DuckDBPyConnection, table: str, columns: dict[str, str]) -> None:
    existing = {
        str(row[1])
        for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
    }
    for column, column_type in columns.items():
        if column not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _join_rule_violations(rule_violations: Optional[list[str]]) -> str:
    if not rule_violations:
        return ""
    cleaned = []
    for violation in rule_violations:
        text = str(violation).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return "; ".join(cleaned)


def _split_rule_violations(value) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _rule_violation_count(entries: pd.DataFrame) -> int:
    if entries.empty or "rule_violations" not in entries:
        return 0
    return sum(len(_split_rule_violations(value)) for value in entries["rule_violations"])


def _float_or_zero(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
