from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from modules.app_env import get_app_env, is_cloud_env
from modules.power_check import get_power_status


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
EVENING_LOG = LOG_DIR / "evening_analysis.log"


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=EVENING_LOG,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run_evening_analysis(require_power: Optional[bool] = None, allow_cloud: bool = False) -> dict:
    configure_logging()
    logger = logging.getLogger(__name__)
    started_at = datetime.now().isoformat(timespec="seconds")
    logger.info("Evening analysis requested at %s", started_at)

    app_env = get_app_env()
    if is_cloud_env(app_env) and not allow_cloud:
        message = "Abendanalyse im Cloud-Modus uebersprungen: Hintergrundjobs sind nur lokal aktiv."
        logger.info(message)
        return {
            "ok": False,
            "skipped": True,
            "message": message,
            "power": "cloud",
            "reports": [],
        }

    effective_require_power = (not is_cloud_env(app_env)) if require_power is None else require_power
    power_status = get_power_status() if effective_require_power else None

    if effective_require_power and power_status is not None and not power_status.on_ac_power:
        message = f"Abendanalyse abgebrochen: {power_status.message}"
        logger.info("%s Raw: %s", message, power_status.raw_output.strip())
        return {
            "ok": False,
            "skipped": True,
            "message": message,
            "power": power_status.source,
            "reports": [],
        }

    from modules.updater import load_config, run_full_update

    config = load_config(BASE_DIR / "config.json")
    result = run_full_update(config, generate_reports=True)
    message = "Abendanalyse abgeschlossen."
    logger.info("%s Reports: %s", message, result.get("reports", []))
    return {
        "ok": True,
        "skipped": False,
        "message": message,
        "power": power_status.source if power_status is not None else "ignored",
        "reports": result.get("reports", []),
        "updated_at": result.get("updated_at"),
        "analysis_result": result,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse Market Sensei Cut CLI")
    parser.add_argument(
        "--mode",
        choices=["evening-analysis"],
        required=True,
        help="CLI mode to run",
    )
    args = parser.parse_args(argv)

    if args.mode == "evening-analysis":
        result = run_evening_analysis(require_power=None)
        print(result["message"])
        if result.get("skipped"):
            return 0
        return 0 if result["ok"] else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
