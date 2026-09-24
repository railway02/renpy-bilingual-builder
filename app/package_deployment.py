"""Transactional installation of an imported game-relative overlay; RPA stays intact."""

from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile

from app.archive import ImportProblem, safe_relative
from app.deployment import _check_destination, check_generic_profile, validate_game_directory
from app.import_pipeline import digest, _loose_files, SCRIPTS, COMPILED
from tools.build_bilingual import validate_language


def read_plan(output: Path) -> dict:
    try:
        plan = json.loads((output / "install-plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportProblem("安装清单缺失或损坏，请重新检查并生成双语。") from exc
    if (not isinstance(plan, dict) or plan.get("version") != 1
            or not isinstance(plan.get("files"), dict) or not plan["files"]
            or type(plan.get("demo")) is not bool):
        raise ImportProblem("安装清单无效，请重新生成。")
    validate_language(plan.get("language"))
    if plan["demo"]:
        raise ImportProblem("内置示例不能安装到真实游戏。请选择自己的游戏或汉化包后重新生成。")
    seen = set()
    for relative, expected in plan["files"].items():
        safe_relative(relative)
        if relative.casefold() in seen or Path(relative).suffix in (".rpa", ".rpi", ".exe"):
            raise ImportProblem(f"安装清单含冲突或不允许写入的文件：{relative}。请重新选择标准汉化包。")
        seen.add(relative.casefold())
        source = output / "game" / relative
        if source.resolve() != source.absolute() or not source.is_file() or digest(source) != expected:
            raise ImportProblem(f"输出文件已改变或缺失：{relative}。请重新生成，避免安装不完整的文件。")
    actual = {p.relative_to(output / "game").as_posix() for p in (output / "game").rglob("*") if p.is_file()}
    if actual != set(plan["files"]):
        raise ImportProblem("输出目录包含清单外文件，请重新生成后安装。")
    if not any(Path(relative).suffix in (".rpy", ".rpym") for relative in plan["files"]):
        raise ImportProblem("没有可安装的双语源脚本，请重新生成。")
    return plan


def deploy_package(output: Path, game: Path, patch: Path | None = None) -> Path:
    output, game = output.resolve(), game.resolve()
    plan = read_plan(output)
    validate_game_directory(game)
    if game == output or game in output.parents or output in game.parents:
        raise ImportProblem("输出目录必须与游戏目录分开，请更换输出位置后重新生成。")
    if plan.get("game") is None or Path(plan["game"]).resolve() != game:
        raise ImportProblem("本次输出未针对这个游戏检查。请先选择该游戏，再重新检查并生成双语。")
    for filename, expected in plan.get("game_files", {}).items():
        path = Path(filename)
        if not path.is_file() or not path.is_relative_to(game):
            raise ImportProblem("游戏文件已移动或改变，请重新检查并生成双语。")
        stat = path.stat()
        if [stat.st_size, stat.st_mtime_ns] != expected:
            raise ImportProblem("游戏文件已改变，请重新检查并生成双语后再安装。")
    current_scripts = {str(path) for _, path, _ in _loose_files(game)
                       if path.suffix in SCRIPTS | COMPILED | {".rpa"} or path.name.endswith("_ren.py")}
    if current_scripts != set(plan.get("game_files", {})):
        raise ImportProblem("游戏内新增或移除了脚本/汉化包，请重新检查并生成双语后再安装。")
    if patch is None:
        check_generic_profile(game)
    elif plan["language"] != "chinese" or not patch.is_file():
        raise ImportProblem("永恒世界专用排版仅适用于 chinese，请检查配置和补丁文件。")
    files = {relative: output / "game" / relative for relative in plan["files"]}
    if patch is not None:
        if patch.name in files and digest(files[patch.name]) != digest(patch):
            raise ImportProblem("汉化包含另一份同名显示补丁，请确认版本后再安装。")
        files[patch.name] = patch
    targets = set(files)
    for relative in files:
        if Path(relative).suffix in (".rpy", ".rpym"):
            targets.add(relative + "c")
    for relative in targets:
        target = game / relative
        _check_destination(target, directory=False)
        for parent in target.parents:
            if parent == game:
                break
            _check_destination(parent, directory=True)
    backup_root = game.parent / "renpy_bilingual_backups"
    _check_destination(backup_root, directory=True)
    legacy = sorted((game / "tl").glob(f"{plan['language']}_backup_*"))
    for path in legacy:
        _check_destination(path, directory=True)
    moved, installed, created_dirs = [], [], []
    with tempfile.TemporaryDirectory(prefix=".rbb-deploy-", dir=game.parent) as temp:
        stage = Path(temp)
        for relative, source in files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # All copying must succeed before game files or backup history change.
        backup_root.mkdir(exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d_%H%M%S_"), dir=backup_root))
        before = {relative: (game / relative).is_file() for relative in sorted(targets)}
        recovery = {"version": 1, "game": str(game), "original_files": before,
                    "installed": sorted(files), "legacy": [str(p.relative_to(game)) for p in legacy]}
        (backup / "restore-manifest.json").write_text(json.dumps(recovery, ensure_ascii=False, indent=2), encoding="utf-8")
        (backup / "恢复说明.txt").write_text(
            "关闭游戏后恢复：\n1. 删除 restore-manifest.json 的 installed 文件及对应 .rpyc/.rpymc。\n"
            "2. 将 original 文件夹内容按相对路径复制回 game，覆盖对应文件。\n"
            "原 RPA 从未修改；原来没有松散文件的路径，删除新文件后会重新使用 RPA 内文件。\n"
            "legacy 中是旧工具留在 game 内的历史备份，不应放回 game 中执行。\n", encoding="utf-8-sig")
        try:
            for relative in sorted(targets):
                target = game / relative
                if target.exists():
                    saved = backup / "original" / relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    moved.append((target, saved))
                    target.replace(saved)
            for target in legacy:
                saved = backup / "legacy" / target.name
                saved.parent.mkdir(exist_ok=True)
                moved.append((target, saved))
                target.replace(saved)
            for relative in sorted(files):
                target = game / relative
                missing = []
                parent = target.parent
                while not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                for directory in reversed(missing):
                    directory.mkdir()
                    created_dirs.append(directory)
                installed.append(target)
                (stage / relative).replace(target)
        except BaseException as error:
            failures = []
            for path in reversed(installed):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    failures.append(f"无法移除 {path}: {exc}")
            for target, saved in reversed(moved):
                try:
                    if not saved.exists():
                        continue  # The failing rename did not move the original.
                    if target.exists():
                        raise FileExistsError(str(target))
                    saved.replace(target)
                except OSError as exc:
                    failures.append(f"无法恢复 {target}: {exc}")
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass  # Never remove a directory now containing other files.
            if failures:
                raise RuntimeError(f"安装失败，自动恢复未完成。请关闭游戏并从 {backup} 恢复原文件。\n" + "\n".join(failures)) from error
            raise
    return backup
