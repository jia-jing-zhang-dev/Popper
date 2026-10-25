"""Build dist/WordPopper-windows.zip: a folder with WordPopper.exe that runs without Python.

    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\python packaging\\build.py
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
NAME = "WordPopper"


def make_icon(path):
    """A dark rounded square with a speaker and a blue 'W', in the card's colors."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(31, 36, 48, 255))
    d.polygon([(52, 104), (82, 104), (122, 70), (122, 186), (82, 152), (52, 152)], fill=(242, 244, 248, 255))
    for r in (34, 58):
        d.arc((122 - r, 128 - r, 122 + r, 128 + r), -45, 45, fill=(124, 196, 255, 255), width=12)
    font = ImageFont.truetype(r"C:\Windows\Fonts\seguisb.ttf", 92)
    d.text((150, 118), "W", font=font, fill=(124, 196, 255, 255))
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    icon = os.path.join(HERE, "icon.ico")
    make_icon(icon)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME, "--icon", icon, "--add-data", f"{icon}{os.pathsep}.",
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
