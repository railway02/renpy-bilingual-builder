"""Create the Windows onedir ZIP. Run with a clean Windows x64 Python venv."""

from __future__ import annotations

import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "RenPy双语工具"
DEPENDENCIES = ("customtkinter", "darkdetect", "packaging", "pillow", "pyinstaller")


def collect_licenses(destination: Path) -> None:
    for name in DEPENDENCIES:
        package = distribution(name)
        found = False
        for file in package.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(package.locate_file(file))
                if source.is_file():
                    target = destination / name / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    found = True
        if not found:
            raise RuntimeError(f"No license files found for {name}")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Missing CPython license: {python_license}")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    # Some CPython installers omit Tcl's license file. Keep an upstream copy.
    for component, fallback in (("tcl8.6", "Tcl-license.terms"), ("tk8.6", "Tk-license.terms")):
        source = Path(sys.base_prefix) / "tcl" / component / "license.terms"
        if not source.is_file():
            source = ROOT / "packaging/licenses" / fallback
        shutil.copy2(source, destination / f"{component}-license.terms")


def main() -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Packaging requires Windows x64 CPython; Linux cannot build this Windows bundle.")
    dist = ROOT / "dist"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(ROOT / "build/pyinstaller"),
        str(ROOT / "packaging/windows.spec"),
    ], cwd=ROOT, check=True)
    bundle = dist / APP_NAME
    internal = bundle / "运行依赖文件"
    collect_licenses(internal / "licenses")
    instructions = (ROOT / "packaging/使用说明.txt").read_text(encoding="utf-8")
    (bundle / "使用说明.txt").write_text(instructions, encoding="utf-8-sig", newline="\r\n")
    manifest = {"python": sys.version, "platform": platform.platform(),
                "unrpyc_revision": "3ae8334ed71a05535927dcc559663d3aca51215b",
                "dependencies": {name: distribution(name).version for name in DEPENDENCIES}}
    (internal / "build-info.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(dist / "RenPy-Bilingual-Builder-windows-x64"), "zip", dist, APP_NAME))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"PORTABLE_ZIP={archive}")


if __name__ == "__main__":
    main()
