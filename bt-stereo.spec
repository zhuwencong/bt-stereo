# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir 模式）。

用法：
    python -m pip install -r requirements.txt pyinstaller
    pyinstaller bt-stereo.spec --noconfirm

产物在 dist/bt-stereo-win64/ 下，整个文件夹才是完整程序。

⚠️ 为什么必须是 onedir 而不是 onefile：
exe 只是引导壳，真正的运行时（python312.dll、tkinter、numpy 的 C 扩展）
都在同级的 _internal/ 里。只分发 exe 会导致双击后毫无反应、进程静默退出
（bootloader 返回 -1，连错误都不打印）。这是本项目踩过的真实坑。
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "docs" / "preview.png"), "docs"),
]

a = Analysis(
    [str(ROOT / "app_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "comtypes",
        "comtypes.client",
        "comtypes.stream",
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 界面是中文的，排掉用不到的大件能省不少体积
    excludes=[
        "matplotlib", "scipy", "pandas", "PIL", "pytest",
        "setuptools", "pip", "wheel", "pydoc_data",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bt-stereo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 程序不弹黑框；CLI 用法靠 cmd 里直接调用
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "docs" / "icon.ico") if (ROOT / "docs" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    # 产物自带一层顶层目录：用户解压后得到一个干净的文件夹，
    # 而不是把 _internal\ 直接倒进下载目录（通用名，会和别的
    # PyInstaller 应用互相覆盖）。
    name="bt-stereo-win64",
)
