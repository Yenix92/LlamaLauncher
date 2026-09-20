#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""llama-server native launcher build script (v1.0).

Builds the single-file, windowed LlamaLauncher.exe from
launcher.spec using PyInstaller. Replaces build_exe.bat.

Usage:
    python build_exe.py

Output: dist\LlamaLauncher.exe (relative to this folder).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = "launcher.spec"
REQS = "requirements.txt"


def find_python():
    return "python"


def run(cmd):
    print("  $ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=HERE)


def main():
    print("=" * 44)
    print("  llama-server native launcher build (v1.0)")
    print("=" * 44)

    py = find_python()
    print("interpreter: " + py)

    # [1/2] Ensure PyInstaller + runtime deps are installed.
    ok = subprocess.call(
        [py, "-c", "import PyInstaller"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ok != 0:
        print("[1/2] Installing PyInstaller and runtime dependencies...")
        rc = run([py, "-m", "pip", "install", "pyinstaller", "-r", REQS])
        if rc != 0:
            print("[ERROR] Dependency install failed.", file=sys.stderr)
            return rc
    else:
        print("[1/2] PyInstaller is ready.")

    # [2/2] Build the single-file, windowed exe.
    print("[2/2] Building native GUI (one file, no console)...")
    rc = run([py, "-m", "PyInstaller", SPEC, "--clean", "--noconfirm"])
    if rc != 0:
        print("[ERROR] PyInstaller build failed; see log above.", file=sys.stderr)
        return rc

    print()
    print("Build complete! Output: dist\\LlamaLauncher.exe")
    print("Double-click to run (settings.json is shared with the web app,")
    print("created next to the exe).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
