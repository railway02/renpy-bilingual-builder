"""Exercise source launchers in disposable projects without starting a Tk window."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == "nt"
LAUNCHER = "start_windows.bat" if WINDOWS else "start.sh"


def prepare(project):
    (project / "app").mkdir(parents=True)
    shutil.copy2(ROOT / LAUNCHER, project / LAUNCHER)
    (project / "requirements.txt").write_text("", encoding="utf-8")
    (project / "app" / "gui.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path('launcher-result.json').write_text(json.dumps({"
        "'cwd': str(Path.cwd()), 'prefix': sys.prefix, "
        "'version': list(sys.version_info[:2])}), encoding='utf-8')\n",
        encoding="utf-8",
    )


def run(project, *, success=True, extra_env=None):
    result_path = project / "launcher-result.json"
    result_path.unlink(missing_ok=True)
    command = (
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", LAUNCHER]
        if WINDOWS else [shutil.which("sh") or "/bin/sh", LAUNCHER]
    )
    env = dict(os.environ, PYTHONUTF8="1", PIP_NO_INDEX="1")
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        command, cwd=project, input="\n", stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        timeout=180, env=env,
    )
    if (completed.returncode == 0) != success:
        raise AssertionError(f"Unexpected exit {completed.returncode}:\n{completed.stdout}")
    if success:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert Path(result["cwd"]).resolve() == project.resolve(), result
        assert Path(result["prefix"]).resolve() == (project / ".venv").resolve(), result
        assert tuple(result["version"]) >= (3, 10), result
    else:
        assert not result_path.exists(), completed.stdout
    return completed.stdout


def main():
    with tempfile.TemporaryDirectory(prefix="rbb-launcher-") as temporary:
        root = Path(temporary)
        # Spaces and punctuation catch quoting mistakes in shell and batch files.
        project = root / "source project (test)"
        prepare(project)
        run(project)
        assert (project / ".venv" / "pyvenv.cfg").is_file()
        run(project)
        assert not list(project.glob(".venv.backup-*"))

        (project / ".venv" / "preserve-me.txt").write_text("old environment", encoding="utf-8")
        interpreter = project / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
        interpreter.unlink()
        run(project)
        backups = list(project.glob(".venv.backup-*/preserve-me.txt"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "old environment"

        (project / "requirements.txt").write_text("-r missing-requirements.txt\n", encoding="utf-8")
        run(project, success=False)
        (project / "requirements.txt").write_text("", encoding="utf-8")
        (project / "app" / "gui.py").write_text("raise RuntimeError('synthetic GUI failure')\n", encoding="utf-8")
        assert "synthetic GUI failure" in run(project, success=False)

        invalid = root / "non-venv directory"
        prepare(invalid)
        (invalid / ".venv").mkdir()
        sentinel = invalid / ".venv" / "user-file.txt"
        sentinel.write_text("keep", encoding="utf-8")
        run(invalid, success=False)
        assert sentinel.read_text(encoding="utf-8") == "keep"
        assert not list(invalid.glob(".venv.backup-*"))

        missing = root / "missing runtime"
        prepare(missing)
        empty_path = root / "limited-path"
        empty_path.mkdir()
        if not WINDOWS:
            # dirname is needed to find the project before Python discovery.
            (empty_path / "dirname").symlink_to(shutil.which("dirname"))
        assert "3.10" in run(missing, success=False, extra_env={"PATH": str(empty_path)})
        assert not (missing / ".venv").exists()

    print(f"LAUNCHER_SMOKE_OK ({LAUNCHER})")


if __name__ == "__main__":
    main()
