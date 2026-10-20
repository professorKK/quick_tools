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
.venv/bin/python -m quicktools --screenshot region  # region/window/freeform/scroll/open

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
- `quicktools/app.py`：持有隐藏的 Tk 根窗口和生命周期。全局快捷键线程和 IPC 服务只把命令放入 `app.commands` 队列；状态栏子进程通过 IPC 与主实例通信。Tk 主线程每 50ms 调用 `_drain_commands()` 处理队列。**任何后台线程都不得直接操作 Tk 控件**，必须通过队列或 `root.after(...)` 回到主线程。`plugin <id> <action>` 命令会转给 `Launcher.dispatch_plugin_action()`；`hide_for_capture()` 统一隐藏启动器、设置窗口和插件窗口，并返回恢复回调。
- `quicktools/launcher.py`：启动器窗口、插件卡片、搜索和插件窗口管理。启动器每次显示时都会重新扫描插件；同一插件最多一个窗口；后台插件在整个应用生命周期内只保留一个实例。
- `quicktools/ipc.py`：单实例 IPC。Linux 使用 `$XDG_RUNTIME_DIR/quicktools-<uid>.sock`（回退 `/tmp`），Windows 使用 `127.0.0.1:50517`。支持 `toggle`、`show`、`settings`、`quit`、`ping`、`menu x y`，以及严格格式的 `plugin <id> <action>`（动作无负载，消息上限 64 字节）。
- `quicktools/paths.py`：配置/数据/日志/插件目录。`package_dir()` 同时处理源码与 PyInstaller `_MEIPASS`；内置插件和资源都从这里定位。
- `quicktools/config.py`：`settings.json` 目前只保存全局快捷键；开机启动状态以操作系统条目为准（`autostart.py`），不写入 settings。
- `quicktools/hotkey.py`：pynput 全局快捷键。Wayland 下不做应用内监听，只返回明确提示；系统快捷键应绑定到 `quicktools --toggle`。
- `quicktools/tray.py`：Linux 优先用系统 Python 启动 `helpers/tray_appindicator.py`（Ayatana AppIndicator/SNI），失败回退 pystray XEmbed + Tk 菜单；Windows 使用 pystray 原生托盘。状态栏运行在独立子进程，通过 IPC 控制主实例。
- `quicktools/settings_ui.py`：设置窗口、快捷键录制、开机启动开关、插件重新扫描。
- `quicktools/ui_theme.py`：共享配色、`pick_fonts()`、`Fonts.u()/m()`、`FlatButton`。`FlatButton` 基于 `tk.Label`，点击不会抢走输入框焦点，计算器键盘依赖这一点；它只在收到配套 `<ButtonPress>` 后于 `<ButtonRelease>` 执行命令，避免启动器卡片按下后新窗口收到遗留 release 造成幽灵点击（例如打开计算器时自动输入 `+`）。

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
- `settings.py`：计算器自己的 `settings.json`，保存“科学模式”和最大保存条数 `max_records`（默认 200，范围 1–5000）；默认关闭，文件损坏时回退默认值。`CalculatorView` 通过 `data_dir` 参数读写它，未传时只在内存中使用默认值，便于测试。
- `scratchpad_store.py`：草稿纸记忆持久化。`ScratchEntry(expression, base)` 记录每行表达式和输入进制，结果不落盘、恢复时用 `evaluate_live` + `format_result` 重算。`scratchpad.json` 结构为 `{version, last_base, rows:[{expression, base}]}`；只保留最新 `max_records` 条，空行/超长/非法行跳过，损坏文件回退空状态。
- `settings_view.py`：点击“草稿纸 · 设置”打开的模态弹窗，编辑最大保存条数、显示当前记忆数、清空全部记录（`messagebox.askyesno` 确认）。保存上限会立即调用视图裁剪。
- `view.py`：草稿纸 UI。首次打开时按持久化的 `scientific_mode` 决定布局；右上角“科学模式”开关调用 `_apply_scientific_mode()`，关闭时隐藏进制转换栏、进制选择行和 A-F 行并强制切回 DEC，开启时按“转换栏 → 进制选择 → 键盘”的 pack 顺序恢复。`ScratchRow._on_write()` 先归一化再按当前进制过滤，随后 `_update_live_result()` 实时显示 `= 结果` 并刷新进制转换栏；`Enter`/`=` 确认当前层，若它是最底层则新建下一层。转换栏顺序为 `BIN DEC / OCT HEX`，底部进制按键顺序为 `BIN OCT HEX DEC`，默认 DEC，选中进制整格高亮。
- 草稿纸记忆：`CalculatorView` 初始化时按 `max_records` 恢复行（逐行 `restore_expression()` 绕过当前进制过滤，用行内 base 求值），末尾始终补一行空输入行。输入/求值后 400ms 防抖保存；删除行、清空、修改上限立即保存。`<Destroy>` 必须用 `_scratchpad_state` 普通数据缓存同步 flush，因为 Tk 子控件在父 `<Destroy>` 之前已销毁。每行右侧 × 调 `delete_row()`，删除后重排 grid、激活邻近行并至少保留一行；`apply_max_records()` 调小上限时立即删除最旧的非空行。
- 修改行为时同步更新 `tests/test_engine.py`、`tests/test_calculator_settings.py`、`tests/test_calculator_scratchpad.py`、`tests/test_calculator_memory_ui.py`、`tests/test_ui_smoke.py`、`tests/test_flat_button.py` 和 README 计算器章节。

### 剪贴板（`quicktools/plugins/clipboard/`）

- `plugin.py`：`background: true` 插件，服务实例跨窗口复用；退出前调用 `flush_pending_edit()`。
- `service.py`：拥有后端、SQLite store 和去重/抑制逻辑。后端线程只把快照放入队列，数据库/图片写入和 UI 通知通过 `root.after` 在 Tk 主线程执行；自己的写回操作会在短时间内抑制记录，避免回环。相同内容按 digest 合并。
- `store.py`：SQLite（WAL）历史库 `history.db`，图片与缩略图分别存于插件数据目录的 `images/`、`thumbs/`。所有方法应在 Tk 主线程调用。
- `settings.py`：剪贴板插件自己的 `settings.json`（暂停记录、历史上限、图片上限、是否捕获图片/文件）。
- `backends/`：`base.py` 定义后端协议；`__init__.py` 按平台选择。Linux 在 Wayland 下使用 `wl-clipboard`，**不会静默回退到 X11**；X11 使用 XFixes/ICCCM；Windows 使用 ctypes 原生剪贴板。`models.py` 必须保持不依赖 Tk 和平台模块。
- 新增后端模块或后端导入新库时，检查 `QuickTools.spec` 的 `hiddenimports`，因为内置插件是运行时动态导入的，PyInstaller 无法静态发现。

### 截图（`quicktools/plugins/screenshot/`）

- 当前进度：核心动作链路、X11/Windows 矩形/窗口/自由/滚动截图、冻结画面选区、标注编辑窗口、最近截图库（搜索/筛选/收藏）、插件设置和截图快捷键已完成；控制窗口采用左侧导航（首页/关于/设置）+ 可点击模式卡，编辑器使用图标工具条。Wayland 通过 portal 支持区域/窗口截图，自由截图走“全屏 + 编辑器套索裁剪”，滚动截图不支持。Wayland 仍需实机验收。
- `plugin.py`：动作白名单为 `open`、`capture_region`、`capture_window`、`capture_freeform`、`capture_scroll`；`_hotkey_managers` 同时注册主快捷键和 `shortcuts.py` 中固定的 `Ctrl+Alt+1~4` 模式快捷键，单个注册失败不影响其他项；所有快捷键只通过 `context.actions.post_action()` 投递动作，不在 pynput 线程直接操作 Tk。
- `shortcuts.py`：`MODE_HOTKEYS` 是模式快捷键与卡片徽标的唯一来源，避免 UI 与注册逻辑漂移。
- `service.py`：负责隐藏窗口 → 抓屏 → 选区 → 编辑器 → 自动保存/复制/另存为/最近库的完整状态机；所有 Tk 操作在主线程，`stop_service()` 必须取消 after、销毁 overlay/editor、恢复窗口。`_autosave_image()` 把编辑器改动写入最近记录（`update_png` 同步原图和缩略图），并在该记录已有 `saved_path` 时覆盖对应文件。普通关闭丢弃 `_restore` 并调用 `actions.hide_windows()`，确保从最近截图打开编辑器等场景也不留下可见窗口；`_editor_closed(return_to_assistant=True)` 必须先 `_restore_windows()` 再 `actions.open_window()` 并调用 `_notify_recent_changed()`，以恢复并聚焦截图助手、强制刷新最近截图列表（窗口一直可见时不会触发 `<Map>`）。
- `capture/`：`x11.py` 用 python-xlib 抓根窗口并通过 XRandR 枚举显示器；`windows.py` 用 Pillow ImageGrab + ctypes 虚拟屏幕/窗口枚举；`wayland.py` 通过 `portal.py`（jeepney）调用 `org.freedesktop.portal.Screenshot`，区域/窗口用交互选择器，自由截图用非交互全屏后由编辑器套索裁剪；**Wayland 不做 X11 回退**。滚动截图只支持 Windows/X11。
- `scroll/`：`stitcher.py` 用纯 Pillow 做缩小灰度重叠检测和纵向拼接（`ImageChops`/`ImageStat`，不引入 numpy/OpenCV）；`controller.py` 在 worker 线程用新采集后端执行滚动/抓帧，通过队列回到主线程控制条。X11 用 XTest 滚轮，Windows 用 `SendInput`；Wayland capabilities 中 `scrolling=False`。滚动截图是 best-effort，低置信度时停止而不是拼垃圾。
- `selection/overlay.py`：显示器级冻结画面覆盖层；矩形拖拽、窗口高亮点击、自由套索三种模式。窗口模式在 X11/Windows 上用后端枚举窗口，被遮挡时由 service 抬升并重新抓屏；自由套索用 `editor/mask.py` 生成抗锯齿透明边缘。
- `editor/`：对象模型标注编辑器。`annotations.py` 定义 `Tool`/`Style`/`Annotation`；`document.py` 负责增删改、撤销/重做、裁剪/旋转/翻转和导出；`render.py` 用 Pillow 在原始分辨率合成；`canvas.py` 是 Tk 交互画布，只渲染当前可见区域以支持滚轮缩放/中键平移，也支持空格+左键拖动以及选择工具下空白处拖动平移；`toolbar.py` 提供工具/颜色/线宽/字号。**标注对象不直接烘焙到图片**，自动保存、复制或另存为时才 `render()`。
- 文字输入用无边框 `tk.Entry`，背景采样点击位置附近的图像颜色以尽量融入截图；Entry 字体使用负数字号（像素），与 Pillow 导出字号一致。FocusOut/点击画布/切换工具时提交，Escape 取消。工具栏 A-/A+ 不抢焦点，可在输入过程中实时调整字号；提交后文字自动选中，字号框继续生效。
- `canvas.py` 的“适应”按窗口等比缩放（可放大也可缩小），“1:1”回到 100%；裁剪工具在图片四边/四角显示控制点，拖动边或角调整裁剪区域，Enter 应用、Esc 取消；工具栏“重置”恢复原始图片，“重做”在无可重做操作时回退到重置。
- `editor/annotations.py`：`coerce_tool()` 按值归一化工具枚举，避免插件动态加载产生重复模块树时 Enum 身份不一致。
- `editor/fonts.py`：用系统 CJK 字体（Noto/WQY/微软雅黑等）渲染文字；找不到字体时编辑窗口显示提示。
- `editor/` 必须提供矩形和圆形/椭圆空心圈选（默认不填充）、箭头、自由画笔、文字、序号、马赛克、贴纸、水印、裁剪/旋转。画笔用 `Annotation.points` 保存路径，渲染时用 `brush_bounds()` 计算包围盒，并支持平移/旋转/翻转/裁剪和撤销重做。
- `recent/store.py`：SQLite WAL + `images/`/`thumbs/`，参考剪贴板 store 的原子写入、缩略图、路径包含校验和裁剪策略。`shots` 表含 `favorite` 列；启动时用 `PRAGMA table_info` 幂等迁移旧库（`ALTER TABLE`），`PRAGMA user_version=2`。`list()` 支持 `favorite`/`mode` 筛选，`set_favorite()`/`toggle_favorite()` 不修改 `updated_at`。
- `ui/control_window.py` + `ui/home_page.py` + `ui/about_page.py` + `ui/recent_view.py`：控制窗口为左侧导航（首页/关于/设置）+ 右侧页面容器；页面容器行 `weight=1`，页脚和状态行固定。首页包含可点击模式卡和最近截图区，最近截图行是 HomePage 中唯一 `weight=1` 的行。关于页读取 `plugin.json` 版本并展示能力、快捷键和文件位置。最近截图使用 `ui/widgets.py` 的 `ScrollableFrame`、`PlaceholderEntry`、`ActionLink`、`FilterMenu` 和 `ColorSwatch`；搜索与筛选叠加，复制/收藏等操作用 toast 反馈。
- `ui/icons.py`：Pillow 在 24×24 逻辑网格上绘制图标并 4 倍超采样；`IconSet` 按 `(名称, 像素尺寸, 颜色)` 缓存 `ImageTk.PhotoImage`，并在宿主 `<Destroy>` 时清空。**所有 PhotoImage 必须由 IconSet 或控件属性持有，且只能在 Tk 主线程创建**。Tk 不支持圆角容器，圆角只用于 Pillow 生成的图标底板/装饰卡。
- `editor/editor_window.py`：工具栏使用 `IconSet` 的图标在上、文字在下布局；复制成功后显示右下角 toast 并短暂把复制按钮改为“已复制 ✓”；另存为/`Ctrl+S` 也显示 toast。**底部不再有“保存”按钮**；文档修改后经 `AUTOSAVE_DELAY_MS`（400ms）防抖调用 `on_autosave`，`_request_close()` 必须先 `_flush_autosave()`，确保关闭前的最后一次修改已落库；`_autosave()` 成功后将 `_done=True` 并 `mark_exported()`。所有 after 任务（含 `_autosave_job`）在关闭时取消。**必须保留 `_copy_button` 文字闪烁为精确的“已复制 ✓”、`_close_return_button` 文本精确为“关闭并返回”、`_zoom_var` 的 `缩放 N%` 格式、`toolbar.width_var`/`font_size_var` 和 `toolbar._redo_or_reset`**，现有 UI 测试依赖这些契约。`close_and_return()` 通过可选 `on_return` 回调通知 service；`close()`、标题栏 X 和 `Esc` 仍走 `on_close`。关闭确认基于 `document.content_signature()` 与 `mark_exported()` 记录的基线比较：`require_action_on_close=True`（新截图）时未导出也会确认，`False`（最近截图）时仅在有未保存修改时确认；`copy()`/`save()`/`save_as()`/自动保存成功后必须调用 `mark_exported()`。
- 复制图片走 `context.actions.copy_png_to_clipboard(png)`，由 launcher 转给剪贴板插件的 `copy_image_png()`；**不要从截图插件 import 剪贴板插件模块**，否则会生成重复模块树和后端实例。
- 选区覆盖鼠标所在显示器；V1 不做跨显示器拖拽。Windows 混合 DPI 多屏仅做了 Win32 负坐标定位兜底，仍需实机验收。
- 新增采集/portal 依赖时，同步更新 `QuickTools.spec` hiddenimports、`pyproject.toml` 和 `requirements.txt`。

## 测试与平台约定

- `tests/test_ui_smoke.py`、`tests/test_calculator_memory_ui.py`、`tests/test_flat_button.py`、`tests/test_clipboard_ui_smoke.py`、`tests/test_plugin_lifecycle.py`、`tests/test_screenshot_ui_smoke.py` 需要可用显示；无 `DISPLAY` 时 skip。
- `tests/test_clipboard_windows.py` 只在 Windows 上运行；Linux 下 skip。截图 Windows 路径目前没有自动化实机测试，需按 README 清单验收。
- 剪贴板服务测试使用 `FakeBackend`/`FakeRoot`，不依赖真实系统剪贴板；引擎测试只依赖 `engine.py`。
- 截图测试：几何/标注/渲染/拼接/设置/最近库/portal/图标绘制/快捷键注册为纯逻辑测试；`test_screenshot_service.py` 用 `FakeRoot`/FakeBackend/FakeOverlay/FakeEditor 测状态机；`test_screenshot_ui_smoke.py` 覆盖画笔绘制、空格+左键平移、选择工具空白处平移、自动保存和关闭前 flush；`test_screenshot_service.py` 覆盖自动保存更新最近记录/缩略图、同步覆盖已导出文件以及返回时刷新最近列表；`test_screenshot_control_window.py` 和 `test_screenshot_backends.py` 的 X11 用例、`test_screenshot_icons.py` 的 IconSet 用例需要显示。Wayland portal 只用 fake 客户端验证，真实 portal 必须按 README 在 Wayland 实机验收。
- 当前实测通过的是 Linux X11；Windows 和 Wayland 代码路径已适配但仍需实机验收，清单见 README。
- 日志位置：Linux `~/.local/share/quicktools/logs/quicktools.log`，Windows `%APPDATA%\QuickTools\logs\quicktools.log`。打包版 Linux 用 `--foreground` 可实时打印日志。
