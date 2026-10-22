# 快捷工具 QuickTools

![QuickTools 快捷工具宣传横幅：一个快捷键，打开你的效率工具箱](docs/images/quicktools-banner.png)

QuickTools 是一个常驻后台的桌面插件启动器：按下全局快捷键唤出启动器，点击卡片打开需要的工具，启动器随即隐藏，插件作为独立窗口继续使用。内置草稿纸计算器、剪贴板历史和截图工具，也可以用 Python 编写自己的插件。

- **运行环境**：Python 3.10+ / Tkinter
- **平台**：Linux（X11）与 Windows 11；Wayland 提供受限支持
- **默认快捷键**：Linux `Ctrl+Alt+Space`，Windows `Ctrl+Space`
- **数据**：全部保存在本机，详见[数据与配置位置](#数据与配置位置)

## 目录

- [主要功能](#主要功能)
  - [快捷键与启动器](#快捷键与启动器)
  - [三件内置工具](#三件内置工具)
  - [统一窗口体验](#统一窗口体验)
  - [插件扩展能力](#插件扩展能力)
- [安装与启动](#安装与启动)
  - [环境要求](#环境要求)
  - [Linux](#linux)
  - [Windows 11](#windows-11)
  - [登录时自动启动](#登录时自动启动)
- [使用](#使用)
  - [启动器操作](#启动器操作)
  - [插件窗口](#插件窗口)
  - [全局快捷键](#全局快捷键)
  - [系统托盘与状态栏](#系统托盘与状态栏)
  - [命令行参数](#命令行参数)
  - [Linux Wayland](#linux-wayland)
- [内置插件](#内置插件)
  - [计算器](#计算器)
  - [剪贴板](#剪贴板)
  - [截图](#截图)
- [打包与分发](#打包与分发)
  - [产物一览](#产物一览)
  - [Windows 一键全量打包](#windows-一键全量打包)
  - [Windows 目录版](#windows-目录版)
  - [Linux 目录版](#linux-目录版)
  - [打包注意事项](#打包注意事项)
- [插件开发](#插件开发)
  - [插件目录与发现](#插件目录与发现)
  - [插件清单](#插件清单)
  - [生命周期与窗口](#生命周期与窗口)
  - [参考](#参考)
- [数据与配置位置](#数据与配置位置)
- [仓库脚本一览](#仓库脚本一览)
- [图片资源](#图片资源)
- [开发与测试](#开发与测试)
  - [运行测试](#运行测试)
  - [提交代码](#提交代码)
- [常见问题](#常见问题)
- [已知边界](#已知边界)
- [实机验收清单](#实机验收清单)
  - [Windows 11 通用](#windows-11-通用)
  - [Windows 剪贴板](#windows-剪贴板)
  - [Windows 截图](#windows-截图)
  - [Wayland 截图](#wayland-截图)
  - [Wayland 剪贴板](#wayland-剪贴板)

## 主要功能

### 快捷键与启动器

- 全局快捷键随时唤出或隐藏启动器；启动器无边框，打开后可直接输入搜索，拖动窗口边缘可调整大小。
- 用快捷键或 `--toggle` 唤出时，启动器会主动取得键盘焦点，点击启动器以外的任意位置会自动隐藏；全新普通启动（当前没有已运行实例）同样支持点击外部隐藏。通过托盘“显示”、`--show`、设置返回或截图恢复等方式显示时不会自动隐藏。Linux X11 使用原生 X 输入焦点实现；Wayland 的焦点由合成器控制，该行为不保证。
- 单实例运行：重复启动只会把命令发给已有实例，不会启动第二个进程。
- 支持登录时自动启动、命令行控制和 `--screenshot` 截图动作。
- 同一个插件最多一个窗口，再次点击卡片会聚焦原窗口。
- 插件主窗口（计算器、剪贴板、截图助手）失去焦点时自动隐藏，再次点击对应卡片即可恢复；已置顶的窗口不会因失焦隐藏。截图编辑器、选区/滚动覆盖层和设置/关于对话框不参与失焦隐藏。
- 插件卡片只显示图标、名称和一句话概述，完整介绍放在“设置 → 关于”中。
- 标题栏的设置/置顶/关于图标使用随包内置的 Material Icons，Windows 与 Linux 显示一致；字体文件缺失或加载失败时自动回退到 Canvas 线稿。
- 关闭启动器只是隐藏，应用继续驻留后台；托盘/顶栏菜单提供“显示”和“退出”。

### 三件内置工具

| 工具 | 能力摘要 | 打开方式 |
| --- | --- | --- |
| [计算器](#计算器) | 草稿纸式实时计算，科学模式支持 BIN/OCT/HEX/DEC 与 A-F 按键，记录自动保存 | 启动器卡片 |
| [剪贴板](#剪贴板) | 后台记录文本、图片和文件列表，支持搜索、筛选、编辑与二次复制 | 启动器卡片 |
| [截图](#截图) | 区域、窗口、自由和滚动截图，内置标注编辑器与最近截图库 | 卡片、`Ctrl+Alt+X`、`Ctrl+Alt+1~4`（X11/Windows） |

### 统一窗口体验

- 所有插件窗口都使用自绘的无边框标题栏：左侧是图标和名称，右侧依次是设置（齿轮）、置顶（图钉）、隐藏、放大和关闭。
- 拖动标题栏可移动窗口，拖动窗口边缘可调整大小，双击标题栏可在“放大/还原”之间切换。
- “设置”打开统一的设置与关于对话框：左侧导航，设置页由插件提供，关于页自动展示版本、详细说明、作者、插件目录和数据目录。
- 每个插件的窗口大小和放大状态会自动记住；位置不保存，重新打开时居中。

### 插件扩展能力

- 插件使用 Python + Tkinter 编写，放入用户插件目录即可被发现，无需修改主程序。
- 普通插件在点击卡片时懒加载；声明 `background: true` 的插件在应用启动后立即运行后台服务。
- 启动器统一提供无边框标题栏、置顶、隐藏、放大、关闭和设置/关于对话框，插件只需实现内容界面。
- 插件运行在主进程内，拥有与主程序相同的权限；**只安装可信插件**。

当前 Linux X11 已实机验证；Windows 与 Wayland 的代码路径已适配，仍需按文末的[实机验收清单](#实机验收清单)在真实环境确认。所有配置、历史记录和截图都保存在本机，不会上传。

## 安装与启动

### 环境要求

- Python 3.10 或更高版本，并带有 Tkinter。
- Linux：X11 会话；Wayland 仅支持部分能力（见 [Linux Wayland](#linux-wayland)）。缺少 Tkinter 时安装发行版提供的 `python3-tk`。
- Windows：Windows 11。
- 首次安装需要联网下载依赖：`pynput`、`pystray`、`Pillow`，Linux 另有 `python-xlib` 和 `jeepney`。

### Linux

在项目根目录执行：

```bash
cd /path/to/quicktools
python3 -m venv .venv
.venv/bin/pip install -e .
./run.sh
```

`run.sh` 优先使用 `.venv/bin/python`，没有虚拟环境时回退到系统 `python3`，参数会原样透传。启动后出现启动器，并注册 Linux 默认快捷键 `Ctrl+Alt+Space`（避开输入法常用的 `Ctrl+Space`）。

关闭启动器只是隐藏，应用继续驻留后台。Linux X11 下点击系统顶栏中的蓝色 QuickTools 图标会弹出“显示 / 退出”菜单；也可以在启动器的“设置”中退出。

如果提示缺少 Tkinter，Debian/Ubuntu 可运行 `sudo apt install python3-tk`。

### Windows 11

在 PowerShell 或命令提示符中：

```bat
cd C:\path\to\quicktools
py -3 -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\pythonw -m quicktools
```

也可以双击 `run.bat`：它使用 `pythonw` 启动，不显示控制台窗口，参数同样原样透传。

### 登录时自动启动

在“设置 → 开机启动”中勾选“登录系统时自动启动 QuickTools（后台运行）”即可。程序会自动识别平台，把当前用户的自启动项写入系统机制，无需 root / 管理员权限：

- **Linux**：XDG Autostart，写入 `$XDG_CONFIG_HOME/autostart/quicktools.desktop`（默认 `~/.config/autostart/quicktools.desktop`）。
- **Windows**：注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 中的 `QuickTools` 值（`REG_SZ`）。

登录后 QuickTools 会在后台静默启动：不弹出启动器，只驻留托盘并注册全局快捷键；如果已有实例运行则静默退出，不会重复启动。取消勾选会删除对应的自启动项。

注意：

- 只作用于当前用户，不做系统级（`/etc/xdg/autostart` 或 `HKLM`）安装。
- 移动或重装应用后，自启动项可能仍指向旧路径；取消勾选再重新勾选即可刷新。
- Windows 任务管理器可以独立禁用该启动项；应用内开关只反映注册表中的值。
- 源码模式下若用 `python.exe` 启动，Windows 登录时可能闪现控制台窗口；打包版或 `pythonw` 不受影响。

## 使用

### 启动器操作

- 用全局快捷键显示/隐藏启动器。用快捷键或 `--toggle` 唤出后，启动器会直接取得键盘焦点，可以直接输入搜索；点击启动器以外的任意位置（其他窗口、桌面等）会自动隐藏启动器。Linux X11 通过 `XSetInputFocus` 让无边框启动器取得真实输入焦点，因此点击外部产生的焦点变化可以被检测到；Wayland 下该行为取决于合成器，不保证生效。
- 通过托盘“显示”、`--show`、从设置返回或截图结束后的恢复显示时，启动器不会自动隐藏；按 `Esc` 或点击界面上的“隐藏”即可收起。全新普通启动的启动器与快捷键唤出一样，点击外部会隐藏。
- 启动器首次打开为 860×560，可拖动上下左右边缘或四角调整大小，最小 720×480；隐藏再唤出后保持当前尺寸。
- 点击插件卡片启动插件。再次点击已打开的插件会聚焦原窗口，不会打开第二个相同插件窗口；插件窗口被“隐藏”或因失焦自动隐藏后，卡片仍显示“已打开”，点击即可恢复。
- 插件主窗口失去焦点时同样会自动隐藏；点击对应卡片可恢复。已置顶的窗口不会因失焦隐藏，方便一边操作其他应用一边查看。截图编辑器、选区覆盖层、滚动控制条以及设置/关于对话框不参与失焦隐藏，避免截图或设置过程中被误关。
- 设置里可录制新快捷键、开启/关闭开机启动、打开插件目录、重新扫描插件、退出应用；设置窗口左上角“← 返回启动器”或标题栏关闭按钮会回到启动器，`Esc` 也可返回。
- 启动器隐藏后，全局快捷键依然可用，插件窗口可以继续使用。

### 插件窗口

- 所有插件窗口都没有系统标题栏。顶部统一标题栏左侧显示插件图标和名称，右侧依次是齿轮（设置）、图钉（置顶）、隐藏、放大和关闭。
- 拖动标题栏可移动窗口；拖动窗口边缘可调整大小；双击标题栏可在“放大/还原”之间切换。
- “设置”打开该插件的设置与关于对话框：对话框使用卡片式布局（左侧导航、页面标题、白色圆角分组卡片和固定底部状态栏），设置页由插件提供，关于页自动展示版本、详细说明、作者、插件目录和数据目录。计算器、剪贴板和截图插件的详细功能说明都在这里。
- “置顶”切换当前窗口的置顶状态，再次点击取消；状态只对当前窗口生效，关闭窗口后不保留。截图选区和滚动控制条这类临时覆盖层不适用。
- “隐藏”在 Windows 上最小化到任务栏；Linux 下无边框窗口不受窗口管理器管理，会收回窗口，可再次用全局快捷键唤出启动器并点击插件卡片恢复。
- 每个插件窗口的大小和放大状态会按插件记住：拖动边缘缩放或点击“放大”后关闭，再打开或重启应用时恢复上次状态；位置不保存，打开时重新居中。若显示器分辨率或缩放变化导致旧尺寸超出当前屏幕，会自动收缩到可用范围。

### 全局快捷键

- Linux 默认 `Ctrl+Alt+Space`，Windows 默认 `Ctrl+Space`，均可在设置中修改。
- 在 Windows 上，QuickTools 优先使用原生 `RegisterHotKey` 注册快捷键。原生注册会独占该组合键，并让快捷键唤出的启动器直接获得前台焦点；若组合键已被其他程序占用，会自动回退到低级键盘钩子，焦点可能比原生路径慢几十毫秒。
- `Ctrl+Space` 在 Windows 上会与部分中文输入法的中英文切换冲突，建议在设置中改绑 `Ctrl+Alt+Space`。
- Linux Wayland 不做应用内全局键盘监听，需要使用系统快捷键（见 [Linux Wayland](#linux-wayland)）。
- 应用内录制快捷键只在 X11/Windows 下自动生效。

### 系统托盘与状态栏

- Linux 优先使用 freedesktop 的 **StatusNotifierItem + DBusMenu**（通过 Ubuntu 的 Ayatana AppIndicator）。菜单由桌面环境绘制，样式与微信、输入法等系统指示器一致，不再是自绘窗口。
- 状态栏助手使用系统 Python 及其 `python3-gi`、`gir1.2-ayatanaappindicator3-0.1`（Ubuntu 22.04 默认已安装）。如果系统缺少这些组件，会自动回退到 XEmbed + Tk 菜单；日志中可确认当前模式：`原生状态栏助手已启动（AppIndicator/SNI）`。
- Windows 使用 `pystray` 原生托盘。
- 菜单提供“显示”和“退出”。Linux 下第一项“显示”打开启动器，第二项“退出”结束程序；状态栏子进程通过 IPC 控制主实例。

### 命令行参数

命令行控制采用单实例 IPC 设计：如果已有实例在运行，命令会发送给该实例，不会启动第二个进程。

下面以源码方式的 `./run.sh` 为例；Linux 打包版把 `./run.sh` 换成 `dist/linux/QuickTools/QuickTools`，Windows 打包版换成 `dist\win\QuickTools\QuickTools.exe` 即可。

| 参数 | 作用 |
| --- | --- |
| 无参数 | 显示启动器；已有实例则唤出已有窗口，无实例则启动并显示 |
| `--show` | 显示启动器；不会启用点击外部自动隐藏 |
| `--toggle` | 切换启动器显示状态；无实例时启动并显示，且支持点击外部自动隐藏 |
| `--background` | 后台启动，不显示窗口；已有实例则静默退出，用于登录自启动 |
| `--quit` | 退出已运行的主实例；没有实例时静默退出 |
| `--screenshot` | 触发矩形截图（默认 `region`） |
| `--screenshot region` | 触发区域截图 |
| `--screenshot window` | 触发窗口截图 |
| `--screenshot freeform` | 触发自由截图 |
| `--screenshot scroll` | 触发滚动截图 |
| `--screenshot open` | 打开截图助手控制窗口 |
| `--foreground` | 前台运行并实时打印日志；可与上述参数组合 |
| `--version` | 显示版本号 |
| `--help` / `-h` | 显示全部参数说明 |
| `--tray-helper` | 状态栏托盘子进程使用的内部参数，普通用户无需指定 |

`--show`、`--toggle`、`--background`、`--quit` 互斥，只能选择一个；`--foreground` 可以和它们组合。

`--screenshot` 系列在没有运行实例时会先启动主程序（不显示启动器）再执行截图动作；`--screenshot open` 同样可以冷启动截图助手。

```bash
./run.sh --toggle                 # 切换启动器显示状态
./run.sh --screenshot region      # 区域截图
./run.sh --background --foreground  # 后台启动并在终端查看日志
```

Linux 打包版（`dist/linux/QuickTools/QuickTools`）在终端里直接运行时会先完成单实例检查，然后自动脱离终端转入后台：命令立即返回，关闭终端不会退出应用。需要在前台观察日志时加 `--foreground`，终端会实时打印运行日志；此时关闭终端会结束应用。源码方式本来就是前台运行，`--foreground` 不改变其行为。

后台运行时的日志写入 `~/.local/share/quicktools/logs/quicktools.log`，可实时查看：

```bash
tail -f ~/.local/share/quicktools/logs/quicktools.log
```

### Linux Wayland

Wayland 不允许应用监听整个桌面的键盘事件，因此 QuickTools 在 Wayland 下会明确提示，而不会假装快捷键已生效。可靠替代方案：

1. 先正常运行应用。
2. 在桌面环境的“自定义快捷键”中，把任意组合键绑定到下面的命令：

```bash
/path/to/quicktools/run.sh --toggle
/path/to/quicktools/run.sh --screenshot region
```

第二次调用会把命令发送给已经运行的主实例，因此可以正常显示/隐藏启动器或触发截图。应用内录制快捷键只在 X11/Windows 下自动生效。

Wayland 下的截图通过 `xdg-desktop-portal` 完成，剪贴板监听需要 `wl-clipboard`，详见[截图](#截图)和[剪贴板](#剪贴板)章节。

## 内置插件

### 计算器

草稿纸式实时计算器：上方是表达式历史，下方是键盘；输入即计算，按 `Enter` 确认当前层并新建下一层。

**布局与缩放**

- 上方是草稿纸，下方是按键；右上角的“科学模式”开关决定是否显示进制转换、进制选择和 A-F 按键。
- 窗口可自由缩放：窗口变矮时先收缩草稿纸，最少保留一层；继续缩小则按键同步变矮，运算符图标会自动切换为文字，不会出现底部按键被裁掉。放大窗口时草稿纸和按键一起扩展。
- “科学模式”默认关闭，此时是普通计算器布局，只保留 `+ - * / () % ^` 等基础运算。打开后显示进制转换栏、进制选择按钮和 A-F 按键；关闭时会自动切回 DEC，避免隐藏的进制继续影响输入。开关状态会立即保存，重新打开计算器或重启应用后保持。

**输入与求值**

- 输入即自动计算，无需按 `Enter` 或 `=`：本行实时显示 `= 结果`，进制转换栏同步更新。按 `Enter` 或 `=` 确认当前层并新建下一层。
- 未写完的表达式按单位元自动补全：以 `+`/`-` 结尾时补 `0`（如 `1+` 视为 `1+0`），以 `*`、`/`、`//`、`%` 结尾时补 `1`（如 `1+2*` 视为 `1+2*1`，显示 `3`）。
- `1^`、`1+(1+` 等无法补全或括号不匹配的输入不显示结果；按 `Enter` 或 `=` 确认时才提示具体错误。
- 键盘输入支持数字、`()`、`+ - * / // % ^ **`。
- `^` 与 `**` 是右结合次方，例如 `2^3^2 = 512`。
- 中文/全角 `（ ）`、全角数字和运算符会自动归一化为英文符号。
- 鼠标可点击表达式任意字符定位光标，然后输入、`Backspace`、`Delete` 或拖选修改；修改后结果实时重算。
- 点击任意历史层可原地编辑并重新计算；多个结果会同时保留。默认视口显示 4 层，滚轮或右侧滚动条可查看更多。
- 使用纯 Python 递归下降解析器，严格求值，不使用 `eval`。

**进制与转换**

- 进制按键带中文说明，从左到右为 `BIN 二进制`、`OCT 八进制`、`HEX 十六进制`、`DEC 十进制`，默认选中 DEC；转换栏按 `BIN DEC / OCT HEX` 两行排列。
- 活动进制决定裸数字的解释和结果显示，并禁用非法数字按键；`0x`、`0b`、`0o` 前缀在任何模式下都有效。
- 输入框会按当前进制过滤字符：BIN 仅允许 `0`/`1`，OCT 允许 `0-7`，HEX 允许 `0-9`/`A-F`，DEC 仅允许十进制数字；非 DEC 模式不能输入小数点，非法字符会被直接丢弃（粘贴同样生效）。裸数字按当前进制解析，例如 HEX 下 `11+11 = 0x22`。
- 当前进制在转换栏中以浅蓝底色、主题色、加粗和更大字号突出显示。
- 转换栏实时显示当前值在四种进制下的表示，可选中复制。非整数只提供十进制表示。
- 非 DEC 模式的小数点输入被禁用；除法仍可产生小数。

**草稿纸记忆与设置**

- 草稿纸会自动记忆：所有非空行在输入后约 0.4 秒写入磁盘（未按 `Enter` 的行也会保存），重新打开计算器或重启应用后恢复表达式和结果。每行会记住自己输入时的进制，HEX/BIN 行不会因为重新打开而丢失。
- 每行右侧的 `×` 可删除该条记录并及时保存。
- 点击窗口标题栏的“设置”打开设置与关于对话框，可调整最大保存条数（默认 200，范围 1–5000）、结果分隔位数（默认 0，范围 0–10）或清空全部记录（需要确认）。
- 调小最大保存条数会立即删除最旧的记录，只保留最近 N 条。运行中界面可以暂时超过上限，但磁盘始终只保存最新 N 条，重新打开后最多恢复 N 条。
- 结果分隔位数控制 DEC 结果的逗号分隔：`0` 不分隔（默认），`3` 会把 `1000` 显示为 `1,000`；带小数时只分隔整数部分（如 `1,234.5`）。HEX/BIN/OCT 结果不受影响。

**数据位置**

“科学模式”、最大保存条数和结果分隔位数保存在 `plugin_data/calculator/settings.json`；草稿纸内容保存在同目录的 `scratchpad.json`：

- Linux：`~/.local/share/quicktools/plugin_data/calculator/`
- Windows：`%APPDATA%\QuickTools\plugin_data\calculator\`

### 剪贴板

内置「剪贴板」插件在 QuickTools 运行期间自动记录复制过的文本、图片和文件列表。历史按复制时间倒序排列，最新记录在最上方。插件声明了 `background: true`，因此关闭窗口后仍会继续记录。

**记录与合并**

- 相同内容会合并为一条并置顶，复制次数累加，避免历史被连续重复内容刷屏。
- 图片以 PNG 保存到插件数据目录并生成缩略图，避免复制后源图片消失。
- 文件列表只保存原始路径（Windows 反斜杠路径原样保留），不会复制文件内容；文件被移动或删除后会显示不可访问提示。
- 历史数据库为 SQLite，重启应用后保留。
- 关闭插件窗口不会停止记录；只要 QuickTools 仍在后台运行，就会继续监听。退出 QuickTools 后停止。

**浏览与编辑**

- 支持搜索、按文本/图片/文件筛选、最新优先/最早优先排序。
- 每条记录右侧有三个图标按钮：二次复制、打开位置、删除；文本记录没有可打开的文件位置，“打开位置”按钮会置灰。详情页可预览文本或图片并查看原始文件路径。
- 点击“二次复制”图标只会写入系统剪贴板并把复制次数加一，不会改变该记录在历史中的位置；只有新捕获的内容才会置顶。
- 文本记录可在详情框中直接编辑，停止输入约 0.7 秒后自动保存；切换记录、关闭窗口或退出应用时也会立即保存。编辑不会改变该记录在历史中的位置；若编辑成与另一条记录相同的内容，会自动合并。
- 设置中可暂停记录、调整历史条数与图片总量上限、关闭图片/文件捕获、清空历史。

**平台支持**

| 平台 | 实现方式 | 说明 |
| --- | --- | --- |
| Linux X11 | XFixes 选择区事件 + ICCCM 读写（含 INCR 大内容分块） | 依赖 `python-xlib`，无需额外工具 |
| Linux Wayland | `wl-clipboard`（`wl-paste` / `wl-copy`） | 不同合成器对后台读取的限制不同，**不保证所有 Wayland 环境都能监听** |
| Windows | 原生 `AddClipboardFormatListener` | 支持 `CF_UNICODETEXT`、`CF_DIB` 和 `CF_HDROP`，不依赖 pywin32 |

Wayland 下需要安装 `wl-clipboard`：Ubuntu/Debian `sudo apt install wl-clipboard`，Fedora `sudo dnf install wl-clipboard`，Arch `sudo pacman -S wl-clipboard`，openSUSE `sudo zypper install wl-clipboard`。缺少依赖时插件会在设置页显示明确提示，不会假装监听成功。

当前开发机只实机验证了 Linux X11；Windows 与 Wayland 的代码路径已实现，但仍需按文末清单在真实环境验收。X11/Wayland 下 QuickTools 退出后系统剪贴板内容是否保留取决于桌面环境；历史记录本身已持久化。

**数据位置**

- Linux：`~/.local/share/quicktools/plugin_data/clipboard/`
- Windows：`%APPDATA%\QuickTools\plugin_data\clipboard\`

### 截图

内置「截图」插件。当前 Linux X11 已实机验证；Windows 和 Wayland 的代码路径已实现，但仍需按文末清单在真实机器上验收。

**控制窗口**

- 左侧导航提供首页、关于和设置。
- 首页顶部是一行四张紧凑的模式卡（矩形/窗口/自由/滚动，只显示图标、名称和快捷键），把鼠标停在模式卡上会显示对应说明；剩余高度全部留给最近截图区。
- 关于页显示版本、能力、快捷键和文件位置。
- 窗口缩小时只有最近截图区域收缩并滚动，左侧设置入口、页脚快捷键和保存目录始终保留。

**四种截图模式**

- **矩形区域截图**：按截图快捷键（默认 `Ctrl+Alt+X`，或模式快捷键 `Ctrl+Alt+1`），QuickTools 窗口会先隐藏，屏幕上出现冻结画面，拖拽选择区域后进入编辑窗口。
- **窗口截图**：按 `Ctrl+Alt+2` 或在模式卡点击进入；冻结画面上移动鼠标会高亮指针下的窗口，点击后采集该窗口；窗口被遮挡时会先抬升再重新抓屏。
- **自由截图**：按 `Ctrl+Alt+3` 或在模式卡点击进入；按住鼠标绘制套索，松开后得到带透明边缘的任意形状截图。
- **滚动截图**：按 `Ctrl+Alt+4` 或在模式卡点击进入；拖拽选择滚动区域后，插件会自动滚动、抓帧并拼接成长图；控制条可随时“完成”或“取消”。仅 Windows/X11 支持，属于 best-effort：固定表头、平滑滚动、虚拟列表或忽略合成滚轮的应用可能拼接失败或出现接缝。请尽量选择不覆盖控制条的滚动区域，否则控制条可能被拼进长图。
- **模式快捷键**：在 X11/Windows 下，`Ctrl+Alt+1~4` 固定注册，分别对应矩形、窗口、自由和滚动截图；主截图快捷键仍可在设置中修改。模式快捷键与启动器或主快捷键重复时自动跳过；若与桌面环境（如工作区切换）或其他软件冲突，可能被系统优先处理。

**标注编辑器**

编辑窗口支持预览、复制到系统剪贴板、自动保存、另存为；关闭编辑器时会自动把最终画面复制到剪贴板，可以直接去粘贴。标注工具包括：

- **矩形**和**圆形/椭圆**空心轮廓，用于圈住内容；默认不填充。
- 箭头、**自由画笔**、文字、自动递增序号、马赛克、图片内贴纸、文字水印。
- **画笔**：选择“画笔”后按住鼠标左键自由绘制，绘制过程实时预览；颜色和线宽可调，绘制完成后可选中移动、撤销/重做，并随截图一起导出。
- **裁剪**：选择“裁剪”后拖动图片的边或角调整保留区域，按 `Enter` 应用，`Esc` 取消；裁剪可撤销。
- 左/右旋转 90°、水平翻转。
- 选择对象后可拖拽移动；矩形/圆形/马赛克/贴纸/水印可拖角点缩放。
- 颜色、线宽、字号可调；支持撤销/重做。
- **滚轮缩放**，缩放以鼠标位置为中心；放大后可按住鼠标中键拖动平移，也可按住空格再用左键拖动；使用选择工具时直接在图片空白处拖动同样可以平移。编辑器顶部工具区的“适应”会把图片按比例放大或缩小到窗口大小，“1:1”恢复原始像素比例。
- 工具栏“重置”一键恢复未编辑原图（重置本身可撤销）；“重做”在有可重做操作时恢复上一步，没有可重做操作时回到未编辑原图。

文字输入框无边框，并自动取点击位置附近的背景色，避免深色输入框遮挡截图；输入框字号按实际像素大小显示，和提交后的文字大小一致。新增文字会自动选中。点击画布空白处、切换工具或输入框失去焦点时会提交，`Esc` 取消。字号可用“字号”输入框或 A-/A+ 调整；A-/A+ 不会抢走输入焦点，输入过程中可实时预览，提交后选中文字仍可继续改字号。文字使用系统 CJK 字体导出；找不到中文字体时编辑窗口会提示。

**自动保存与最近截图**

- 编辑器的每次修改（标注、移动、裁剪、旋转等）会在约 0.4 秒后自动写回最近截图，原图和缩略图同步更新；如果该截图之前已经导出过文件，也会同步覆盖该文件。
- 编辑器不提供“保存”按钮。需要另存为新文件时使用“另存为”；`Ctrl+S` 仍可手动保存到设置中的保存目录。
- 关闭编辑器时会立即完成尚未执行的自动保存，并把最终画面复制到系统剪贴板；即使没有点过“复制”，关闭后也可以直接粘贴。自动复制失败不会阻止关闭，只会在日志和状态栏记录原因。
- 每次截图会保存一份原图到插件数据目录。控制窗口中的最近截图区域支持滚动、搜索、星标收藏、筛选（全部/已收藏/按截图模式）、打开、复制、删除和清空；收藏状态会写入 `recent.db`，重启后保留。
- 编辑、复制或另存为后，最近记录会更新为带标注的最终图，返回截图助手时缩略图会立即刷新。
- 编辑器点击“复制”后会显示“已复制到剪贴板”提示条，按钮文字临时变为“已复制 ✓”，底部状态栏同步更新；最近截图里的复制同样会弹出提示。关闭编辑器时也会自动执行一次复制，无需先点“复制”。

**关闭行为**

- “关闭”会结束本次截图流程，并确保不留下任何 QuickTools 窗口：截图前被隐藏的窗口不会恢复；从最近截图打开编辑器时，原本可见的截图助手也会一并隐藏。
- “关闭并返回”会在关闭编辑器后重新显示并聚焦截图助手，方便连续截图；即使截图由全局快捷键发起、助手窗口尚未打开，也会打开助手窗口。
- 修改会自动保存，因此直接关闭不会提示未保存；截图本身在打开编辑器时就已写入“最近截图”，所以即使没做任何标注、也没复制或另存为，关闭后该记录依然保留，可以之后再打开继续编辑。只有自动保存失败、确实存在未落库的修改时才会询问确认。
- 无论点击“关闭”“关闭并返回”、标题栏关闭按钮还是按 `Esc`，关闭前都会把最终画面复制到系统剪贴板；确认框里选择取消则不会复制。

**设置与快捷键**

- 可修改保存目录、图片格式（PNG/JPEG/WebP）、JPEG 质量、最近截图上限、截图快捷键和启用状态。
- 滚动截图可调滚动格数、每帧等待时间、最大高度和忽略顶部/底部像素。
- 编辑窗口快捷键：`Ctrl+Z` 撤销、`Ctrl+Y` 或 `Ctrl+Shift+Z` 重做、`Delete` 删除选中对象、`Ctrl+0` 适应窗口、`Ctrl+1` 原始比例（1:1）、`Ctrl+C` 复制、`Ctrl+S` 手动保存到保存目录、`Esc` 取消当前操作或关闭窗口；放大后按住空格并拖动左键可平移画面。

**平台支持**

- X11/Windows：矩形、窗口、自由、滚动截图全部可用。
- Wayland：区域和窗口截图通过 `xdg-desktop-portal` 的系统选择器完成；自由截图先由 portal 截取全屏，再在编辑器中用“套索裁剪”圈出保留区域；滚动截图明确不支持，也不会静默回退到 X11。
- Linux Wayland 不提供任何应用内全局截图快捷键（包括 `Ctrl+Alt+1~4`），请把系统快捷键绑定到 `quicktools --screenshot region/window/freeform/scroll`。
- Wayland 使用系统截图选择器时，选择界面由桌面环境（GNOME/KDE 等）提供，QuickTools 无法自定义其外观；不同桌面的行为可能有差异。
- 截图选区覆盖“鼠标所在显示器”，暂不支持一次拖拽跨多个显示器；Windows 混合 DPI 多屏仅做了 Win32 负坐标定位兜底，仍需实机验收。
- 窗口模式在 X11/Windows 下通过枚举窗口并抬升后重新抓屏实现；被其他窗口遮挡且无法抬升时，可能采集到冻结画面中的可见部分。

**数据位置**

- Linux：`~/.local/share/quicktools/plugin_data/screenshot/`（`recent.db`、`images/`、`thumbs/`、`settings.json`）
- Windows：`%APPDATA%\QuickTools\plugin_data\screenshot\`
- 默认保存目录：Linux 为 `~/Pictures/Screenshots`（遵循 XDG Pictures 目录），Windows 为 `%USERPROFILE%\Pictures\Screenshots`

## 打包与分发

QuickTools 使用 PyInstaller 打包，这不是“编译”，而是把 Python 运行时和依赖一起装进独立程序，目标机器不需要安装 Python。PyInstaller 不能跨平台打包：Linux 包在 Linux 上打，Windows 包在 Windows 上打。打包必须使用仓库中的 `QuickTools.spec`（目录版）或 `QuickTools-onefile.spec`（单文件版）。

### 产物一览

产物统一放在 `dist/` 下，按平台分目录，两边的包不会互相覆盖：

```text
dist/
├─ win/
│  ├─ QuickTools/            目录版（整个文件夹分发）
│  ├─ QuickTools.exe         单文件版（直接分发这一个文件）
│  └─ QuickTools-Setup.exe   安装包（安装 Inno Setup 后生成）
└─ linux/
   └─ QuickTools/            目录版（整个文件夹分发）
```

| 平台 | 命令 | 产物 | 说明 |
| --- | --- | --- | --- |
| Windows 全量 | `build_all.bat` | 目录版、单文件版、安装包 | 一次产出三种，缺少 Inno Setup 时跳过安装包；产物在 `dist\win\` |
| Windows 目录版 | `build_windows.bat` | 整个 `dist\win\QuickTools\` 文件夹 | 只需要目录版时使用 |
| Linux 目录版 | `./build_linux.sh` | 整个 `dist/linux/QuickTools/` 文件夹 | 启动更快，分发整个文件夹 |

中间文件放在 `build/win/`、`build/win_onefile/`、`build/linux/`，与分发包分开；`dist/` 和 `build/` 整体被 `.gitignore` 忽略。

### 快速开始

根据平台和需求选择下面的脚本，在项目根目录直接执行：

```bash
# Windows：全量打包（推荐）
build_all.bat

# Windows：仅打包目录版
build_windows.bat

# Linux：打包目录版
./build_linux.sh
```

每个脚本会自动创建虚拟环境、安装依赖、调用 PyInstaller，产物在 `dist/` 目录下。首次打包可能需要几分钟；再次打包会利用缓存，通常更快。

### Windows 一键全量打包

双击或执行 `build_all.bat`，脚本会依次完成：

1. 缺少 `.venv` 时自动创建；依赖已安装时跳过 pip，只有缺依赖才安装（避免网络或代理不通时卡在下载 setuptools 的构建隔离环境里）。
2. 按 `QuickTools.spec` 打包目录版，产出 `dist\win\QuickTools\QuickTools.exe`（启动最快，分发时要整个 `dist\win\QuickTools` 文件夹一起拷贝）。
3. 按 `QuickTools-onefile.spec` 打包单文件版，产出 `dist\win\QuickTools.exe`（约 21 MB，直接发这一个文件；启动时会解压到临时目录，首次启动约 3 秒，退出后自动清理）。
4. 检测到 [Inno Setup 6](https://jrsoftware.org/isdl.php) 时调用 `installer.iss`，产出 `dist\win\QuickTools-Setup.exe`；未安装则跳过安装包，前两项照常完成。

脚本会检查 `QuickTools.exe` 是否正在运行——文件被占用时 PyInstaller 会失败，请先从状态栏菜单退出程序。

构建结束后脚本会把 `dist\win` 下的产物标回 Medium 完整性。若某些安全软件/沙箱给 exe 打上了 Low 完整性标签，单文件版会以低权限启动，并在解压时提示 `Could not create temporary directory!`；可手动执行 `icacls "dist\win" /setintegritylevel Medium /T` 修复。

安装包按用户安装到 `%LOCALAPPDATA%\Programs\QuickTools`，不需要管理员权限；安装向导本身是英文（Inno Setup 官方不带简体中文语言文件），应用名和快捷方式为中文。

单文件版和安装包都没有代码签名，首次运行时 Windows SmartScreen 可能提示“Windows 已保护你的电脑”，选择“更多信息 → 仍要运行”即可。

### Windows 目录版

如果只需要目录版，执行 `build_windows.bat`。它会自动创建 `.venv`、检查并安装缺失依赖，然后按 `QuickTools.spec` 打包，产出 `dist\win\QuickTools\QuickTools.exe`，分发时需要拷贝整个 `dist\win\QuickTools` 文件夹。

与 `build_all.bat` 的区别只有一个：前者只出目录版，后者额外出单文件版和安装包。

### Linux 目录版

`./build_linux.sh` 会自动创建 `.venv`、安装依赖并调用 PyInstaller，产出 `dist/linux/QuickTools/`。等价的命令是：

```bash
.venv/bin/pip install -e '.[dev]' pyinstaller
.venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/linux --workpath build/linux QuickTools.spec
```

产出是 `dist/linux/QuickTools/QuickTools`。Linux 打包版在终端里的行为和日志：

```bash
dist/linux/QuickTools/QuickTools              # 启动并立即返回终端，关闭终端不退出
dist/linux/QuickTools/QuickTools --foreground # 前台运行，实时打印日志（关闭终端会结束应用）
dist/linux/QuickTools/QuickTools --toggle     # 切换启动器显示状态
dist/linux/QuickTools/QuickTools --quit       # 退出已运行的实例
```

后台日志位于 `~/.local/share/quicktools/logs/quicktools.log`，可用 `tail -f` 实时查看。

单文件版和安装包目前只配置了 Windows。`QuickTools-onefile.spec` 本身不限定平台，但产物目录和图标是按 Windows 准备的。

### 打包注意事项

- 必须在项目根目录执行打包脚本，并确认 `QuickTools.exe` 没有在运行。
- 内置插件和部分模块是运行时动态导入的，PyInstaller 无法静态发现；新增采集、portal 或其他依赖时，要同步更新两份 spec 的 `hiddenimports`。
- 不要往 `dist/` 里放中间文件；产物和构建缓存目录都已被 `.gitignore` 忽略。
- `.bat` 和 `.iss` 必须保持 CRLF 换行，`.sh` 保持 LF；cmd.exe 会把 LF 换行的批处理当成一条命令执行。
- Windows 包只能在 Windows 上构建，Linux 包只能在 Linux 上构建。

## 插件开发

> **安全提示**：插件在 QuickTools 主进程内运行，拥有与主程序相同的权限，没有进程沙箱。只安装你信任的插件。

### 插件目录与发现

用户插件目录：

- Linux：`~/.local/share/quicktools/plugins`（遵循 `XDG_DATA_HOME`）
- Windows：`%APPDATA%\QuickTools\plugins`

每个插件放在一个独立文件夹中，至少包含 `plugin.json` 和入口 Python 文件，例如：

```text
<用户插件目录>/
  hello/
    plugin.json
    plugin.py
    helper.py        # 可选，支持相对导入
```

把文件夹放好后，下次唤出启动器会自动扫描；也可以在设置中点击“重新扫描插件”。同一插件 `id` 重复时内置插件优先，用户插件会被忽略并记录错误。

扫描时只读取并校验 `plugin.json`，不导入入口代码。普通插件在点击卡片时才懒加载；`background: true` 的插件在应用启动后立即加载并调用 `start_service()`。

### 插件清单

最小的 `plugin.json` 如下：

```json
{
  "api_version": 1,
  "id": "hello",
  "name": "示例插件",
  "summary": "一句话说明这个插件做什么",
  "description": "详细说明会显示在“设置 → 关于”中，可以包含换行。",
  "author": "你的名字",
  "version": "0.1.0",
  "entry": "plugin.py",
  "class": "HelloPlugin",
  "icon": "H",
  "order": 100,
  "background": false
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `api_version` | 是 | 当前固定为 `1` |
| `id` | 是 | 小写字母/数字/下划线/短横线，1–64 字符，必须唯一 |
| `name` | 是 | 启动器卡片和插件标题栏显示的名称 |
| `summary` | 否 | 卡片上的一句话概述，建议 20–40 字；没有时自动截取 `description` 的第一句 |
| `description` | 否 | 详细说明，显示在“设置 → 关于”；可以包含 `\n` 换行和项目符号 |
| `author` | 否 | 作者信息，显示在关于页；没有时显示“未提供” |
| `version` | 是 | 插件版本字符串，显示在关于页 |
| `entry` | 是 | 相对插件文件夹的 `.py` 入口，不能越出插件目录 |
| `class` | 是 | 入口文件中导出的插件类名 |
| `icon` | 否 | 一个短文本，作为卡片和标题栏图标；emoji 在部分 Tk 平台上不可见时会回退为插件名首字 |
| `order` | 否 | 数字，越小越靠前；默认 100 |
| `background` | 否 | 布尔值；为 `true` 时应用启动后立即调用 `start_service()`，无需用户点击卡片。默认 `false` |

启动器卡片保持紧凑，只显示图标、名称和 `summary`（一句话）。插件版本、`description` 详细说明、`author`、插件目录和数据目录由框架自动展示在“设置 → 关于”页，插件无需自己再写关于页。

### 生命周期与窗口

- 普通插件：窗口首次打开时创建新实例并调用 `create_ui(window)`；关闭窗口后再开是新实例。
- `background: true` 的插件：应用启动扫描后立即创建唯一实例并调用 `start_service()`；窗口可反复打开关闭，`stop_service()` 只在退出、插件删除或版本/目录变化时调用。服务必须幂等，且后台线程不能直接操作 Tk 控件，必须通过队列或 `root.after(...)` 回到主线程。
- 插件窗口由 QuickTools 统一提供无边框标题栏、置顶、隐藏、放大、关闭和“设置 → 关于”对话框；插件只需实现 `create_ui(window)`，可选实现 `create_settings_ui(parent)`。
- 可声明 `settings_cards = True` 自行创建多组设置卡片；否则宿主会把设置页包进一张白色圆角卡片。设置组件应复用 `quicktools.settings_widgets` 中的 `Card`、`SectionHeader`、`SettingsRow`、`ToggleRow`。
- 不要在插件里再画标题栏、调用 `overrideredirect(True)`，或在主窗口内容里放置“置顶”图钉和“关于”标题。插件额外创建的 Toplevel 可自行调用 `WindowFrame(...)`。
- 插件窗口的大小和放大状态会按插件 `id` 自动持久化，插件无需自己保存。

### 参考

- 完整契约、标题栏行为和示例：[docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md)
- 可运行的最小插件：[examples/hello_plugin](examples/hello_plugin)
- 稳定 API：`quicktools/plugin_api.py`（`PluginMeta`、`PluginContext`、`PluginBase`）

## 数据与配置位置

| 内容 | Linux | Windows |
| --- | --- | --- |
| 应用设置（快捷键） | `~/.config/quicktools/settings.json` | `%APPDATA%\QuickTools\settings.json` |
| 插件窗口尺寸 | `~/.config/quicktools/window_state.json` | `%APPDATA%\QuickTools\window_state.json` |
| 数据、日志、用户插件 | `~/.local/share/quicktools/` | `%APPDATA%\QuickTools\` |
| 日志 | `~/.local/share/quicktools/logs/quicktools.log` | `%APPDATA%\QuickTools\logs\quicktools.log` |
| 用户插件 | `~/.local/share/quicktools/plugins/` | `%APPDATA%\QuickTools\plugins\` |

Linux 路径遵循 `XDG_CONFIG_HOME` 和 `XDG_DATA_HOME`；未设置时使用上面的默认值。内置插件的数据相对上述数据目录，分别位于：

- **计算器**：`plugin_data/calculator/settings.json`（科学模式、最大保存条数、结果分隔位数）与 `scratchpad.json`（草稿纸内容）。
- **剪贴板**：`plugin_data/clipboard/`（`history.db`、`images/`、`thumbs/`、`settings.json`）。
- **截图**：`plugin_data/screenshot/`（`recent.db`、`images/`、`thumbs/`、`settings.json`）；默认保存目录为 Linux `~/Pictures/Screenshots`、Windows `%USERPROFILE%\Pictures\Screenshots`。

## 仓库脚本一览

仓库根目录下的脚本都是便捷入口，源码和打包产物都不依赖它们，直接使用 `python -m quicktools` 等命令也能达到同样效果。

| 脚本 | 平台 | 作用 |
| --- | --- | --- |
| `run.sh` | Linux | 从源码启动应用：优先用 `.venv/bin/python`，没有虚拟环境时回退到系统 `python3`；参数原样透传（如 `./run.sh --toggle`） |
| `run.bat` | Windows | 从源码启动应用，用 `pythonw` 运行，不弹控制台窗口；参数原样透传 |
| `build_linux.sh` | Linux | 打包目录版：缺少 `.venv` 时自动创建、安装依赖，再按 `QuickTools.spec` 打包，产出 `dist/linux/QuickTools/QuickTools` |
| `build_windows.bat` | Windows | **只打包目录版**：产出 `dist\win\QuickTools\QuickTools.exe`，分发时要整个文件夹一起拷贝 |
| `build_all.bat` | Windows | **一键全量打包**：依次产出目录版 `dist\win\QuickTools\`、单文件版 `dist\win\QuickTools.exe`、安装包 `dist\win\QuickTools-Setup.exe`；未安装 Inno Setup 时自动跳过安装包 |
| `git-update.sh` | Linux/macOS/Git Bash | 按仓库约定的格式提交：`./git-update.sh 描述文字` 会执行 `git add .` 并提交为 `YYMMDD: 描述文字`；没有改动时直接提示并退出。详见[提交代码](#提交代码) |
| `git-update.bat` | Windows cmd/PowerShell | 上面脚本的 Windows 包装器，用法相同：`git-update.bat 描述文字`；内部转调 `git-update.sh`，需要 Git for Windows 自带的 bash |

其它构建相关文件：

- `QuickTools.spec`：目录版 PyInstaller 配置，Windows 和 Linux 共用。
- `QuickTools-onefile.spec`：Windows 单文件版配置。
- `installer.iss`：Inno Setup 6 安装包脚本，由 `build_all.bat` 调用。
- `scripts/quicktools_launcher.py`：PyInstaller 的入口脚本，打包时调用，日常开发用不到。
- `scripts/prepare_assets.py`：根据 `logo.png` 重新生成图标资源，见[图片资源](#图片资源)。

## 图片资源

Logo 源文件与派生图标统一放在 `quicktools/assets/`，清单见 [assets/README.md](quicktools/assets/README.md)。更换 `logo.png` 后运行：

```bash
.venv/bin/python scripts/prepare_assets.py
```

会重新生成窗口图标、启动器标题图标、Linux/Windows 状态栏图标和 Windows `.ico`。只重新生成状态栏图标时可加 `--tray-only`：

```bash
.venv/bin/python scripts/prepare_assets.py --tray-only
```

README 顶部的宣传横幅存放在 `docs/images/quicktools-banner.png`，仅用于文档展示，不参与应用打包。

## 开发与测试

### 运行测试

```bash
.venv/bin/pip install -e '.[dev]'
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
```

截图专项测试（几何、标注、渲染、滚动拼接、设置、最近库、portal、UI）：

```bash
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest \
  tests/test_screenshot_geometry.py tests/test_screenshot_annotations.py \
  tests/test_screenshot_render.py tests/test_screenshot_stitcher.py \
  tests/test_screenshot_settings.py tests/test_screenshot_store.py \
  tests/test_screenshot_portal.py tests/test_screenshot_ui_smoke.py -q
```

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于避开当前 Ubuntu 环境中 ROS 注入的 pytest 插件；普通干净环境可以省略。
- `DISPLAY` 是 Tk 冒烟测试必需的；没有显示环境时相关测试会自动 skip。
- 项目未配置 lint/format 检查步骤，`pyproject.toml` 只配置了 pytest。
- `tests/test_clipboard_windows.py` 只在 Windows 上运行；截图 Windows 路径目前没有自动化实机测试，需按[实机验收清单](#实机验收清单)验收。
- 当前实测通过的是 Linux X11；Windows 和 Wayland 代码路径已适配，但仍需实机验收。

### 提交代码

仓库的提交信息统一使用 `YYMMDD: 描述` 格式，日期是提交当天，例如 2026-10-19 提交“新增加了开机自启动开关”：

```text
261019: 新增加了开机自启动开关
```

仓库提供了两个便捷脚本自动生成日期前缀，按所在平台选一个即可，参数都是“描述文字”（多个词之间用空格，不用加引号）：

```bash
./git-update.sh 描述文字        # Linux / macOS / Git Bash
git-update.bat 描述文字         # Windows cmd / PowerShell
```

例如：

```bash
./git-update.sh 修复 CAN 通道分配      # Linux / Git Bash
git-update.bat 修复 CAN 通道分配       # Windows cmd / PowerShell
```

两个脚本行为完全一致（`.bat` 只是转调 `.sh`，提交逻辑只有一份）：

- 自动切换到仓库根目录再执行，从任何子目录调用都不会漏提交；
- 执行 `git add .`，把**当前所有改动**加入暂存区，然后按格式提交；
- 没有改动时提示“没有需要提交的改动，已跳过”，不会报错；
- 不带描述文字时打印用法并返回失败。

> **注意**：`git add .` 会把工作区所有改动（包括未跟踪的新文件）一起提交。提交前先用 `git status` 确认，避免把不该入库的文件（例如本地配置、临时产物）带上。`git-update.bat` 依赖 Git for Windows 自带的 bash，找不到时会提示安装。

## 常见问题

**按下全局快捷键没有反应？**

先确认程序是否正在运行、组合键是否被其他软件占用。Windows 上可查看日志是否出现“回退 pynput”；Linux Wayland 不支持应用内全局监听，需要把系统快捷键绑定到 `--toggle`（见 [Linux Wayland](#linux-wayland)）。

**Windows 上 `Ctrl+Space` 和中文输入法冲突怎么办？**

在设置中改绑 `Ctrl+Alt+Space`。Windows 原生注册会独占组合键，改绑后立即生效。

**启动器点击外部没有自动隐藏？**

自动隐藏会在启动器由快捷键、`--toggle` 或全新普通启动显示、并确认取得前台焦点后启用。通过托盘“显示”、`--show`、设置返回或截图恢复的启动器不会自动隐藏，按 `Esc` 或点击“隐藏”即可。普通启动时若已有实例，只会唤醒已有窗口，不会重新武装自动隐藏。

插件主窗口（计算器、剪贴板、截图助手）也会在失去焦点时隐藏，点击卡片可恢复；已置顶的窗口会跳过这一行为。截图编辑器、选区/滚动覆盖层和设置/关于对话框不会失焦隐藏。若某个窗口管理器不允许程序设置原生焦点，插件窗口的失焦检测可能不可靠。

Linux X11 需要 Tk 窗口取得原生 X 输入焦点：QuickTools 会在显示启动器后调用 `XSetInputFocus`，日志中应出现“启动器已取得前台焦点”。如果出现“启动器未能取得前台焦点，保持显示”，说明窗口管理器（例如部分平铺式 WM）拒绝了焦点请求，自动隐藏会被主动关闭，避免误隐藏。Wayland 不允许应用自行设置焦点，点击外部自动隐藏在 Wayland 下取决于合成器，可能不生效。

**Linux 顶栏没有 QuickTools 图标？**

需要系统安装 AppIndicator 相关组件；缺少时会回退到 XEmbed 菜单，Wayland 下回退图标不保证显示。此时仍可用全局快捷键唤出启动器。

**Wayland 下截图快捷键无效？**

这是预期行为。Wayland 不允许应用监听全局键盘事件，请把系统快捷键绑定到 `quicktools --screenshot region` 等命令。

**单文件版启动为什么比目录版慢？**

单文件版启动时要把依赖解压到临时目录，冷启动约 3 秒；目录版约 1 秒。经常使用建议选择目录版或安装包。

**如何彻底退出 QuickTools？**

关闭启动器或插件窗口只是隐藏。请使用托盘/顶栏菜单的“退出”、设置里的退出按钮，或运行 `--quit`。

**数据会上传吗？**

不会。快捷键配置、窗口尺寸、剪贴板历史、截图和插件数据都保存在本机，不上传。

## 已知边界

- **Windows 全局快捷键**：优先通过 `RegisterHotKey` 注册（`WM_HOTKEY`）。Windows 只允许“持有前台输入队列”的线程调用 `SetForegroundWindow`；`WM_HOTKEY` 正好投递给注册线程，因此启动器能立即取得焦点。若组合键已被其他程序占用，则回退到 pynput 低级键盘钩子，并用临时 `AttachThreadInput` 兜底；此时焦点可能比原生路径慢几十毫秒。`RegisterHotKey` 会独占组合键，`Ctrl+Space` 与中文输入法冲突，推荐 `Ctrl+Alt+Space`。
- **Linux Wayland**：不做应用内全局键盘监听，使用 `--toggle` + 系统快捷键（见 [Linux Wayland](#linux-wayland)）。原生 AppIndicator 状态栏在支持 StatusNotifier 的桌面环境下可用；无 AppIndicator 时会回退到 XEmbed（Wayland 下回退图标不保证显示）。当前 X11 已验证。
- **插件权限**：V1 不支持 C++ 插件 ABI，也不对插件做进程沙箱。
- **无边框窗口**：通过 `overrideredirect` 实现。Windows 上会恢复任务栏按钮和 Alt+Tab，并支持最小化；Linux X11 的窗口管理器不接管 override-redirect 窗口，因此插件窗口不会出现在任务栏/Alt+Tab，“隐藏”会退化为收回窗口（可再次从启动器打开）。移动和缩放由自绘标题栏与边缘拖拽提供。Linux X11 下 Tk 的 `focus_force()` 不会为 override-redirect 窗口设置原生焦点，QuickTools 在显示启动器（以及从启动器打开的插件窗口）时会额外调用 `XSetInputFocus`；Wayland 由合成器管理焦点，点击外部自动隐藏无法保证。
- **Linux X11 置顶**：Tk 的 `-topmost` 对 override-redirect 窗口会被窗口管理器忽略，读回也是 False。QuickTools 会自己记录置顶状态并在开启时 `lift()` 窗口；这类窗口本身就在普通窗口之上，所以“置顶”表现为保持在其他应用上方，但“取消置顶”无法把它压回普通窗口层。Windows 使用原生 `SetWindowPos(HWND_TOPMOST)`，置顶/取消置顶都是完整的。
- **窗口管理**：自绘标题栏不提供 Windows 原生的贴边分屏、Aero Snap 和窗口动画；需要全屏工作时请点击标题栏“放大”或双击标题栏。
- **计算器草稿纸**：记忆会持久化到 `scratchpad.json`；自动保存有约 0.4 秒防抖，强制结束进程最多可能丢失最后约 0.4 秒的输入。
- **剪贴板**：Linux Wayland 下依赖 `wl-clipboard`，且不同合成器限制不同；无法保证所有 Wayland 环境可用。
- **截图能力范围**：当前支持 X11/Windows 矩形/窗口/自由/滚动截图、矩形/圆形/椭圆空心圈选、箭头/自由画笔/文字/序号/马赛克/贴纸/水印、裁剪旋转、复制/自动保存/另存为和最近截图；Wayland 支持 portal 的区域/窗口截图和“全屏 + 套索裁剪”的自由截图，不支持滚动截图。滚动截图是 best-effort，复杂页面可能失败或出现接缝；文字导出依赖系统安装的中文字体。
- **截图多显示器**：选区覆盖“鼠标所在显示器”，暂不支持一次拖拽跨多个显示器；Windows 混合 DPI 多屏仍需实机验证。
- **截图窗口模式**：在 X11/Windows 下通过枚举窗口并抬升后重新抓屏实现；被其他窗口遮挡且无法抬升时，可能采集到冻结画面中的可见部分。
- **验收状态**：当前环境已验证 Linux X11；Windows 11 的代码路径已做平台适配，但仍需在真实 Windows 机器上完成验收。剪贴板 Windows 后端的实机验收项见下方清单。

## 实机验收清单

以下清单用于在真实目标机器上逐项验收。当前开发机实测通过的是 Linux X11。

### Linux X11 启动器

在 GNOME/KDE 等 X11 会话中确认：

1. 首次启动以及每次用快捷键或 `--toggle` 唤出后，启动器位于屏幕中央，不会停在左上角；唤出后可直接输入搜索，无需先点击窗口；日志中出现“启动器已取得前台焦点”。
2. 点击启动器以外的其他窗口或桌面，启动器在约 150ms 内自动隐藏；点击搜索框、滚动卡片或插件卡片不会误隐藏。
3. 持续点击启动器内部（切换焦点到搜索框、按钮等）不会触发自动隐藏。
4. 通过托盘“显示”、`--show`、设置返回或截图恢复的启动器不会自动隐藏；全新普通启动的启动器支持点击外部隐藏。
5. 日志中不应出现“启动器未能取得前台焦点”；若出现，该窗口管理器拒绝程序设置焦点，自动隐藏会被主动关闭。
6. 插件窗口点击图钉后图标高亮，窗口保持在其他应用上方；再次点击取消高亮。X11 下取消置顶不会把窗口压回普通窗口层（override-redirect 限制），属预期行为。
7. 打开计算器/剪贴板/截图助手后点击其他应用窗口，插件主窗口自动隐藏；再次点击卡片恢复。打开设置/关于对话框时父窗口不隐藏；截图编辑器、选区和滚动控制条不因失焦而关闭。
8. 拖动启动器边缘或四角可调整大小，最小 720×480；隐藏再唤出后保持当前尺寸。打开插件后点击标题栏“隐藏”，卡片仍显示完整的“已打开”（末字不被裁切），点击卡片恢复窗口。

### Windows 11 通用

在真实 Windows 11 上请逐项确认：

1. `.venv\Scripts\pythonw -m quicktools` 启动后无控制台窗口，启动器出现。
2. 默认 `Ctrl+Space` 与自定义快捷键都能唤出/隐藏启动器；Windows 原生注册会独占组合键，若 `Ctrl+Space` 影响输入法切换，用设置改绑 `Ctrl+Alt+Space`。日志中应出现“Win32 RegisterHotKey”；若出现“回退 pynput”，说明组合已被其他程序占用。
3. 快捷键唤出后启动器立即获得键盘焦点（可直接输入搜索），点击桌面、其他应用或插件窗口后启动器自动隐藏；点击搜索框、滚动卡片或插件卡片不会误隐藏。从托盘“显示”、`--show`、设置返回的启动器点击外部不隐藏。日志中不应出现“启动器未能取得前台焦点”。
4. 启动器没有系统标题栏；拖动顶部标题区域可移动窗口，拖动边缘可调整大小且隐藏再唤出后尺寸保持。插件卡片只显示图标、名称和一句话概述，没有长描述；“已打开”状态文字完整显示在卡片内。
5. 点击计算器后启动器隐藏、计算器获得焦点；自绘标题栏显示图标、名称和设置/置顶/隐藏/放大/关闭按钮，没有系统标题栏。
6. 点击“设置”打开无边框的设置对话框，左侧有“设置/关于”；关于页显示版本、详细说明、作者、插件目录和数据目录。点击“置顶”后窗口保持在其他窗口上方；点击“放大/还原”与双击标题栏行为一致；点击“隐藏”后任务栏仍有按钮，可从任务栏恢复。
7. 再次唤出启动器并点击计算器会聚焦原窗口；拖动插件窗口边缘可调整大小；关闭再打开或重启应用后保持上次大小和放大状态；关闭按钮和 `Alt+F4` 均能关闭窗口。
8. 单实例：再运行一次普通命令只显示已有启动器；`--toggle`、`--quit` 生效。
9. 中文输入法输入 `（）` 后自动变成 `()`；鼠标点字、`Backspace`/`Delete`、`=` 求值正常。
10. 高 DPI 下字体与窗口尺寸合理；关闭启动器后进程仍在后台。
11. Windows 系统托盘出现 QuickTools 图标；点击可恢复启动器，托盘菜单的“显示 / 退出”可用。
12. 若打包：`QuickTools.exe --toggle` 能唤出已运行的实例。
13. 插件主窗口失去焦点时自动隐藏，点击卡片可恢复；截图编辑器、选区/滚动覆盖层和设置/关于对话框不参与失焦隐藏。

### Windows 剪贴板

当前开发机无法运行 Windows，以下项目必须在真实 Windows 10/11 上逐项确认：

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests\test_clipboard_windows.py -q
.venv\Scripts\pytest -q
run.bat
```

1. 复制文本后，剪贴板列表出现新记录，最新记录位于顶部。
2. 复制图片（例如截图工具或浏览器图片）后，可查看预览并点击记录右侧的“二次复制”图标再次写入剪贴板。
3. 在文件资源管理器中复制单个文件，路径以 `C:\...` 原样显示。
4. 在文件资源管理器中复制多个文件，显示为多条路径或“N 个文件”。
5. 搜索、类别筛选、排序、详情、删除、清空历史均可用。
6. 退出并重启 QuickTools 后，历史记录仍在。
7. 移动或删除已复制的文件后，详情显示不可访问提示，点击记录右侧的“打开位置”和“二次复制”图标会给出明确错误。
8. 关闭启动器和剪贴板窗口后，复制内容仍被后台记录。
9. 在设置中暂停记录后，继续复制不会新增历史；恢复后重新开始记录。
10. 二次复制文本、图片和文件列表后，可在资源管理器中粘贴验证。
11. 使用 PyInstaller 打包后再执行 1–10 的核心项。

`tests/test_clipboard_windows.py` 会在 Windows 上实际执行原生剪贴板读写与监听测试；在 Linux 上这 4 个测试会被跳过。

### Windows 截图

在真实 Windows 10/11 上逐项确认：

1. 默认 `Ctrl+Alt+X` 触发矩形截图，`Ctrl+Alt+1~4` 分别触发矩形/窗口/自由/滚动截图；启动器、设置窗口和截图插件窗口都不出现在截图中。
2. 100%/125%/150% 缩放以及主屏左侧/上方的副屏：选区位置与实际像素一致；记录混合 DPI 的偏差。
3. 窗口截图能高亮并采集目标窗口；被遮挡窗口抬升后采集；自由截图边缘透明；滚动截图对简单长页面/文档可用，能自动停止和取消。
4. 矩形、圆形/椭圆为空心圈选，内部内容不被填充；箭头、文字、序号、马赛克、贴纸、水印、裁剪、旋转可用；中文文字正常。
5. 复制到画图、Word、浏览器后尺寸/颜色正确；不点“复制”直接关闭编辑器后，也能把标注结果粘贴到画图/Word；保存 PNG/JPEG/WebP 正常；最近截图在重启后仍可打开，星标收藏和筛选状态保留。
6. 修改主截图快捷键并重启后仍生效；`Ctrl+Alt+1~4` 模式快捷键可用；快捷键与启动器冲突时有明确提示。
7. `--screenshot region/window/freeform/scroll` 在有/无实例时行为正确；打包版重复 1–6 的核心项。

### Wayland 截图

在 GNOME Wayland 或 KDE Wayland 会话中：

1. 安装并确认 `jeepney` 可用；把系统快捷键绑定到 `quicktools --screenshot region`。
2. 触发区域/窗口截图时出现桌面自带的系统选择器；取消后 QuickTools 窗口恢复，不产生最近记录。
3. 系统选择器返回的图片进入编辑器；矩形/圆形/箭头/画笔/文字/马赛克等标注和复制/自动保存/另存为/最近截图可用；关闭编辑器后无需点“复制”即可直接粘贴。
4. 自由截图先请求系统全屏截图，再在编辑器中用“套索裁剪”圈出保留区域；PNG 角落透明。
5. 滚动截图显示明确“不支持”提示，不静默失败。
6. 应用内不尝试注册任何全局截图快捷键（包括模式快捷键）；首页/关于页和设置页显示系统快捷键绑定说明。
7. 不同桌面环境的 portal 选择器外观和可用模式可能不同，请记录实际行为。

### Wayland 剪贴板

在 GNOME Wayland 或 KDE Wayland 会话中安装 `wl-clipboard` 后，重复[剪贴板](#剪贴板)章节中的文本/图片/文件/暂停/重启测试。插件状态区应显示 `Wayland (wl-clipboard)`；若未安装依赖，应显示不可用及安装提示。部分合成器可能限制后台读取，请记录实际结果，不要假定所有 Wayland 环境都可用。
