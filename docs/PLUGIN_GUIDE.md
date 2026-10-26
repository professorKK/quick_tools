# QuickTools 插件开发指南

QuickTools 的启动器只负责发现、展示和打开插件。插件是普通的 Python + Tkinter 程序，运行在 QuickTools 主进程内，并拥有独立窗口。

> **信任边界**：插件代码没有沙箱，拥有与主程序相同的权限。只安装你信任的插件。扫描插件时不会导入代码；普通插件只有点击卡片时才会懒加载入口文件，`background: true` 的插件则在应用启动时加载并启动后台服务。加载后代码即拥有完整权限。

## 1. 插件目录

用户插件目录：

- Linux：`~/.local/share/quicktools/plugins`（遵循 `XDG_DATA_HOME`）
- Windows：`%APPDATA%\QuickTools\plugins`

你也可以在“设置 → 插件 → 打开插件目录”中直接打开它。

每个插件放在一个独立文件夹中，例如：

```text
<用户插件目录>/
  hello/
    plugin.json
    plugin.py
    helper.py        # 可选，支持相对导入
```

把文件夹放好后，下次唤出启动器会自动扫描；也可以在设置中点击“重新扫描插件”。插件的 `id` 必须全局唯一；与内置插件 id 重复的用户插件会被忽略。

## 2. plugin.json

```json
{
  "api_version": 1,
  "id": "hello",
  "name": "示例插件",
  "summary": "一个展示插件框架用法的 Hello World",
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
| `summary` | 否 | 卡片上的**一句话概述**，建议 20–40 字；没有时自动截取 `description` 的第一句 |
| `description` | 否 | **详细说明**，显示在“设置 → 关于”；可以包含 `\n` 换行和项目符号 |
| `author` | 否 | 作者信息，显示在关于页；没有时显示“未提供” |
| `version` | 是 | 插件版本字符串，显示在关于页 |
| `entry` | 是 | 相对插件文件夹的 `.py` 入口，不能越出插件目录 |
| `class` | 是 | 入口文件中导出的插件类名 |
| `icon` | 否 | 一个短文本，作为卡片和标题栏图标。emoji 在部分 Tk 平台上不可见时会自动回退为插件名首字 |
| `order` | 否 | 数字，越小越靠前；默认 100 |
| `background` | 否 | 布尔值；为 `true` 时应用启动后立即调用 `start_service()`，无需用户点击卡片。默认 `false` |

### 卡片和关于页的分工

启动器卡片保持紧凑，只显示：图标、名称、`summary`（一句话）。请不要把长段落塞进 `summary`。

插件版本、`description` 详细说明、`author`、插件目录和数据目录由框架自动展示在“设置 → 关于”页，插件无需自己再写关于页。

## 3. 统一窗口框架（重要）

QuickTools 会为插件主窗口自动创建无边框标题栏和窗口行为。插件**不要**再自己做这些事：

- 不要调用 `window.overrideredirect(True)`；
- 不要自己绘制标题栏、关闭/最小化按钮；
- 不要在主窗口内容里再放“置顶”图钉或“关于”标题；
- 不要依赖系统标题栏的关闭行为，关闭按钮由框架接管。

标题栏布局由框架固定：

```text
[图标] [插件名称]                              [设置] [置顶] [隐藏] [放大] [关闭]
```

- **设置**：打开共享的“设置/关于”对话框。插件通过 `create_settings_ui(parent)` 提供设置页，关于页由框架根据 `plugin.json` 自动生成。
- **置顶**：切换窗口的 `-topmost`，按钮会显示激活状态；再次点击取消。
- **隐藏**：Windows 上最小化到任务栏；Linux X11 上无边框窗口不受窗口管理器管理，会退化为收回窗口，可再次从启动器打开。
- **放大/还原**：使用当前显示器的工作区（Windows 会避开任务栏），双击标题栏有相同效果。对话框不显示该按钮。
- **关闭**：关闭窗口并清理插件窗口的注册状态；`Alt+F4` 也会走同一路径。

框架还负责：

- 拖动标题栏移动窗口；
- 拖动窗口四边/四角调整大小，并尊重 `window.minsize(...)`。四周约 5px 是缩放热区，内容不要依赖贴边的最后 5px 做点击；
- 双击标题栏放大/还原；
- Windows 下恢复任务栏按钮、Alt+Tab 和 Windows 11 圆角；对话框不会出现在任务栏；
- 标题栏按钮使用 Canvas 绘制，不会抢走 Entry/Text 的键盘焦点。设置按钮显示齿轮、置顶按钮显示图钉；两个平台都使用随包内置的 Material Icons 字体，字体无法加载时回退到 Canvas 线稿。
- 插件主窗口失去焦点时会自动隐藏（`withdraw`），再次点击启动器卡片即可恢复；窗口实例和数据不会丢失。点击标题栏图钉置顶后，窗口不会因失焦隐藏。插件在主窗口之外自行创建的 Toplevel（编辑器、全屏覆盖层、对话框等）不受该行为影响。

### 编写 `create_ui(window)`

插件只需要在 `window` 中填充内容。标题栏已经先被 `pack` 到窗口顶部，插件直接 `pack`/`grid` 后的内容会自动排在标题栏下方：

```python
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.ui_theme import BG, PANEL, TEXT


class HelloPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        window.title("示例插件 · 快捷工具")
        window.geometry("420x260")
        window.configure(bg=BG)

        body = tk.Frame(window, bg=PANEL, padx=24, pady=24)
        body.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(
            body, text="Hello!", bg=PANEL, fg=TEXT,
            font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor="w")
```

要点：

- `window.title(...)` 仍建议设置，它用于任务栏和窗口枚举；可见标题栏的文字来自 `plugin.json` 的 `name`。
- `window.geometry(...)`、`center_on_screen(window, ...)`、`window.minsize(...)` 仍然有效。框架会读取 `wm_minsize` 作为拖拽缩放的最小尺寸。
- 宿主会自动记住每个插件窗口的大小和放大状态（按 `plugin.json` 的 `id`，保存在 `window_state.json`），关闭再打开或重启应用后恢复。`create_ui()` 里的 `geometry()`/`center_on_screen()` 只是首次打开时的默认值；恢复时位置会重新居中，尺寸超过当前屏幕或小于 `wm_minsize` 时自动调整。插件不需要自己保存窗口尺寸。
- 不要用 `window.resizable(...)` 控制插件窗口：是否允许缩放由 `WindowFrame(resizable=...)` 决定，当前所有平台使用框架的 Tk 自绘边缘缩放。
- **不要直接在 `Toplevel` 上使用 `grid` 放内容**：标题栏已经用 `pack` 放在窗口顶部，同一个容器混用 `pack` 和 `grid` 会让 Tk 报错。把内容放进一个 `tk.Frame(window)`，再 `pack` 这个 Frame（本指南所有示例都是这样）。
- 内容背景建议使用 `quicktools.ui_theme` 里的 `BG` / `PANEL` / `BORDER` / `TEXT` / `MUTED`，这样和标题栏、设置对话框保持一致。
- 不要给主窗口绑定新的 `<Destroy>` 清理逻辑而不使用 `add="+"`；框架和启动器也会监听窗口销毁。订阅事件时请使用 `add="+"`，并在销毁时取消自己的 `after` 任务。
- `create_ui` 可能被多次调用（尤其是 `background: true` 插件），视图代码要支持重复创建。

### 添加设置页

插件不需要自己创建设置窗口。实现可选方法，并复用 `quicktools.settings_widgets` 的组件，默认写法是“宿主提供一张白色圆角卡片，插件只填内容”：

```python
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.settings_widgets import SectionHeader, SettingsRow, ToggleRow
from quicktools.ui_theme import ACCENT, CARD_BG, FlatButton

class MyPlugin(PluginBase):
    def create_settings_ui(self, parent: tk.Misc) -> None:
        SectionHeader(
            parent, "我的设置", "调整这个插件的行为。",
            bg=CARD_BG,
        ).pack(fill="x", pady=(0, 4))

        enabled = tk.BooleanVar(value=True)
        ToggleRow(
            parent, "启用功能", enabled,
            description="关闭后不再处理新的内容。",
            bg=CARD_BG,
        ).pack(fill="x")

        row = SettingsRow(
            parent, "保留天数",
            description="超过天数的记录会被自动清理。",
            bg=CARD_BG, last=True,
        )
        row.pack(fill="x")
        tk.Spinbox(row.control, from_=1, to=365, width=8).pack()

        status = tk.StringVar()

        def save() -> None:
            status.set("设置已保存")
            host = parent.winfo_toplevel()
            setter = getattr(host, "set_status", None)
            if callable(setter):
                setter("设置已保存")

        FlatButton(
            parent, "保存设置", save, accent=True, font_size=10,
            padx=16, pady=8,
        ).pack(anchor="e", pady=(12, 0))
```

如果设置项较多、需要多张分组卡片，声明类属性并自行创建卡片：

```python
from quicktools.settings_widgets import Card, SectionHeader
from quicktools.ui_theme import SURFACE

class MyPlugin(PluginBase):
    settings_cards = True

    def create_settings_ui(self, parent: tk.Misc) -> None:
        SectionHeader(
            parent, "基本设置", "所有修改保存后生效。",
            bg=SURFACE,
        ).pack(fill="x", pady=(0, 10))
        card = Card(parent)
        card.pack(fill="x")
        # 把 SettingsRow / ToggleRow 放进 card.body，背景使用 CARD_BG
```

约定：

- 默认 `parent` 已经是宿主卡片的内部容器，背景为 `CARD_BG`；直接放 `SectionHeader`、`SettingsRow`、`ToggleRow` 即可，**不要再套自己的 `Card`**，否则会出现卡片套卡片。
- 声明 `settings_cards = True` 后宿主不再外包卡片，`parent` 的背景是页面底色 `SURFACE`；此时用 `Card(parent)` 建分组卡片，操作按钮放在 `SURFACE` 上。内置插件使用这种写法。
- `SettingsRow.control` 是右侧控件区，把 Entry/Spinbox/Combobox 放进它；描述文本会随行宽自动换行。每组的最后一行传 `last=True`，避免多出一条分隔线。
- `ToggleRow` 自带自绘开关；点击标签也能切换。保存时读取对应的 `BooleanVar`。
- 设置页在可滚动容器中，内容可以高于对话框；宽度会自动适配。操作按钮建议放在内容底部；框架底部的“关闭”按钮负责关闭对话框。
- 如果宿主是 `PluginSettingsDialog`，可以调用 `self.winfo_toplevel().set_status("…")` 在底部状态栏显示反馈；不是所有宿主都有该方法，调用前请 `getattr` 检查。
- 不要在设置页里再放“关于”页；关于信息由 manifest 自动生成。
- 如果插件没有可配置项，可以不实现 `create_settings_ui`，框架会显示“这个插件没有可配置的选项”，但关于页仍然可用。

### 从内容里打开设置

标题栏的设置按钮会调用 `plugin.open_settings(window)`。如果内容里也有设置入口（例如侧边栏），调用同一个方法：

```python
self.open_settings(window)          # PluginBase 提供，自动复用同一个对话框
```

不要在内容里再创建第二个设置窗口。

### 对话窗口、编辑器等次级窗口

如果插件需要额外的 `Toplevel`（对话框、编辑器等），用同一个 `WindowFrame` 保持统一外观：

```python
import tkinter as tk

from quicktools.window_frame import WindowFrame


def open_dialog(master: tk.Misc, fonts) -> tk.Toplevel:
    window = tk.Toplevel(master)
    window.withdraw()
    window.configure(bg="#ffffff")
    window.transient(master)
    window.protocol("WM_DELETE_WINDOW", window.destroy)

    frame = WindowFrame(
        window,
        title="我的对话框",
        icon="D",
        fonts=fonts,
        dialog=True,        # 只显示“关闭”，不显示设置/置顶/最小化/放大
        resizable=True,     # 允许边缘拖拽缩放
        on_close=window.destroy,
    )
    # 在 window 中继续构建内容；标题栏已经占用了顶部。
    return window
```

`WindowFrame` 参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `title` | 必填 | 标题栏文字 |
| `icon` | `"◆"` | 左侧图标文字 |
| `fonts` | 自动 | 传入 `pick_fonts(...)` 的 `Fonts` 以复用字体 |
| `subtitle` | `""` | 标题旁的小字，可选 |
| `on_settings` | `None` | 传入后显示设置按钮 |
| `on_close` | `None` | 关闭按钮回调；不传则直接 `destroy()` |
| `pin` | `True` | 是否显示置顶按钮 |
| `minimize` | `True` | 是否显示隐藏按钮 |
| `maximize` | `True` | 是否显示放大按钮 |
| `resizable` | `True` | 是否启用边缘拖拽缩放 |
| `dialog` | `False` | 对话框模式：不进入任务栏，只保留关闭按钮 |

主窗口由启动器创建 `WindowFrame`，可通过 `getattr(window, "quicktools_frame", None)` 取得实例，用于高级场景（例如 `set_title()`、`set_subtitle()`、`refresh_pin()`）。一般插件不需要这样做。

### 不应该使用框架的窗口

截图选区覆盖层、滚动截图控制条这类临时覆盖层需要完全无边框、置顶且不接收普通窗口管理，继续使用 `overrideredirect` 自行处理即可；它们不属于插件主窗口框架。

## 4. 插件 API

```python
from quicktools.plugin_api import PluginBase, PluginContext


class MyPlugin(PluginBase):
    def create_ui(self, window) -> None:
        ...
```

- `PluginContext` 提供：
  - `context.root`：隐藏的 Tk 根窗口；不要销毁它。需要 `after` 定时任务时使用它，窗口关闭后回调仍可存活。
  - `context.plugin_id`：插件 id。
  - `context.plugin_dir`：插件自身目录。
  - `context.data_dir`：插件专属的数据目录，已验证可写，可用于保存配置和数据库。路径为 `<插件数据根目录>/<plugin_id>`，默认根目录是应用数据目录下的 `plugin_data/`，用户可在“设置 → 插件数据”中迁移到其他位置；插件不要假设它是固定路径，也不要把它写进配置后跨启动复用。
  - `context.meta`：当前插件的 `PluginMeta`（包含 `name`、`version`、`summary`、`description`、`author`、`icon` 等），用于自定义界面时读取插件信息；旧宿主可能为 `None`。
- QuickTools 负责创建并关闭插件的 `Toplevel` 窗口。`create_ui(window)` 中只需要填充内容、设置标题和初始尺寸；标题栏和窗口行为由框架提供。
- 普通插件（`background` 不为 `true`）：`create_ui` 在窗口首次打开时调用；窗口关闭后再次打开会创建一个新的插件实例。
- 后台插件（`background: true`）：
  - 应用启动并扫描到插件后立即创建**唯一实例**并调用 `start_service()`，即使从未打开窗口。
  - 打开窗口时复用同一实例并调用 `create_ui(window)`；窗口关闭只销毁 `Toplevel`，不会调用 `stop_service()`。
  - 同一个实例可能多次收到 `create_ui`，因此视图代码需要支持重复创建，并在 `<Destroy>` 时移除自己的 Tk 定时器和监听回调。
  - 应用退出、插件被删除或版本/目录变化时，QuickTools 调用 `stop_service()`。
  - `start_service()`、`stop_service()` 必须幂等；后台线程不得直接操作 Tk 控件，应通过队列 + `context.root.after(...)` 回到主线程。
  - 如果 `create_ui` 在服务启动失败后仍被调用，建议显示可读的错误状态而不是让窗口加载失败。

```python
from quicktools.plugin_api import PluginBase


class MyPlugin(PluginBase):
    def start_service(self) -> None:
        # 应用启动时调用；启动后台线程/数据库/系统监听
        ...

    def stop_service(self) -> None:
        # 应用退出或插件变更时调用；停止线程并释放资源
        ...

    def create_ui(self, window) -> None:
        # 可被多次调用；每次填充新的 Toplevel
        ...
```

- 同一个插件最多只有一个窗口，重复点击卡片会聚焦已有窗口。
- 插件窗口关闭不影响主程序或启动器；启动器通过全局快捷键再次唤出。
- `on_window_shown(window)`（可选）：宿主每次显示插件主窗口时调用，包括首次打开和之后从启动器恢复已隐藏/最小化的窗口。窗口内的控件和状态会保留；如果希望“每次进入”都回到初始视图（例如把输入焦点移到一条新行），在这里重置。该方法在 Tk 主线程调用，默认实现为空操作。

### 插件动作（可选）

内置插件可以通过 `PluginBase.handle_action(action)` 接收来自 CLI、IPC 或插件自身的命名动作。这是可选能力，默认实现为空操作，现有插件无需修改。

```python
class MyPlugin(PluginBase):
    def handle_action(self, action: str) -> None:
        if action == "capture":
            ...
```

- `handle_action` 总是在 Tk 主线程调用，必须尽快返回；耗时工作放到后台线程，并通过 `context.root.after(...)` 回到主线程。
- 动作名是 ASCII 标识符，不带参数；不同变体使用不同动作名。
- 插件必须忽略未知动作，不要因为未知动作抛异常。
- `context.actions` 是可选字段，可能为 `None`。它提供：
  - `post_action(action)`：线程安全，把动作投递到主线程；适合快捷键回调。
  - `open_window()`：打开插件自己的主窗口，仅主线程。
  - `hide_windows()`：隐藏启动器、设置窗口和所有插件窗口，返回恢复回调；仅主线程，用于截图等需要隐藏 QuickTools 窗口的场景。
  - `copy_png_to_clipboard(png)`：把 PNG 字节写入系统剪贴板，并记录到剪贴板历史；仅主线程。
  - `app_hotkey_display()`：返回启动器快捷键的可读文本，用于冲突提示。
- 动作分发目前只支持 `background: true` 插件；普通插件没有常驻实例，无法可靠接收动作。

命令行 `--screenshot [MODE]` 和 IPC 命令 `plugin <id> <action>` 会经过同一条动作链路。IPC 只接受本地连接、严格格式的 ASCII 动作名，不接受任意负载。

### 相对导入

入口文件会被包装成一个独立的“包”加载，因此插件目录内可以使用相对导入：

```python
# plugin.py
from .helper import VALUE
```

请避免把插件助手模块命名为可能与已安装第三方库冲突的顶层名字；使用相对导入最安全。

## 5. 完整最小示例

见仓库 [examples/hello_plugin](../examples/hello_plugin/)：

```python
import tkinter as tk
from quicktools.plugin_api import PluginBase


class HelloPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        window.title("Hello · 快捷工具")
        window.geometry("420x240")
        self.label = tk.Label(window, text="Hello, QuickTools!")
        self.label.pack(expand=True)

    def create_settings_ui(self, parent: tk.Misc) -> None:
        tk.Label(parent, text="示例设置").pack(anchor="w")
```

把整个文件夹复制到用户插件目录，在设置里重新扫描，启动器就会显示新卡片。

## 6. 错误处理与日志

- `plugin.json` 不合法时，插件不会出现在启动器中；错误会记录在设置页和日志里。
- 入口文件导入失败或类不符合 `PluginBase` 时，点击卡片会显示错误弹窗，启动器保持可用。
- 插件事件回调中的未捕获异常会写入 `logs/quicktools.log`，并显示错误对话框。
- 请让插件在无法完成初始化时抛出带有可读消息的异常，用户更容易定位问题。
- 自定义标题栏/对话框中的回调异常会写入日志；设置页构建失败时对话框仍会打开并显示错误提示。

## 7. 设计限制

- 不支持 C++ 插件 ABI；V1 插件语言是 Python。
- 插件没有进程隔离或权限限制。
- 插件依赖需要安装到 QuickTools 所用的同一个 Python 环境中。源码运行时可使用项目 `.venv`。
- 无边框窗口在 Linux X11 上不会被窗口管理器接管：不会出现在任务栏/Alt+Tab，“隐藏”退化为收回窗口。Windows 上框架会恢复任务栏和 Alt+Tab。
- 自绘标题栏不提供 Windows 原生的贴边分屏、Aero Snap 和窗口动画；插件窗口需要全屏工作时使用标题栏“放大”或双击标题栏。
- 当前 API 版本为 1，后续不兼容变更会升级 `api_version`。本指南新增的 `summary` / `author` 字段、`create_settings_ui`、`open_settings` 和 `context.meta` 都是向后兼容的可选项。

### 从旧版插件迁移

- 删除插件窗口里的“置顶”图钉：主窗口标题栏已经有统一按钮。`quicktools.window_pin.PinButton` 仍保留，供自定义次级窗口使用。
- 删除自己绘制的标题、关闭按钮或“关于”入口；把详细说明写进 `plugin.json` 的 `description`。
- 在 `plugin.json` 增加 `summary`，卡片会自动变紧凑；没有时回退到 `description` 第一句。
- 把原有设置窗口的内容迁移到 `create_settings_ui(parent)`；内容里的设置入口改为调用 `self.open_settings(window)`。
- 额外的 `Toplevel` 建议用 `WindowFrame(dialog=True, …)` 包裹，避免继续出现系统标题栏。
