"""xdg-desktop-portal Screenshot client built on jeepney."""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

from ..models import CaptureCancelled, CaptureUnavailable

log = logging.getLogger(__name__)

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_INTERFACE = "org.freedesktop.portal.Screenshot"
_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
_MAX_FILE_BYTES = 50 * 1024 * 1024


def expected_request_path(sender: str, token: str) -> str:
    safe_sender = sender.lstrip(":").replace(".", "_")
    safe_token = token.strip().replace("/", "_")
    return f"/org/freedesktop/portal/desktop/request/{safe_sender}/{safe_token}"


def build_options(
    token: str, *, interactive: bool, modal: bool = True
) -> dict[str, tuple[str, object]]:
    return {
        "handle_token": ("s", token),
        "interactive": ("b", bool(interactive)),
        "modal": ("b", bool(modal)),
    }


def _variant_value(value):
    if isinstance(value, tuple) and len(value) == 2:
        return value[1]
    return value


def parse_response(results: dict) -> Path:
    uri = _variant_value(results.get("uri"))
    if not isinstance(uri, str) or not uri:
        raise CaptureUnavailable("系统截图没有返回文件")
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise CaptureUnavailable("系统截图返回了不支持的文件地址")
    path = Path(unquote(parsed.path))
    if not path.is_file():
        raise CaptureUnavailable("系统截图文件不存在")
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise CaptureUnavailable("系统截图文件过大")
    except OSError as exc:
        raise CaptureUnavailable(f"无法读取系统截图文件：{exc}") from exc
    return path


class PortalScreenshotClient:
    def __init__(self, timeout_s: float = 120.0) -> None:
        self.timeout_s = timeout_s

    def capture(self, *, interactive: bool, modal: bool = True) -> bytes:
        """Ask the desktop portal for a screenshot and return PNG bytes."""
        try:
            from jeepney import DBusAddress, MatchRule, new_method_call
            from jeepney.io.blocking import open_dbus_connection, unwrap_msg
            from jeepney.wrappers import DBusErrorResponse
        except ImportError as exc:  # pragma: no cover - depends on runtime
            raise CaptureUnavailable(
                "Wayland 截图需要 jeepney；请重新安装 QuickTools 依赖"
            ) from exc

        try:
            connection = open_dbus_connection(bus="SESSION")
        except Exception as exc:
            raise CaptureUnavailable(f"无法连接桌面 portal：{exc}") from exc
        try:
            token = f"quicktools_{uuid.uuid4().hex}"
            request_path = expected_request_path(connection.unique_name, token)
            rule = MatchRule(
                type="signal",
                interface=_REQUEST_INTERFACE,
                member="Response",
                path=request_path,
            )
            address = DBusAddress(
                _PORTAL_PATH,
                bus_name=_PORTAL_BUS,
                interface=_PORTAL_INTERFACE,
            )
            with connection.filter(rule) as matches:
                message = new_method_call(
                    address,
                    "Screenshot",
                    "sa{sv}",
                    ("", build_options(token, interactive=interactive, modal=modal)),
                )
                try:
                    body = unwrap_msg(
                        connection.send_and_get_reply(message, timeout=10.0)
                    )
                except DBusErrorResponse as exc:
                    raise CaptureUnavailable(
                        f"桌面 portal 拒绝了截图请求：{exc}"
                    ) from exc
                handle = body[0] if body else request_path
                if handle and handle != request_path:
                    # Some portal versions return a different request path.
                    handle_rule = MatchRule(
                        type="signal",
                        interface=_REQUEST_INTERFACE,
                        member="Response",
                        path=handle,
                    )
                    with connection.filter(handle_rule) as handle_matches:
                        try:
                            signal = connection.recv_until_filtered(
                                handle_matches, timeout=self.timeout_s
                            )
                        except TimeoutError as exc:
                            raise CaptureUnavailable(
                                "等待系统截图超时"
                            ) from exc
                else:
                    try:
                        signal = connection.recv_until_filtered(
                            matches, timeout=self.timeout_s
                        )
                    except TimeoutError as exc:
                        raise CaptureUnavailable("等待系统截图超时") from exc
            response, results = signal.body
            if response == 1:
                raise CaptureCancelled("用户取消了系统截图")
            if response != 0:
                raise CaptureUnavailable(f"系统截图失败（响应码 {response}）")
            path = parse_response(results)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise CaptureUnavailable(f"读取系统截图失败：{exc}") from exc
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    if image.format != "PNG":
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        data = buffer.getvalue()
            except Exception as exc:
                raise CaptureUnavailable("系统截图文件不是有效图片") from exc
            return data
        finally:
            try:
                connection.close()
            except Exception:
                pass
