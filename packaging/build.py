"""Build dist/the app-windows.zip: a folder with the app.exe that runs without Python.

    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\python packaging\\build.py
"""

import os
import shutil
import subprocess
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
NAME = "DesktopStudyCats"


def make_icon(path):
    """The app icon: a cat's paw (appicon.py)."""
    sys.path.insert(0, ROOT)
    import appicon
    appicon.save_ico(path)


def main():
    icon = os.path.join(HERE, "icon.ico")
    make_icon(icon)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME, "--icon", icon, "--add-data", f"{icon}{os.pathsep}.", "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",
        "--collect-all", "winocr", "--collect-submodules", "winrt", "--collect-data", "certifi",
        "--distpath", DIST, "--workpath", os.path.join(ROOT, "build"), "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "word_popper.py"),
    ], check=True, cwd=ROOT)

    app_dir = os.path.join(DIST, NAME)
    for doc in ("使用说明 How to use.txt",):
        shutil.copy(os.path.join(HERE, doc), app_dir)
    archive = shutil.make_archive(os.path.join(DIST, f"{NAME}-windows"), "zip", DIST, NAME)
    print(f"{archive}: {os.path.getsize(archive) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
