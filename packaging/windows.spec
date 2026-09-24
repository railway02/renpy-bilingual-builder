# Build with tools/package_windows.py using Windows x64 CPython.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files("customtkinter", excludes=["**/.DS_Store"])
datas += [
    (str(root / "patches/zz_bilingual_ui_patch.rpy"), "patches"),
    (str(root / "samples/demo"), "samples/demo"),
    (str(root / "tests/fixtures/import_game"), "samples/import_demo"),
    (str(root / "vendor/unrpyc/LICENSE"), "licenses/unrpyc"),
    (str(root / "vendor/unrpyc/UPSTREAM.md"), "licenses/unrpyc"),
    (str(root / "LICENSE"), "licenses/project"),
    (str(root / "THIRD_PARTY_NOTICES.md"), "licenses"),
    (str(root / "packaging/licenses"), "licenses"),
]
for package in ("customtkinter", "darkdetect", "packaging", "pillow"):
    datas += copy_metadata(package)

a = Analysis(
    [str(root / "run_desktop.py")],
    pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="RenPy双语工具", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    contents_directory="运行依赖文件",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RenPy双语工具")
