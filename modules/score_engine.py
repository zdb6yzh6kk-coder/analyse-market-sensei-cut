from __future__ import annotations


DEFAULT_SCORE_WEIGHTS = {
    "spy_trend": 15,
    "qqq_trend": 15,
    "market_confirmation": 15,
    "mag7": 15,
    "sector_strength": 15,
    "relative_strength": 10,
    "trend_following": 15,
}


class ScoreEngine:
    def __init__(self, weights: dict | None = None) -> None:
        self.weights = DEFAULT_SCORE_WEIGHTS.copy()
        for key, value in (weights or {}).items():
            if key in self.weights:
                self.weights[key] = int(value)

    def score(
        self,
        snapshot: dict,
        market_context: dict,
        relative_strength: float = 0.0,
        ticker: str = "",
        trend: str = "neutral",
        sector_ticker: str = "",
    ) -> dict:
        spy_trend = market_context.get("spy_trend", "neutral")
        qqq_trend = market_context.get("qqq_trend", "neutral")
        close = snapshot.get("close", 0)
        mag7_context = market_context.get("mag7", {})
        sector_context = market_context.get("sector_strength", {})
        sector_state = sector_context.get(sector_ticker, sector_context.get("average", {}))

        components = {
            "spy_trend_points": _trend_points(spy_trend, self.weights["spy_trend"]),
            "qqq_trend_points": _trend_points(qqq_trend, self.weights["qqq_trend"]),
            "market_alignment_points": _market_confirmation_points(
                spy_trend,
                qqq_trend,
                self.weights["market_confirmation"],
            ),
            "mag7_points": _mag7_points(mag7_context, self.weights["mag7"]),
            "sector_strength_points": _sector_strength_points(
                sector_state,
                self.weights["sector_strength"],
            ),
            "relative_strength_points": _relative_strength_points(
                relative_strength,
                self.weights["relative_strength"],
            ),
            "trend_following_points": _trend_following_points(
                close,
                snapshot,
                trend,
                self.weights["trend_following"],
            ),
            "score_model": "sensei_chain_v2",
            "sector_ticker": sector_ticker,
            "sector_trend": sector_state.get("trend", "neutral"),
            "sector_relative_strength": round(float(sector_state.get("relative_strength", 0.0)), 2),
            "mag7_bullish_count": int(mag7_context.get("bullish_count", 0)),
            "mag7_bearish_count": int(mag7_context.get("bearish_count", 0)),
        }
        score_keys = [
            "spy_trend_points",
            "qqq_trend_points",
            "market_alignment_points",
            "mag7_points",
            "sector_strength_points",
            "relative_strength_points",
            "trend_following_points",
        ]
        components["score"] = int(sum(int(components[key]) for key in score_keys))
        # Legacy columns stay populated so older report/table views keep working.
        components["ema20_points"] = _ema_points(close, snapshot.get("ema_20"), 4)
        components["ema50_points"] = _ema_points(close, snapshot.get("ema_50"), 4)
        components["ema100_points"] = _ema_points(close, snapshot.get("ema_100"), 3)
        components["ema200_points"] = _ema_points(close, snapshot.get("ema_200"), 4)
        return components


def _ema_points(close: float, ema_value: float, points: int) -> int:
    if not ema_value:
        return 0
    return points if close > ema_value else 0


def _trend_points(trend: str, max_points: int) -> int:
    if trend == "bullish":
        return max_points
    if trend == "neutral":
        return round(max_points * 0.4)
    return 0


def _market_confirmation_points(spy_trend: str, qqq_trend: str, max_points: int) -> int:
    if spy_trend == "bullish" and qqq_trend == "bullish":
        return max_points
    if spy_trend == qqq_trend and spy_trend != "neutral":
        return round(max_points * 0.65)
    if spy_trend == "neutral" and qqq_trend == "neutral":
        return round(max_points * 0.35)
    return 0


def _mag7_points(context: dict, max_points: int) -> int:
    total = int(context.get("total", 0))
    bullish = int(context.get("bullish_count", 0))
    bearish = int(context.get("bearish_count", 0))
    if total <= 0:
        return 0
    bullish_ratio = bullish / total
    if bullish_ratio >= 0.70:
        return max_points
    if bullish_ratio >= 0.55:
        return round(max_points * 0.7)
    if bullish >= bearish:
        return round(max_points * 0.35)
    return 0


def _sector_strength_points(sector_state: dict, max_points: int) -> int:
    trend = sector_state.get("trend", "neutral")
    relative_strength = float(sector_state.get("relative_strength", 0.0))
    if trend == "bullish" and relative_strength > 0:
        return max_points
    if trend == "bullish" or relative_strength > 0:
        return round(max_points * 0.65)
    if trend == "neutral":
        return round(max_points * 0.35)
    return 0


def _relative_strength_points(relative_strength: float, max_points: int) -> int:
    if relative_strength > 0:
        return max_points
    if relative_strength > -2:
        return round(max_points * 0.5)
    return 0


def _trend_following_points(close: float, snapshot: dict, trend: str, max_points: int) -> int:
    ema20 = snapshot.get("ema_20")
    ema50 = snapshot.get("ema_50")
    ema100 = snapshot.get("ema_100")
    ema200 = snapshot.get("ema_200")
    raw_points = 0
    raw_points += 4 if close and ema20 and close > ema20 else 0
    raw_points += 4 if ema20 and ema50 and ema20 > ema50 else 0
    raw_points += 3 if ema50 and ema100 and ema50 > ema100 else 0
    raw_points += 2 if ema100 and ema200 and ema100 > ema200 else 0
    raw_points += 2 if close and ema200 and close > ema200 else 0
    if trend == "bullish":
        raw_points = max(raw_points, round(max_points * 0.7))
    return min(max_points, raw_points)
