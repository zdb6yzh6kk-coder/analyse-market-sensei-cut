from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PowerStatus:
    on_ac_power: bool
    source: str
    raw_output: str
    message: str


def get_power_status() -> PowerStatus:
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        message = f"Power-Check fehlgeschlagen: {exc}"
        logger.warning(message)
        return PowerStatus(False, "unknown", "", message)

    raw = (result.stdout or "") + (result.stderr or "")
    normalized = raw.lower()
    on_ac = "ac power" in normalized or "no batteries" in normalized
    source = "AC Power" if on_ac else "Battery Power"
    message = "Mac haengt am Netzteil." if on_ac else "Mac haengt nicht am Netzteil."

    if result.returncode != 0:
        message = f"pmset meldet Fehlercode {result.returncode}."
        logger.warning("%s Ausgabe: %s", message, raw.strip())
        return PowerStatus(False, "unknown", raw, message)

    return PowerStatus(on_ac, source, raw, message)


def is_on_ac_power() -> bool:
    return get_power_status().on_ac_power
