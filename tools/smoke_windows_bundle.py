"""Verify the released ZIP from a Chinese/spaced path without Python on PATH."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Run this smoke test on Windows.")
    with tempfile.TemporaryDirectory(prefix="rbb-portable-test-") as temporary:
        root = Path(temporary)
        relocated = root / "中文 路径 (便携测试)"
        with zipfile.ZipFile(args.archive) as archive:
            archive.extractall(relocated)
        bundle = relocated / "RenPy双语工具"
        assert sorted(p.name for p in bundle.iterdir()) == sorted([
            "RenPy双语工具.exe", "运行依赖文件", "使用说明.txt"])
        internal = bundle / "运行依赖文件"
        for name in (
            "customtkinter/assets/themes/blue.json",
            "customtkinter/assets/fonts/CustomTkinter_shapes_font.otf",
            "customtkinter/assets/fonts/Roboto/Roboto-Regular.ttf",
            "customtkinter/assets/fonts/Roboto/Roboto-Medium.ttf",
            "patches/zz_bilingual_ui_patch.rpy", "samples/demo/chinese/chapter_demo.rpy",
            "samples/demo/original/chapter_demo.rpy", "samples/demo/spanish/chapter_demo.rpy",
            "licenses/project/LICENSE", "licenses/Roboto-LICENSE.txt",
            "licenses/Python-LICENSE.txt", "licenses/Tcl-license.terms", "licenses/Tk-license.terms",
            "licenses/unrpyc/LICENSE", "samples/import_demo/original.rpyc.bin",
            "samples/import_demo/translation.rpyc.bin", "samples/import_demo/module.rpymc.bin",
        ):
            assert (internal / name).is_file(), name
        before = snapshot(bundle)
        env = dict(os.environ)
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env["LOCALAPPDATA"] = str(root / "用户 数据")
        for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(key, None)
        result_path = root / "smoke-result.json"
        subprocess.run([str(bundle / "RenPy双语工具.exe"), "--smoke-test", str(result_path)],
                       cwd=root, env=env, check=True, timeout=120)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["ok"] and result["frozen"], result
        assert result["processed_statements"] == 4, result
        assert result["archive_processed"] == 3 and result["unmatched_preserved"] == 1, result
        assert result["module_extension_preserved"] and result["dependencies_preserved"], result
        assert result["archive_install_backup"], result
        assert result["zero_match_blocked"] and result["failure_report"] and result["previous_output_preserved"], result
        assert Path(result["resources"]) == internal, result
        assert before == snapshot(bundle), "The application wrote into its resource directory"
        assert Path(result["data"]).is_relative_to(root / "用户 数据"), result
        print(json.dumps(result, ensure_ascii=False, indent=2))
    print("WINDOWS_PORTABLE_SMOKE_OK")


if __name__ == "__main__":
    main()
