from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

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
        sector_rotation: Optional[pd.DataFrame] = None,
    ) -> list[Path]:
        market_path = self.reports_dir / "market_summary.csv"
        watchlist_path = self.reports_dir / "watchlist.csv"
        sector_rotation_path = self.reports_dir / "sector_rotation.csv"
        evening_path = self.reports_dir / "evening_summary.txt"

        market_summary.to_csv(market_path, index=False)
        watchlist.to_csv(watchlist_path, index=False)
        report_paths = [market_path, watchlist_path]
        if sector_rotation is not None and not sector_rotation.empty:
            sector_rotation.to_csv(sector_rotation_path, index=False)
            report_paths.append(sector_rotation_path)
        evening_path.write_text(
            build_evening_summary(
                market_summary,
                watchlist,
                updated_at,
                runtime_mode,
                sector_rotation=sector_rotation,
            ),
            encoding="utf-8",
        )
        report_paths.append(evening_path)
        return report_paths


def build_evening_summary(
    market_summary: pd.DataFrame,
    watchlist: pd.DataFrame,
    updated_at: str,
    runtime_mode: str,
    sector_rotation: Optional[pd.DataFrame] = None,
) -> str:
    daily_market = market_summary[market_summary["timeframe"] == "1d"].copy()
    daily_watchlist = watchlist[watchlist["timeframe"] == "1d"].copy()
    top_watchlist = daily_watchlist.sort_values("score", ascending=False).head(3)
    daily_sectors = pd.DataFrame()
    if sector_rotation is not None and not sector_rotation.empty:
        daily_sectors = sector_rotation[sector_rotation["timeframe"] == "1d"].copy()
        if "relative_strength" in daily_sectors:
            daily_sectors["relative_strength_numeric"] = pd.to_numeric(
                daily_sectors["relative_strength"],
                errors="coerce",
            ).fillna(0)

    lines = [
        "Analyse Market Sensei Cut - Evening Summary",
        f"Letzte Aktualisierung: {updated_at}",
        f"Vorbereiteter Modus: {runtime_mode}",
        "Hinweis: Keine Orders, kein Trading, keine Broker-Funktion.",
        "Risk Management: harte Regeln, keine Gefuehlsentscheidungen.",
    ]
    lines.extend(["", *build_data_quality_lines(market_summary, watchlist, sector_rotation)])
    lines.extend(["", "Marktueberblick 1d:"])
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

    if not daily_sectors.empty:
        top_sectors = daily_sectors.sort_values(
            ["relative_strength_numeric", "score"],
            ascending=False,
        ).head(5)
        weak_sectors = daily_sectors.sort_values(
            ["relative_strength_numeric", "score"],
            ascending=True,
        ).head(3)
        lines.extend(["", "Sektorrotation 1d - Staerke gegen SPY:"])
        for _, row in top_sectors.iterrows():
            lines.append(
                f"- {row['label']} ({row['ticker']}): RS {row['relative_strength']:.2f}, "
                f"Score {int(row['score'])}/100, Trend {row['trend']}"
            )
        lines.extend(["", "Sektorrotation 1d - Schwach:"])
        for _, row in weak_sectors.iterrows():
            lines.append(
                f"- {row['label']} ({row['ticker']}): RS {row['relative_strength']:.2f}, "
                f"Score {int(row['score'])}/100, Trend {row['trend']}"
            )

    return "\n".join(lines) + "\n"


def build_data_quality_lines(
    market_summary: pd.DataFrame,
    watchlist: pd.DataFrame,
    sector_rotation: Optional[pd.DataFrame] = None,
) -> list[str]:
    frames = [market_summary, watchlist]
    if sector_rotation is not None and not sector_rotation.empty:
        frames.append(sector_rotation)
    valid_frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not valid_frames:
        return ["Datenqualitaet:", "- Keine Analyse-Daten vorhanden."]
    combined = pd.concat(valid_frames, ignore_index=True)
    if "data_status" not in combined:
        return ["Datenqualitaet:", "- Keine Datenqualitaets-Metadaten vorhanden."]

    daily = combined[combined["timeframe"] == "1d"].copy() if "timeframe" in combined else combined.copy()
    if daily.empty:
        daily = combined.copy()
    daily["data_status"] = daily["data_status"].fillna("unbekannt").astype(str).str.lower()
    counts = daily["data_status"].value_counts().to_dict()
    clean_dates = pd.to_datetime(
        daily["last_clean_date"] if "last_clean_date" in daily else pd.Series(dtype=str),
        errors="coerce",
    ).dropna()
    last_clean = clean_dates.max().date().isoformat() if not clean_dates.empty else "nicht verfuegbar"
    lines = [
        "Datenqualitaet:",
        f"- Status 1d: live {int(counts.get('live', 0))}, delayed {int(counts.get('delayed', 0))}, cache {int(counts.get('cache', 0))}, fehlerhaft {int(counts.get('fehlerhaft', 0))}",
        f"- Letzter sauberer Datenstand: {last_clean}",
    ]
    issues = daily[daily["data_status"].isin(["cache", "fehlerhaft", "unbekannt"])]
    if issues.empty:
        lines.append("- Keine Datenqualitaets-Warnungen.")
    else:
        for _, row in issues.head(10).iterrows():
            message = row.get("data_message", "")
            lines.append(
                f"- {row.get('ticker', 'n/a')}: {row.get('data_status', 'unbekannt')} "
                f"via {row.get('data_source', 'unknown')} - {message}"
            )
    return lines


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
        path / "sector_rotation.csv",
        path / "market_regime_report.csv",
        path / "regime_history.csv",
        path / "regime_strategy_map.csv",
        path / "papertrading_journal.csv",
        path / "real_money_journal.csv",
        path / "evening_summary.txt",
    ]
    return [report for report in fixed if report.exists()]
