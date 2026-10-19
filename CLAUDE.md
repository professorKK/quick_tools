# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 文档同步（硬性要求）

每次修改功能、行为、命令、配置格式或插件契约时，必须在同一次改动中检查并更新对应说明文件。禁止出现“功能代码已改、说明文件仍描述旧行为”的情况。

| 改动内容 | 必须检查的说明文件 |
| --- | --- |
| 用户可见功能/操作方式（计算器、剪贴板、CLI、平台限制） | `README.md` |
| 插件清单字段、`PluginBase` 生命周期、`background` 语义、API 版本 | `docs/PLUGIN_GUIDE.md` |
| 图标资源或生成方式 | `quicktools/assets/README.md` |
| 内置插件在启动器卡片上的名称/描述 | 对应 `plugin.json` |
| 开发命令、架构、工作流 | 本文件 `CLAUDE.md` |

提交前搜索旧文案（状态栏提示、README 按键说明、插件描述等），确认没有遗留过时描述。所有面向用户的界面文本、日志和文档使用中文。

## 常用命令

环境要求：Python 3.10+、Tkinter。依赖和 pytest 配置见 `pyproject.toml`。

```bash
# 安装（可编辑 + 测试依赖）
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# 源码运行 / CLI
./run.sh                                  # Linux
run.bat                                   # Windows（pythonw，无控制台）
.venv/bin/python -m quicktools            # 直接运行
.venv/bin/python -m quicktools --foreground
.venv/bin/python -m quicktools --toggle   # 还有 --show / --background / --quit

# 测试（当前 Ubuntu 环境必须禁用 pytest 插件自动加载）
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q

# 单个测试
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/pytest tests/test_engine.py::test_arithmetic -q

# 重新生成图标资源
.venv/bin/python scripts/prepare_assets.py

# 打包（PyInstaller，产出 dist/QuickTools/）
./build_linux.sh
build_windows.bat
```

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于避开系统 ROS 注入的 pytest 插件；干净环境可省略。
- `DISPLAY` 是 Tk 冒烟测试必需的；没有显示环境时相关测试会自动 skip。
- 未配置 lint/format 检查步骤，`pyproject.toml` 只配置了 pytest。
- 打包必须使用项目的 `QuickTools.spec`；Windows 包只能在 Windows 上构建。
- 仓库提交信息格式为 `YYMMDD: 描述`（如 `261019: 新增加了开机自启动开关`）；`./git-update.sh 描述` 会按此格式执行 `git add .` 并提交。仅在用户明确要求提交时使用。

## 运行时架构

- `quicktools/__main__.py`：CLI 入口。先做单实例 IPC 预检，再创建 `QuickToolsApp`。Linux 打包版在终端启动时会自动脱离终端（`--foreground` 可禁用）。
- `quicktools/app.py`：持有隐藏的 Tk 根窗口和生命周期。全局快捷键线程和 IPC 服务只把命令放入 `app.commands` 队列；状态栏子进程通过 IPC 与主实例通信。Tk 主线程每 50ms 调用 `_drain_commands()` 处理队列。**任何后台线程都不得直接操作 Tk 控件**，必须通过队列或 `root.after(...)` 回到主线程。
- `quicktools/launcher.py`：启动器窗口、插件卡片、搜索和插件窗口管理。启动器每次显示时都会重新扫描插件；同一插件最多一个窗口；后台插件在整个应用生命周期内只保留一个实例。
- `quicktools/ipc.py`：单实例 IPC。Linux 使用 `$XDG_RUNTIME_DIR/quicktools-<uid>.sock`（回退 `/tmp`），Windows 使用 `127.0.0.1:50517`。支持 `toggle`、`show`、`settings`、`quit`、`ping`、`menu x y`。
- `quicktools/paths.py`：配置/数据/日志/插件目录。`package_dir()` 同时处理源码与 PyInstaller `_MEIPASS`；内置插件和资源都从这里定位。
- `quicktools/config.py`：`settings.json` 目前只保存全局快捷键；开机启动状态以操作系统条目为准（`autostart.py`），不写入 settings。
- `quicktools/hotkey.py`：pynput 全局快捷键。Wayland 下不做应用内监听，只返回明确提示；系统快捷键应绑定到 `quicktools --toggle`。
- `quicktools/tray.py`：Linux 优先用系统 Python 启动 `helpers/tray_appindicator.py`（Ayatana AppIndicator/SNI），失败回退 pystray XEmbed + Tk 菜单；Windows 使用 pystray 原生托盘。状态栏运行在独立子进程，通过 IPC 控制主实例。
- `quicktools/settings_ui.py`：设置窗口、快捷键录制、开机启动开关、插件重新扫描。
- `quicktools/ui_theme.py`：共享配色、`pick_fonts()`、`Fonts.u()/m()`、`FlatButton`。`FlatButton` 基于 `tk.Label`，点击不会抢走输入框焦点，计算器键盘依赖这一点。

## 插件系统

- `quicktools/plugin_loader.py`：启动时只读取并校验 `plugin.json`，点击卡片时才懒加载入口代码。入口以合成包名（`_quicktools_plugin_<id>_<generation>`）导入，因此插件目录内可使用相对导入。重新扫描会使旧模块失效。
- 扫描顺序是内置插件在前、用户插件在后；重复 `id` 时内置插件优先，用户插件被忽略并记录错误。插件按 `(order, name, id)` 排序。
- `quicktools/plugin_api.py` 是稳定契约：`PluginMeta`、`PluginContext`、`PluginBase`。
- 普通插件：窗口首次打开时创建新实例并调用 `create_ui(window)`；关闭窗口后再开是新实例。
- `background: true` 的插件：应用启动扫描后立即创建唯一实例并调用 `start_service()`；窗口可反复打开关闭，`stop_service()` 只在退出、插件删除或版本/目录变化时调用。服务必须幂等，且线程不能直接碰 Tk。
- 完整契约和示例见 `docs/PLUGIN_GUIDE.md` 与 `examples/hello_plugin/`。

## 内置插件

### 计算器（`quicktools/plugins/calculator/`）

- `engine.py`：纯 Python 递归下降解析器，不使用 `eval`；支持 `0x/0b/0o` 前缀、整数/浮点、`//`、`%`、`^`/`**`。`evaluate()` 是严格求值；`evaluate_live()` 用于输入过程，悬空的 `+`/`-` 补 `0`，`*`/`/`/`//`/`%` 补 `1`，但 `^`/`**` 和括号不匹配仍不可计算；`filter_input()` 按进制过滤键入/粘贴字符。
- `view.py`：草稿纸 UI。`ScratchRow._on_write()` 先归一化再按当前进制过滤，随后 `_update_live_result()` 实时显示 `= 结果` 并刷新进制转换栏；`Enter`/`=` 确认当前层，若它是最底层则新建下一层。转换栏顺序为 `BIN DEC / OCT HEX`，底部进制按键顺序为 `BIN OCT HEX DEC`，默认 DEC，选中进制整格高亮。
- 修改行为时同步更新 `tests/test_engine.py`、`tests/test_ui_smoke.py` 和 README 计算器章节。

### 剪贴板（`quicktools/plugins/clipboard/`）

- `plugin.py`：`background: true` 插件，服务实例跨窗口复用；退出前调用 `flush_pending_edit()`。
- `service.py`：拥有后端、SQLite store 和去重/抑制逻辑。后端线程只把快照放入队列，数据库/图片写入和 UI 通知通过 `root.after` 在 Tk 主线程执行；自己的写回操作会在短时间内抑制记录，避免回环。相同内容按 digest 合并。
- `store.py`：SQLite（WAL）历史库 `history.db`，图片与缩略图分别存于插件数据目录的 `images/`、`thumbs/`。所有方法应在 Tk 主线程调用。
- `settings.py`：剪贴板插件自己的 `settings.json`（暂停记录、历史上限、图片上限、是否捕获图片/文件）。
- `backends/`：`base.py` 定义后端协议；`__init__.py` 按平台选择。Linux 在 Wayland 下使用 `wl-clipboard`，**不会静默回退到 X11**；X11 使用 XFixes/ICCCM；Windows 使用 ctypes 原生剪贴板。`models.py` 必须保持不依赖 Tk 和平台模块。
- 新增后端模块或后端导入新库时，检查 `QuickTools.spec` 的 `hiddenimports`，因为内置插件是运行时动态导入的，PyInstaller 无法静态发现。

## 测试与平台约定

- `tests/test_ui_smoke.py`、`tests/test_clipboard_ui_smoke.py`、`tests/test_plugin_lifecycle.py` 需要可用显示；无 `DISPLAY` 时 skip。
- `tests/test_clipboard_windows.py` 只在 Windows 上运行；Linux 下 skip。
- 剪贴板服务测试使用 `FakeBackend`/`FakeRoot`，不依赖真实系统剪贴板；引擎测试只依赖 `engine.py`。
- 当前实测通过的是 Linux X11；Windows 代码路径已适配但仍需实机验收，清单见 README。
- 日志位置：Linux `~/.local/share/quicktools/logs/quicktools.log`，Windows `%APPDATA%\QuickTools\logs\quicktools.log`。打包版 Linux 用 `--foreground` 可实时打印日志。
