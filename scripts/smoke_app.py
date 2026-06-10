from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


COLUMNS = [
    "label",
    "ticker",
    "timeframe",
    "trend",
    "score",
    "risk_state",
    "risk_score",
    "max_risk_pct",
    "max_position_pct",
    "close",
    "ema_20",
    "ema_50",
    "ema_100",
    "ema_200",
    "return_1",
    "return_5",
    "return_20",
    "relative_strength",
    "last_updated",
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
    "risk_rule_hits",
    "data_status",
    "data_source",
    "data_message",
    "data_rows",
    "last_clean_date",
    "data_fetched_at",
]


def make_analysis_rows(symbols: list[tuple[str, str, int]]) -> pd.DataFrame:
    rows = []
    for index, (label, ticker, score) in enumerate(symbols):
        rows.append(
            [
                label,
                ticker,
                "1d",
                "bullish" if score >= 80 else "neutral",
                score,
                "OK" if score >= 75 else "REDUCED",
                score,
                0.5,
                5.0,
                100.0 + index,
                99.0,
                98.0,
                97.0,
                96.0,
                0.4,
                1.2,
                4.5,
                1.0 - index * 0.1,
                "smoke",
                15,
                15,
                20,
                15,
                15,
                10,
                10,
                10,
                10,
                10,
                15,
                "",
                "delayed",
                "smoke",
                "Smoke-Testdaten geladen.",
                90,
                str(datetime.now().date()),
                datetime.now().isoformat(timespec="seconds"),
            ]
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def make_history(ticker: str, offset: int) -> pd.DataFrame:
    dates = [datetime.now() - timedelta(days=index) for index in range(90, 0, -1)]
    return pd.DataFrame(
        {
            "date": dates,
            "ticker": [ticker] * len(dates),
            "timeframe": ["1d"] * len(dates),
            "open": [100 + offset + index * 0.1 for index in range(len(dates))],
            "high": [101 + offset + index * 0.1 for index in range(len(dates))],
            "low": [99 + offset + index * 0.1 for index in range(len(dates))],
            "close": [100.5 + offset + index * 0.1 for index in range(len(dates))],
            "volume": [1_000_000 + index for index in range(len(dates))],
            "ema_20": [100 + offset + index * 0.09 for index in range(len(dates))],
            "ema_50": [99 + offset + index * 0.08 for index in range(len(dates))],
            "ema_100": [98 + offset + index * 0.07 for index in range(len(dates))],
            "ema_200": [97 + offset + index * 0.06 for index in range(len(dates))],
        }
    )


def fake_result() -> dict:
    dashboard_symbols = [
        ("SPY", "SPY", 92),
        ("SPX500", "^GSPC", 89),
        ("QQQ", "QQQ", 87),
        ("Nasdaq100", "^NDX", 84),
        ("GLD", "GLD", 76),
        ("Gold", "GC=F", 78),
        ("DAX", "^GDAXI", 72),
    ]
    watch_symbols = [
        (symbol, symbol, 90 - index * 3)
        for index, symbol in enumerate(["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"])
    ]
    sector_symbols = [
        ("Technology", "XLK", 92),
        ("Financials", "XLF", 82),
        ("Homebuilders / Bau", "XHB", 74),
        ("US Dollar Index", "DX-Y.NYB", 64),
        ("Treasury 1-3Y", "SHY", 58),
        ("Treasury Yield 5Y", "^FVX", 62),
        ("Treasury Yield 10Y", "^TNX", 60),
    ]
    histories = {
        f"{ticker}|1d": make_history(ticker, index)
        for index, (_, ticker, _) in enumerate(dashboard_symbols + watch_symbols + sector_symbols)
    }
    return {
        "dashboard": make_analysis_rows(dashboard_symbols),
        "watchlist": make_analysis_rows(watch_symbols),
        "sector_rotation": make_analysis_rows(sector_symbols),
        "histories": histories,
        "reports": [],
        "updated_at": "smoke",
    }


def run_page(page: str) -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.session_state["authenticated_email"] = "dev@local"
    app.session_state["authenticated"] = True
    app.session_state["app_password_ok"] = True
    app.session_state["dev_login_active"] = True
    app.session_state["sensitive_unlocked"] = True
    app.session_state["sensitive_unlocked_until"] = 9_999_999_999
    app.session_state["analysis_result"] = fake_result()
    app.session_state["navigation_page"] = page
    app.run()
    errors = list(app.error) + list(app.exception)
    if errors:
        details = "\n".join(str(item) for item in errors)
        raise RuntimeError(f"{page} failed:\n{details}")


def main() -> None:
    for page in [
        "Heute ansehen",
        "Dashboard",
        "Workspace",
        "Watchlist",
        "Sektorrotation",
        "Backtesting",
        "Papertrading",
        "Real Money",
        "Reports",
        "Updates",
        "Online-Betrieb",
        "Settings",
    ]:
        run_page(page)
        print(f"OK {page}")
    print("Analyse Market Sensei Cut Streamlit smoke OK")


if __name__ == "__main__":
    main()
