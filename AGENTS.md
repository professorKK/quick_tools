# AGENTS.md

常驻后台的跨平台桌面插件启动器：全局快捷键唤出启动器，内置草稿纸计算器（独立 PyQt6 进程）、剪贴板历史与截图工具（Tkinter），并支持用 Python 编写自己的插件。面向 Linux（X11）与 Windows，Wayland 仅部分支持。

> **本文件是 Agent 的工作契约，不是项目百科。**
> 深度细节（模块级职责、每个插件的字段语义、回归历史）在仓库根目录 `CLAUDE.md`；用户可见行为与实机验收清单在 `README.md`；插件契约在 `docs/PLUGIN_GUIDE.md`。
> 改动前先读 `CLAUDE.md` 对应章节，改完后按“文档同步”表检查说明文件。

## Setup commands

- 安装依赖：`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- 源码运行：`./run.sh`（Linux）/ `run.bat`（Windows，pythonw 无控制台）/ `.venv/bin/python -m quicktools`
- CLI：`.venv/bin/python -m quicktools --toggle|--show|--quit|--foreground|--screenshot region|window|freeform|scroll|open`
- 打包：Linux `./build_linux.sh` → `dist/linux/QuickTools/`；Windows `build_windows.bat` / `build_all.bat` → `dist/win/`（必须用 `QuickTools.spec` 或 `QuickTools-onefile.spec`；Windows 包只能在 Windows 构建，Linux 脚本在 Linux 上构建）
- 测试：`DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q`
- 单个用例：`DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest tests/test_engine.py::test_arithmetic -q`
- 重新生成图标资源：`.venv/bin/python scripts/prepare_assets.py`
- Lint / Typecheck：未配置（`pyproject.toml` 只配了 pytest），不要顺手引入新工具

## Project layout

- `quicktools/` — 主程序：启动器、单实例 IPC、全局快捷键、托盘、无边框窗口框架、共享设置 UI
- `quicktools/plugins/` — 内置插件：`calculator/`（PyQt6，独立进程）、`clipboard/`、`screenshot/`、`gp/`（PyQt6 圆形悬浮窗，独立进程）
- `quicktools/assets/` — 图标与内置 Material Icons 字体（说明见 `quicktools/assets/README.md`）
- `quicktools/helpers/` — 托盘状态栏子进程（AppIndicator）
- `tests/` — pytest 测试，命名 `test_*.py`；`tests/qt_calculator_cases.py` 是 Qt 子进程用例
- `docs/PLUGIN_GUIDE.md` — 插件开发指南：清单字段、生命周期、设置页接入
- `examples/hello_plugin/` — 最小插件模板
- `scripts/` — 资源生成脚本与启动器脚本
- `build_linux.sh` / `build_windows.bat` / `build_all.bat` / `installer.iss` / `QuickTools*.spec` — 打包链路
- `dist/`、`build/` — 分发产物与中间文件，已被 git 忽略；不要往 `dist/` 里放中间文件

## 架构地图

主进程是 Tk。命令一律排队后在 Tk 主线程执行。

- `quicktools/__main__.py` — CLI 入口；先做单实例 IPC 预检再建 `QuickToolsApp`；隐藏参数 `--calculator-qt-helper --data-dir <dir>` 在创建 Tk 应用前分派给计算器 helper，`--gp-qt-helper --data-dir <dir> --plugin-dir <dir>` 分派给 gp 悬浮窗 helper
- `quicktools/app.py` — 隐藏的 Tk 根窗口 + 生命周期；全局快捷键回调与 IPC 只把命令塞进 `app.commands` 队列，主线程每 50ms `_drain_commands()`
- `quicktools/launcher.py` — 启动器窗口、插件卡片、搜索、插件窗口管理、窗口尺寸恢复
- `quicktools/ipc.py` — 单实例 IPC：Linux 用 unix socket（`$XDG_RUNTIME_DIR/quicktools-<uid>.sock`，回退 `/tmp`），Windows 用 `127.0.0.1:50517`；命令 `toggle`/`show`/`settings`/`quit`/`ping`/`menu x y`/`plugin <id> <action>`
- `quicktools/hotkey.py` + `win32_hotkey.py` — 全局快捷键；Windows 优先原生 `RegisterHotKey`（主线程回调，同时是拿到前台激活权限的关键），失败回退 pynput；Wayland 不做应用内监听
- `quicktools/tray.py` + `helpers/tray_appindicator.py` — 托盘/顶栏状态栏；Linux 优先系统 Python 跑 AppIndicator 子进程，失败回退 pystray
- `quicktools/window_frame.py` — 所有插件窗口的无边框框架（标题栏、拖动、八向缩放、置顶/隐藏/放大/关闭）
- `quicktools/plugin_api.py` / `plugin_loader.py` — 插件稳定契约与懒加载器
- `quicktools/modal_dialogs.py` — X11 上让 Tk 原生对话框叠在无边框窗口之上并拿到真实输入焦点
- `quicktools/x11_focus.py` / `win32_focus.py` / `win32_window.py` — 平台原生焦点激活、无边框窗口任务栏/圆角/工作区
- `quicktools/ui_theme.py` / `ui_icons.py` / `icon_font.py` / `settings_widgets.py` / `plugin_settings.py` / `settings_ui.py` — 共享配色、图标字体、设置 UI 组件与共享设置/关于对话框
- `quicktools/paths.py` / `config.py` / `window_state.py` / `data_migration.py` — 路径、settings.json、窗口尺寸持久化、插件数据根迁移

数据落盘位置（`quicktools/paths.py`）：

- 配置目录：Linux `$XDG_CONFIG_HOME/quicktools`、Windows `%APPDATA%\QuickTools` → `settings.json`、`window_state.json`
- 数据目录：Linux `$XDG_DATA_HOME/quicktools`、Windows `%APPDATA%\QuickTools` → `plugins/`（用户插件）、`plugin_data/`（插件数据根）、`logs/quicktools.log`

## 不可破坏的不变量

这些是踩过坑之后固化的行为，**改之前先确认不违反**；违反会出现“窗口闪一下就消失”“点击外部误隐藏”“插件设置报 `No module named ...`”等难查回归。

### 线程与事件循环

- **后台线程不得直接操作 Tk 控件**：跨线程更新走 `app.commands` 队列或 `root.after(...)` 回到主线程。剪贴板后端线程、截图滚动 worker、IPC 线程都遵守此规则。
- **禁止在同一窗口或同一进程内混用 Tkinter 与 PyQt 事件循环**；需要 Qt 就独立窗口或独立进程，并明确主线程事件循环归属。
- 新增界面优先 PyQt6；Tk 只用于宿主窗口（启动器、`WindowFrame` 插件窗口）内部的内容。不把 Qt 控件嵌进 Tk 容器，迁移界面时整窗迁移。
- Wayland **不做 X11 回退**（剪贴板、截图 portal 都是如此）。

### 窗口生命周期

- **不要在可见状态下直接 `destroy()`**：Tk 会逐个销毁子控件，仍然映射的 Toplevel 会闪出浅色空背景（剪贴板几百张卡片时表现为关闭前闪一下“白板”）。统一走 `withdraw()` + `update_idletasks()` 再 `destroy()`。
- **Linux X11：先 `center_on_screen()` 再 `deiconify()`**。X11 首次映射 override-redirect 窗口会忽略与初始 map 竞争的定位请求，窗口会停在左上角被顶栏挡住、表现为“无法拖动”。Windows 顺序相反。
- 编辑器类窗口创建后先 `withdraw()`，UI 构建与尺寸计算完成后再显示，并在显示前同步完成首帧渲染，否则会先出现在 (0,0) 且画布空白约 1 秒。
- 插件窗口关闭后实例随 Toplevel 销毁，重新打开会绑定新实例；同一插件最多一个窗口。

### 焦点与激活

- **X11 上 Tk 的 `focus_force()` 只更新内部焦点模型**，不调用 `XSetInputFocus`：必须再调 `x11_focus.force_foreground()`，否则窗口收不到键盘输入、也永远收不到 `<FocusOut>`。
- 无边框窗口失去焦点后重新点击时只调 `force_foreground()`，**不要调 `window.focus_force()`**（会把焦点从被点击的子控件抢回 Toplevel）。
- **未确认前台前不得武装自动隐藏**：`_verify_foreground()` 未通过前既不武装自动隐藏，也不因 `FocusOut` 自行隐藏。
- 置顶窗口是失焦自动隐藏的豁免项，不要删；置顶状态在 Linux 由内部 `_pinned` 记录（X11 忽略 override-redirect 窗口的 `-topmost`）。
- Linux 的 `iconify()` 对 override-redirect 窗口会抛 `TclError`，隐藏按钮必须 `withdraw()` 兜底。

### 模态对话框

- **所有原生模态对话框必须走 `quicktools/modal_dialogs.py` 的 `run_modal_dialog()` / `open_native_file_dialog()`**（剪贴板的 `clipboard/dialogs.py` 也复用它）。GNOME/X11 会把窗口管理器管理的对话框放在 override-redirect 窗口下方，直接 `askyesno`/`askopenfilename` 会看不见却仍抢输入，表现为卡死。
- **不要恢复“对话框期间 withdraw 所有 QuickTools 窗口”的旧行为**：只回退到该路径的环境是 XWayland 等无法控制 X11 焦点的场景。
- 对话框打开期间，定时悬停检查里的 `winfo_containing()` 必须捕获 `KeyError`（原生对话框由 Tcl 创建、没有 Python 控件包装），否则会弹错误框并写日志。

### 插件系统

- 入口以合成包名 `_quicktools_plugin_<id>_<generation>` 导入，插件目录内可相对导入。**重新扫描时已导入的合成包必须继续留在 `sys.modules`**——不要在 `_invalidate()` 里 pop，否则插件方法里懒加载兄弟模块会报 `No module named '_quicktools_plugin_clipboard_1'`。
- 扫描顺序：内置插件在前、用户插件在后；`id` 重复时内置优先、用户插件被忽略并记错误；按 `(order, name, id)` 排序。
- `PluginBase` 契约：`create_ui(window)`、`create_settings_ui(parent)`（可选）、类属性 `settings_cards`（默认 `False` = 宿主包一张卡片；`True` = 插件自建分组卡片）、`open_settings(master)`（委托共享对话框）、`on_window_shown(window)`（宿主每次显示主窗口时调用，含首次打开与从启动器恢复）、`start_service()`/`stop_service()`。
- `background: true` 的插件在启动扫描后立即创建唯一实例并 `start_service()`；服务必须幂等，线程不能直接碰 Tk；`stop_service()` 只在退出、插件删除或版本/目录变化时调用。

### 计算器（独立 PyQt6 进程）

- Tk 主进程只保留一个不可见的生命周期代理窗口（`_qt_external_ui = True`），不绘制任何计算器 UI。**不要把 Qt 控件嵌回 Tk 窗口，也不要在同一进程里混用两个事件循环**，也没有 Tk 回退兜底。
- helper 进程 stdout 的 `ready` 握手不能删：否则缺 Qt 平台库时用户只看到窗口消失。helper 的 stderr 不能改回 `DEVNULL`，否则 PyQt 未处理异常的 traceback 会丢失。
- `engine.py` 是纯 Python 递归下降解析器，**不使用 `eval`**。整数结果上限 `MAX_RESULT_BITS = 14_000` bit，**不要调回 100_000**，否则 `format_result()` 抛 `ValueError`、在 Qt 槽函数里未捕获会导致 PyQt `qFatal()` 直接杀死进程（`code=-6`）。
- 置顶必须用平台原生 API（X11 EWMH `_NET_WM_STATE_ABOVE`、Windows `SetWindowPos`），**不要改回 `setWindowFlags(WindowStaysOnTopHint)`**：后者会销毁重建原生窗口，表现为置顶时窗口闪退再打开。
- 超长结果的 `ResultLabel` 把 sizeHint 限在 148–260px 并中间省略，**不要恢复成普通 `QLabel` 或取消上限**，否则几千位结果会把表达式输入框挤到十几像素。
- 草稿纸与键盘的纵向 stretch 是 5:1，只把键盘最小高度提高到 `min(56, spare // 8)`；纵向拉高是为了多看草稿纸历史行。
- Qt 测试只能在子进程以 `QT_QPA_PLATFORM=offscreen` 运行：在主 pytest 进程创建 `QApplication` 会改变 fontconfig 当前配置，导致随后的 Tk 测试读不到内置 Material Icons 字体。

### 剪贴板

- `copy_entry()`（二次复制）只累加 `copy_count`，**不得更新 `last_copied_at`**，否则历史列表会把该条重新置顶；列表排序只由新捕获的 `add()` 改变。
- 事件契约：`deleted` 增量移除卡片、`added` 增量插入或合并防抖刷新、`copied` 只闪提示并原地更新次数、`cleared` 立即空列表刷新。**调用方不得再手动 `refresh()`**，否则会重复重建列表。
- `maintenance()` 只删 `images/`、`thumbs/` 内未被引用且超过 60 秒 grace period 的文件；`images/` 扫描失败时跳过删行，绝不能把全部记录误判为缺失。
- 原图被外部删除时整条记录失效并清理缩略图，**不要恢复“只保留缩略图占位”的旧行为**。
- 后端按平台选择：Wayland 用 `wl-clipboard`、X11 用 XFixes/ICCCM、Windows 用 ctypes 原生；`models.py` 必须不依赖 Tk 和平台模块。

### 截图

- 日志是硬要求：新增用户动作或 `except` 分支必须补日志，异常用 `log.exception`/`exc_info=True`，不要静默吞掉。日志级别固定 INFO。
- 最近库是**文件型**（`screenshot_<时间戳>_<模式>_<宽>x<高>[_fav].<ext>`），不再用 SQLite。`prune()` 是 no-op，**不得自动删除用户文件**；扫描失败时不得清理任何文件。
- 标注对象不直接烘焙到图片，自动保存/复制/另存为时才渲染。贴纸预览与导出用 `resize()` 拉伸填满 bounds，不要改回 `thumbnail`/`ImageOps.contain`。
- 复制图片走 `context.actions.copy_png_to_clipboard(png)` 由 launcher 转给剪贴板插件；**不要从截图插件 import 剪贴板插件模块**，否则会产生重复模块树和重复后端实例。
- 贴纸是即选即用：点工具栏“贴纸”立刻弹文件选择框并以图片中心插入，取消或失败要切回选择工具，不要把贴纸模式留到下一次画布点击。
- 最近截图行内动作顺序固定为 打开 → 复制 → 编辑 → 收藏 → 删除；单条删除不弹确认，清空必须确认。

### gp 插件（独立 PyQt6 悬浮窗）

- 悬浮窗和它的设置对话框都跑在独立进程（`--gp-qt-helper`），Tk 侧只保留不可见代理窗口；**不要用 Tk 实现 gp 的任何界面**，也不要在一进程混用两个事件循环。
- `__main__.py` 的模块级 Tk 导入守卫要同时排除 `--calculator-qt-helper` 和 `--gp-qt-helper`；两个 helper 分派都必须早于 `_should_detach()` 返回，否则 Linux 打包版会把 helper 自己 detach 掉。
- helper 的命令行/环境在 `host.py`（`qt_env.py` 已删除）；Linux 上 Qt 的 xcb 插件需要 `libxcb-cursor.so.0`，必须保留 `helper_environment()` 的 `LD_LIBRARY_PATH` 回退，否则进程起不来。
- helper 的 stdout 行由后台线程**只进队列**，Tk 主线程用 `root.after` 抽干再分发，**后台线程不得直接碰 Tk**；协议只有 `show`/`hide`/`quit` → `ready`/`closed`/`position x y`。
- 代理窗口 `<Destroy>` 必须终止 helper 子进程，**不能留下孤儿进程**；不要给代理窗口绑 `<Unmap>` 隐藏，悬浮窗要常驻桌面。启动 8 秒未 ready 或异常退出要记录 stderr、弹错并销毁代理窗口。
- 位置/拖动/对话框摆放的纯逻辑在 `geometry.py`，**不要只按主屏夹取**：优先按保存的显示器名称恢复，屏幕不存在时选最大交集/最近屏，且自动回退**不得覆盖** `settings.json` 中的原位置。设置对话框垂直居中，底部至少保留 56px 边距，避免贴底。
- 拖动必须用全局坐标 + `self.pos()` 计算固定偏移；只有 `Shift + 左键` 才拖动，松手时夹入可见屏幕、立即落盘并发 `position x y`。
- 右键菜单弹出会触发 `leaveEvent`；菜单打开期间必须保持悬停透明度，关闭后用 `QCursor.pos()` 重新判定鼠标是否仍在悬浮窗上，否则右键后悬浮窗会一直保持半透明。
- 设置对话框**不设父窗口**（挂到圆形悬浮窗上会被摆到屏幕外），先 `adjustSize()` 再按悬浮窗所在屏幕定位，保持置顶、单实例；打开对话框不得移动悬浮窗。设置页不提供底部“关闭”按钮，关闭使用标题栏 X 或 `Esc`。
- 对话框只在打开时定位一次；**设置变化（透明度/直径/恢复位置）不得重新摆放对话框**，否则用户手动拖动后一拉滑块就会被弹回原位。
- helper 必须 `setQuitOnLastWindowClosed(False)`（见 `configure_application()`）：悬浮窗是 `Qt.Tool`，不参与“最后主窗口”判定；否则关闭设置对话框会直接退出 helper。helper 只应在收到 `quit` 命令、右键菜单“退出”或 stdin EOF 时退出。
- 右键“退出”必须真正结束 gp 插件：widget 发 `closed` 并调用 `controller.quit()` 退出 helper；Tk 侧收到 `closed` 立即销毁代理窗口，启动器卡片恢复未打开。**不要恢复“只隐藏悬浮窗、卡片仍显示已打开”的旧语义**。
- 设置改动**自动保存**（400ms 防抖，关闭/隐藏/退出/EOF 时冲刷），**不要加“保存设置”按钮**；右键“设置”直接在 Qt 进程内打开对话框，**不要绕回 Tk 共享设置页**（第一次点击会打不开）。
- 圆圈背景色默认关闭（只留描边），可勾选“填充圆圈背景色”打开。
- 直径滑块范围 10–250，手动输入范围 0–1000；拖滑块同步输入框，手动输入超出滑块范围时滑块停在端点但实际直径仍按手动值生效。手动输入 0 时按 10px 渲染，保留右键入口，避免无法恢复。
- **Shift 点击穿透**：不按 Shift 时整个方形窗口保持可见但鼠标穿透（左键/右键落到后面的文件或窗口）；按住 Shift 才恢复交互，`Shift+左键`拖动、`Shift+右键`菜单。平台实现集中在 `input_mode.py`：X11 Shape INPUT 区域、Windows `WS_EX_TRANSPARENT`；**禁止运行时 `setWindowFlags()`**（会重建原生窗口）。
- XWayland/Wayland 按 Wayland 处理：无法可靠获取全局 Shift 或输入区域时保持“始终可交互”，绝不能把窗口永久卡成穿透。X11 恢复输入区域失败时持续重试恢复，不能再请求穿透。
- Shift 轮询周期 30ms；`show` 启动、`hide` 停止、`shutdown` 关闭。拖动中或菜单打开时即使松开 Shift 也保持可交互；释放左键/关闭菜单后再恢复穿透。悬停透明度只在菜单打开或 Shift 按住且鼠标位于窗口上时生效。
- `contextMenuEvent` 必须先检查 `event.modifiers() & ShiftModifier`，没有 Shift 直接忽略。Windows 分层窗口需铺 alpha=1/255 的整矩形底色，否则透明角落无法命中；保留 `WS_EX_LAYERED`。
- gp 测试必须注入 fake `input_mode`，避免真实 X11 输入区域影响测试窗口；新增 `input_mode.py` 时同步两份 spec 的 hiddenimports 和 Linux 的 `Xlib.ext.shape`。

### 打包依赖

- 内置插件是运行时动态导入的，PyInstaller 无法静态发现：新增后端模块、Qt 模块、采集/portal 依赖时，**同步更新 `QuickTools.spec` 与 `QuickTools-onefile.spec` 的 `hiddenimports`**，以及 `pyproject.toml`、`requirements.txt`；平台库还要进 `datas`。
- 两份 spec 都必须包含 `quicktools.win32_window`、`quicktools.window_pin`、`quicktools.x11_focus`、`quicktools.modal_dialogs`。
- 单文件版每次打开计算器会重复解压，Qt 计算器体验差；推荐目录版或安装包。
- 打包后脚本会执行 `icacls dist\win /setintegritylevel Medium /T`（沙箱 Low 完整性标签会导致单文件版无法写 `%TEMP%`）。Linux 构建脚本无需此步。

## Code style

- 所有面向用户的界面文本、日志和文档使用中文。
- **Windows 批处理脚本必须保持 CRLF 换行**（`.gitattributes` 已强制 `*.bat`/`*.iss` → CRLF、`*.sh` → LF）。cmd.exe 不支持 LF 批处理，会把整个文件当成一条命令。
- 跟随邻近代码的类型标注与命名习惯；不引入新的 lint/format 步骤。
- Tk 没有圆角容器：圆角卡片用 `settings_widgets.Card`（Canvas 自绘）或 Pillow 生成图；PhotoImage 必须在 Tk 主线程创建。

## 文档同步（硬性要求）

改了行为就必须同一次改动里更新对应说明文件，禁止“代码已改、文档仍描述旧行为”。

| 改动内容 | 必须检查的文件 |
| --- | --- |
| 用户可见功能/操作方式、平台限制 | `README.md` |
| 插件清单字段、`PluginBase` 生命周期、`background` 语义、API 版本 | `docs/PLUGIN_GUIDE.md` |
| 图标资源或生成方式 | `quicktools/assets/README.md` |
| 内置插件卡片名称/概述、插件关于页说明 | 对应 `plugin.json` 的 `name`/`summary`/`description`/`author` |
| 开发命令、架构、工作流 | `CLAUDE.md` |

提交前搜索旧文案（状态栏提示、README 按键说明、插件描述），确认没有遗留过时描述。

## Testing instructions

- 单元测试：pytest（命令见上）。新增行为都要补测试，放在 `tests/` 下同主题文件里。
- `DISPLAY` 是 Tk 冒烟测试必需的；没有显示环境时相关用例自动 skip（`test_flat_button.py`、`test_clipboard_ui_smoke.py`、`test_plugin_lifecycle.py`、`test_plugin_actions.py`、`test_launcher_window_state.py`、`test_launcher_autohide.py`、`test_x11_focus.py`、`test_ui_icons.py`、`test_win32_focus.py`、`test_window_pin.py`、`test_window_frame.py`、`test_plugin_settings.py`、`test_screenshot_ui_smoke.py`、`test_gp_qt_window.py`）。`test_gp_plugin.py` 的设置/协议/纯几何用例和 `test_gp_input_mode.py` 的工厂/Wayland 判定不需要显示环境。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于避开系统注入的 pytest 插件；干净环境可省略。
- **Qt 测试必须在子进程以 `QT_QPA_PLATFORM=offscreen` 运行**，见计算器小节。gp 悬浮窗的 Qt 用例例外：离屏平台不支持窗口透明度，它需要真实显示环境（无 `DISPLAY` 时整组 skip），但仍然只能在子进程里跑；多屏/负坐标/对话框摆放等纯几何逻辑放在 `test_gp_plugin.py`，用假屏幕测试。`closing_settings_does_not_quit` 用例会在真实事件循环里关闭设置对话框，确认 helper 不会提前退出；`settings_dialog_stays_put_when_changed` 用例确认手动拖动对话框后，调整滑块/直径/恢复位置不会把它挪回原位；`context_menu_exit_quits_helper` 与 `test_host_exit_event_destroys_proxy` 确认右键“退出”会结束 helper 并销毁代理窗口。`input_*` 用例验证 Shift 穿透、拖动/菜单期间保持可交互、失败降级和定时器生命周期；`context_menu_requires_shift` 验证 Shift 门控；`win32_hit_fill` 验证 Windows 命中填充绘制；所有 gp Qt 用例注入 fake input mode，不触碰真实 X11 输入区域。
- 跨平台用例按平台 skip：`test_clipboard_windows.py` 只在 Windows 跑；`test_hotkey_win32.py` 只测 Win32 虚拟键映射；Wayland portal 只用 fake 客户端验证。
- 剪贴板服务测试用 `FakeBackend`/`FakeRoot`，不依赖真实系统剪贴板；截图用 `FakeRoot`/`FakeBackend`/`FakeOverlay`/`FakeEditor` 测状态机。
- 当前实测通过的是 Linux X11；Windows 与 Wayland 代码路径已适配但需按 `README.md` 的实机验收清单在真实环境确认。

## PR & commit conventions

- 分支从 `main` 切出，不直接推 `main`。
- 提交信息统一 `YYMMDD: 描述`（如 `261019: 新增加了开机自启动开关`），用 `./git-update.sh 描述`（Linux/Git Bash）或 `git-update.bat 描述`（Windows）生成；仅在用户明确要求时提交。
- 提交前 `git status` 确认没有把本地配置或临时产物带进暂存区（脚本会 `git add .`）。

## Security

- 插件在主进程内运行、拥有与应用相同的权限：只安装可信插件。
- 不要把密钥或令牌写进代码、配置或日志。
- 所有数据（含剪贴板历史、截图）仅保存在本机，不上传；调试日志不要打印这些原文。
