# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 文档同步（硬性要求）

每次修改功能、行为、命令、配置格式或插件契约时，必须在同一次改动中检查并更新对应说明文件。禁止出现“功能代码已改、说明文件仍描述旧行为”的情况。

| 改动内容 | 必须检查的说明文件 |
| --- | --- |
| 用户可见功能/操作方式（计算器、剪贴板、CLI、平台限制） | `README.md` |
| 插件清单字段、`PluginBase` 生命周期、`background` 语义、API 版本 | `docs/PLUGIN_GUIDE.md` |
| 图标资源或生成方式 | `quicktools/assets/README.md` |
| 内置插件在启动器卡片上的名称/一句话概述，以及关于页的详细说明 | 对应 `plugin.json` 的 `name`/`summary`/`description`/`author` |
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

# 打包（PyInstaller；产物按平台分目录：dist/win/、dist/linux/）
./build_linux.sh                           # Linux 目录版 → dist/linux/QuickTools/QuickTools
build_windows.bat                          # Windows 目录版 → dist\win\QuickTools\QuickTools.exe
build_all.bat                              # Windows：目录版 + 单文件版 + 安装包（Inno Setup 缺失时跳过）
.venv/Scripts/python -m PyInstaller --noconfirm --distpath dist\win --workpath build\win_onefile QuickTools-onefile.spec
```

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于避开系统 ROS 注入的 pytest 插件；干净环境可省略。
- `DISPLAY` 是 Tk 冒烟测试必需的；没有显示环境时相关测试会自动 skip。
- 未配置 lint/format 检查步骤，`pyproject.toml` 只配置了 pytest。
- 打包必须使用项目的 `QuickTools.spec`（目录版）或 `QuickTools-onefile.spec`（单文件版）；Windows 包只能在 Windows 上构建。单文件版会把依赖解压到临时目录，冷启动约 3 秒；目录版约 1 秒。`installer.iss` 用 Inno Setup 6 把 `dist/win/QuickTools` 打成 `dist/win/QuickTools-Setup.exe`，由 `build_all.bat` 自动调用。`build_all.bat`/`build_windows.bat` 会先检查依赖，已安装则跳过 pip；只有缺依赖时才用 `--no-build-isolation` 安装，避免 pip 在构建隔离环境里下载 setuptools 时因网络/代理卡住。构建结束后两个脚本都会执行 `icacls dist\win /setintegritylevel Medium /T`：某些沙箱会给工作区文件打 Low 完整性标签，导致 exe 以低权限启动、单文件版无法写 `%TEMP%` 并报 `Could not create temporary directory!`。
- **产物目录**：分发产物统一放在 `dist/` 下按平台分目录——`dist/win/`（`QuickTools/` 目录版、`QuickTools.exe` 单文件版、`QuickTools-Setup.exe` 安装包）和 `dist/linux/`（`QuickTools/`）；中间文件在 `build/win/`、`build/win_onefile/`、`build/linux/`。`dist/` 和 `build/` 整体被 `.gitignore` 忽略，不要在 `dist/` 里放中间文件。
- **换行符**：`.gitattributes` 规定 `*.bat`/`*.iss` 为 CRLF、`*.sh` 为 LF。cmd.exe 不支持 LF 换行的批处理——会把整个文件当成一条命令，注释与下一条命令拼接后报错。新增 Windows 脚本必须保持 CRLF。
- 仓库提交信息格式为 `YYMMDD: 描述`（如 `261019: 新增加了开机自启动开关`）；`./git-update.sh 描述`（Linux/Git Bash）或 `git-update.bat 描述`（Windows cmd/PowerShell，转调同一个 .sh）会按此格式执行 `git add .` 并提交；两个脚本都会先切到仓库根目录，从子目录调用也不会漏提交。仅在用户明确要求提交时使用。

## 运行时架构

- `quicktools/__main__.py`：CLI 入口。先做单实例 IPC 预检，再创建 `QuickToolsApp`。Linux 打包版在终端启动时会自动脱离终端（`--foreground` 可禁用）。无实例时的 `--toggle` 以 `start_visible=False` 启动，再把 `toggle` 命令放入队列，因此冷启动与快捷键唤出的行为一致；`--screenshot` 同样走队列。无参数的全新普通启动以 `start_visible=True, start_auto_hide=True` 创建应用（首次显示即可点击外部隐藏）；已有实例时普通启动只发送 `show`，`--show` 冷启动也保持 `start_auto_hide=False`。
- `quicktools/app.py`：持有隐藏的 Tk 根窗口和生命周期。全局快捷键回调（Windows 原生 `WM_HOTKEY` 在主线程；pynput 回退时在其监听线程）和 IPC 服务只把命令放入 `app.commands` 队列；状态栏子进程通过 IPC 与主实例通信。Tk 主线程每 50ms 调用 `_drain_commands()` 处理队列。**任何后台线程都不得直接操作 Tk 控件**，必须通过队列或 `root.after(...)` 回到主线程。`plugin <id> <action>` 命令会转给 `Launcher.dispatch_plugin_action()`；`hide_for_capture()` 统一隐藏启动器、设置窗口和插件窗口，并返回恢复回调。
- `quicktools/launcher.py`：启动器窗口、插件卡片、搜索和插件窗口管理。启动器自身无边框（`make_frameless`），顶部标题区域可拖动；首次打开为 860×560，复用 `ResizeGrips(background=BG)` 支持八方向边缘缩放（最小 720×480），`show()` 通过 `_window_size()` 读取当前尺寸并重新居中，用户调整后的尺寸在本次运行内保持。卡片系列只显示图标、名称和一句话概述（`meta.display_summary`），详细说明在插件关于页；卡片状态标签必须先于可扩展的文本列 `pack`，否则长概述会把“已打开”的末字挤出卡片。插件窗口隐藏后仍保留在 `_plugin_windows`，卡片继续显示“已打开”。插件窗口创建时先挂 `WindowFrame`（图标/名称 + 设置/置顶/隐藏/放大/关闭），再把 `create_ui(window)` 的内容排到标题栏下方；`window.quicktools_frame` 保留框架引用供高级插件使用。Linux 下 `-topmost` 对 override-redirect 窗口无效且读回 False，`WindowFrame` 用 `_pinned` 自行记录开关状态，开启时调用 `lift()`；Windows 仍以 `attributes("-topmost")` 的实际值为准。`create_ui()` 之后按插件 `id` 从 `window_state.json` 恢复上次窗口大小；`<Configure>` 防抖记录，关闭窗口和应用退出（`flush_window_states()`）时立即落盘。只保存宽高与放大状态，打开时重新居中；旧尺寸超过当前屏幕或小于 `wm_minsize` 时自动收缩/放大到合法范围。`window_state.json` 与 `settings.json` 分离。标题栏“设置”调用 `instance.open_settings(window)`，失败弹错误框。启动器每次显示时都会重新扫描插件；同一插件最多一个窗口；后台插件在整个应用生命周期内只保留一个实例。`show()` 在 Linux 下**先 `center_on_screen()` 再 `deiconify()`**（X11 首次映射 override-redirect 窗口时会忽略与初始 map 竞争的定位请求，窗口会停在左上角并被桌面顶栏挡住，表现为“无法拖动”），Windows 下仍先 `deiconify` 再布局；随后聚焦，再 `after_idle` 刷新插件。`_activate_window()` 在 Windows 下调用 `win32_focus.force_foreground()`，失败时回退 `focus_force()`。`_verify_foreground()` 按 `_FOCUS_RETRY_DELAYS_MS` 重试并用 `is_foreground()` 确认（Windows 和 Linux X11），**未确认前台前不得武装自动隐藏，也不得因 `FocusOut` 自行隐藏**；`_had_focus` 只在真实前台激活/点击后置位。Linux 下 `Toplevel.overrideredirect(True)` 会让 Tk 的 `focus_force()` 只更新内部焦点模型、不调用 `XSetInputFocus`，因此 `_activate_window()` 在 `focus_force()` 之后额外调用 `x11_focus.force_foreground()`；否则窗口收不到键盘输入，也永远收不到点击外部产生的 `<FocusOut>`。`_hide_if_clicked_outside()` 先用 `is_foreground()` 判断原生焦点是否仍在启动器上，避免 X11 内部焦点切换时 `focus_get()` 短暂为 `None` 造成误隐藏；Wayland 下 `is_foreground()` 不可验证，保持旧的焦点事件逻辑。启动器支持“点击外部自动隐藏”：只有 `toggle()` 或**全新普通启动**调用 `show(auto_hide=True)` 武装（没有已运行实例时 `__main__` 传入 `start_auto_hide=True`），`hide()` 解除并取消待执行检查；已有实例时的普通启动、`show` 命令、托盘“显示”、`--show`、设置返回和截图后的恢复都保持不武装。判定用 `<FocusOut>` 后延迟 `_AUTO_HIDE_DELAY_MS` 复查 `focus_get()`（子控件、子 Toplevel 和 transient 对话框算作内部），与 `_tray_popup` 的焦点模式一致。`hide_all_windows()` 直接 withdraw 而不走 `hide()`，必须同步 `_set_auto_hide(False)`；`open_plugin()` 弹错误框前也要解除。**只作用于启动器窗口，插件窗口不受影响**。自动隐藏依赖启动器真的获得过焦点，因此不能删除 `_activate_window()`；否则窗口会在无焦点状态下显示，必须先点一下才会在点击外部时隐藏。
- 插件主窗口失焦自动隐藏：`open_plugin()` 给插件主窗口绑定 `<FocusIn>/<FocusOut>`，用 `window._qt_had_focus` 记录是否真正取得过焦点；FocusOut 后延迟 `_AUTO_HIDE_DELAY_MS` 调用 `_hide_plugin_if_focus_left()`，依次检查原生前台（`is_foreground`）、Tk 焦点是否在窗口/子 Toplevel/transient 对话框内（`_focus_within`）、是否存在可见子 Toplevel（`_has_visible_dialog`），全部通过才 `withdraw()`。`_show_plugin_window()` 和 `_focus_window()` 调 `_mark_plugin_shown()` 重置状态并重新聚焦；`hide_all_windows()` 对插件窗口调 `_reset_plugin_focus_state()`，避免截图恢复后被误隐藏。**只绑定启动器创建的插件主窗口**；截图编辑器、选区/滚动覆盖层、设置/关于对话框由插件或共享对话框自行创建，不参与失焦隐藏。`window.quicktools_frame.pinned` 为真时 `_on_plugin_focus_out()`/`_hide_plugin_if_focus_left()` 直接跳过，置顶窗口在用户操作其他应用时保持可见；`WindowFrame.toggle_pin()` 会记录“插件窗口置顶：已开启/已取消”日志。**不要删除置顶豁免**，否则点击其他应用时窗口会消失，置顶看起来失效。
- `quicktools/win32_focus.py`：Windows 专用前台激活。`focus_force()` 只走 `SetForegroundWindow`，后台实例（快捷键或 `--toggle` 唤醒）会被系统的前台激活限制拒绝。这里先临时 `AttachThreadInput` 到当前前台窗口线程，再 `ShowWindow`/`BringWindowToTop`/`SetForegroundWindow`/`SetActiveWindow`/`SetFocus`，并用 `SendMessageTimeoutW(WM_NULL)` 等待异步激活完成；`is_foreground()` 供启动器校验。非 Windows 平台直接返回 False。
- `quicktools/x11_focus.py`：Linux X11 原生输入焦点辅助。Tk 对 `overrideredirect` 窗口的 `focus_force()` 只改内部焦点模型，必须再对 Tk Toplevel 的**外层包装窗口**（X 树中 root 的直接子窗口，不一定是 `winfo_id()`）调用 `XSetInputFocus`；焦点设在内部内容窗口上虽然能收到键盘事件，但 Tk 收不到 `<FocusOut>`，点击外部自动隐藏仍然失效。`force_foreground()` 先聚焦并校验，`is_foreground()` 沿 X 树向上匹配焦点窗口；Wayland（`WAYLAND_DISPLAY`/`XDG_SESSION_TYPE=wayland`）下 `supported()` 返回 False，`force_foreground()` 不做任何事，`is_foreground()` 返回 True 以保持原有事件逻辑。模块只在 Linux 导入，须列入两份 spec 的 `hiddenimports`。
- `quicktools/win32_hotkey.py`：Windows 原生全局热键。用隐藏的 message-only 窗口注册 `RegisterHotKey`，`WM_HOTKEY` 由 Tk 主线程的消息循环分发，回调因此运行在主线程。**这是拿到前台激活权限的关键**：`WM_HOTKEY` 投递给注册线程，该线程可合法调用 `SetForegroundWindow`；pynput 低级钩子没有这个权限。注册失败时 `HotkeyManager` 回退 pynput。`Ctrl+Space` 会被原生注册独占，与中文输入法冲突时建议改绑 `Ctrl+Alt+Space`。
- `quicktools/ipc.py`：单实例 IPC。Linux 使用 `$XDG_RUNTIME_DIR/quicktools-<uid>.sock`（回退 `/tmp`），Windows 使用 `127.0.0.1:50517`。支持 `toggle`、`show`、`settings`、`quit`、`ping`、`menu x y`，以及严格格式的 `plugin <id> <action>`（动作无负载，消息上限 64 字节）。
- `quicktools/paths.py`：配置/数据/日志/插件目录。`package_dir()` 同时处理源码与 PyInstaller `_MEIPASS`；内置插件和资源都从这里定位；`window_state_file()` 指向配置目录下的 `window_state.json`。
- `quicktools/config.py`：`settings.json` 目前只保存全局快捷键；开机启动状态以操作系统条目为准（`autostart.py`），不写入 settings。
- `quicktools/window_state.py`：插件窗口大小持久化。`WindowStateStore` 按插件 `id` 保存 `width`/`height`/`maximized`，用临时文件 + `os.replace` 原子写入；文件损坏、字段非法或尺寸过小时按缺失处理，保存失败只记日志，不影响窗口操作。位置不落盘，启动时由启动器重新居中。
- `quicktools/hotkey.py`：全局快捷键管理。Windows 优先使用 `win32_hotkey.Win32Hotkey`（`RegisterHotKey`/`WM_HOTKEY`，主线程回调）；注册失败或非 Windows 使用 pynput。Wayland 下不做应用内监听，只返回明确提示；系统快捷键应绑定到 `quicktools --toggle`。
- `quicktools/tray.py`：Linux 优先用系统 Python 启动 `helpers/tray_appindicator.py`（Ayatana AppIndicator/SNI），失败回退 pystray XEmbed + Tk 菜单；Windows 使用 pystray 原生托盘。状态栏运行在独立子进程，通过 IPC 控制主实例。
- `quicktools/settings_ui.py`：应用设置窗口、快捷键录制、开机启动开关、插件重新扫描。`SettingsWindow` 挂 `WindowFrame`（关闭/隐藏，进入任务栏），`HotkeyRecorder` 使用 `WindowFrame(dialog=True)`；内容标题改为“应用设置”避免与标题栏重复。
- `quicktools/ui_theme.py`：共享配色、`pick_fonts()`、`Fonts.u()/m()`、`FlatButton`、`round_rect()`。`SURFACE`/`CARD_BG`/`CARD_BORDER`/`DIVIDER` 是设置页的画布与卡片色；`pick_fonts()` 先调用 `icon_font.ensure_loaded()`，`Fonts.symbol` 保存随包 Material Icons 的字体族名，Windows 只在字体加载失败时回退到 Segoe Fluent Icons / Segoe MDL2 Assets，其他平台回退到 Canvas。`FlatButton` 基于 `tk.Label`，点击不会抢走输入框焦点，计算器键盘依赖这一点；它只在收到配套 `<ButtonPress>` 后于 `<ButtonRelease>` 执行命令，避免启动器卡片按下后新窗口收到遗留 release 造成幽灵点击（例如打开计算器时自动输入 `+`）。
- `quicktools/icon_font.py`：随包图标字体加载。字体在 `assets/fonts/MaterialIcons-Regular.ttf`（Apache 2.0），Windows 用 `AddFontResourceExW(FR_PRIVATE)`、Linux 用 fontconfig `FcConfigAppFontAddFile` 注册到当前进程，返回字体族 `Material Icons`；加载失败返回空字符串。必须用 `assets/fonts/*` 打进 `pyproject.toml` package-data；两份 spec 的 `quicktools/assets` 目录复制会自动包含字体。
- `quicktools/ui_icons.py`：标题栏和设置侧栏的小图标。两个平台都用 Material Icons 的码位（`pin`=F10D、`settings`=E8B8、`about`=E88F），颜色跟随按钮状态；字体不可用时回退到 Canvas 绘制的图钉/齿轮/信息图标。新增图标时保持 30px 逻辑网格，并从 `MaterialIcons-Regular.codepoints` 取码位。
- `quicktools/window_frame.py`：所有插件窗口的无边框框架。`WindowFrame` 负责自绘标题栏（图标、标题、副标题、设置/置顶/隐藏/放大/关闭按钮）、拖动移动、双击放大/还原、八方向边缘拖拽缩放、Windows 任务栏样式与圆角；标题栏的设置按钮显示齿轮、置顶按钮显示图钉（由 `quicktools.ui_icons` 绘制），`TitleBarButton` 用 Canvas 画图标，不抢输入焦点；`Tooltip` 提供悬停提示，传入 `container=` 时容器的所有子控件共用一个提示，指针在复合控件内部移动时不会闪烁。标题栏“隐藏”调用 `WindowFrame.minimize()`：Windows 走 `ShowWindow(SW_MINIMIZE)`；X11 下 Tk 对 override-redirect 窗口的 `iconify()` 会抛 `TclError`，必须立即 `withdraw()` 兜底，不能直接 return，否则所有插件的隐藏按钮都会失效。`dialog=True` 时只保留关闭按钮、不进入任务栏。`make_frameless()` 供启动器使用，`enable_drag()`/`ResizeGrips` 可复用。`ResizeGrips` 用 `RESIZE_INTERVAL_MS`（15ms）合并 `<B1-Motion>`，只把最新指针位置应用为窗口几何，松手时立即补最后一次位置，避免 Tk 重绘追不上输入事件导致窗口边缘拖影；可选 `background=` 让拖拽区与宿主窗口同色（启动器传 `BG`，插件窗口沿用默认的标题栏/内容色）。主窗口由 launcher 自动创建，插件额外 Toplevel 自行 `WindowFrame(...)`。该模块会导入 `quicktools.win32_window`，两者都必须列入 PyInstaller `hiddenimports`（内置截图编辑器会动态导入它）。
- `quicktools/win32_window.py`：Windows 无边框窗口辅助。清除 Tk 为 override-redirect 窗口设置的 `WS_EX_TOOLWINDOW`、设置 `WS_EX_APPWINDOW` 恢复任务栏/Alt+Tab；`prepare_tool_window()` 让对话框/提示不进入任务栏；DWM 圆角（Win11）；`minimize()` 走 `ShowWindow(SW_MINIMIZE)`；`work_area()` 返回显示器工作区供自绘放大使用。非 Windows 全部 no-op。
- `quicktools/plugin_settings.py`：所有插件共享的“设置/关于”对话框。`SURFACE` 页面底色 + 左侧白色圆角导航卡 + 右侧页面标题/副标题 + 白色圆角卡片（软阴影、1px 边框）+ 固定底部状态/关闭栏；关于页从 `PluginMeta` 自动生成（徽章、版本、`summary`、`description`、作者、目录、数据目录、打开目录/复制信息）。设置页由 `PluginBase.create_settings_ui(parent)` 填充；默认把整页包进一张卡片，插件声明 `settings_cards = True` 时则自行创建多张分组卡片，内置插件使用后者。`open_plugin_settings(plugin, master)` 复用每个插件实例上的 `_settings_dialog`，`PluginBase.open_settings()` 调用它。对话框本身使用 `WindowFrame(dialog=True)`，可滚动、Esc 关闭。
- `quicktools/settings_widgets.py`：共享设置 UI 组件。`Card` 用 Canvas 绘制圆角卡片和底部软阴影（Tk 没有圆角容器，子 Frame 的内缩大于圆角半径以避免方角露出）；`SectionHeader` 提供带强调条的区块标题；`SettingsRow` 是左文右控件的行，描述文本会随行宽自动换行；`ToggleRow`/`ToggleSwitch` 是自绘开关；`NavItem`/`IconBadge` 用于侧栏导航和插件徽章。插件设置页应复用这些组件，不要自建边框面板。

- `quicktools/window_pin.py`：兼容保留的 `PinButton`（`FlatButton` 子类），供外部插件在自定义次级窗口中手动放置图钉。内置主窗口已统一使用 `WindowFrame` 的标题栏图钉，不再在内容区放 `PinButton`；`test_window_pin.py` 继续验证其切换 `-topmost` 和状态同步。Linux 下与 `WindowFrame` 一样用内部 `_pinned` 记录状态（X11 忽略 override-redirect 窗口的 `-topmost`），Windows 读取实际属性。`window_pin` 仍需列入两份 spec 的 `hiddenimports`。

## 插件系统

- `quicktools/plugin_loader.py`：启动时只读取并校验 `plugin.json`，点击卡片时才懒加载入口代码。入口以合成包名（`_quicktools_plugin_<id>_<generation>`）导入，因此插件目录内可使用相对导入。扫描时解析可选字段 `summary`（卡片一句话）与 `author`（关于页）；`description` 作为关于页详细说明。重新扫描会清空加载器缓存，但**已导入的合成包必须继续留在 `sys.modules`**：启动器每次显示都会扫描，后台插件实例仍存活，方法里懒加载兄弟模块（例如 `create_settings_ui` 里的 `from .settings_view import ...`）依赖父包；新代次有唯一模块名，不会与旧代次冲突。不要在 `_invalidate()` 里 pop 这些模块。
- 扫描顺序是内置插件在前、用户插件在后；重复 `id` 时内置插件优先，用户插件被忽略并记录错误。插件按 `(order, name, id)` 排序。
- `quicktools/plugin_api.py` 是稳定契约：`PluginMeta`、`PluginContext`、`PluginBase`。`PluginMeta.display_summary` 在没有 `summary` 时回退到 `description` 第一句；`PluginContext.meta` 暴露当前插件元数据；`PluginBase` 新增可选的 `create_settings_ui(parent)`、类属性 `settings_cards`（默认 `False`，设置页会被宿主包进一张卡片；为 `True` 时插件自行创建卡片分组）和默认的 `open_settings(master)`（委托 `plugin_settings.open_plugin_settings`）。
- 普通插件：窗口首次打开时创建新实例并调用 `create_ui(window)`；关闭窗口后再开是新实例。宿主会按插件 `id` 记住窗口大小与放大状态，`create_ui()` 里的 `geometry()`/`center_on_screen()` 只是首次打开时的默认值。
- `background: true` 的插件：应用启动扫描后立即创建唯一实例并调用 `start_service()`；窗口可反复打开关闭，`stop_service()` 只在退出、插件删除或版本/目录变化时调用。服务必须幂等，且线程不能直接碰 Tk。
- 完整契约和示例见 `docs/PLUGIN_GUIDE.md` 与 `examples/hello_plugin/`。

## 内置插件

### 计算器（`quicktools/plugins/calculator/`）

- `engine.py`：纯 Python 递归下降解析器，不使用 `eval`；支持 `0x/0b/0o` 前缀、整数/浮点、`//`、`%`、`^`/`**`。`evaluate()` 是严格求值；`evaluate_live()` 用于输入过程，悬空的 `+`/`-` 补 `0`，`*`/`/`/`//`/`%` 补 `1`，但 `^`/`**` 和括号不匹配仍不可计算；`filter_input()` 按进制过滤键入/粘贴字符。
- `settings.py`：计算器自己的 `settings.json`，保存“科学模式”、最大保存条数 `max_records`（默认 200，范围 1–5000）和结果分隔位数 `result_group_size`（默认 0，范围 0–10；0 不分隔，3 表示 `1,000`）；默认关闭，文件损坏时回退默认值。`CalculatorView` 通过 `data_dir` 参数读写它，未传时只在内存中使用默认值，便于测试。
- `scratchpad_store.py`：草稿纸记忆持久化。`ScratchEntry(expression, base)` 记录每行表达式和输入进制，结果不落盘、恢复时用 `evaluate_live` + `format_result` 重算。`scratchpad.json` 结构为 `{version, last_base, rows:[{expression, base}]}`；只保留最新 `max_records` 条，空行/超长/非法行跳过，损坏文件回退空状态。
- `settings_view.py`：`CalculatorSettingsPanel`，嵌入共享设置对话框的“设置”页；插件类声明 `settings_cards = True`，面板用 `SectionHeader` + 一张 `Card` 组织“当前记忆/最多保存条数/结果分隔位数”，按钮放在页面底色上。编辑最大保存条数、结果分隔位数、显示当前记忆数、清空全部记录（`messagebox.askyesno` 确认）；保存后留在对话框并显示状态，不再自建 Toplevel。保存上限会立即调用视图裁剪，修改分隔位数会立即刷新已有结果标签。
- `view.py`：草稿纸 UI。内容顶部左侧保留“草稿纸”标题 label，右侧是“科学模式”开关；不再有内嵌设置按钮或图钉，设置入口由标题栏提供，视图通过 `on_open_settings` 回调把请求交给插件。根布局使用 grid：草稿纸行与键盘行按 5:1 分配多余高度，草稿纸行最小一层（`_paper_row_min`），键盘行最小高度随可见键行数变化；窗口缩小时按键行同步变矮而不是被裁掉，缩到最小窗口时草稿纸只显示一层。operator/equal 的固定尺寸图标在行高不足时通过 `FlatButton.set_face()` 切换为文字，避免裁切；`minimum_content_height()`/`minimum_window_height()` 供插件初始化和模式切换更新窗口 `minsize`。`_on_canvas_configure()` 立即同步内嵌行宽，但把 scrollregion/底部对齐通过 `after_idle` 合并；`_sync_paper_layout()` 默认不再调用 `update_idletasks()`（仅换行/滚到底时 `measure=True`），避免缩放时每个 Configure 都强制重排放大拖影。首次打开时按持久化的 `scientific_mode` 决定布局；右上角“科学模式”开关调用 `_apply_scientific_mode()`，关闭时隐藏进制转换栏、进制选择行和 A-F 行并强制切回 DEC，开启时用 grid 恢复“转换栏（row 3）→ 进制选择（row 4）→ 键盘（row 5）”，A-F 行在键盘内恢复为 row 1。`ScratchRow._on_write()` 先归一化再按当前进制过滤，随后 `_update_live_result()` 实时显示 `= 结果` 并刷新进制转换栏；`Enter`/`=` 确认当前层，若它是最底层则新建下一层。所有 `format_result()` 调用都传 `self.result_group_size`；`apply_result_group_size()` 保存设置后刷新已有行的结果标签。转换栏顺序为 `BIN DEC / OCT HEX`，底部进制按键顺序为 `BIN OCT HEX DEC`，默认 DEC，选中进制整格高亮。
- 草稿纸记忆：`CalculatorView` 初始化时按 `max_records` 恢复行（逐行 `restore_expression()` 绕过当前进制过滤，用行内 base 求值），末尾始终补一行空输入行。输入/求值后 400ms 防抖保存；删除行、清空、修改上限立即保存。`<Destroy>` 必须用 `_scratchpad_state` 普通数据缓存同步 flush，因为 Tk 子控件在父 `<Destroy>` 之前已销毁。每行右侧 × 调 `delete_row()`，删除后重排 grid、激活邻近行并至少保留一行；`apply_max_records()` 调小上限时立即删除最旧的非空行。
- 修改行为时同步更新 `tests/test_engine.py`、`tests/test_calculator_settings.py`、`tests/test_calculator_scratchpad.py`、`tests/test_calculator_memory_ui.py`、`tests/test_ui_smoke.py`、`tests/test_flat_button.py` 和 README 计算器章节。

### 剪贴板（`quicktools/plugins/clipboard/`）

- `plugin.py`：`background: true` 插件，服务实例跨窗口复用；退出前调用 `flush_pending_edit()`。
- `service.py`：拥有后端、SQLite store 和去重/抑制逻辑。后端线程只把快照放入队列，数据库/图片写入和 UI 通知通过 `root.after` 在 Tk 主线程执行；自己的写回操作会在短时间内抑制记录，避免回环。相同内容按 digest 合并。`copy_entry()`（二次复制）调用 `store.mark_copied()` 只累加 `copy_count`，**不得更新 `last_copied_at`**，否则历史列表会把该条重新置顶；列表排序只由新捕获的 `add()` 改变。
- `store.py`：SQLite（WAL）历史库 `history.db`，图片与缩略图分别存于插件数据目录的 `images/`、`thumbs/`。所有方法应在 Tk 主线程调用。`mark_copied()` 保持 `last_copied_at` 不变以维持历史位置。
- `settings.py`：剪贴板插件自己的 `settings.json`（暂停记录、历史上限、图片上限、是否捕获图片/文件）。
- `settings_view.py`：`ClipboardSettingsPanel`，嵌入共享设置对话框；插件类声明 `settings_cards = True`，面板用 `SectionHeader` + `Card` 展示监听状态、三个 `ToggleRow`、容量 `SettingsRow`，按钮放在页面底色上。展示后端状态、记录开关、历史条数/图片容量上限、清空历史和打开数据目录；保存或清空后调用视图刷新并显示状态。设置入口从内容侧边栏和标题栏都走 `PluginBase.open_settings()`，不再自建 Toplevel。
- `view.py`：三栏历史界面；详情区顶部不再放图钉，置顶由标题栏统一提供。每条记录卡片末尾有三个图标（二次复制/打开位置/删除），由 `widgets.CardActionBar` 在**单个 Canvas** 上绘制并做横向命中检测；三套独立 Canvas 会让大历史首次打开明显变慢。Tooltip 在第一次悬停时才创建（`Tooltip.schedule()`），避免每行三个 Tooltip 拖慢列表构建。文本记录的“打开位置”置灰；详情页不再重复放置三个文字按钮。卡片背景在悬停/选中切换时通过 `_apply_card_background()` 同步给动作栏，否则图标周围会出现旧底色方块。`_open_settings()` 只触发插件传入的 `on_open_settings` 回调。
- `backends/`：`base.py` 定义后端协议；`__init__.py` 按平台选择。Linux 在 Wayland 下使用 `wl-clipboard`，**不会静默回退到 X11**；X11 使用 XFixes/ICCCM；Windows 使用 ctypes 原生剪贴板。`models.py` 必须保持不依赖 Tk 和平台模块。
- 新增后端模块或后端导入新库时，检查 `QuickTools.spec` 的 `hiddenimports`，因为内置插件是运行时动态导入的，PyInstaller 无法静态发现。

### 截图（`quicktools/plugins/screenshot/`）

- 当前进度：核心动作链路、X11/Windows 矩形/窗口/自由/滚动截图、冻结画面选区、标注编辑窗口、最近截图库（搜索/筛选/收藏）、插件设置和截图快捷键已完成；控制窗口采用左侧导航（首页/关于/设置）+ 一行紧凑模式卡，编辑器使用图标工具条。Wayland 通过 portal 支持区域/窗口截图，自由截图走“全屏 + 编辑器套索裁剪”，滚动截图不支持。Wayland 仍需实机验收。
- `plugin.py`：动作白名单为 `open`、`capture_region`、`capture_window`、`capture_freeform`、`capture_scroll`；`_hotkey_managers` 同时注册主快捷键和 `shortcuts.py` 中固定的 `Ctrl+Alt+1~4` 模式快捷键，单个注册失败不影响其他项；所有快捷键只通过 `context.actions.post_action()` 投递动作，不在 pynput 线程直接操作 Tk。`create_settings_ui()` 构建 `ScreenshotSettingsPanel`，保存后通过 `_on_settings_saved()` 刷新控制窗口。
- `shortcuts.py`：`MODE_HOTKEYS` 是模式快捷键与模式卡快捷键文字的唯一来源，避免 UI 与注册逻辑漂移。
- `service.py`：负责隐藏窗口 → 抓屏 → 选区 → 编辑器 → 自动保存/复制/另存为/最近库的完整状态机；所有 Tk 操作在主线程，`stop_service()` 必须取消 after、销毁 overlay/editor、恢复窗口。`_autosave_image()` 把编辑器改动写入最近记录（`update_png` 同步原图和缩略图），并在该记录已有 `saved_path` 时覆盖对应文件。**关闭即保留**：`_editor_closed()` 不删除新截图记录，因为打开编辑器时原图已入库、改动由自动保存落库（以前“没动过就关闭”会删记录的逻辑已移除，不要加回来）。普通关闭丢弃 `_restore` 并调用 `actions.hide_windows()`，确保从最近截图打开编辑器等场景也不留下可见窗口；`_editor_closed(return_to_assistant=True)` 必须先 `_restore_windows()` 再 `actions.open_window()` 并调用 `_notify_recent_changed()`，以恢复并聚焦截图助手、强制刷新最近截图列表（窗口一直可见时不会触发 `<Map>`）。
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
- `ui/control_window.py` + `ui/home_page.py` + `ui/about_page.py` + `ui/recent_view.py`：控制窗口为左侧导航（首页/关于/设置）+ 右侧页面容器；页面容器行 `weight=1`，页脚和状态行固定。**首页/关于页不再放 `PinButton`**，置顶由外层 `WindowFrame` 标题栏统一提供；`show_page()` 不再同步页面图钉。侧边栏“设置”和关于页“打开设置”都调用 `plugin.open_settings(...)`，打开共享设置/关于对话框。首页顶部是一行四张紧凑模式卡（`ui/widgets.py` 的 `ModeCard` 只显示图标、名称和快捷键，说明文字改用 `Tooltip` 悬停显示），最近截图行是 HomePage 中唯一 `weight=1` 的行，占据剩余高度。关于页读取 `plugin.json` 版本并展示能力、快捷键和文件位置。最近截图使用 `ui/widgets.py` 的 `ScrollableFrame`、`PlaceholderEntry`、`ActionLink`、`FilterMenu` 和 `ColorSwatch`；搜索与筛选叠加，复制/收藏等操作用 toast 反馈。
- `ui/settings_view.py`：`_HotkeyRecorder` 和 `ScreenshotSettingsPanel`。截图设置已从独立 Toplevel 改为嵌入共享设置对话框的面板；插件类声明 `settings_cards = True`，面板用三个 `Card` 分组“保存位置与格式 / 快捷键 / 滚动截图”（保存目录、格式、质量、最近上限、快捷键、滚动参数），保存后通过 `on_saved` 刷新控制窗口并显示状态；`_HotkeyRecorder` 仍为独立对话框，但使用 `WindowFrame(dialog=True)` 自绘标题栏，内容也使用 `SectionHeader` + `Card`。
- `ui/icons.py`：Pillow 在 24×24 逻辑网格上绘制图标并 4 倍超采样；`IconSet` 按 `(名称, 像素尺寸, 颜色)` 缓存 `ImageTk.PhotoImage`，并在宿主 `<Destroy>` 时清空。**所有 PhotoImage 必须由 IconSet 或控件属性持有，且只能在 Tk 主线程创建**。Tk 不支持圆角容器，圆角只用于 Pillow 生成的图标底板/装饰卡。
- `editor/editor_window.py`：编辑窗口在内容构建前挂 `WindowFrame`（标题“编辑截图”、图标 S，置顶/隐藏/放大/关闭由标题栏提供），内容顶部原图钉已移除；`self.pin_button` 指向标题栏图钉以兼容测试。工具栏使用 `IconSet` 的图标在上、文字在下布局；复制成功后显示右下角 toast 并短暂把复制按钮改为“已复制 ✓”；另存为/`Ctrl+S` 也显示 toast。**底部不再有“保存”按钮**；文档修改后经 `AUTOSAVE_DELAY_MS`（400ms）防抖调用 `on_autosave`。`_request_close()` 先 `commit_pending_entry()`，再在 `content_signature()` 与基线不一致时调用 `_flush_autosave()` 立即落库，落库成功后 `mark_exported()` 前移基线，因此正常关闭不会弹确认；确认关闭后调用 `_copy_on_close()`，把最终画面通过 `on_copy` 自动写入剪贴板再 `_finish()`，失败只记日志并更新状态栏、不能阻止关闭，取消确认框时不得复制；只有自动保存失败等确实未落库的情况才基于 `document.content_signature()` 与 `mark_exported()` 基线比较弹出确认。**不存在“新截图必须复制或保存”这条规则**（原 `require_action_on_close` 已移除，不要加回来）。`_autosave()` 成功后设置 `_done=True` 并 `mark_exported()`。所有 after 任务（含 `_autosave_job`）在关闭时取消。**必须保留 `_copy_button` 文字闪烁为精确的“已复制 ✓”、`_close_return_button` 文本精确为“关闭并返回”、`_zoom_var` 的 `缩放 N%` 格式、`toolbar.width_var`/`font_size_var` 和 `toolbar._redo_or_reset`**，现有 UI 测试依赖这些契约。`close_and_return()` 通过可选 `on_return` 回调通知 service；`close()`、标题栏 X 和 `Esc` 仍走 `on_close`。`copy()`/`save()`/`save_as()`/自动保存成功后必须调用 `mark_exported()`。
- 复制图片走 `context.actions.copy_png_to_clipboard(png)`，由 launcher 转给剪贴板插件的 `copy_image_png()`；**不要从截图插件 import 剪贴板插件模块**，否则会生成重复模块树和后端实例。
- 选区覆盖鼠标所在显示器；V1 不做跨显示器拖拽。Windows 混合 DPI 多屏仅做了 Win32 负坐标定位兜底，仍需实机验收。
- 新增采集/portal 依赖时，同步更新 `QuickTools.spec` hiddenimports、`pyproject.toml` 和 `requirements.txt`。

## 测试与平台约定

- `tests/test_ui_smoke.py`、`tests/test_calculator_memory_ui.py`、`tests/test_flat_button.py`、`tests/test_clipboard_ui_smoke.py`、`tests/test_plugin_lifecycle.py`、`tests/test_plugin_actions.py`、`tests/test_launcher_window_state.py`、`tests/test_launcher_autohide.py`、`tests/test_x11_focus.py`、`tests/test_ui_icons.py`、`tests/test_win32_focus.py`、`tests/test_window_pin.py`、`tests/test_window_frame.py`、`tests/test_plugin_settings.py`、`tests/test_screenshot_ui_smoke.py` 需要可用显示；无 `DISPLAY` 时 skip。`test_x11_focus.py` 在真实 X11 上验证 `force_foreground()` 能把焦点移到 override-redirect 窗口、`is_foreground()` 能识别焦点窗口，并在结束后恢复用户原来的焦点；Wayland 下整组 skip。`test_launcher_autohide.py` 的“点击外部”用例会把 `is_foreground` 固定为 False，模拟原生焦点已经离开启动器。`test_ui_icons.py` 验证内置 Material Icons 字体能注册、`pick_fonts()` 返回该字体族、绘制的是对应码位，并覆盖字体缺失时走 Canvas 回退。`test_hotkey_win32.py` 只测 Win32 虚拟键映射，非 Windows 全部 skip。`test_window_frame.py` 验证自绘标题栏按钮、置顶、放大/还原、关闭/设置回调、对话框模式，以及 Tk 缩放的事件合并；`test_window_state.py` 验证窗口尺寸文件的往返、损坏回退和非法值过滤，`test_launcher_window_state.py` 验证关闭重开与退出前 flush 后的尺寸恢复；`test_plugin_settings.py` 验证共享设置/关于对话框的内容、复用与关闭；`test_window_pin.py` 只验证兼容保留的 `PinButton`，并覆盖 Linux 下 X11 忽略 `-topmost` 时仍能保持内部置顶状态；`test_window_frame.py` 的 `test_pin_state_is_tracked_when_x11_ignores_topmost` 验证标题栏图钉的同一行为。`test_plugin_loader.py` 包含“重新扫描后旧实例仍能懒加载相对导入”的回归用例（启动器每次显示都会扫描，剪贴板设置页曾因此报 `No module named '_quicktools_plugin_clipboard_1'`，不要恢复在 `_invalidate()` 里删除已导入包的行为）。`test_plugin_settings.py` 还验证默认包一张卡片与 `settings_cards=True` 不重复外包。`test_launcher_autohide.py` 用真实 `tk.Tk`/`Launcher`，并通过 monkeypatch `window.after`/`after_cancel` 记录调度，不等待真实计时器；`test_win32_focus.py` 的 Win32 用例只在 Windows 上运行。Windows 上无边框窗口在未映射时 Tk 不会给子控件分配尺寸，`test_screenshot_ui_smoke.py` 的平移/缩放用例会先 `deiconify()` 再测量；不要改回只 `withdraw()`。整轮测试偶尔会在 Tk 初始化时抛 `couldn't read ... tcl8.6/init.tcl`（Windows 上创建 Tk 的并发问题），重跑即可恢复，与业务代码无关。
- `tests/test_clipboard_windows.py` 只在 Windows 上运行；Linux 下 skip。截图 Windows 路径目前没有自动化实机测试，需按 README 清单验收。
- 剪贴板服务测试使用 `FakeBackend`/`FakeRoot`，不依赖真实系统剪贴板；引擎测试只依赖 `engine.py`。
- 截图测试：几何/标注/渲染/拼接/设置/最近库/portal/图标绘制/快捷键注册为纯逻辑测试；`test_screenshot_service.py` 用 `FakeRoot`/FakeBackend/FakeOverlay/FakeEditor 测状态机；`test_screenshot_ui_smoke.py` 覆盖画笔绘制、空格+左键平移、选择工具空白处平移、自动保存和关闭前 flush；`test_screenshot_service.py` 覆盖自动保存更新最近记录/缩略图、同步覆盖已导出文件以及返回时刷新最近列表；`test_screenshot_control_window.py` 和 `test_screenshot_backends.py` 的 X11 用例、`test_screenshot_icons.py` 的 IconSet 用例需要显示。Wayland portal 只用 fake 客户端验证，真实 portal 必须按 README 在 Wayland 实机验收。
- `test_settings_widgets.py` 验证自绘开关和 `Card` 的圆角/阴影绘制；`test_plugin_settings.py` 的剪贴板用例会在真实加载器上先重扫再打开设置页，覆盖打包版曾出现的 `No module named '_quicktools_plugin_clipboard_1'` 回归。
- 当前实测通过的是 Linux X11；Windows 和 Wayland 代码路径已适配但仍需实机验收，清单见 README。
- 日志位置：Linux `~/.local/share/quicktools/logs/quicktools.log`，Windows `%APPDATA%\QuickTools\logs\quicktools.log`。打包版 Linux 用 `--foreground` 可实时打印日志。
