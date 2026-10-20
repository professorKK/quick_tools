from __future__ import annotations

from pathlib import Path

import pytest

from quicktools.plugins.screenshot.capture.portal import (
    build_options,
    expected_request_path,
    parse_response,
)
from quicktools.plugins.screenshot.models import CaptureUnavailable


def test_expected_request_path_sanitizes_sender() -> None:
    assert (
        expected_request_path(":1.42", "quicktools_abc")
        == "/org/freedesktop/portal/desktop/request/1_42/quicktools_abc"
    )


def test_build_options_uses_dbus_signatures() -> None:
    options = build_options("token", interactive=True, modal=False)
    assert options["handle_token"] == ("s", "token")
    assert options["interactive"] == ("b", True)
    assert options["modal"] == ("b", False)


def test_parse_response_accepts_file_uri(tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"png")
    assert parse_response({"uri": ("s", path.as_uri())}) == path
    assert parse_response({"uri": path.as_uri()}) == path


def test_parse_response_rejects_non_file_uri() -> None:
    with pytest.raises(CaptureUnavailable):
        parse_response({"uri": ("s", "https://example.com/shot.png")})


def test_parse_response_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CaptureUnavailable):
        parse_response({"uri": ("s", (tmp_path / "missing.png").as_uri())})


def test_parse_response_rejects_empty_results() -> None:
    with pytest.raises(CaptureUnavailable):
        parse_response({})
