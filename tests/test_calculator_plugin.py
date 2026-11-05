from __future__ import annotations

from types import SimpleNamespace

import pytest

from quicktools.plugins.calculator import plugin as calculator_plugin


def test_calculator_requires_pyqt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The calculator has no Tk fallback; missing PyQt6 is a hard error."""
    monkeypatch.setattr(calculator_plugin, "qt_available", lambda: False)
    instance = calculator_plugin.CalculatorPlugin(
        SimpleNamespace(data_dir=None)
    )
    with pytest.raises(RuntimeError, match="PyQt6"):
        instance.create_ui(None)
