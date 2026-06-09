from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd


class ReportGenerator:
    def __init__(self, reports_dir: Union[str, Path] = "reports") -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_reports(
        self,
        market_summary: pd.DataFrame,
        watchlist: pd.DataFrame,
        updated_at: str,
        runtime_mode: str,
    ) -> list[Path]:
        market_path = self.reports_dir / "market_summary.csv"
        watchlist_path = self.reports_dir / "watchlist.csv"
        evening_path = self.reports_dir / "evening_summary.txt"

        market_summary.to_csv(market_path, index=False)
        watchlist.to_csv(watchlist_path, index=False)
        evening_path.write_text(
            build_evening_summary(market_summary, watchlist, updated_at, runtime_mode),
            encoding="utf-8",
        )
        return [market_path, watchlist_path, evening_path]


def build_evening_summary(
    market_summary: pd.DataFrame,
    watchlist: pd.DataFrame,
    updated_at: str,
    runtime_mode: str,
) -> str:
    daily_market = market_summary[market_summary["timeframe"] == "1d"].copy()
    daily_watchlist = watchlist[watchlist["timeframe"] == "1d"].copy()
    top_watchlist = daily_watchlist.sort_values("score", ascending=False).head(3)

    lines = [
        "Analyse Market Sensei Cut - Evening Summary",
        f"Letzte Aktualisierung: {updated_at}",
        f"Vorbereiteter Modus: {runtime_mode}",
        "Hinweis: Keine Orders, kein Trading, keine Broker-Funktion.",
        "Risk Management: harte Regeln, keine Gefuehlsentscheidungen.",
        "",
        "Marktueberblick 1d:",
    ]
    for _, row in daily_market.iterrows():
        lines.append(
            f"- {row['label']} ({row['ticker']}): {row['trend']}, Score {int(row['score'])}/100, Risk {row['risk_state']} ({int(row['risk_score'])}/100)"
        )

    lines.extend(["", "Top Watchlist 1d:"])
    for _, row in top_watchlist.iterrows():
        lines.append(
            f"- {row['ticker']}: {row['trend']}, Score {int(row['score'])}/100, Risk {row['risk_state']}, MaxRisk {row['max_risk_pct']:.2f}%, RS {row['relative_strength']:.2f}"
        )

    blocked = daily_watchlist[daily_watchlist["risk_state"] == "BLOCKED"]
    lines.extend(["", "BLOCKED 1d:"])
    if blocked.empty:
        lines.append("- Keine BLOCKED-Symbole.")
    else:
        for _, row in blocked.iterrows():
            lines.append(f"- {row['ticker']}: {row['risk_rule_hits']}")

    if top_watchlist.empty:
        lines.append("- Keine Watchlist-Daten verfuegbar.")

    return "\n".join(lines) + "\n"


def list_csv_reports(reports_dir: Union[str, Path] = "reports") -> list[Path]:
    path = Path(reports_dir)
    path.mkdir(parents=True, exist_ok=True)
    return sorted(path.glob("*.csv"), reverse=True)


def list_report_files(reports_dir: Union[str, Path] = "reports") -> list[Path]:
    path = Path(reports_dir)
    path.mkdir(parents=True, exist_ok=True)
    fixed = [
        path / "market_summary.csv",
        path / "watchlist.csv",
        path / "papertrading_journal.csv",
        path / "real_money_journal.csv",
        path / "evening_summary.txt",
    ]
    return [report for report in fixed if report.exists()]
