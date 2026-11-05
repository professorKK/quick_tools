# 第三方运行库

## linux-x86_64/libxcb-cursor.so.0

Qt 6.5+ 的 xcb 平台插件需要 `libxcb-cursor.so.0`，部分最小化 Ubuntu
安装没有该库。`quicktools/plugins/calculator/qt_host.py` 只在系统
`libxcb-cursor` 不可用时把本目录加入帮助进程的 `LD_LIBRARY_PATH`。

- 来源：Ubuntu jammy `libxcb-cursor0` 0.1.1-3ubuntu1（universe）
  `http://archive.ubuntu.com/ubuntu/pool/universe/x/xcb-util-cursor/`
- 许可：MIT/X Consortium License，见 `linux-x86_64/libxcb-cursor.COPYRIGHT`
- 仅放置 x86_64 版本；其他架构请在系统中安装 `libxcb-cursor0`，否则计算器无法启动，会在日志中提示缺少 Qt xcb 平台库。
