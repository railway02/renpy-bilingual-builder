"""Optional engine test, exclusively using this repository's original fixtures."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_import_pipeline import rpa, FIXTURES
from app.import_pipeline import import_inputs, build_imported
from app.package_deployment import deploy_package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--renpy", required=True, type=Path, help="SDK renpy.sh or renpy.exe")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rbb-engine-import-") as directory:
        root = Path(directory)
        game = root / "project/game"
        game.mkdir(parents=True)
        original_archive = game / "original.rpa"
        rpa(original_archive, {"script.rpyc": (FIXTURES / "original.rpyc.bin").read_bytes(),
                               "extras/optional.rpymc": (FIXTURES / "module.rpymc.bin").read_bytes()})
        archive_bytes = original_archive.read_bytes()
        package = root / "patch.rpa"
        rpa(package, {"tl/chinese/different.rpyc": (FIXTURES / "translation.rpyc.bin").read_bytes(),
                      "extras/optional.rpymc": (FIXTURES / "module.rpymc.bin").read_bytes()})
        session = import_inputs(game, package, root / "work")
        build_imported(session, session.candidates[0].id, root / "out", root / "report.json")
        deploy_package(root / "out", game)
        assert original_archive.read_bytes() == archive_bytes
        shutil.copy2(ROOT / "tests/renpy_import/game/verify.rpy", game / "zz_verify.rpy")
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        completed = subprocess.run([str(args.renpy.resolve()), str(game.parent), "rbb_import_check"],
                                   env=env, timeout=120, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode or "RBB_IMPORTED_RPA_MODULE_OK" not in completed.stdout:
            raise RuntimeError(completed.stdout + completed.stderr)
        print(completed.stdout.strip())


if __name__ == "__main__":
    main()
