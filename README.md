# 快捷工具 QuickTools

一个常驻后台的桌面插件启动器：按全局快捷键唤出，点击插件后启动器隐藏，插件作为独立窗口继续使用。内置草稿纸计算器、剪贴板历史，以及支持区域/窗口/自由/滚动截图和圈选标注的截图插件。

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

> 首次安装需要联网下载 `pynput`、`pystray`、`Pillow`、`python-xlib`（Linux）与 `jeepney`（Linux，Wayland 截图 portal 使用）。Linux 若提示缺少 Tkinter，请安装发行版提供的 `python3-tk`。

## 使用

- 全局快捷键显示/隐藏启动器：Linux 默认 `Ctrl+Alt+Space`，Windows 默认 `Ctrl+Space`。
- 点击插件卡片启动插件。再次点击已打开的插件会聚焦原窗口，不会开第二个相同插件窗口。
- 启动器隐藏后，全局快捷键依然可用，插件窗口可以继续使用。
- 状态栏/顶栏有一个 QuickTools 图标。Linux 下点击它弹出原生下拉菜单：第一项“显示”打开启动器，第二项“退出”结束程序。Windows 使用系统托盘的“显示 / 退出”菜单。
- 设置里可录制新快捷键、开启/关闭开机启动、打开插件目录、重新扫描插件、退出应用；设置窗口左上角“← 返回启动器”或窗口关闭按钮会回到启动器，Esc 也可返回。
- Linux 默认值已避开输入法常用的 `Ctrl+Space`。Windows 的 `Ctrl+Space` 若与输入法冲突，也可在设置中改绑（例如 `Ctrl+Alt+Space`）。

### 命令行参数

命令行控制采用单实例 IPC 设计：如果已有实例在运行，命令会发送给该实例，不会启动第二个进程。下面以源码方式 `./run.sh` 为例；打包版把 `./run.sh` 换成 `dist/QuickTools/QuickTools` 即可。

```bash
./run.sh               # 不带参数：显示启动器
                       # 如果已有实例运行，唤出已有窗口
                       # 如果无实例运行，启动新实例并显示窗口

./run.sh --show        # 显示启动器
                       # 如果已有实例运行，显示启动器窗口
                       # 如果无实例运行，启动新实例并显示窗口

./run.sh --toggle      # 切换启动器显示状态
                       # 如果启动器隐藏，则显示它
                       # 如果启动器显示，则隐藏它
                       # 如果无实例运行，启动新实例并显示窗口

./run.sh --background  # 后台启动（登录自启动使用）
                       # 如果已有实例运行，静默退出（不启动第二个）
                       # 如果无实例运行，启动新实例但不显示窗口
                       # 应用在后台驻留，快捷键按下时才显示启动器

./run.sh --quit        # 退出已运行的主实例
                       # 如果有实例运行，向其发送退出信号
                       # 如果无实例运行，静默退出

./run.sh --screenshot            # 触发矩形截图（默认 region）
./run.sh --screenshot window     # 触发窗口截图
./run.sh --screenshot freeform   # 触发自由截图
./run.sh --screenshot scroll     # 触发滚动截图
./run.sh --screenshot open       # 打开截图插件控制窗口
                                 # 无实例时会隐藏启动主程序并执行动作
                                 # Wayland 下可把系统快捷键绑定到该命令

./run.sh --foreground  # 前台运行，不脱离终端，实时打印运行日志
                       # 只影响 Linux 打包版：不加时启动后终端立即释放
                       # 源码方式本来就是前台运行，此参数不改变行为
                       # 可以和其他参数组合，例如 --background --foreground

./run.sh --version     # 显示版本号

./run.sh --help        # 显示全部参数说明（也可写 -h）
```

`--show`、`--toggle`、`--background`、`--quit` 互斥，只能选择一个；`--foreground` 可以和它们组合。`--tray-helper` 是状态栏托盘子进程使用的内部参数，普通用户不需要指定。

Linux 打包版（`dist/QuickTools/QuickTools`）在终端里直接运行时会先完成单实例检查，然后自动脱离终端转入后台：命令立即返回，关闭终端不会退出应用。需要在前台观察日志时加 `--foreground`，终端会实时打印运行日志；此时关闭终端会结束应用。

后台运行时的日志写入 `~/.local/share/quicktools/logs/quicktools.log`，可实时查看：

```bash
tail -f ~/.local/share/quicktools/logs/quicktools.log
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
/home/kk/quicktools/run.sh --screenshot region
```

第二次调用会把命令发送给已经运行的主实例，因此可以正常显示/隐藏启动器或触发截图。应用内录制快捷键只在 X11/Windows 下自动生效。

## 计算器

上方是草稿纸，下方是按键；右上角的“科学模式”开关决定是否显示进制转换、进制选择和 A-F 按键。

- “科学模式”默认关闭，此时是普通计算器布局，只保留 `+ - * / () % ^` 等基础运算。点击开关后显示进制转换栏、进制选择按钮和 A-F 按键；关闭时会自动切回 DEC，避免隐藏的进制继续影响输入。开关状态会立即保存，重新打开计算器或重启应用后保持。
- 草稿纸会自动记忆：所有非空行在输入后约 0.4 秒写入磁盘（未按 `Enter` 的行也会保存），重新打开计算器或重启应用后恢复表达式和结果。每行会记住自己输入时的进制，HEX/BIN 行不会因为重新打开而丢失。
- 每行右侧的 `×` 可删除该条记录并及时保存；点击顶部“草稿纸 · 设置”打开设置，可调整最大保存条数（默认 200，范围 1–5000），或清空全部记录（需要确认）。
- 调小最大保存条数会立即删除最旧的记录，只保留最近 N 条。运行中界面可以暂时超过上限，但磁盘始终只保存最新 N 条，重新打开后最多恢复 N 条。
- 输入即自动计算，无需按 `Enter` 或 `=`：本行实时显示 `= 结果`，进制转换栏同步更新。按 `Enter` 或 `=` 确认当前层并新建下一层。
- 未写完的表达式按单位元自动补全：以 `+`/`-` 结尾时补 `0`（如 `1+` 视为 `1+0`），以 `*`、`/`、`//`、`%` 结尾时补 `1`（如 `1+2*` 视为 `1+2*1`，显示 `3`）。
- `1^`、`1+(1+` 等无法补全或括号不匹配的输入不显示结果；按 `Enter` 或 `=` 确认时才提示具体错误。
- 键盘输入支持数字、`()`、`+ - * / // % ^ **`。
- `^` 与 `**` 是右结合次方，例如 `2^3^2 = 512`。
- 中文/全角 `（ ）`、全角数字和运算符会自动归一化为英文符号。
- 鼠标可点击表达式任意字符定位光标，然后输入、Backspace、Delete 或拖选修改；修改后结果实时重算。
- 点击任意历史层可原地编辑并重新计算；多个结果会同时保留。默认视口显示 4 层，滚轮或右侧滚动条可查看更多。
- 进制按键带中文说明，从左到右为 `BIN 二进制`、`OCT 八进制`、`HEX 十六进制`、`DEC 十进制`，默认选中 DEC；转换栏按 `BIN DEC / OCT HEX` 两行排列。活动进制决定裸数字的解释和结果显示，并禁用非法数字按键；`0x`、`0b`、`0o` 前缀在任何模式下都有效。
- 输入框会按当前进制过滤字符：BIN 仅允许 `0`/`1`，OCT 允许 `0-7`，HEX 允许 `0-9`/`A-F`，DEC 仅允许十进制数字；非 DEC 模式不能输入小数点，非法字符会被直接丢弃（粘贴同样生效）。裸数字按当前进制解析，例如 HEX 下 `11+11 = 0x22`。
- 当前进制在转换栏中以浅蓝底色、主题色、加粗和更大字号突出显示。
- 转换栏实时显示当前值在四种进制下的表示，可选中复制。非整数只提供十进制表示。
- 非 DEC 模式的小数点输入被禁用；除法仍可产生小数。
- 安全的递归下降解析器，不使用 `eval`。
- “科学模式”和最大保存条数保存在 Linux `~/.local/share/quicktools/plugin_data/calculator/settings.json`；草稿纸内容保存在同目录的 `scratchpad.json`（Windows 为 `%APPDATA%\QuickTools\plugin_data\calculator\`）。

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

## 截图

内置「截图」插件。当前 Linux X11 已实机验证；Windows 和 Wayland 的代码路径已实现，但仍需按下方清单在真实机器上验收。

当前能力：

- **控制窗口**：左侧导航提供首页、关于和设置；首页包含四张可点击的模式卡（矩形/窗口/自由/滚动）和最近截图区，关于页显示版本、能力、快捷键和文件位置。
- **矩形区域截图**：X11/Windows 下按截图快捷键（默认 `Ctrl+Alt+X`，或模式快捷键 `Ctrl+Alt+1`），QuickTools 窗口会先隐藏，屏幕上出现冻结画面，拖拽选择区域后进入编辑窗口。
- **窗口截图**：按 `Ctrl+Alt+2` 或在模式卡点击进入；冻结画面上移动鼠标会高亮指针下的窗口，点击后采集该窗口；窗口被遮挡时会先抬升再重新抓屏。
- **自由截图**：按 `Ctrl+Alt+3` 或在模式卡点击进入；按住鼠标绘制套索，松开后得到带透明边缘的任意形状截图。
- **滚动截图**：按 `Ctrl+Alt+4` 或在模式卡点击进入；拖拽选择滚动区域后，插件会自动滚动、抓帧并拼接成长图；控制条可随时“完成”或“取消”。仅 Windows/X11 支持，属于 best-effort：固定表头、平滑滚动、虚拟列表或忽略合成滚轮的应用可能拼接失败或出现接缝。请尽量选择不覆盖控制条的滚动区域，否则控制条可能被拼进长图。
- **模式快捷键**：`Ctrl+Alt+1~4` 固定注册，分别对应矩形、窗口、自由和滚动截图；主截图快捷键仍可在设置中修改。模式快捷键与启动器或主快捷键重复时自动跳过；若与桌面环境（如工作区切换）或其他软件冲突，可能被系统优先处理。
- **编辑与圈选**：编辑窗口支持预览、复制到系统剪贴板、自动保存、另存为。标注工具包括：
  - **矩形**和**圆形/椭圆**空心轮廓，用于圈住内容；默认不填充。
  - 箭头、**自由画笔**、文字、自动递增序号、马赛克、图片内贴纸、文字水印。
  - **画笔**：选择“画笔”后按住鼠标左键自由绘制，绘制过程实时预览；颜色和线宽可调，绘制完成后可选中移动、撤销/重做，并随截图一起导出。
  - 文字输入框无边框，并自动取点击位置附近的背景色，避免深色输入框遮挡截图；输入框字号按实际像素大小显示，和提交后的文字大小一致。新增文字会自动选中。
  - 字号可用“字号”输入框或 A-/A+ 调整；输入过程中用 A-/A+ 可实时预览，提交后选中文字仍可继续改字号。
  - **裁剪**：选择“裁剪”后拖动图片的边或角调整保留区域，按 Enter 应用，Esc 取消；裁剪可撤销。
  - 左/右旋转 90°、水平翻转。
  - 选择对象后可拖拽移动；矩形/圆形/马赛克/贴纸/水印可拖角点缩放。
  - 颜色、线宽、字号可调；支持撤销/重做。
  - **滚轮缩放**，缩放以鼠标位置为中心；放大后可按住鼠标中键拖动平移，也可按住空格再用左键拖动；使用选择工具时直接在图片空白处拖动同样可以平移。标题栏“适应”会把图片按比例放大或缩小到窗口大小，“1:1”恢复原始像素比例。
  - 工具栏“重置”一键恢复未编辑原图（重置本身可撤销）；“重做”在有可重做操作时恢复上一步，没有可重做操作时回到未编辑原图。
- **自动保存**：编辑器的每次修改（标注、移动、裁剪、旋转等）会在约 0.4 秒后自动写回最近截图，原图和缩略图同步更新；如果该截图之前已经导出过文件，也会同步覆盖该文件。编辑器不再提供“保存”按钮，需要另存为新文件时使用“另存为”；`Ctrl+S` 仍可手动保存到设置中的保存目录。关闭编辑器时会立即完成尚未执行的自动保存。
- **最近截图**：每次截图会保存一份原图到插件数据目录。控制窗口中的最近截图区域支持滚动、搜索、星标收藏、筛选（全部/已收藏/按截图模式）、打开、复制、删除和清空；收藏状态会写入 `recent.db`，重启后保留。编辑、复制或另存为后最近记录会更新为带标注的最终图，返回截图助手时缩略图会立即刷新。窗口缩小时只有最近截图区域收缩并滚动，左侧设置入口、页脚快捷键和保存目录始终保留。
- **复制反馈**：编辑器点击“复制”后会显示“已复制到剪贴板”提示条，按钮文字临时变为“已复制 ✓”，底部状态栏同步更新；不需要额外确认操作。最近截图里的复制同样会弹出提示。
- **关闭与返回**：编辑器底部的“关闭”会结束本次截图流程，并确保不留下任何 QuickTools 窗口：截图前被隐藏的窗口不会恢复；从最近截图打开编辑器时，原本可见的截图助手也会一并隐藏。“关闭并返回”会在关闭编辑器后重新显示并聚焦截图助手，方便连续截图；即使截图由全局快捷键发起、助手窗口尚未打开，也会打开助手窗口。修改会自动保存，因此正常关闭不会再因为改动而提示；只有新截图既没有产生修改、也没有复制或另存为时才会询问确认。若自动保存失败，仍会提示存在未保存的修改。标题栏关闭按钮和 `Esc` 的行为与“关闭”相同。
- **设置**：可修改保存目录、图片格式（PNG/JPEG/WebP）、JPEG 质量、最近截图上限、截图快捷键和启用状态；滚动截图可调滚动格数、每帧等待时间、最大高度和忽略顶部/底部像素。
- **CLI/IPC**：`--screenshot region`、`--screenshot window`、`--screenshot freeform`、`--screenshot scroll` 均已在 Windows/X11 下可用；`open` 打开控制窗口。
- **Wayland**：区域和窗口截图通过 `xdg-desktop-portal` 的系统选择器完成；自由截图先由 portal 截取全屏，再在编辑器中用“套索裁剪”圈出保留区域；滚动截图明确不支持；不会静默回退到 X11。Linux Wayland 不提供任何应用内全局截图快捷键（包括 `Ctrl+Alt+1~4`），请把系统快捷键绑定到 `quicktools --screenshot region/window/freeform/scroll`。

编辑窗口快捷键：`Ctrl+Z` 撤销、`Ctrl+Y` 或 `Ctrl+Shift+Z` 重做、`Delete` 删除选中对象、`Ctrl+0` 适应窗口、`Ctrl+1` 原始比例（1:1）、`Ctrl+C` 复制、`Ctrl+S` 手动保存到保存目录、`Esc` 取消当前操作或关闭窗口；放大后按住空格并拖动左键可平移画面。文字使用系统 CJK 字体导出；找不到中文字体时编辑窗口会提示。

Wayland 使用系统截图选择器时，选择界面由桌面环境（GNOME/KDE 等）提供，QuickTools 无法自定义其外观；不同桌面的行为可能有差异。

数据位置：

- Linux：`~/.local/share/quicktools/plugin_data/screenshot/`（`recent.db`、`images/`、`thumbs/`、`settings.json`）
- Windows：`%APPDATA%\QuickTools\plugin_data\screenshot\`
- 默认保存目录：Linux 为 `~/Pictures/Screenshots`（遵循 XDG Pictures 目录），Windows 为 `%USERPROFILE%\Pictures\Screenshots`

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
- 计算器草稿纸记忆会持久化到 `scratchpad.json`；自动保存有约 0.4 秒防抖，强制结束进程最多可能丢失最后约 0.4 秒的输入。
- 剪贴板在 Linux Wayland 下依赖 `wl-clipboard`，且不同合成器限制不同；无法保证所有 Wayland 环境可用。
- 截图插件当前支持 X11/Windows 矩形/窗口/自由/滚动截图、矩形/圆形/椭圆空心圈选、箭头/自由画笔/文字/序号/马赛克/贴纸/水印、裁剪旋转、复制/自动保存/另存为和最近截图；Wayland 支持 portal 的区域/窗口截图和“全屏 + 套索裁剪”的自由截图，不支持滚动截图。滚动截图是 best-effort，复杂页面可能失败或出现接缝；文字导出依赖系统安装的中文字体。
- 截图选区覆盖“鼠标所在显示器”，暂不支持一次拖拽跨多个显示器；Windows 混合 DPI 多屏仍需实机验证。
- 截图窗口模式在 X11/Windows 下通过枚举窗口并抬升后重新抓屏实现；被其他窗口遮挡且无法抬升时，可能采集到冻结画面中的可见部分。
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

## 截图 Windows 验收清单

在真实 Windows 10/11 上逐项确认：

1. 默认 `Ctrl+Alt+X` 触发矩形截图，`Ctrl+Alt+1~4` 分别触发矩形/窗口/自由/滚动截图；启动器、设置窗口和截图插件窗口都不出现在截图中。
2. 100%/125%/150% 缩放以及主屏左侧/上方的副屏：选区位置与实际像素一致；记录混合 DPI 的偏差。
3. 窗口截图能高亮并采集目标窗口；被遮挡窗口抬升后采集；自由截图边缘透明；滚动截图对简单长页面/文档可用，能自动停止和取消。
4. 矩形、圆形/椭圆为空心圈选，内部内容不被填充；箭头、文字、序号、马赛克、贴纸、水印、裁剪、旋转可用；中文文字正常。
5. 复制到画图、Word、浏览器后尺寸/颜色正确；保存 PNG/JPEG/WebP 正常；最近截图在重启后仍可打开，星标收藏和筛选状态保留。
6. 修改主截图快捷键并重启后仍生效；`Ctrl+Alt+1~4` 模式快捷键可用；快捷键与启动器冲突时有明确提示。
7. `--screenshot region/window/freeform/scroll` 在有/无实例时行为正确；打包版重复 1–6 的核心项。


在 GNOME Wayland 或 KDE Wayland 会话中：

1. 安装并确认 `jeepney` 可用；把系统快捷键绑定到 `quicktools --screenshot region`。
2. 触发区域/窗口截图时出现桌面自带的系统选择器；取消后 QuickTools 窗口恢复，不产生最近记录。
3. 系统选择器返回的图片进入编辑器；矩形/圆形/箭头/画笔/文字/马赛克等标注和复制/自动保存/另存为/最近截图可用。
4. 自由截图先请求系统全屏截图，再在编辑器中用“套索裁剪”圈出保留区域；PNG 角落透明。
5. 滚动截图显示明确“不支持”提示，不静默失败。
6. 应用内不尝试注册任何全局截图快捷键（包括模式快捷键）；首页/关于页和设置页显示系统快捷键绑定说明。
7. 不同桌面环境的 portal 选择器外观和可用模式可能不同，请记录实际行为。

## Linux Wayland 剪贴板验收

在 GNOME Wayland 或 KDE Wayland 会话中安装 `wl-clipboard` 后，重复上述文本/图片/文件/暂停/重启测试。插件状态区应显示 `Wayland (wl-clipboard)`；若未安装依赖，应显示不可用及安装提示。部分合成器可能限制后台读取，请记录实际结果，不要假定所有 Wayland 环境都可用。

## 运行测试

```bash
.venv/bin/pip install -e '.[dev]'
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q

# 截图专项（几何、标注、渲染、滚动拼接、设置、最近库、portal、UI）
DISPLAY=:0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest \
  tests/test_screenshot_geometry.py tests/test_screenshot_annotations.py \
  tests/test_screenshot_render.py tests/test_screenshot_stitcher.py \
  tests/test_screenshot_settings.py tests/test_screenshot_store.py \
  tests/test_screenshot_portal.py tests/test_screenshot_ui_smoke.py -q
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

产出是 `dist/QuickTools/QuickTools`。Linux 打包版在终端里的行为和日志：

```bash
dist/QuickTools/QuickTools              # 启动并立即返回终端，关闭终端不退出
dist/QuickTools/QuickTools --foreground # 前台运行，实时打印日志（关闭终端会结束应用）
dist/QuickTools/QuickTools --toggle     # 切换启动器显示状态
dist/QuickTools/QuickTools --quit       # 退出已运行的实例
```

后台日志位于 `~/.local/share/quicktools/logs/quicktools.log`，可用 `tail -f` 实时查看。打包脚本依赖项目根目录的 `QuickTools.spec`；仓库只保留两个打包脚本：Linux 用 `build_linux.sh`，Windows 用 `build_windows.bat`。脚本会自动创建 `.venv`、安装依赖并调用 PyInstaller。

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
