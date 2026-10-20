# 图片资源

- `logo.png`：用户提供的原始 K 标志（唯一源文件，1254×1254 RGBA）。
- `icon.png`：256×256 应用/窗口图标。
- `launcher.png`：48×48 启动器标题栏品牌图标。
- `tray.png`：64×64 方形托盘图标（Windows 使用）。透明背景、较大且不额外加粗的亮蓝渐变 K，无外框。
- `tray-linux.png`：96×64 原生 IPC 状态栏图标。透明背景、K 保持原始笔画粗细，并横向拉长以填满 Linux 顶栏的宽槽位，无外框。
- `quicktools.ico`：Windows 可执行文件图标（多尺寸 ICO）。
- `keypad/`：计算器运算符图标（plus、minus、multiply、divide、equals），由脚本以 4 倍分辨率绘制后缩小，保证边缘平滑。

截图插件控制窗口和编辑器使用的线性图标不是图片资源，由 `quicktools/plugins/screenshot/ui/icons.py` 在运行时用 Pillow 绘制并缓存，不需要在此目录生成文件。

这些派生图片由 `scripts/prepare_assets.py` 从 `logo.png` 生成。更换标志时替换 `logo.png`，重新运行：

```bash
.venv/bin/python scripts/prepare_assets.py
```

只重新生成两个状态栏图标（不会覆盖窗口图标等其他资源）：

```bash
.venv/bin/python scripts/prepare_assets.py --tray-only
```
