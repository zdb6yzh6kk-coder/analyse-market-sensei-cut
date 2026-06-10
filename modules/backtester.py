from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


BACKTEST_SETUPS = ["Trendfolge", "Breakout", "Pullback", "Relative Staerke"]


@dataclass
class BacktestSettings:
    timeframe: str = "1d"
    benchmark: str = "QQQ"
    min_score: int = 60
    hold_period: int = 20
    stop_loss_pct: float = 5.0
    target_pct: float = 10.0
    max_signals_per_symbol_setup: int = 200


class Backtester:
    def __init__(self, histories: dict[str, pd.DataFrame]) -> None:
        self.histories = histories or {}

    def run(
        self,
        symbols: list[str],
        setups: list[str],
        settings: BacktestSettings,
    ) -> dict:
        cleaned_symbols = _unique_upper(symbols)
        cleaned_setups = [setup for setup in setups if setup in BACKTEST_SETUPS]
        if not cleaned_symbols or not cleaned_setups:
            return _empty_result("Keine Symbole oder Setups ausgewaehlt.")

        benchmark = self.history(settings.benchmark, settings.timeframe)
        spy = self.history("SPY", settings.timeframe)
        qqq = self.history("QQQ", settings.timeframe)
        if benchmark.empty or spy.empty or qqq.empty:
            return _empty_result("Benchmark, SPY oder QQQ fehlen in den geladenen Historiendaten.")

        trades = []
        skipped = []
        for symbol in cleaned_symbols:
            history = self.history(symbol, settings.timeframe)
            if history.empty:
                skipped.append({"ticker": symbol, "reason": "Keine Historiendaten geladen"})
                continue
            prepared = prepare_backtest_frame(
                symbol=symbol,
                history=history,
                benchmark=benchmark,
                spy=spy,
                qqq=qqq,
            )
            if prepared.empty:
                skipped.append({"ticker": symbol, "reason": "Zu wenig saubere Daten"})
                continue
            for setup in cleaned_setups:
                trades.extend(run_setup(prepared, symbol, setup, settings))

        trades_df = pd.DataFrame(trades)
        if not trades_df.empty:
            trades_df = trades_df.sort_values(["entry_date", "ticker", "setup_category"]).reset_index(drop=True)

        return {
            "message": "",
            "trades": trades_df,
            "summary": summarize_trades(trades_df),
            "setup_summary": summarize_by_setup(trades_df),
            "score_summary": summarize_by_score_bucket(trades_df),
            "equity_curve": build_equity_curve(trades_df),
            "skipped": pd.DataFrame(skipped),
        }

    def history(self, ticker: str, timeframe: str) -> pd.DataFrame:
        history = self.histories.get(f"{ticker}|{timeframe}")
        if history is None or history.empty:
            return pd.DataFrame()
        return normalize_history(history)


def prepare_backtest_frame(
    symbol: str,
    history: pd.DataFrame,
    benchmark: pd.DataFrame,
    spy: pd.DataFrame,
    qqq: pd.DataFrame,
) -> pd.DataFrame:
    frame = normalize_history(history)
    if frame.empty:
        return frame

    benchmark_frame = normalize_history(benchmark)[["date", "close"]].rename(
        columns={"close": "benchmark_close"}
    )
    spy_frame = normalize_history(spy)[["date", "close", "ema_20", "ema_50"]].rename(
        columns={
            "close": "spy_close",
            "ema_20": "spy_ema_20",
            "ema_50": "spy_ema_50",
        }
    )
    qqq_frame = normalize_history(qqq)[["date", "close", "ema_20", "ema_50"]].rename(
        columns={
            "close": "qqq_close",
            "ema_20": "qqq_ema_20",
            "ema_50": "qqq_ema_50",
        }
    )
    merged = frame.merge(benchmark_frame, on="date", how="inner")
    merged = merged.merge(spy_frame, on="date", how="inner")
    merged = merged.merge(qqq_frame, on="date", how="inner")
    if merged.empty:
        return merged

    merged["symbol_return_20"] = merged["close"].pct_change(20) * 100
    merged["benchmark_return_20"] = merged["benchmark_close"].pct_change(20) * 100
    merged["relative_strength"] = merged["symbol_return_20"] - merged["benchmark_return_20"]
    merged["prior_high_20"] = merged["high"].rolling(20, min_periods=10).max().shift(1)
    merged["trend_state"] = merged.apply(
        lambda row: classify_trend_from_values(row["close"], row["ema_20"], row["ema_50"]),
        axis=1,
    )
    merged["spy_trend"] = merged.apply(
        lambda row: classify_trend_from_values(row["spy_close"], row["spy_ema_20"], row["spy_ema_50"]),
        axis=1,
    )
    merged["qqq_trend"] = merged.apply(
        lambda row: classify_trend_from_values(row["qqq_close"], row["qqq_ema_20"], row["qqq_ema_50"]),
        axis=1,
    )
    merged["historical_score"] = merged.apply(historical_score, axis=1)
    merged["ticker"] = symbol
    return merged.dropna(subset=["close", "open", "high", "low", "historical_score"]).reset_index(drop=True)


def run_setup(
    frame: pd.DataFrame,
    symbol: str,
    setup: str,
    settings: BacktestSettings,
) -> list[dict]:
    trades = []
    next_allowed_index = 0
    for index in range(220, max(0, len(frame) - 2)):
        if index < next_allowed_index:
            continue
        row = frame.iloc[index]
        if int(row["historical_score"]) < int(settings.min_score):
            continue
        if not setup_signal(frame, index, setup):
            continue
        trade = simulate_long_trade(frame, index, symbol, setup, settings)
        if trade is None:
            continue
        trades.append(trade)
        next_allowed_index = int(trade["exit_index"]) + 1
        if len(trades) >= int(settings.max_signals_per_symbol_setup):
            break
    return trades


def setup_signal(frame: pd.DataFrame, index: int, setup: str) -> bool:
    row = frame.iloc[index]
    previous = frame.iloc[index - 1] if index > 0 else row
    close = _float(row.get("close"))
    ema20 = _float(row.get("ema_20"))
    ema50 = _float(row.get("ema_50"))
    ema100 = _float(row.get("ema_100"))
    ema200 = _float(row.get("ema_200"))
    relative_strength = _float(row.get("relative_strength"))

    if setup == "Trendfolge":
        return close > ema20 > ema50 > ema100 > ema200 > 0
    if setup == "Breakout":
        prior_high = _float(row.get("prior_high_20"))
        return prior_high > 0 and close > prior_high and close > ema20 > ema50 > 0
    if setup == "Pullback":
        previous_close = _float(previous.get("close"))
        previous_ema20 = _float(previous.get("ema_20"))
        return ema50 > ema200 > 0 and previous_close < previous_ema20 and close > ema20 > ema50
    if setup == "Relative Staerke":
        previous_rs = _float(previous.get("relative_strength"))
        return previous_rs <= 0 < relative_strength and close > ema50 > 0
    return False


def simulate_long_trade(
    frame: pd.DataFrame,
    signal_index: int,
    symbol: str,
    setup: str,
    settings: BacktestSettings,
) -> Optional[dict]:
    entry_index = signal_index + 1
    if entry_index >= len(frame):
        return None
    entry = frame.iloc[entry_index]
    signal = frame.iloc[signal_index]
    entry_price = _float(entry.get("open")) or _float(entry.get("close"))
    if entry_price <= 0:
        return None

    stop_price = entry_price * (1 - max(0.0, float(settings.stop_loss_pct)) / 100)
    target_price = entry_price * (1 + max(0.0, float(settings.target_pct)) / 100)
    exit_limit = min(len(frame) - 1, entry_index + max(1, int(settings.hold_period)))
    exit_index = exit_limit
    exit_price = _float(frame.iloc[exit_limit].get("close"))
    exit_reason = "Zeitablauf"

    for current_index in range(entry_index, exit_limit + 1):
        current = frame.iloc[current_index]
        low = _float(current.get("low"))
        high = _float(current.get("high"))
        if settings.stop_loss_pct > 0 and low <= stop_price:
            exit_index = current_index
            exit_price = stop_price
            exit_reason = "Stop"
            break
        if settings.target_pct > 0 and high >= target_price:
            exit_index = current_index
            exit_price = target_price
            exit_reason = "Ziel"
            break

    return_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
    return {
        "ticker": symbol,
        "setup_category": setup,
        "timeframe": settings.timeframe,
        "signal_date": pd.to_datetime(signal["date"]).date(),
        "entry_date": pd.to_datetime(entry["date"]).date(),
        "exit_date": pd.to_datetime(frame.iloc[exit_index]["date"]).date(),
        "entry_price": round(float(entry_price), 4),
        "exit_price": round(float(exit_price), 4),
        "return_pct": round(float(return_pct), 4),
        "worked": bool(return_pct > 0),
        "exit_reason": exit_reason,
        "bars_held": int(exit_index - entry_index + 1),
        "signal_score": int(signal["historical_score"]),
        "score_bucket": score_bucket(int(signal["historical_score"])),
        "relative_strength": round(_float(signal.get("relative_strength")), 4),
        "trend_state": str(signal.get("trend_state", "neutral")),
        "exit_index": int(exit_index),
    }


def summarize_trades(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "signals": 0,
            "win_rate": 0.0,
            "average_return": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "best_return": 0.0,
            "worst_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "average_score": 0.0,
        }
    returns = pd.to_numeric(trades["return_pct"], errors="coerce").fillna(0)
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    equity = build_equity_curve(trades)
    max_drawdown = _float(equity["drawdown_pct"].min()) if not equity.empty else 0.0
    loss_sum = abs(float(losses.sum()))
    profit_factor = float(wins.sum() / loss_sum) if loss_sum else float(wins.sum() > 0)
    return {
        "signals": int(len(trades)),
        "win_rate": float((returns > 0).mean() * 100),
        "average_return": float(returns.mean()),
        "average_win": float(wins.mean()) if not wins.empty else 0.0,
        "average_loss": float(losses.mean()) if not losses.empty else 0.0,
        "best_return": float(returns.max()),
        "worst_return": float(returns.min()),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "average_score": float(pd.to_numeric(trades["signal_score"], errors="coerce").fillna(0).mean()),
    }


def summarize_by_setup(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = trades.copy()
    frame["return_pct"] = pd.to_numeric(frame["return_pct"], errors="coerce").fillna(0)
    grouped = (
        frame.groupby("setup_category", as_index=False)
        .agg(
            signals=("ticker", "count"),
            win_rate=("worked", lambda values: float(values.mean() * 100)),
            average_return=("return_pct", "mean"),
            best_return=("return_pct", "max"),
            worst_return=("return_pct", "min"),
            average_score=("signal_score", "mean"),
        )
        .sort_values(["average_return", "win_rate"], ascending=False)
    )
    return grouped


def summarize_by_score_bucket(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = trades.copy()
    frame["return_pct"] = pd.to_numeric(frame["return_pct"], errors="coerce").fillna(0)
    return (
        frame.groupby("score_bucket", as_index=False)
        .agg(
            signals=("ticker", "count"),
            win_rate=("worked", lambda values: float(values.mean() * 100)),
            average_return=("return_pct", "mean"),
            best_return=("return_pct", "max"),
            worst_return=("return_pct", "min"),
        )
        .sort_values("score_bucket")
    )


def build_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = trades.sort_values(["exit_date", "ticker", "setup_category"]).copy()
    frame["return_pct"] = pd.to_numeric(frame["return_pct"], errors="coerce").fillna(0)
    frame["equity"] = (1 + frame["return_pct"] / 100).cumprod() - 1
    frame["equity_pct"] = frame["equity"] * 100
    frame["peak"] = frame["equity_pct"].cummax()
    frame["drawdown_pct"] = frame["equity_pct"] - frame["peak"]
    return frame[["exit_date", "ticker", "setup_category", "return_pct", "equity_pct", "drawdown_pct"]]


def historical_score(row) -> int:
    close = _float(row.get("close"))
    ema20 = _float(row.get("ema_20"))
    ema50 = _float(row.get("ema_50"))
    ema100 = _float(row.get("ema_100"))
    ema200 = _float(row.get("ema_200"))
    spy_trend = str(row.get("spy_trend", "neutral"))
    qqq_trend = str(row.get("qqq_trend", "neutral"))
    relative_strength = _float(row.get("relative_strength"))
    score = 0
    score += 15 if spy_trend == "bullish" else 6 if spy_trend == "neutral" else 0
    score += 15 if qqq_trend == "bullish" else 6 if qqq_trend == "neutral" else 0
    score += 20 if spy_trend == qqq_trend else 0
    score += 10 if close > ema20 > 0 else 0
    score += 10 if close > ema50 > 0 else 0
    score += 10 if close > ema100 > 0 else 0
    score += 10 if close > ema200 > 0 else 0
    score += 10 if relative_strength > 0 else 0
    return int(min(100, max(0, score)))


def classify_trend_from_values(close, ema20, ema50) -> str:
    close = _float(close)
    ema20 = _float(ema20)
    ema50 = _float(ema50)
    if close > ema20 > ema50 > 0:
        return "bullish"
    if close < ema20 < ema50 and ema20 > 0 and ema50 > 0:
        return "bearish"
    return "neutral"


def score_bucket(score: int) -> str:
    if score >= 80:
        return "80-100"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    if score >= 50:
        return "50-59"
    return "0-49"


def normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ["open", "high", "low", "close", "volume", "ema_20", "ema_50", "ema_100", "ema_200"]:
        if column not in frame:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _unique_upper(values: list[str]) -> list[str]:
    cleaned = []
    for value in values or []:
        text = str(value).strip().upper()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _empty_result(message: str) -> dict:
    return {
        "message": message,
        "trades": pd.DataFrame(),
        "summary": summarize_trades(pd.DataFrame()),
        "setup_summary": pd.DataFrame(),
        "score_summary": pd.DataFrame(),
        "equity_curve": pd.DataFrame(),
        "skipped": pd.DataFrame(),
    }


def _float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
