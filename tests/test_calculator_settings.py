from __future__ import annotations

import json
from pathlib import Path

from quicktools.plugins.calculator.settings import (
    DEFAULT_MAX_RECORDS,
    DEFAULT_RESULT_GROUP_SIZE,
    DEFAULT_SCIENTIFIC_MODE,
    MAX_MAX_RECORDS,
    MAX_RESULT_GROUP_SIZE,
    MIN_MAX_RECORDS,
    SETTINGS_VERSION,
    load_max_records,
    load_result_group_size,
    load_scientific_mode,
    normalize_max_records,
    normalize_result_group_size,
    save_max_records,
    save_result_group_size,
    save_scientific_mode,
    settings_path,
)


def test_scientific_mode_defaults_to_off(tmp_path: Path) -> None:
    assert DEFAULT_SCIENTIFIC_MODE is False
    assert load_scientific_mode(tmp_path) is False
    assert load_scientific_mode(None) is False


def test_scientific_mode_roundtrip(tmp_path: Path) -> None:
    save_scientific_mode(tmp_path, True)
    assert load_scientific_mode(tmp_path) is True
    payload = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["version"] == SETTINGS_VERSION
    assert payload["scientific_mode"] is True

    save_scientific_mode(tmp_path, False)
    assert load_scientific_mode(tmp_path) is False


def test_max_records_defaults_and_range(tmp_path: Path) -> None:
    assert DEFAULT_MAX_RECORDS == 200
    assert load_max_records(tmp_path) == DEFAULT_MAX_RECORDS
    assert load_max_records(None) == DEFAULT_MAX_RECORDS
    assert normalize_max_records(0) == MIN_MAX_RECORDS
    assert normalize_max_records(-5) == MIN_MAX_RECORDS
    assert normalize_max_records(MAX_MAX_RECORDS + 1) == MAX_MAX_RECORDS
    assert normalize_max_records("300") == 300
    assert normalize_max_records(True) == DEFAULT_MAX_RECORDS
    assert normalize_max_records("nope") == DEFAULT_MAX_RECORDS
    assert normalize_max_records(None) == DEFAULT_MAX_RECORDS


def test_max_records_roundtrip_and_preserves_other_settings(
    tmp_path: Path,
) -> None:
    assert save_max_records(tmp_path, 120) == 120
    assert load_max_records(tmp_path) == 120

    save_scientific_mode(tmp_path, True)
    assert load_max_records(tmp_path) == 120
    assert load_scientific_mode(tmp_path) is True

    assert save_max_records(tmp_path, 80) == 80
    assert load_scientific_mode(tmp_path) is True
    assert load_max_records(tmp_path) == 80

    payload = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["version"] == SETTINGS_VERSION
    assert payload["scientific_mode"] is True
    assert payload["max_records"] == 80


def test_result_group_size_defaults_and_range(tmp_path: Path) -> None:
    assert DEFAULT_RESULT_GROUP_SIZE == 0
    assert load_result_group_size(tmp_path) == 0
    assert load_result_group_size(None) == 0
    assert normalize_result_group_size(3) == 3
    assert normalize_result_group_size(-1) == 0
    assert normalize_result_group_size(MAX_RESULT_GROUP_SIZE + 1) == (
        MAX_RESULT_GROUP_SIZE
    )
    assert normalize_result_group_size("4") == 4
    assert normalize_result_group_size(True) == 0
    assert normalize_result_group_size("nope") == 0
    assert normalize_result_group_size(None) == 0


def test_result_group_size_roundtrip_and_preserves_other_settings(
    tmp_path: Path,
) -> None:
    save_scientific_mode(tmp_path, True)
    save_max_records(tmp_path, 120)
    assert save_result_group_size(tmp_path, 3) == 3
    assert load_result_group_size(tmp_path) == 3
    assert load_scientific_mode(tmp_path) is True
    assert load_max_records(tmp_path) == 120

    payload = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["version"] == SETTINGS_VERSION
    assert payload["scientific_mode"] is True
    assert payload["max_records"] == 120
    assert payload["result_group_size"] == 3


def test_corrupt_settings_fall_back_to_default(tmp_path: Path) -> None:
    settings_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_scientific_mode(tmp_path) is False
    assert load_max_records(tmp_path) == DEFAULT_MAX_RECORDS
    # Saving over a corrupt file should recover.
    save_scientific_mode(tmp_path, True)
    save_max_records(tmp_path, 50)
    assert load_scientific_mode(tmp_path) is True
    assert load_max_records(tmp_path) == 50
