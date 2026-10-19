"""Logging setup shared by the app and plugin loader."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths


def setup_logging(log_path: Path | None = None) -> Path:
    path = log_path or paths.log_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if getattr(root, "_quicktools_configured", False):
        return path
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # pythonw/windowed builds have no usable stderr. Only add a console
    # handler for real terminal sessions.
    if sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    root._quicktools_configured = True  # type: ignore[attr-defined]
    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
