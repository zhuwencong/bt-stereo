# -*- coding: utf-8 -*-
"""打包发布用的 zip。

    python build_release.py

做三件事：
1. 打包（调 PyInstaller）
2. 把产物套进 bt-stereo-win64/ 顶层目录
3. 重新压 zip，并修正文件名编码

第 3 步是必要的：PyInstaller / PowerShell 打出来的 zip 常把路径分隔符写成
反斜杠、且中文文件名条目不置 UTF-8 标志位。Windows 资源管理器解压正常，
但 Git Bash / 7-Zip / macOS 上会解出乱码文件名——在开发机上永远发现不了。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_DIR = DIST / "bt-stereo-win64"
OUT_ZIP = ROOT / "bt-stereo-win64.zip"


def run_build() -> None:
    print("[1/4] PyInstaller 打包 ...")
    cmd = [sys.executable, "-m", "PyInstaller", "bt-stereo.spec", "--noconfirm"]
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit("打包失败，先 pip install pyinstaller")
    if not APP_DIR.is_dir():
        raise SystemExit(f"没有找到产物目录：{APP_DIR}")


def add_readme() -> None:
    print("[2/4] 补上使用说明 ...")
    src = ROOT / "README.md"
    # zip 里的文件名尽量用 ASCII，避免各种解压工具的编码问题
    (APP_DIR / "README.md").write_bytes(src.read_bytes())


def add_launcher_guard() -> None:
    """放一个启动器，先检查 _internal 在不在。

    这是唯一能堵住"只把 exe 拷出来"的办法——PyInstaller 的 bootloader
    在缺 _internal 时直接 return -1，一个字都不打印，用户只会看到
    "双击没反应"。
    """
    print("[3/4] 生成带检查的启动脚本 ...")
    bat = """@echo off
setlocal
cd /d "%~dp0"

rem 缺 _internal 时 exe 会静默退出（bootloader 返回 -1，不打印任何东西），
rem 用户只会看到"双击没反应"。这里提前拦住并说清楚。
if not exist "%~dp0_internal\\" (
    echo ==========================================
    echo   [X] 缺少 _internal 文件夹
    echo ==========================================
    echo.
    echo  这个 exe 只是引导程序，真正的运行库在同目录的 _internal 里。
    echo  请解压整个 zip 后再双击，不要把 bt-stereo.exe 单独拷出来。
    echo.
    pause
    exit /b 1
)

start "" "%~dp0bt-stereo.exe"
"""
    (APP_DIR / "启动.bat").write_bytes(
        bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")
    )


def make_zip() -> None:
    print("[4/4] 重新压缩（修正文件名编码）...")
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()

    files = sorted(p for p in APP_DIR.rglob("*") if p.is_file())
    base = APP_DIR.parent  # dist/，这样 zip 内第一层就是 bt-stereo-win64/
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            arcname = p.relative_to(base).as_posix()  # 强制正斜杠
            info = zipfile.ZipInfo(arcname)
            info.flag_bits |= 0x800                   # 强制 UTF-8 文件名
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())

    mb = OUT_ZIP.stat().st_size / 1024 / 1024
    print(f"\n完成：{OUT_ZIP}  ({mb:.1f} MB, {len(files)} 个文件)")
    print(f"上传这个 zip 到 GitHub / Gitee Releases 即可。")


if __name__ == "__main__":
    if APP_DIR.exists() and "--reuse" in sys.argv:
        print("复用已有产物")
    else:
        run_build()
    add_readme()
    add_launcher_guard()
    make_zip()
