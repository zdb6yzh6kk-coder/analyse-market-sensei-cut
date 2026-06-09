from __future__ import annotations


class ScoreEngine:
    def score(self, snapshot: dict, market_context: dict, relative_strength: float = 0.0) -> dict:
        spy_trend = market_context.get("spy_trend", "neutral")
        qqq_trend = market_context.get("qqq_trend", "neutral")
        close = snapshot.get("close", 0)

        components = {
            "spy_trend_points": 15 if spy_trend == "bullish" else 0,
            "qqq_trend_points": 15 if qqq_trend == "bullish" else 0,
            "market_alignment_points": (
                20 if spy_trend == qqq_trend and spy_trend != "neutral" else 0
            ),
            "ema20_points": _ema_points(close, snapshot.get("ema_20"), 10),
            "ema50_points": _ema_points(close, snapshot.get("ema_50"), 10),
            "ema100_points": _ema_points(close, snapshot.get("ema_100"), 10),
            "ema200_points": _ema_points(close, snapshot.get("ema_200"), 10),
            "relative_strength_points": 10 if relative_strength > 0 else 0,
        }
        components["score"] = int(sum(components.values()))
        return components


def _ema_points(close: float, ema_value: float, points: int) -> int:
    if not ema_value:
        return 0
    return points if close > ema_value else 0
