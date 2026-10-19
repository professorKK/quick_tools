"""Discover and lazily import QuickTools plugins."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Type

from .logging_setup import get_logger
from .plugin_api import PluginBase, PluginError, PluginMeta

log = get_logger(__name__)

API_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REQUIRED_STRINGS = ("name", "version", "entry", "class")


def _manifest_error(folder: Path, message: str) -> str:
    return f"{folder.name}: {message}"


def _read_manifest(folder: Path, builtin: bool) -> PluginMeta:
    manifest_path = folder / "plugin.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PluginError("缺少 plugin.json") from None
    except json.JSONDecodeError as exc:
        raise PluginError(f"plugin.json 格式错误：{exc.msg}") from None
    except OSError as exc:
        raise PluginError(f"无法读取 plugin.json：{exc}") from None

    if not isinstance(raw, dict):
        raise PluginError("plugin.json 根节点必须是对象")
    if raw.get("api_version") != API_VERSION:
        raise PluginError(f"插件 API 版本必须为 {API_VERSION}")

    plugin_id = raw.get("id")
    if not isinstance(plugin_id, str) or not _ID_RE.fullmatch(plugin_id):
        raise PluginError("id 必须是小写字母/数字/下划线/短横线，长度 1-64")

    for field in _REQUIRED_STRINGS:
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise PluginError(f"字段 {field} 必须是非空字符串")

    class_name = raw["class"].strip()
    if not _CLASS_RE.fullmatch(class_name):
        raise PluginError("class 必须是合法的 Python 类名")

    entry_raw = raw["entry"].strip()
    entry = (folder / entry_raw).resolve()
    root = folder.resolve()
    try:
        entry.relative_to(root)
    except ValueError:
        raise PluginError("entry 不能指向插件目录之外") from None
    if not entry.is_file():
        raise PluginError(f"入口文件不存在：{entry_raw}")
    if entry.suffix.lower() != ".py":
        raise PluginError("entry 必须是 .py 文件")

    icon = raw.get("icon", "◆")
    if not isinstance(icon, str):
        icon = "◆"
    description = raw.get("description", "")
    if not isinstance(description, str):
        description = ""
    order_raw = raw.get("order", 100)
    if isinstance(order_raw, bool) or not isinstance(order_raw, (int, float)):
        order = 100
    else:
        order = int(order_raw)
    background = raw.get("background") is True

    return PluginMeta(
        id=plugin_id,
        name=raw["name"].strip(),
        description=description.strip(),
        version=raw["version"].strip(),
        entry=entry_raw,
        class_name=class_name,
        folder=folder.resolve(),
        icon=icon,
        order=order,
        builtin=builtin,
        background=background,
    )


class PluginLoader:
    """Scans metadata eagerly and imports plugin code only when opened."""

    def __init__(self, user_plugins: Path, builtin_plugins: Path) -> None:
        self.user_plugins = user_plugins
        self.builtin_plugins = builtin_plugins
        self.errors: list[str] = []
        self._generation = 0
        self._classes: dict[str, Type[PluginBase]] = {}
        self._modules: dict[str, str] = {}

    def scan(self) -> list[PluginMeta]:
        self.errors = []
        self._invalidate()
        self._generation += 1
        plugins: list[PluginMeta] = []
        seen: set[str] = set()

        roots = (
            (self.builtin_plugins, True),
            (self.user_plugins, False),
        )
        for root, builtin in roots:
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if not folder.is_dir() or folder.name.startswith("."):
                    continue
                if not (folder / "plugin.json").is_file():
                    continue
                try:
                    meta = _read_manifest(folder, builtin)
                except PluginError as exc:
                    message = _manifest_error(folder, str(exc))
                    self.errors.append(message)
                    log.warning("插件发现失败：%s", message)
                    continue
                if meta.id in seen:
                    message = _manifest_error(
                        folder, f"插件 id '{meta.id}' 重复，已忽略"
                    )
                    self.errors.append(message)
                    log.warning(message)
                    continue
                seen.add(meta.id)
                plugins.append(meta)

        plugins.sort(key=lambda p: (p.order, p.name.casefold(), p.id))
        return plugins

    def load_class(self, meta: PluginMeta) -> Type[PluginBase]:
        cached = self._classes.get(meta.id)
        if cached is not None:
            return cached

        module_name = f"_quicktools_plugin_{meta.id}_{self._generation}"
        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                meta.folder / meta.entry,
                submodule_search_locations=[str(meta.folder)],
            )
            if spec is None or spec.loader is None:
                raise PluginError("无法创建插件模块")
            module: ModuleType = importlib.util.module_from_spec(spec)
            module.__package__ = module_name
            sys.modules[module_name] = module
            self._modules[meta.id] = module_name
            spec.loader.exec_module(module)
            plugin_class = getattr(module, meta.class_name, None)
            if plugin_class is None:
                raise PluginError(f"入口文件中找不到类 {meta.class_name}")
            if not isinstance(plugin_class, type) or not issubclass(
                plugin_class, PluginBase
            ):
                raise PluginError(
                    f"类 {meta.class_name} 必须继承 quicktools.plugin_api.PluginBase"
                )
        except PluginError:
            self._forget_module(meta.id)
            raise
        except Exception as exc:
            self._forget_module(meta.id)
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            log.exception("插件 %s 加载失败", meta.id)
            raise PluginError(detail) from exc

        self._classes[meta.id] = plugin_class
        return plugin_class

    def _forget_module(self, plugin_id: str) -> None:
        module_name = self._modules.pop(plugin_id, None)
        if module_name:
            sys.modules.pop(module_name, None)

    def _invalidate(self) -> None:
        for module_name in list(self._modules.values()):
            sys.modules.pop(module_name, None)
        self._modules.clear()
        self._classes.clear()
