# -*- mode: python ; coding: utf-8 -*-

import sys

# Built-in plugins are loaded dynamically from the data directory, so
# PyInstaller's static analysis cannot see their imports. Keep this list in
# sync with quicktools/plugins/clipboard and quicktools/plugins/screenshot.
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


a = Analysis(
    ['scripts/quicktools_launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[('quicktools/plugins', 'quicktools/plugins'), ('quicktools/assets', 'quicktools/assets'), ('quicktools/helpers', 'quicktools/helpers')],
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
    [],
    exclude_binaries=True,
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QuickTools',
)
