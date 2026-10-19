from __future__ import annotations

from quicktools import paths


def test_native_tray_helper_is_packaged() -> None:
    helper = paths.package_dir() / "helpers" / "tray_appindicator.py"
    assert helper.is_file()
    assert "AyatanaAppIndicator3" in helper.read_text(encoding="utf-8")
    # Ensure the standalone helper is syntactically valid without importing GI.
    compile(helper.read_text(encoding="utf-8"), str(helper), "exec")


def test_native_tray_icon_asset_exists() -> None:
    assert (paths.assets_dir() / "tray-linux.png").is_file()
