from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd


TIMEFRAME_LABELS = {
    "1mo": "Monthly",
    "1wk": "Weekly",
    "1d": "Daily",
}

REGIME_LABELS = [
    "Bullischer Trendmarkt",
    "Baerischer Trendmarkt",
    "Seitwaertsmarkt",
    "Hohe Volatilitaet",
    "Niedrige Volatilitaet",
    "Risk-On Markt",
    "Risk-Off Markt",
    "Gold-Staerke",
    "Sektor-Rotation",
]

REGIME_SCORE_COLUMNS = {
    "Bullischer Trendmarkt": "Bullish Trend Score",
    "Baerischer Trendmarkt": "Bearish Trend Score",
    "Seitwaertsmarkt": "Sideways Score",
    "Hohe Volatilitaet": "High Volatility Score",
    "Niedrige Volatilitaet": "Low Volatility Score",
    "Risk-On Markt": "Risk-On Score",
    "Risk-Off Markt": "Risk-Off Score",
    "Gold-Staerke": "Gold Strength Score",
    "Sektor-Rotation": "Sector Rotation Score",
}

STRATEGY_MAP = [
    {
        "Regime": "Bullischer Trendmarkt",
        "Strategy Type": "Trendfolge; Pullbacks; Breakouts",
        "Description": "Trendfolgende und relative Pullback-Analysen passen besser, wenn SPY und QQQ oberhalb zentraler EMAs laufen.",
    },
    {
        "Regime": "Baerischer Trendmarkt",
        "Strategy Type": "Short Trendfolge; Defensive Werte; Kapitalerhalt",
        "Description": "Defensive Analyse und Kapitalerhalt stehen im Vordergrund, wenn breite Marktindizes unter wichtigen EMAs liegen.",
    },
    {
        "Regime": "Seitwaertsmarkt",
        "Strategy Type": "Mean Reversion; Range Trading",
        "Description": "Range- und Mean-Reversion-Analysen sind besser passend, wenn Trend und Volatilitaet keine klare Richtung zeigen.",
    },
    {
        "Regime": "Hohe Volatilitaet",
        "Strategy Type": "Positionsgroesse reduzieren; Risiko-Filter; keine aggressiven Breakouts",
        "Description": "Bei hoher ATR und hoher realisierter Volatilitaet bekommen Risiko-Filter mehr Gewicht als aggressive Breakout-Analysen.",
    },
    {
        "Regime": "Niedrige Volatilitaet",
        "Strategy Type": "Breakout-Vorbereitung; Volatility Expansion Watch",
        "Description": "Niedrige Volatilitaet spricht fuer Beobachtung von Volatilitaetsausweitungen, ohne daraus ein Handelssignal abzuleiten.",
    },
    {
        "Regime": "Risk-On Markt",
        "Strategy Type": "QQQ; Mag7; staerkste Sektoren; Relative-Staerke-Strategien",
        "Description": "Relative Staerke und Trendfolge sind in Risk-On-Umfeldern oft sinnvoller als reine Mean-Reversion-Analysen.",
    },
    {
        "Regime": "Risk-Off Markt",
        "Strategy Type": "GLD; defensive Sektoren; Cash/Defensive Analyse",
        "Description": "Defensive und Absicherungsanalysen stehen im Vordergrund, wenn QQQ schwaecher als SPY ist und defensive Assets fuehren.",
    },
    {
        "Regime": "Gold-Staerke",
        "Strategy Type": "Gold-Strategien; GLD Relative-Staerke-Analyse",
        "Description": "GLD wird relativ wichtiger, wenn Gold SPY und QQQ outperformt und oberhalb zentraler EMAs liegt.",
    },
    {
        "Regime": "Sektor-Rotation",
        "Strategy Type": "staerkster Sektor; Relative-Staerke-Ranking; Rotation-Monitoring",
        "Description": "Sektor-Rankings und Fuehrungswechsel werden wichtiger, wenn einzelne Sektoren deutlich vom breiten Markt abweichen.",
    },
]

GROWTH_SECTORS = {"QQQ", "XLK", "XLY", "XLC", "SMH"}
DEFENSIVE_SECTORS = {"XLP", "XLV", "XLU", "GLD", "SHY", "IEF"}
CORE_TICKERS = {"SPY", "QQQ", "GLD", "^GSPC", "^NDX", "GC=F", "^GDAXI", "IWM"}


class MarketRegimeEngine:
    def __init__(self, config: dict, analysis_result: dict) -> None:
        self.config = config
        self.result = analysis_result or {}
        self.histories = self.result.get("histories", {}) or {}

    def evaluate(self) -> dict:
        ranking_frames: dict[str, pd.DataFrame] = {}
        contexts: dict[str, dict] = {}
        report_rows = []
        history_rows = []
        issues: list[str] = []

        for interval, label in TIMEFRAME_LABELS.items():
            context = self._context_for(interval)
            contexts[label] = context
            if context["missing_required"]:
                issues.append(
                    f"{label}: Fehlende Kernhistorien: {', '.join(context['missing_required'])}"
                )
                continue

            scores, reasons = self._score_regimes(context)
            ranking = pd.DataFrame(
                [
                    {
                        "Regime": regime,
                        "Score": int(round(score)),
                        "Strategy Type": strategy_for_regime(regime),
                        "Description": description_for_regime(regime),
                    }
                    for regime, score in scores.items()
                ]
            ).sort_values("Score", ascending=False, ignore_index=True)
            active_regime = str(ranking.iloc[0]["Regime"])
            confidence = int(ranking.iloc[0]["Score"])
            ranking_frames[label] = ranking

            report_rows.append(
                {
                    "Datum": context["date"],
                    "Timeframe": label,
                    "Active Regime": active_regime,
                    "Confidence Score": confidence,
                    "SPY Status": context["spy_status"],
                    "QQQ Status": context["qqq_status"],
                    "GLD Status": context["gld_status"],
                    "Volatility Status": context["volatility_status"],
                    "Strongest Sector": context["strongest_sector"],
                    "Recommended Strategy": strategy_for_regime(active_regime),
                    "Explanation": explanation_for_regime(active_regime, context, reasons.get(active_regime, [])),
                }
            )

            history_row = {
                "Datum": context["date"],
                "Timeframe": label,
                "Active Regime": active_regime,
            }
            for regime, column in REGIME_SCORE_COLUMNS.items():
                history_row[column] = int(round(scores.get(regime, 0)))
            history_rows.append(history_row)

        summary = pd.DataFrame(report_rows)
        history = pd.DataFrame(history_rows)
        return {
            "summary": summary,
            "history": history,
            "rankings": ranking_frames,
            "contexts": contexts,
            "strategy_map": strategy_map_frame(),
            "issues": issues,
        }

    def _context_for(self, interval: str) -> dict:
        spy = self._metrics_for("SPY", interval)
        qqq = self._metrics_for("QQQ", interval)
        gld = self._metrics_for("GLD", interval)
        dax = self._metrics_for(self._dax_ticker(), interval)

        missing_required = [
            ticker
            for ticker, metrics in [("SPY", spy), ("QQQ", qqq), ("GLD", gld)]
            if not metrics["ok"]
        ]
        mag7 = [self._metrics_for(ticker, interval) for ticker in self._mag7()]
        sectors = [self._metrics_for(ticker, interval, label=label) for label, ticker in self._sector_symbols()]
        sectors = [row for row in sectors if row["ok"]]
        spy_return = spy["return_20"] if spy["ok"] else 0.0
        for metrics in [qqq, gld, dax]:
            if metrics["ok"]:
                metrics["relative_strength_spy"] = metrics["return_20"] - spy_return
        for sector in sectors:
            sector["relative_strength_spy"] = sector["return_20"] - spy_return

        growth_strength = _mean([sector["relative_strength_spy"] for sector in sectors if sector["ticker"] in GROWTH_SECTORS])
        defensive_strength = _mean(
            [sector["relative_strength_spy"] for sector in sectors if sector["ticker"] in DEFENSIVE_SECTORS]
        )
        sector_spread = 0.0
        strongest_sector = "nicht verfuegbar"
        strongest_sector_ticker = ""
        if sectors:
            sectors_sorted = sorted(sectors, key=lambda item: item["relative_strength_spy"], reverse=True)
            strongest = sectors_sorted[0]
            weakest = sectors_sorted[-1]
            strongest_sector = f"{strongest['label']} ({strongest['ticker']})"
            strongest_sector_ticker = strongest["ticker"]
            sector_spread = strongest["relative_strength_spy"] - weakest["relative_strength_spy"]

        volatility_average = _mean([spy["atr_ratio"], qqq["atr_ratio"]])
        realized_vol_ratio = _mean([spy["volatility_ratio"], qqq["volatility_ratio"]])
        volatility_status = "Normal"
        if volatility_average >= 1.2 or realized_vol_ratio >= 1.2:
            volatility_status = "Hoch"
        elif 0 < volatility_average <= 0.85 and 0 < realized_vol_ratio <= 0.9:
            volatility_status = "Niedrig"

        mag7_bullish = len([row for row in mag7 if row["trend"] == "bullish"])
        mag7_loaded = len([row for row in mag7 if row["ok"]])
        market_date = latest_common_date([spy, qqq, gld])
        return {
            "date": market_date or datetime.now().date().isoformat(),
            "interval": interval,
            "spy": spy,
            "qqq": qqq,
            "gld": gld,
            "dax": dax,
            "mag7": mag7,
            "sectors": sectors,
            "missing_required": missing_required,
            "spy_status": status_text(spy),
            "qqq_status": status_text(qqq),
            "gld_status": status_text(gld),
            "dax_status": status_text(dax),
            "volatility_status": volatility_status,
            "volatility_average": volatility_average,
            "realized_vol_ratio": realized_vol_ratio,
            "growth_strength": growth_strength,
            "defensive_strength": defensive_strength,
            "mag7_bullish": mag7_bullish,
            "mag7_loaded": mag7_loaded,
            "strongest_sector": strongest_sector,
            "strongest_sector_ticker": strongest_sector_ticker,
            "sector_spread": sector_spread,
            "sector_leadership_changed": sector_leadership_changed(sectors),
        }

    def _score_regimes(self, context: dict) -> tuple[dict[str, float], dict[str, list[str]]]:
        spy = context["spy"]
        qqq = context["qqq"]
        gld = context["gld"]
        sectors = context["sectors"]
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}

        scores["Bullischer Trendmarkt"], reasons["Bullischer Trendmarkt"] = score_bullish_trend(spy, qqq)
        scores["Baerischer Trendmarkt"], reasons["Baerischer Trendmarkt"] = score_bearish_trend(spy, qqq)
        scores["Seitwaertsmarkt"], reasons["Seitwaertsmarkt"] = score_sideways(spy, qqq)
        scores["Hohe Volatilitaet"], reasons["Hohe Volatilitaet"] = score_high_volatility(context)
        scores["Niedrige Volatilitaet"], reasons["Niedrige Volatilitaet"] = score_low_volatility(context)
        scores["Risk-On Markt"], reasons["Risk-On Markt"] = score_risk_on(context)
        scores["Risk-Off Markt"], reasons["Risk-Off Markt"] = score_risk_off(context)
        scores["Gold-Staerke"], reasons["Gold-Staerke"] = score_gold_strength(gld, spy, qqq)
        scores["Sektor-Rotation"], reasons["Sektor-Rotation"] = score_sector_rotation(context, sectors)
        return {key: clamp_score(value) for key, value in scores.items()}, reasons

    def _metrics_for(self, ticker: str, interval: str, label: Optional[str] = None) -> dict:
        history = self._history_for(ticker, interval)
        prepared = prepare_history(history, interval)
        if prepared.empty:
            return empty_metrics(ticker, label or ticker, interval)
        latest = prepared.iloc[-1]
        previous = prepared.iloc[-2] if len(prepared) > 1 else latest
        close = _float(latest.get("close"))
        ema20 = _float(latest.get("ema_20"))
        ema50 = _float(latest.get("ema_50"))
        ema100 = _float(latest.get("ema_100"))
        ema200 = _float(latest.get("ema_200"))
        return20 = _float(latest.get("return_20"))
        return60 = _float(latest.get("return_60"))
        volatility_20 = _float(latest.get("volatility_20"))
        volatility_avg = _float(latest.get("volatility_avg_100"))
        atr14 = _float(latest.get("atr_14"))
        atr_avg = _float(latest.get("atr_avg_50"))
        ema20_slope = _float(latest.get("ema20_slope"))
        ema50_slope = _float(latest.get("ema50_slope"))
        price_distance_ema50 = abs(close - ema50) / close * 100 if close and ema50 else 0.0
        prior_high = _float(previous.get("prior_high_20"))
        higher_high = bool(close > prior_high) if prior_high else False
        return {
            "ok": True,
            "ticker": ticker.strip().upper(),
            "label": label or ticker.strip().upper(),
            "interval": interval,
            "date": pd.to_datetime(latest.get("date")).date().isoformat(),
            "close": close,
            "ema_20": ema20,
            "ema_50": ema50,
            "ema_100": ema100,
            "ema_200": ema200,
            "return_20": return20,
            "return_60": return60,
            "relative_strength_spy": 0.0,
            "volatility_20": volatility_20,
            "volatility_ratio": volatility_20 / volatility_avg if volatility_avg else 0.0,
            "atr_14": atr14,
            "atr_ratio": atr14 / atr_avg if atr_avg else 0.0,
            "ema20_slope": ema20_slope,
            "ema50_slope": ema50_slope,
            "price_distance_ema50": price_distance_ema50,
            "higher_high": higher_high,
            "trend": trend_from_metrics(close, ema20, ema50),
            "over_ema50": bool(close > ema50) if ema50 else False,
            "over_ema200": bool(close > ema200) if ema200 else False,
            "under_ema50": bool(close < ema50) if ema50 else False,
            "under_ema200": bool(close < ema200) if ema200 else False,
            "prepared": prepared,
        }

    def _history_for(self, ticker: str, interval: str) -> pd.DataFrame:
        ticker = str(ticker).strip()
        candidates = [ticker, ticker.upper()]
        if ticker.upper() == "DAX":
            candidates.append("^GDAXI")
        for candidate in candidates:
            history = self.histories.get(f"{candidate}|{interval}")
            if isinstance(history, pd.DataFrame) and not history.empty:
                return history
        return pd.DataFrame()

    def _dax_ticker(self) -> str:
        for item in self.config.get("dashboard_symbols", []):
            if isinstance(item, dict) and str(item.get("label", "")).lower() == "dax":
                return str(item.get("ticker", "^GDAXI"))
        return "^GDAXI"

    def _mag7(self) -> list[str]:
        return [
            str(item).strip().upper()
            for item in self.config.get("score_model", {}).get(
                "mag7_symbols",
                ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"],
            )
            if str(item).strip()
        ]

    def _sector_symbols(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for item in self.config.get("sector_rotation_symbols", []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("ticker") or "").strip()
            ticker = str(item.get("ticker") or "").strip().upper()
            category = str(item.get("category", "")).strip()
            if not ticker or ticker in CORE_TICKERS:
                continue
            if category in {"US Sektoren", "Bau", "Themen"}:
                rows.append((label or ticker, ticker))
        return rows


def prepare_history(history: pd.DataFrame, interval: str) -> pd.DataFrame:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return pd.DataFrame()
    required = {"date", "close"}
    if not required.issubset(history.columns):
        return pd.DataFrame()
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        if column not in frame:
            frame[column] = frame["close"] if column != "volume" else 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    if frame.empty:
        return pd.DataFrame()
    for period in [20, 50, 100, 200]:
        column = f"ema_{period}"
        if column not in frame or frame[column].isna().all():
            frame[column] = frame["close"].ewm(span=period, adjust=False, min_periods=min(period, len(frame))).mean()
        else:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    close_previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - close_previous).abs(),
            (frame["low"] - close_previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr_14"] = true_range.rolling(14, min_periods=min(14, len(frame))).mean()
    frame["atr_avg_50"] = frame["atr_14"].rolling(50, min_periods=min(20, len(frame))).mean()
    annualization = {"1d": 252, "1wk": 52, "1mo": 12}.get(interval, 252)
    returns = frame["close"].pct_change()
    frame["volatility_20"] = returns.rolling(20, min_periods=min(10, len(frame))).std() * np.sqrt(annualization) * 100
    frame["volatility_avg_100"] = frame["volatility_20"].rolling(100, min_periods=min(30, len(frame))).mean()
    frame["return_20"] = frame["close"].pct_change(20) * 100
    frame["return_60"] = frame["close"].pct_change(60) * 100
    frame["ema20_slope"] = frame["ema_20"].pct_change(5) * 100
    frame["ema50_slope"] = frame["ema_50"].pct_change(5) * 100
    frame["prior_high_20"] = frame["high"].rolling(20, min_periods=min(10, len(frame))).max().shift(1)
    return frame


def score_bullish_trend(spy: dict, qqq: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    if spy["over_ema50"]:
        score += 20
        reasons.append("SPY notiert ueber EMA50.")
    if qqq["over_ema50"]:
        score += 20
        reasons.append("QQQ notiert ueber EMA50.")
    if spy["ema_20"] > spy["ema_50"] > 0:
        score += 10
        reasons.append("SPY EMA20 liegt ueber EMA50.")
    if qqq["ema_20"] > qqq["ema_50"] > 0:
        score += 10
        reasons.append("QQQ EMA20 liegt ueber EMA50.")
    if spy["trend"] == qqq["trend"] == "bullish":
        score += 20
        reasons.append("SPY und QQQ bestaetigen dieselbe bullische Richtung.")
    if spy["over_ema200"] and qqq["over_ema200"]:
        score += 20
        reasons.append("SPY und QQQ liegen beide ueber EMA200.")
    return score, reasons


def score_bearish_trend(spy: dict, qqq: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    if spy["under_ema50"]:
        score += 20
        reasons.append("SPY notiert unter EMA50.")
    if qqq["under_ema50"]:
        score += 20
        reasons.append("QQQ notiert unter EMA50.")
    if 0 < spy["ema_20"] < spy["ema_50"]:
        score += 10
        reasons.append("SPY EMA20 liegt unter EMA50.")
    if 0 < qqq["ema_20"] < qqq["ema_50"]:
        score += 10
        reasons.append("QQQ EMA20 liegt unter EMA50.")
    if spy["trend"] == qqq["trend"] == "bearish":
        score += 20
        reasons.append("SPY und QQQ bestaetigen dieselbe baerische Richtung.")
    if spy["under_ema200"] and qqq["under_ema200"]:
        score += 20
        reasons.append("SPY und QQQ liegen beide unter EMA200.")
    return score, reasons


def score_sideways(spy: dict, qqq: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    flat = abs(spy["ema20_slope"]) <= 1.0 and abs(spy["ema50_slope"]) <= 1.0
    if flat:
        score += 25
        reasons.append("SPY EMA20 und EMA50 verlaufen flach.")
    if not spy["higher_high"] and not qqq["higher_high"]:
        score += 25
        reasons.append("SPY und QQQ zeigen keine klaren neuen 20-Perioden-Hochs.")
    if _mean([spy["atr_ratio"], qqq["atr_ratio"]]) <= 0.95:
        score += 25
        reasons.append("ATR liegt unter dem Durchschnitt.")
    if _mean([spy["price_distance_ema50"], qqq["price_distance_ema50"]]) <= 3.0:
        score += 25
        reasons.append("Preis liegt nahe an EMA50.")
    return score, reasons


def score_high_volatility(context: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    atr_ratio = context["volatility_average"]
    vol_ratio = context["realized_vol_ratio"]
    if atr_ratio > 1.0:
        score += min(50, (atr_ratio - 1.0) / 0.5 * 50)
        reasons.append(f"ATR14 liegt bei {atr_ratio:.2f}x des Durchschnitts.")
    if vol_ratio > 1.0:
        score += min(50, (vol_ratio - 1.0) / 0.5 * 50)
        reasons.append(f"Realisierte Volatilitaet liegt bei {vol_ratio:.2f}x des Durchschnitts.")
    return score, reasons


def score_low_volatility(context: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    atr_ratio = context["volatility_average"]
    vol_ratio = context["realized_vol_ratio"]
    if 0 < atr_ratio < 1.0:
        score += min(50, (1.0 - atr_ratio) / 0.35 * 50)
        reasons.append(f"ATR14 liegt nur bei {atr_ratio:.2f}x des Durchschnitts.")
    if 0 < vol_ratio < 1.0:
        score += min(50, (1.0 - vol_ratio) / 0.35 * 50)
        reasons.append(f"Realisierte Volatilitaet liegt nur bei {vol_ratio:.2f}x des Durchschnitts.")
    return score, reasons


def score_risk_on(context: dict) -> tuple[float, list[str]]:
    qqq = context["qqq"]
    spy = context["spy"]
    qqq_vs_spy = qqq["return_20"] - spy["return_20"]
    score = 0.0
    reasons = []
    if qqq_vs_spy > 0:
        score += 20 + min(10, qqq_vs_spy * 2)
        reasons.append(f"QQQ ist staerker als SPY ({qqq_vs_spy:.2f} Punkte RS).")
    if context["strongest_sector_ticker"] in GROWTH_SECTORS:
        score += 20
        reasons.append("Ein Wachstumssektor fuehrt das Sektor-Ranking.")
    if context["mag7_loaded"]:
        mag7_ratio = context["mag7_bullish"] / context["mag7_loaded"]
        score += mag7_ratio * 25
        reasons.append(f"Mag7 bullish: {context['mag7_bullish']} von {context['mag7_loaded']}.")
    if context["growth_strength"] > context["defensive_strength"]:
        score += 25
        reasons.append("Wachstumssektoren sind staerker als defensive Gruppen.")
    return score, reasons


def score_risk_off(context: dict) -> tuple[float, list[str]]:
    qqq = context["qqq"]
    spy = context["spy"]
    gld = context["gld"]
    qqq_vs_spy = qqq["return_20"] - spy["return_20"]
    score = 0.0
    reasons = []
    if qqq_vs_spy < 0:
        score += 20 + min(10, abs(qqq_vs_spy) * 2)
        reasons.append(f"QQQ ist schwaecher als SPY ({qqq_vs_spy:.2f} Punkte RS).")
    if context["defensive_strength"] > context["growth_strength"]:
        score += 25
        reasons.append("Defensive Gruppen fuehren gegen Wachstumssektoren.")
    if gld["return_20"] > spy["return_20"]:
        score += 20
        reasons.append("GLD ist staerker als SPY.")
    weak_market_points = 0
    if spy["trend"] in {"bearish", "neutral"} or spy["return_20"] < 0:
        weak_market_points += 12.5
    if qqq["trend"] in {"bearish", "neutral"} or qqq["return_20"] < 0:
        weak_market_points += 12.5
    if weak_market_points:
        score += weak_market_points
        reasons.append("SPY/QQQ sind nicht klar bullisch.")
    return score, reasons


def score_gold_strength(gld: dict, spy: dict, qqq: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    if gld["return_20"] > spy["return_20"]:
        score += 25
        reasons.append("GLD outperformt SPY.")
    if gld["return_20"] > qqq["return_20"]:
        score += 25
        reasons.append("GLD outperformt QQQ.")
    if gld["over_ema50"]:
        score += 25
        reasons.append("GLD liegt ueber EMA50.")
    if gld["over_ema200"]:
        score += 25
        reasons.append("GLD liegt ueber EMA200.")
    return score, reasons


def score_sector_rotation(context: dict, sectors: list[dict]) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    if not sectors:
        return score, ["Keine Sektor-Historiendaten geladen."]
    strongest = max(sectors, key=lambda item: item["relative_strength_spy"])
    if strongest["relative_strength_spy"] > 0:
        score += min(35, strongest["relative_strength_spy"] / 6 * 35)
        reasons.append(
            f"{strongest['label']} ist staerker als SPY ({strongest['relative_strength_spy']:.2f} Punkte RS)."
        )
    if context["sector_spread"] > 0:
        score += min(35, context["sector_spread"] / 10 * 35)
        reasons.append(f"Sektor-Spread Top zu Bottom: {context['sector_spread']:.2f} Punkte.")
    if context["sector_leadership_changed"]:
        score += 20
        reasons.append("Fuehrungswechsel zwischen 20- und 60-Perioden-Staerke sichtbar.")
    if len(sectors) >= 5:
        score += 10
        reasons.append(f"{len(sectors)} Sektorgruppen geladen.")
    return score, reasons


def apply_relative_strengths(evaluation: dict) -> dict:
    for context in evaluation.get("contexts", {}).values():
        spy_return = context.get("spy", {}).get("return_20", 0.0)
        for key in ["qqq", "gld", "dax"]:
            if key in context and context[key].get("ok"):
                context[key]["relative_strength_spy"] = context[key]["return_20"] - spy_return
        for sector in context.get("sectors", []):
            sector["relative_strength_spy"] = sector["return_20"] - spy_return
    return evaluation


def strategy_map_frame() -> pd.DataFrame:
    return pd.DataFrame(STRATEGY_MAP)


def strategy_for_regime(regime: str) -> str:
    for row in STRATEGY_MAP:
        if row["Regime"] == regime:
            return row["Strategy Type"]
    return "Analyse beobachten"


def description_for_regime(regime: str) -> str:
    for row in STRATEGY_MAP:
        if row["Regime"] == regime:
            return row["Description"]
    return "Keine Strategie-Zuordnung vorhanden."


def explanation_for_regime(regime: str, context: dict, reasons: list[str]) -> str:
    base = (
        f"Der Markt befindet sich aktuell in einem {regime} mit {context.get('volatility_status', 'Normal')}er "
        "Volatilitaet. "
    )
    if regime == "Risk-On Markt":
        base += "Trendfolge und relative Staerke sind in diesem Umfeld statistisch sinnvoller als reine Mean-Reversion-Analysen. "
    elif regime == "Risk-Off Markt":
        base += "Defensive Analyse und Kapitalerhalt bekommen in diesem Umfeld mehr Gewicht. "
    elif regime == "Hohe Volatilitaet":
        base += "Risiko-Filter und kleinere Positionsannahmen sind wichtiger als aggressive Breakout-Auswertungen. "
    elif regime == "Niedrige Volatilitaet":
        base += "Volatility-Expansion-Beobachtung ist wichtiger als aktive Signalinterpretation. "
    else:
        base += f"Passende Strategie-Typen: {strategy_for_regime(regime)}. "
    if reasons:
        base += "Gruende: " + " ".join(reasons[:4])
    return base.strip()


def write_market_regime_reports(
    evaluation: dict,
    reports_dir: Union[str, Path] = "reports",
) -> list[Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    summary_path = reports_path / "market_regime_report.csv"
    history_path = reports_path / "regime_history.csv"
    strategy_path = reports_path / "regime_strategy_map.csv"

    summary = evaluation.get("summary", pd.DataFrame()).copy()
    history = evaluation.get("history", pd.DataFrame()).copy()
    strategy = evaluation.get("strategy_map", strategy_map_frame()).copy()
    if not summary.empty:
        columns = [
            "Datum",
            "Timeframe",
            "Active Regime",
            "Confidence Score",
            "SPY Status",
            "QQQ Status",
            "GLD Status",
            "Volatility Status",
            "Strongest Sector",
            "Recommended Strategy",
        ]
        summary[columns].to_csv(summary_path, index=False)
    else:
        pd.DataFrame(
            columns=[
                "Datum",
                "Timeframe",
                "Active Regime",
                "Confidence Score",
                "SPY Status",
                "QQQ Status",
                "GLD Status",
                "Volatility Status",
                "Strongest Sector",
                "Recommended Strategy",
            ]
        ).to_csv(summary_path, index=False)

    history_columns = [
        "Datum",
        "Timeframe",
        "Bullish Trend Score",
        "Bearish Trend Score",
        "Sideways Score",
        "High Volatility Score",
        "Low Volatility Score",
        "Risk-On Score",
        "Risk-Off Score",
        "Gold Strength Score",
        "Sector Rotation Score",
        "Active Regime",
    ]
    if history_path.exists():
        existing = pd.read_csv(history_path)
        history = pd.concat([existing, history], ignore_index=True)
    if not history.empty:
        history = history.reindex(columns=history_columns)
        history = history.drop_duplicates(["Datum", "Timeframe"], keep="last")
        history.to_csv(history_path, index=False)
    else:
        pd.DataFrame(columns=history_columns).to_csv(history_path, index=False)
    strategy.to_csv(strategy_path, index=False)
    return [summary_path, history_path, strategy_path]


def evaluate_market_regime(config: dict, analysis_result: dict) -> dict:
    engine = MarketRegimeEngine(config, analysis_result)
    return engine.evaluate()


def empty_metrics(ticker: str, label: str, interval: str) -> dict:
    return {
        "ok": False,
        "ticker": ticker.strip().upper(),
        "label": label,
        "interval": interval,
        "date": "",
        "close": 0.0,
        "ema_20": 0.0,
        "ema_50": 0.0,
        "ema_100": 0.0,
        "ema_200": 0.0,
        "return_20": 0.0,
        "return_60": 0.0,
        "relative_strength_spy": 0.0,
        "volatility_20": 0.0,
        "volatility_ratio": 0.0,
        "atr_14": 0.0,
        "atr_ratio": 0.0,
        "ema20_slope": 0.0,
        "ema50_slope": 0.0,
        "price_distance_ema50": 0.0,
        "higher_high": False,
        "trend": "unbekannt",
        "over_ema50": False,
        "over_ema200": False,
        "under_ema50": False,
        "under_ema200": False,
        "prepared": pd.DataFrame(),
    }


def status_text(metrics: dict) -> str:
    if not metrics.get("ok"):
        return "Daten fehlen"
    return (
        f"{metrics['trend']} | Close {metrics['close']:.2f} | "
        f"EMA50 {metrics['ema_50']:.2f} | EMA200 {metrics['ema_200']:.2f}"
    )


def trend_from_metrics(close: float, ema20: float, ema50: float) -> str:
    if close > ema20 > ema50 > 0:
        return "bullish"
    if close < ema20 < ema50 and ema20 > 0:
        return "bearish"
    return "neutral"


def sector_leadership_changed(sectors: list[dict]) -> bool:
    if len(sectors) < 2:
        return False
    top20 = max(sectors, key=lambda item: item["return_20"])
    top60 = max(sectors, key=lambda item: item["return_60"])
    return top20["ticker"] != top60["ticker"]


def latest_common_date(metrics: list[dict]) -> str:
    dates = [item.get("date") for item in metrics if item.get("date")]
    return max(dates) if dates else ""


def clamp_score(value: float) -> int:
    if pd.isna(value):
        return 0
    return int(max(0, min(100, round(float(value)))))


def _float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if value is not None and not pd.isna(value)]
    return float(sum(clean) / len(clean)) if clean else 0.0
