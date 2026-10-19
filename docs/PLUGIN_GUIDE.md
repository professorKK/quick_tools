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
  "description": "一个最小的插件。",
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
| `name` | 是 | 启动器卡片显示名 |
| `description` | 否 | 卡片说明 |
| `version` | 是 | 插件版本字符串 |
| `entry` | 是 | 相对插件文件夹的 `.py` 入口，不能越出插件目录 |
| `class` | 是 | 入口文件中导出的插件类名 |
| `icon` | 否 | 一个短文本，作为卡片图标。emoji 在部分 Tk 平台上不可见时会自动回退为插件名首字 |
| `order` | 否 | 数字，越小越靠前；默认 100 |
| `background` | 否 | 布尔值；为 `true` 时应用启动后立即调用 `start_service()`，无需用户点击卡片。默认 `false` |

## 3. 插件 API

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
  - `context.data_dir`：插件专属的数据目录，已验证可写，可用于保存配置和数据库。
- QuickTools 负责创建并关闭插件的 `Toplevel` 窗口。`create_ui(window)` 中只需要填充内容、设置标题和初始尺寸。
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

### 支持的插件 UI

你可以使用任何 Tkinter 控件，也可以创建额外的 `Toplevel`。如果希望和主程序视觉一致，可以导入（非稳定 API）：

```python
from quicktools.ui_theme import BG, PANEL, TEXT, MUTED
```

用户插件不强制依赖 `quicktools.ui_theme`；`tkinter` 标准库足够。

### 相对导入

入口文件会被包装成一个独立的“包”加载，因此插件目录内可以使用相对导入：

```python
# plugin.py
from .helper import VALUE
```

请避免把插件助手模块命名为可能与已安装第三方库冲突的顶层名字；使用相对导入最安全。

## 4. 完整最小示例

见仓库 [examples/hello_plugin](../examples/hello_plugin/)：

```python
import tkinter as tk
from quicktools.plugin_api import PluginBase


class HelloPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        window.title("Hello · 快捷工具")
        window.geometry("420x220")
        label = tk.Label(window, text="Hello, QuickTools!")
        label.pack(expand=True)
```

把整个文件夹复制到用户插件目录，在设置里重新扫描，启动器就会显示新卡片。

## 5. 错误处理与日志

- `plugin.json` 不合法时，插件不会出现在启动器中；错误会记录在设置页和日志里。
- 入口文件导入失败或类不符合 `PluginBase` 时，点击卡片会显示错误弹窗，启动器保持可用。
- 插件事件回调中的未捕获异常会写入 `logs/quicktools.log`，并显示错误对话框。
- 请让插件在无法完成初始化时抛出带有可读消息的异常，用户更容易定位问题。

## 6. 设计限制

- 不支持 C++ 插件 ABI；V1 插件语言是 Python。
- 插件没有进程隔离或权限限制。
- 插件依赖需要安装到 QuickTools 所用的同一个 Python 环境中。源码运行时可使用项目 `.venv`。
- 当前 API 版本为 1，后续不兼容变更会升级 `api_version`。
