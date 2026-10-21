# -*- mode: python ; coding: utf-8 -*-

"""Windows 单文件打包配置：产出 dist/win/QuickTools.exe。

与 QuickTools.spec（目录版）的区别：
1. 依赖和数据全部塞进 EXE（exclude_binaries=False），运行时自解压到临时目录；
2. datas 只收集源文件、跳过 __pycache__，避免把其它平台生成的 .pyc 打进去。

该 spec 不限定平台，但产物目录名和图标是按 Windows 命名的；Windows 一键脚本
build_all.bat 用 --distpath dist\\win --workpath build\\win_onefile 调用它，
单文件 exe 与目录版的 QuickTools 文件夹并列存放。
hiddenimports 必须与 QuickTools.spec 保持一致：内置插件是运行时动态导入的，
PyInstaller 的静态分析看不到它们的依赖。
"""

import sys
from pathlib import Path

hiddenimports = [
    'quicktools.window_pin',
    'quicktools.win32_hotkey',
    'quicktools.win32_focus',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL.ImageOps',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageGrab',
    'PIL.ImageChops',
    'PIL.ImageStat',
    'PIL.ImageColor',
    'PIL.BmpImagePlugin',
    'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.WebPImagePlugin',
    'PIL._tkinter_finder',
    'sqlite3',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.simpledialog',
    'tkinter.ttk',
    'tkinter.font',
    'hashlib',
    'uuid',
    'shutil',
    'struct',
    'select',
    'urllib.parse',
    'urllib.request',
]
if sys.platform.startswith('linux'):
    hiddenimports.extend([
        'Xlib.X',
        'Xlib.Xatom',
        'Xlib.display',
        'Xlib.error',
        'Xlib.protocol.event',
        'Xlib.ext.xfixes',
        'Xlib.ext.randr',
        'Xlib.ext.xtest',
        'jeepney',
        'jeepney.auth',
        'jeepney.bus_messages',
        'jeepney.io.blocking',
        'jeepney.low_level',
        'jeepney.wrappers',
    ])


def collect(root):
    """按文件收集数据，跳过 __pycache__ 和其它平台生成的字节码。"""
    base = Path(root)
    return [
        (str(path), str(path.parent))
        for path in base.rglob('*')
        if path.is_file()
        and '__pycache__' not in path.parts
        and path.suffix not in {'.pyc', '.pyo'}
    ]


datas = (
    collect('quicktools/plugins')
    + collect('quicktools/assets')
    + collect('quicktools/helpers')
)

a = Analysis(
    ['scripts/quicktools_launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    exclude_binaries=False,
    name='QuickTools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='quicktools/assets/quicktools.ico',
)
