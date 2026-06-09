from __future__ import annotations


class RiskManager:
    def __init__(self, config: dict) -> None:
        self.config = config

    def evaluate(self, row: dict, market_context: dict) -> dict:
        rules = self.config.get("risk_management", {})
        limits = rules.get("limits", {})
        thresholds = rules.get("thresholds", {})

        score = int(row.get("score", 0))
        close = float(row.get("close", 0))
        ema_20 = float(row.get("ema_20", 0))
        ema_50 = float(row.get("ema_50", 0))
        ema_200 = float(row.get("ema_200", 0))
        relative_strength = float(row.get("relative_strength", 0))
        trend = row.get("trend", "neutral")
        spy_trend = market_context.get("spy_trend", "neutral")
        qqq_trend = market_context.get("qqq_trend", "neutral")

        violations = []
        warnings = []

        if score < int(thresholds.get("blocked_score_below", 40)):
            violations.append("score_below_minimum")
        if trend == "bearish":
            violations.append("symbol_bearish")
        if close < ema_200:
            violations.append("below_ema200")
        if spy_trend == "bearish" and qqq_trend == "bearish":
            violations.append("market_bearish")

        if score < int(thresholds.get("reduced_score_below", 60)):
            warnings.append("score_reduced")
        if close < ema_50:
            warnings.append("below_ema50")
        if close < ema_20:
            warnings.append("below_ema20")
        if relative_strength < 0:
            warnings.append("relative_strength_negative")
        if spy_trend != qqq_trend:
            warnings.append("market_mixed")

        if violations:
            risk_state = "BLOCKED"
            max_risk = 0.0
            max_size = 0.0
        elif warnings:
            risk_state = "REDUCED"
            max_risk = float(limits.get("reduced_risk_per_signal_pct", 0.25))
            max_size = float(limits.get("reduced_position_size_pct", 2.5))
        else:
            risk_state = "OK"
            max_risk = float(limits.get("standard_risk_per_signal_pct", 0.5))
            max_size = float(limits.get("standard_position_size_pct", 5.0))

        risk_score = calculate_risk_score(violations, warnings, score)
        stop_distance = float(limits.get("technical_stop_distance_pct", 3.0))

        return {
            "risk_state": risk_state,
            "risk_score": risk_score,
            "max_risk_pct": max_risk,
            "max_position_pct": max_size,
            "technical_stop_distance_pct": stop_distance if risk_state != "BLOCKED" else 0.0,
            "portfolio_daily_loss_limit_pct": float(limits.get("portfolio_daily_loss_limit_pct", 1.0)),
            "portfolio_weekly_loss_limit_pct": float(limits.get("portfolio_weekly_loss_limit_pct", 3.0)),
            "max_correlation_group_pct": float(limits.get("max_correlation_group_pct", 20.0)),
            "risk_rule_hits": ",".join(violations + warnings) if violations or warnings else "none",
        }


def calculate_risk_score(violations: list[str], warnings: list[str], score: int) -> int:
    value = 100
    value -= len(violations) * 25
    value -= len(warnings) * 8
    if score < 50:
        value -= 10
    return max(0, min(100, value))
