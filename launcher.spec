# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the native (tkinter) launcher, v1.0.
# 单文件、无控制台窗口；core.py 与 GUI 打包进 exe，无 static/ 依赖。

block_cipher = None


a = Analysis(
    ['native_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # 动态/条件导入（core.py 在函数内 import，显式列出以防漏）
        'psutil',
        'pynvml',
        'requests',
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LlamaLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 原生 GUI，无黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
