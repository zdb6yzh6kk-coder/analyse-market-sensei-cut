from __future__ import annotations

import ast
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .database import MarketDatabase
from .market_analyzer import MarketAnalyzer
from .report_generator import ReportGenerator


logger = logging.getLogger(__name__)

ALLOWED_UPDATE_FILES = {"app.py", "config.json"}
ALLOWED_MODULE_DIR = "modules"
BLOCKED_CALL_NAMES = {"eval", "exec"}


def load_config(path: Union[str, Path] = "config.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_config(config: dict, path: Union[str, Path] = "config.json") -> None:
    Path(path).write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def run_full_update(config: dict, generate_reports: bool = False) -> dict:
    analyzer = MarketAnalyzer(config)
    database = MarketDatabase(config["data"].get("database_path", "data/market.duckdb"))

    dashboard = analyzer.analyze_symbols(
        config.get("dashboard_symbols", []),
        benchmark_ticker=config.get("benchmark", "QQQ"),
    )
    watchlist = analyzer.analyze_symbols(
        config.get("watchlist", []),
        benchmark_ticker=config.get("benchmark", "QQQ"),
    )

    database.save_prices(analyzer.histories)
    database.save_analysis("dashboard", dashboard)
    database.save_analysis("watchlist", watchlist)

    reports = []
    updated_at = datetime.now().isoformat(timespec="seconds")
    if generate_reports:
        generator = ReportGenerator(config.get("reports_dir", "reports"))
        runtime_mode = config.get("runtime_mode", {}).get("active", "papertrading")
        report_paths = generator.write_reports(dashboard, watchlist, updated_at, runtime_mode)
        for report_path in report_paths:
            kind = report_path.stem
            row_count = len(dashboard) if kind == "market_summary" else len(watchlist)
            database.record_report(report_path, kind, row_count)
        reports = [str(path) for path in report_paths]

    result = {
        "dashboard": dashboard,
        "watchlist": watchlist,
        "histories": analyzer.histories,
        "reports": reports,
        "updated_at": updated_at,
    }
    _write_update_status(config, result)
    logger.info("Market analysis updated at %s", updated_at)
    return result


def _write_update_status(config: dict, result: dict) -> None:
    logs_dir = Path(config.get("logs_dir", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": result["updated_at"],
        "dashboard_rows": len(result["dashboard"]),
        "watchlist_rows": len(result["watchlist"]),
        "reports": result["reports"],
    }
    (logs_dir / "last_update.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_current_version(project_root: Union[str, Path]) -> dict:
    version_path = Path(project_root) / "version.json"
    if not version_path.exists():
        version = {
            "version": "0.1.0",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        version_path.write_text(json.dumps(version, indent=2), encoding="utf-8")
        return version
    return json.loads(version_path.read_text(encoding="utf-8"))


def create_backup(project_root: Union[str, Path]) -> Path:
    root = Path(project_root)
    backup_dir = root / "backups" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    counter = 1
    while backup_dir.exists():
        backup_dir = root / "backups" / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{counter}"
        counter += 1

    backup_dir.mkdir(parents=True, exist_ok=False)
    for filename in ["app.py", "config.json", "version.json"]:
        source = root / filename
        if source.exists():
            shutil.copy2(source, backup_dir / filename)

    modules_source = root / "modules"
    modules_target = backup_dir / "modules"
    if modules_source.exists():
        shutil.copytree(
            modules_source,
            modules_target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    _write_update_log(root, f"Backup erstellt: {backup_dir}")
    return backup_dir


def list_backups(project_root: Union[str, Path]) -> list[Path]:
    backup_root = Path(project_root) / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    return sorted(
        [path for path in backup_root.iterdir() if path.is_dir()],
        reverse=True,
    )


def inspect_update_files(project_root: Union[str, Path]) -> dict:
    root = Path(project_root)
    updates_dir = root / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    files = _candidate_update_files(updates_dir)

    errors = []
    allowed_files = []
    for path in files:
        rel = path.relative_to(updates_dir)
        rel_text = rel.as_posix()
        if not _is_allowed_update_path(rel):
            errors.append(f"Nicht erlaubte Datei: {rel_text}")
            continue
        validation_error = _validate_update_file(path, rel)
        if validation_error:
            errors.append(f"{rel_text}: {validation_error}")
            continue
        allowed_files.append(rel_text)

    return {
        "ok": not errors,
        "files": allowed_files,
        "errors": errors,
        "updates_dir": str(updates_dir),
    }


def apply_code_update(project_root: Union[str, Path]) -> dict:
    root = Path(project_root)
    backup_dir = None
    inspection = inspect_update_files(root)
    if not inspection["ok"]:
        message = "Update abgebrochen: " + "; ".join(inspection["errors"])
        _write_update_log(root, message)
        return {"ok": False, "message": message, "backup": None, "version": None}
    if not inspection["files"]:
        message = "Update abgebrochen: Keine gueltigen Update-Dateien gefunden."
        _write_update_log(root, message)
        return {"ok": False, "message": message, "backup": None, "version": None}

    try:
        backup_dir = create_backup(root)
        updates_dir = root / "updates"
        for rel_text in inspection["files"]:
            source = updates_dir / rel_text
            target = root / rel_text
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        version = bump_version(root)
        _write_changelog(
            root,
            f"Update angewendet: Version {version['version']} | Dateien: {', '.join(inspection['files'])}",
        )
        _write_update_log(root, f"Update angewendet: Version {version['version']}")
        return {
            "ok": True,
            "message": "Update angewendet. Bitte Streamlit neu starten, falls Änderungen nicht sichtbar sind.",
            "backup": str(backup_dir),
            "version": version["version"],
        }
    except Exception as exc:
        if backup_dir is not None:
            try:
                _restore_backup_contents(root, backup_dir)
                _write_update_log(root, f"Update-Fehler automatisch zurueckgerollt: {backup_dir}")
            except Exception as rollback_exc:
                _write_update_log(root, f"Automatischer Rollback fehlgeschlagen: {rollback_exc}")
        message = f"Update fehlgeschlagen: {exc}"
        _write_update_log(root, message)
        logger.exception("Code update failed")
        return {"ok": False, "message": message, "backup": None, "version": None}


def restore_latest_backup(project_root: Union[str, Path]) -> dict:
    root = Path(project_root)
    backups = list_backups(root)
    if not backups:
        message = "Kein Backup zum Wiederherstellen gefunden."
        _write_update_log(root, message)
        return {"ok": False, "message": message, "backup": None}

    backup_dir = backups[0]
    try:
        _restore_backup_contents(root, backup_dir)
        _write_changelog(root, f"Backup wiederhergestellt: {backup_dir.name}")
        _write_update_log(root, f"Backup wiederhergestellt: {backup_dir}")
        return {
            "ok": True,
            "message": "Letztes Backup wiederhergestellt. Bitte Streamlit neu starten.",
            "backup": str(backup_dir),
        }
    except Exception as exc:
        message = f"Rollback fehlgeschlagen: {exc}"
        _write_update_log(root, message)
        logger.exception("Rollback failed")
        return {"ok": False, "message": message, "backup": str(backup_dir)}


def _restore_backup_contents(root: Path, backup_dir: Path) -> None:
    for filename in ["app.py", "config.json", "version.json"]:
        source = backup_dir / filename
        if source.exists():
            shutil.copy2(source, root / filename)

    modules_source = backup_dir / "modules"
    modules_target = root / "modules"
    if modules_source.exists():
        if modules_target.exists():
            shutil.rmtree(modules_target)
        shutil.copytree(
            modules_source,
            modules_target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )


def bump_version(project_root: Union[str, Path]) -> dict:
    root = Path(project_root)
    version_info = get_current_version(root)
    version_info["version"] = _increment_patch_version(version_info.get("version", "0.1.0"))
    version_info["updated_at"] = datetime.now().isoformat(timespec="seconds")
    (root / "version.json").write_text(
        json.dumps(version_info, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return version_info


def read_update_log(project_root: Union[str, Path], max_lines: int = 80) -> str:
    log_path = Path(project_root) / "logs" / "update_log.txt"
    if not log_path.exists():
        return "Noch keine Update-Logs vorhanden."
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])


def read_changelog(project_root: Union[str, Path], max_lines: int = 80) -> str:
    path = Path(project_root) / "logs" / "changelog.txt"
    if not path.exists():
        return "Noch kein Changelog vorhanden."
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])


def _candidate_update_files(updates_dir: Path) -> list[Path]:
    ignored = {".DS_Store", "__pycache__", "last_update.json"}
    files = []
    for path in updates_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored for part in path.relative_to(updates_dir).parts):
            continue
        files.append(path)
    return sorted(files)


def _is_allowed_update_path(rel: Path) -> bool:
    rel_text = rel.as_posix()
    if rel_text in ALLOWED_UPDATE_FILES:
        return True
    return len(rel.parts) == 2 and rel.parts[0] == ALLOWED_MODULE_DIR and rel.suffix == ".py"


def _validate_update_file(path: Path, rel: Path) -> Optional[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "Datei ist nicht UTF-8 lesbar."

    if rel.suffix == ".py":
        try:
            tree = ast.parse(content, filename=rel.as_posix())
        except SyntaxError as exc:
            return f"Python-Syntaxfehler: {exc}"
        blocked = _find_blocked_calls(tree)
        if blocked:
            return f"Nicht erlaubter Funktionsaufruf: {', '.join(sorted(blocked))}"

    if rel.as_posix() == "config.json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"JSON-Fehler: {exc}"

    return None


def _find_blocked_calls(tree: ast.AST) -> set[str]:
    blocked = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALL_NAMES:
            blocked.add(node.func.id)
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALL_NAMES:
            blocked.add(node.func.attr)
    return blocked


def _increment_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "0.1.1"
    major, minor, patch = [int(part) for part in parts]
    return f"{major}.{minor}.{patch + 1}"


def _write_update_log(project_root: Path, message: str) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} | {message}\n"
    with (log_dir / "update_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(line)


def _write_changelog(project_root: Path, message: str) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} | {message}\n"
    with (log_dir / "changelog.txt").open("a", encoding="utf-8") as handle:
        handle.write(line)
