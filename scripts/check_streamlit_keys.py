#!/usr/bin/env python3
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_FILES = [PROJECT_ROOT / "app.py"] + sorted((PROJECT_ROOT / "modules").glob("*.py"))

KEY_REQUIRED_CALLS = {
    "button",
    "download_button",
    "checkbox",
    "selectbox",
    "multiselect",
    "radio",
    "slider",
    "text_input",
    "text_area",
    "number_input",
    "date_input",
    "file_uploader",
    "data_editor",
    "dataframe",
    "plotly_chart",
    "form_submit_button",
}

LABEL_UNIQUE_CALLS = {
    "expander",
}


def main() -> int:
    missing_keys: list[str] = []
    literal_keys: dict[str, list[str]] = defaultdict(list)
    static_labels: dict[tuple[str, str], list[str]] = defaultdict(list)

    for path in TARGET_FILES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            name = streamlit_call_name(node)
            if not name:
                continue

            location = f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
            if name == "form":
                if not has_keyword(node, "key") and not node.args:
                    missing_keys.append(f"{location} st.form braucht einen Key.")
                record_literal_key(node, location, literal_keys)
                continue

            if name in KEY_REQUIRED_CALLS:
                if not has_keyword(node, "key"):
                    missing_keys.append(f"{location} st.{name} braucht key=make_key(...).")
                record_literal_key(node, location, literal_keys)
                continue

            if name in LABEL_UNIQUE_CALLS:
                label = static_first_arg(node)
                if label:
                    static_labels[(name, label)].append(location)

    duplicate_literal_keys = [
        f"Key `{key}` doppelt in {', '.join(locations)}"
        for key, locations in literal_keys.items()
        if len(locations) > 1
    ]
    duplicate_static_labels = [
        f"st.{name} Label `{label}` mehrfach ohne dynamischen Prefix: {', '.join(locations)}"
        for (name, label), locations in static_labels.items()
        if len(locations) > 1
    ]

    problems = missing_keys + duplicate_literal_keys + duplicate_static_labels
    if problems:
        print("Streamlit key check FAILED")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("Streamlit key check OK")
    return 0


def streamlit_call_name(node: ast.Call) -> Optional[str]:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if is_streamlit_object(func.value):
        return func.attr
    return None


def is_streamlit_object(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "st"
    if isinstance(node, ast.Attribute):
        return is_streamlit_object(node.value)
    return False


def has_keyword(node: ast.Call, keyword: str) -> bool:
    return any(item.arg == keyword for item in node.keywords if item.arg)


def record_literal_key(node: ast.Call, location: str, literal_keys: dict[str, list[str]]) -> None:
    for item in node.keywords:
        if item.arg == "key" and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
            literal_keys[item.value.value].append(location)


def static_first_arg(node: ast.Call) -> Optional[str]:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
