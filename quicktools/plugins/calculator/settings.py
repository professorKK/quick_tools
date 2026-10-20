"""Persistent settings for the calculator plugin."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
SETTINGS_VERSION = 2
DEFAULT_SCIENTIFIC_MODE = False
DEFAULT_MAX_RECORDS = 200
MIN_MAX_RECORDS = 1
MAX_MAX_RECORDS = 5000


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILE


def load_settings(data_dir: Path | None) -> dict[str, Any]:
    if data_dir is None:
        return {}
    path = settings_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("读取计算器设置失败，使用默认值：%s", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def load_scientific_mode(data_dir: Path | None) -> bool:
    value = load_settings(data_dir).get("scientific_mode")
    return value if isinstance(value, bool) else DEFAULT_SCIENTIFIC_MODE


def normalize_max_records(value: Any) -> int:
    if isinstance(value, bool):
        return DEFAULT_MAX_RECORDS
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RECORDS
    return max(MIN_MAX_RECORDS, min(MAX_MAX_RECORDS, number))


def load_max_records(data_dir: Path | None) -> int:
    return normalize_max_records(load_settings(data_dir).get("max_records"))


def save_scientific_mode(data_dir: Path | None, enabled: bool) -> None:
    if data_dir is None:
        return
    raw = load_settings(data_dir)
    raw["version"] = SETTINGS_VERSION
    raw["scientific_mode"] = bool(enabled)
    atomic_write_json(settings_path(data_dir), raw)


def save_max_records(data_dir: Path | None, value: Any) -> int:
    normalized = normalize_max_records(value)
    if data_dir is None:
        return normalized
    raw = load_settings(data_dir)
    raw["version"] = SETTINGS_VERSION
    raw["max_records"] = normalized
    atomic_write_json(settings_path(data_dir), raw)
    return normalized


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
