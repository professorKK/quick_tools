# 快捷工具 QuickTools

一个常驻后台的桌面插件启动器：按全局快捷键唤出，点击插件后启动器隐藏，插件作为独立窗口继续使用。内置草稿纸计算器和剪贴板历史。

- Python 3.10+ / Tkinter
- Linux（X11）与 Windows 11
- 默认全局快捷键：Linux 为 `Ctrl+Alt+Space`，Windows 为 `Ctrl+Space`；均可在设置中修改
- 插件使用 Python + Tkinter 编写，放入用户插件目录即可被发现

## 安装与启动

### Linux

```bash
cd /home/kk/quicktools
python3 -m venv .venv
.venv/bin/pip install -e .
./run.sh
```

启动后会出现插件启动器，同时注册 Linux 默认快捷键 `Ctrl+Alt+Space`（避开输入法常用的 `Ctrl+Space`）。关闭启动器只是隐藏，应用继续驻留后台；Linux X11 下点击系统顶栏中的蓝色 QuickTools 图标会弹出“显示 / 退出”下拉菜单。可在启动器的“设置”中退出。

### Windows 11

在 PowerShell/命令提示符中：

```bat
cd C:\path\to\quicktools
py -3 -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\pythonw -m quicktools
```

也可以双击 `run.bat`。`pythonw` 不显示控制台窗口。

> 首次安装需要联网下载 `pynput`、`pystray`、`Pillow` 与 `python-xlib`（Linux）。Linux 若提示缺少 Tkinter，请安装发行版提供的 `python3-tk`。

## 使用

- 全局快捷键显示/隐藏启动器：Linux 默认 `Ctrl+Alt+Space`，Windows 默认 `Ctrl+Space`。
- 点击插件卡片启动插件。再次点击已打开的插件会聚焦原窗口，不会开第二个相同插件窗口。
- 启动器隐藏后，全局快捷键依然可用，插件窗口可以继续使用。
- 状态栏/顶栏有一个 QuickTools 图标。Linux 下点击它弹出原生下拉菜单：第一项“显示”打开启动器，第二项“退出”结束程序。Windows 使用系统托盘的“显示 / 退出”菜单。
- 设置里可录制新快捷键、开启/关闭开机启动、打开插件目录、重新扫描插件、退出应用；设置窗口左上角“← 返回启动器”或窗口关闭按钮会回到启动器，Esc 也可返回。
- Linux 默认值已避开输入法常用的 `Ctrl+Space`。Windows 的 `Ctrl+Space` 若与输入法冲突，也可在设置中改绑（例如 `Ctrl+Alt+Space`）。
- 命令行控制（需要主实例已在运行）：

```bash
./run.sh --show        # 显示启动器
./run.sh --toggle      # 切换启动器
./run.sh --background  # 后台启动（登录自启动使用）
./run.sh --quit        # 退出主实例
```

## Linux 原生状态栏菜单

Linux 优先使用 freedesktop 的 **StatusNotifierItem + DBusMenu**（通过 Ubuntu 的 Ayatana AppIndicator）。菜单由桌面环境绘制，所以样式与微信、输入法等系统指示器一致，不再是自绘窗口。

状态栏助手使用系统 Python 及其 `python3-gi`、`gir1.2-ayatanaappindicator3-0.1`（Ubuntu 22.04 默认已安装）。如果系统缺少这些组件，会自动回退到 XEmbed + Tk 菜单；日志中可确认当前模式：`原生状态栏助手已启动（AppIndicator/SNI）`。

## Linux Wayland 说明

pynput 无法在 Wayland 会话中监听整个桌面的键盘事件。当前工具在 Wayland 下会明确提示，而不会假装快捷键已生效。可靠替代方案：

1. 先正常运行应用。
2. 在桌面环境的“自定义快捷键”中，把任意组合键绑定到下面的命令：

```bash
/home/kk/quicktools/run.sh --toggle
```

第二次调用会把命令发送给已经运行的主实例，因此可以正常显示/隐藏启动器。应用内录制快捷键只在 X11/Windows 下自动生效。

## 计算器

上方是草稿纸，下方是按键和进制转换。

- 键盘输入支持数字、`()`、`+ - * / // % ^ **`。按 `Enter` 或 `=` 计算。
- `^` 与 `**` 是右结合次方，例如 `2^3^2 = 512`。
- 中文/全角 `（ ）`、全角数字和运算符会自动归一化为英文符号。
- 鼠标可点击表达式任意字符定位光标，然后输入、Backspace、Delete 或拖选修改。
- 计算成功后本行显示 `= 结果`，若它是最后一行，会自动新增空白层并滚到底部。
- 点击任意历史层可原地编辑并重新计算；多个结果会同时保留。默认视口显示 4 层，滚轮或右侧滚动条可查看更多。
- 进制支持 DEC / HEX / OCT / BIN。活动进制决定裸数字的解释和结果显示，并禁用非法数字按键；`0x`、`0b`、`0o` 前缀在任何模式下都有效。
- 转换栏实时显示当前值在四种进制下的表示，可选中复制。非整数只提供十进制表示。
- 非 DEC 模式的小数点输入被禁用；除法仍可产生小数。
- 安全的递归下降解析器，不使用 `eval`；除零、括号不匹配、非法进制数字、指数过大等都会显示错误。

## 剪贴板

内置「剪贴板」插件在 QuickTools 运行期间自动记录复制过的文本、图片和文件列表。历史按复制时间倒序排列，最新记录在最上方。

- 支持搜索、按文本/图片/文件筛选、最新优先/最早优先排序。
- 详情页可预览文本或图片、查看原始文件路径、二次复制、打开文件位置、删除单条记录。
- 文本记录可在详情框中直接编辑，停止输入约 0.7 秒后自动保存；切换记录、关闭窗口或退出应用时也会立即保存。编辑不会改变该记录在历史中的位置；若编辑成与另一条记录相同的内容，会自动合并。
- 文件列表只保存原始路径（Windows 反斜杠路径原样保留），不会复制文件内容；文件被移动/删除后会显示不可访问提示。
- 图片以 PNG 保存到插件数据目录并生成缩略图，避免复制后源图片消失。
- 相同内容会合并为一条并置顶，复制次数累加，避免历史被连续重复内容刷屏。
- 设置中可暂停记录、调整历史条数与图片总量上限、关闭图片/文件捕获、清空历史。
- 关闭插件窗口不会停止记录；只要 QuickTools 仍在后台运行，就会继续监听。退出 QuickTools 后停止。
- 历史数据库为 SQLite，重启应用后保留。

数据位置：

- Linux：`~/.local/share/quicktools/plugin_data/clipboard/`
- Windows：`%APPDATA%\QuickTools\plugin_data\clipboard\`

### 剪贴板平台说明

- **Linux X11**：使用 XFixes 选择区事件监听和 ICCCM 选择区读写（含 INCR 大内容分块），无需安装额外工具。依赖已在 Linux 上自动安装的 `python-xlib`。
- **Linux Wayland**：Wayland 没有跨应用的标准剪贴板监听 API，需要安装 `wl-clipboard`（`wl-paste` / `wl-copy`）。不同合成器（GNOME/KDE 等）对后台读取的限制不同，**不保证所有 Wayland 环境都能监听**。安装示例：Ubuntu/Debian `sudo apt install wl-clipboard`，Fedora `sudo dnf install wl-clipboard`，Arch `sudo pacman -S wl-clipboard`，openSUSE `sudo zypper install wl-clipboard`。缺少依赖时插件会在设置页显示明确提示，不会假装监听成功。
- **Windows**：使用原生 `AddClipboardFormatListener` 消息监听，支持 `CF_UNICODETEXT`、`CF_DIB` 和 `CF_HDROP`，不依赖 pywin32。
- **验证状态**：当前开发机只实机验证了 Linux X11；Windows 与 Wayland 的代码路径已实现，但仍需按下方清单在真实环境验收，不能把“已实现”等同于“已验证”。
- X11/Wayland 下 QuickTools 退出后系统剪贴板内容是否保留取决于桌面环境；历史记录本身已持久化。

## 插件

用户插件目录：

- Linux：`~/.local/share/quicktools/plugins`
- Windows：`%APPDATA%\QuickTools\plugins`

每个插件是一个文件夹，至少包含 `plugin.json` 和入口 Python 文件。把文件夹复制进去后，下次唤出启动器会自动发现；也可以在设置中点击“重新扫描插件”。

完整契约和示例见 [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md)，可运行的最小插件见 [examples/hello_plugin](examples/hello_plugin)。

插件在应用主进程内运行，拥有与主程序相同的权限；**只安装可信插件**。

## 数据与配置位置

- Linux 配置：`~/.config/quicktools/settings.json`
- Linux 数据/日志/插件：`~/.local/share/quicktools/`
- Windows 配置、插件、日志：`%APPDATA%\QuickTools\`
- 日志：`logs/quicktools.log`

## 已知边界

- Linux Wayland 不做应用内全局键盘监听，使用 `--toggle` + 系统快捷键（见上）。原生 AppIndicator 状态栏在支持 StatusNotifier 的桌面环境下可用；无 AppIndicator 时会回退到 XEmbed（Wayland 下回退图标不保证显示）。当前 X11 已验证。
- V1 不支持 C++ 插件 ABI，也不对插件做进程沙箱。
- 计算器历史只在当前窗口生命周期内保留。
- 剪贴板在 Linux Wayland 下依赖 `wl-clipboard`，且不同合成器限制不同；无法保证所有 Wayland 环境可用。
- 当前环境已验证 Linux X11；Windows 11 的代码路径已做平台适配，但仍需在真实 Windows 机器上完成验收。剪贴板 Windows 后端的实机验收项见下方清单。

## Windows 11 验收清单

在真实 Windows 11 上请逐项确认：

1. `.venv\Scripts\pythonw -m quicktools` 启动后无控制台窗口，启动器出现。
2. 默认 `Ctrl+Space` 与自定义快捷键都能唤出/隐藏启动器（Windows 默认未改）；若与中文输入法冲突，使用设置中的自定义快捷键。
3. 点击计算器后启动器隐藏、计算器获得焦点；再次唤出启动器并点击计算器会聚焦原窗口。
4. 单实例：再运行一次普通命令只显示已有启动器；`--toggle`、`--quit` 生效。
5. 中文输入法输入 `（）` 后自动变成 `()`；鼠标点字、Backspace/Delete、`=` 求值正常。
6. 高 DPI 下字体与窗口尺寸合理；关闭启动器后进程仍在后台。
7. Windows 系统托盘出现 QuickTools 图标；点击可恢复启动器，托盘菜单的“设置/退出”可用。
8. 若打包：`QuickTools.exe --toggle` 能唤出已运行的实例。

## 剪贴板 Windows 验收清单

当前开发机无法运行 Windows，以下项目必须在真实 Windows 10/11 上逐项确认：

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests\test_clipboard_windows.py -q
.venv\Scripts\pytest -q
run.bat
```

1. 复制文本后，剪贴板列表出现新记录，最新记录位于顶部。
2. 复制图片（例如截图工具或浏览器图片）后，可查看预览并点击“二次复制”再次写入剪贴板。
3. 在文件资源管理器中复制单个文件，路径以 `C:\...` 原样显示。
4. 在文件资源管理器中复制多个文件，显示为多条路径或“N 个文件”。
5. 搜索、类别筛选、排序、详情、删除、清空历史均可用。
6. 退出并重启 QuickTools 后，历史记录仍在。
7. 移动或删除已复制的文件后，详情显示不可访问提示，“打开位置”和“二次复制”给出明确错误。
8. 关闭启动器和剪贴板窗口后，复制内容仍被后台记录。
9. 在设置中暂停记录后，继续复制不会新增历史；恢复后重新开始记录。
10. 二次复制文本、图片和文件列表后，可在资源管理器中粘贴验证。
11. 使用 PyInstaller 打包后再执行 1–10 的核心项。

`tests/test_clipboard_windows.py` 会在 Windows 上实际执行原生剪贴板读写与监听测试；在 Linux 上这 4 个测试会被跳过。

## Linux Wayland 剪贴板验收

在 GNOME Wayland 或 KDE Wayland 会话中安装 `wl-clipboard` 后，重复上述文本/图片/文件/暂停/重启测试。插件状态区应显示 `Wayland (wl-clipboard)`；若未安装依赖，应显示不可用及安装提示。部分合成器可能限制后台读取，请记录实际结果，不要假定所有 Wayland 环境都可用。

## 运行测试

```bash
.venv/bin/pip install -e '.[dev]'
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于避开当前 Ubuntu 环境中 ROS 注入的 pytest 插件；普通干净环境可以省略。

## 可选：打包 / 开机启动

这不是“编译”，而是用 PyInstaller 把 Python 应用打包成独立的可执行程序。必须在项目根目录执行，且 PyInstaller 不能跨平台打包（Linux 包在 Linux 上打，Windows 包在 Windows 上打）。

也可直接运行仓库根目录的便捷脚本：

- Linux：`./build_linux.sh`，产出 `dist/QuickTools/QuickTools`
- Windows：`build_windows.bat`，产出 `dist\QuickTools\QuickTools.exe`（需在真实 Windows 上执行）

Linux 目录版（默认，启动更快，产出为一个文件夹）：

```bash
cd /home/kk/quicktools
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --noconfirm --windowed --name QuickTools \
  --add-data "quicktools/plugins:quicktools/plugins" \
  --add-data "quicktools/assets:quicktools/assets" \
  --add-data "quicktools/helpers:quicktools/helpers" \
  --paths . scripts/quicktools_launcher.py
```

产出是 `dist/QuickTools/QuickTools`。启动后可用以下命令唤出/退出：

```bash
dist/QuickTools/QuickTools --toggle
dist/QuickTools/QuickTools --quit
```

如果希望得到单个可执行文件，增加 `--onefile`：

```bash
.venv/bin/pyinstaller --noconfirm --onefile --windowed --name QuickTools \
  --add-data "quicktools/plugins:quicktools/plugins" \
  --add-data "quicktools/assets:quicktools/assets" \
  --add-data "quicktools/helpers:quicktools/helpers" \
  --paths . scripts/quicktools_launcher.py
```

此时产出为 `dist/QuickTools`，第一次启动会稍慢。用户插件仍从用户数据目录读取，不会打进二进制。

Windows 上把 `--add-data` 的分隔符改成 `;`：

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --icon "quicktools\assets\quicktools.ico" --name QuickTools ^
  --add-data "quicktools\plugins;quicktools\plugins" ^
  --add-data "quicktools\assets;quicktools\assets" ^
  --add-data "quicktools\helpers;quicktools\helpers" ^
  --paths . scripts\quicktools_launcher.py
```

Windows 目录版产出 `dist\QuickTools\QuickTools.exe`；如需单文件，再加上 `--onefile`。打包后先启动程序，再用 `QuickTools.exe --toggle` 验证单实例唤出。

## 图片资源

Logo 源文件与派生图标统一放在 `quicktools/assets/`，清单见 [assets/README.md](quicktools/assets/README.md)。更换 `logo.png` 后运行：

```bash
.venv/bin/python scripts/prepare_assets.py
```

会重新生成窗口图标、启动器标题图标、Linux/Windows 状态栏图标和 Windows `.ico`。

## 开机启动

在“设置 → 开机启动”中勾选“登录系统时自动启动 QuickTools（后台运行）”即可。程序会自动识别平台，把当前用户的自启动项写入系统机制，无需 root / 管理员权限：

- **Linux**：XDG Autostart，写入 `$XDG_CONFIG_HOME/autostart/quicktools.desktop`（默认 `~/.config/autostart/quicktools.desktop`）。
- **Windows**：注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 中的 `QuickTools` 值（`REG_SZ`）。

登录后 QuickTools 会在后台静默启动：不弹出启动器，只驻留托盘并注册全局快捷键；如果已有实例运行则静默退出，不会重复启动。取消勾选会删除对应的自启动项。

注意：

- 只作用于当前用户，不做系统级（`/etc/xdg/autostart` 或 `HKLM`）安装。
- 移动或重装应用后，自启动项可能仍指向旧路径；取消勾选再重新勾选即可刷新。
- Windows 任务管理器可以独立禁用该启动项；应用内开关只反映注册表中的值。
- 源码模式下若用 `python.exe` 启动，Windows 登录时可能闪现控制台窗口；打包版或 `pythonw` 不受影响。
