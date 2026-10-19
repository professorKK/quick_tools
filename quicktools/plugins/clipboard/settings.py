"""Per-plugin settings stored next to the clipboard database."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import ClipboardError

SETTINGS_NAME = "settings.json"
MIN_ENTRIES = 50
MAX_ENTRIES = 5000
MIN_IMAGE_MB = 10
MAX_IMAGE_MB = 2000


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@dataclass
class ClipboardSettings:
    recording: bool = True
    max_entries: int = 500
    max_image_mb: int = 200
    capture_images: bool = True
    capture_files: bool = True

    def normalized(self) -> "ClipboardSettings":
        return ClipboardSettings(
            recording=bool(self.recording),
            max_entries=_clamp_int(self.max_entries, 500, MIN_ENTRIES, MAX_ENTRIES),
            max_image_mb=_clamp_int(
                self.max_image_mb, 200, MIN_IMAGE_MB, MAX_IMAGE_MB
            ),
            capture_images=bool(self.capture_images),
            capture_files=bool(self.capture_files),
        )

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_mb * 1024 * 1024

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_NAME


def load_settings(data_dir: Path) -> ClipboardSettings:
    path = settings_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ClipboardSettings()
    except (OSError, json.JSONDecodeError):
        return ClipboardSettings()
    if not isinstance(raw, dict):
        return ClipboardSettings()
    defaults = ClipboardSettings()
    return ClipboardSettings(
        recording=raw.get("recording", defaults.recording)
        if isinstance(raw.get("recording", defaults.recording), bool)
        else defaults.recording,
        max_entries=_clamp_int(
            raw.get("max_entries"), defaults.max_entries, MIN_ENTRIES, MAX_ENTRIES
        ),
        max_image_mb=_clamp_int(
            raw.get("max_image_mb"), defaults.max_image_mb, MIN_IMAGE_MB, MAX_IMAGE_MB
        ),
        capture_images=raw.get("capture_images", defaults.capture_images)
        if isinstance(raw.get("capture_images", defaults.capture_images), bool)
        else defaults.capture_images,
        capture_files=raw.get("capture_files", defaults.capture_files)
        if isinstance(raw.get("capture_files", defaults.capture_files), bool)
        else defaults.capture_files,
    )


def save_settings(data_dir: Path, settings: ClipboardSettings) -> None:
    """Atomically persist settings; failures are surfaced to the caller."""
    settings = settings.normalized()
    target = settings_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(settings.to_json())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ClipboardError(f"保存设置失败：{exc}") from exc
