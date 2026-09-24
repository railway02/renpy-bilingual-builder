"""Deploy without leaving executable translation backups inside game/."""

from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile


def _check_destination(path: Path, *, directory: bool):
    # resolve() also detects Windows junctions, which is_symlink() may miss.
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"部署目标不能是符号链接或目录联接：{path}")
    if path.exists() and not (path.is_dir() if directory else path.is_file()):
        kind = "目录" if directory else "文件"
        raise ValueError(f"部署目标必须是{kind}：{path}")


def _has_source(output_dir: Path):
    for source in output_dir.rglob("*"):
        if source.suffix not in (".rpy", ".rpym"):
            continue
        if source.is_file():
            with source.open("rb") as stream:
                if any(line.strip() for line in stream):
                    return True
    return False


OWNED_UI_PATCH = "zz_bilingual_ui_patch.rpy"


def validate_game_directory(game_dir: Path):
    """Accept a game directory, but reject arbitrary folders selected by mistake."""
    if not game_dir.is_dir():
        raise NotADirectoryError(f"游戏 game 目录不存在：{game_dir}")
    if game_dir.name.lower() != "game" and not (
        (game_dir / "tl").is_dir()
        or any(game_dir.glob("*.rpy"))
        or any(game_dir.glob("*.rpa"))
        or any(game_dir.glob("*.rpyc"))
    ):
        raise ValueError("未识别到 Ren'Py 游戏目录。请选择游戏根目录内的 game 文件夹。")


def check_generic_profile(game_dir: Path):
    """Never silently leave an Eternum-specific runtime patch in generic mode."""
    installed = [game_dir / OWNED_UI_PATCH, game_dir / Path(OWNED_UI_PATCH).with_suffix(".rpyc")]
    if any(path.exists() or path.is_symlink() for path in installed):
        raise ValueError(
            "检测到旧版永恒世界 UI 补丁。通用模式不会修改游戏界面；"
            "请先将 game/zz_bilingual_ui_patch.rpy 和同名 .rpyc 移到 game 目录外备份，"
            "或选择“永恒世界 0.9.5”配置后重新构建。"
        )


def deploy_to_game(output_dir: Path, game_dir: Path, patch_file: Path | None = None, *, language: str = "chinese"):
    # The language becomes a directory name. Keep this check at the write boundary,
    # including callers that bypass the GUI and builder.
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", language) or language == "None" or language.lower() in {
        "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }:
        raise ValueError(f"无效的翻译语言标识：{language!r}")
    output_dir, game_dir = output_dir.resolve(), game_dir.resolve()
    if output_dir == game_dir or game_dir in output_dir.parents or output_dir in game_dir.parents:
        raise ValueError("输出目录不能位于游戏目录内，也不能包含游戏目录。")
    if not output_dir.is_dir() or (patch_file is not None and not patch_file.is_file()):
        raise FileNotFoundError("双语输出目录或 UI 补丁不存在。")
    validate_game_directory(game_dir)
    if patch_file is None:
        check_generic_profile(game_dir)
    elif patch_file.name == OWNED_UI_PATCH and language != "chinese":
        raise ValueError("永恒世界 UI 补丁只适用于 chinese 翻译，请改用通用模式。")
    if not _has_source(output_dir):
        raise ValueError("双语输出目录中没有非空的 .rpy/.rpym 源文件，请先完成构建。")

    target_tl = game_dir / "tl" / language
    target_patch = game_dir / patch_file.name if patch_file is not None else None
    # Ren'Py recursively loads scripts under game/, regardless of folder name.
    backup_root = game_dir.parent / "renpy_bilingual_backups"
    _check_destination(target_tl.parent, directory=True)
    _check_destination(target_tl, directory=True)
    if target_patch is not None:
        _check_destination(target_patch, directory=False)
        _check_destination(target_patch.with_suffix(".rpyc"), directory=False)
    _check_destination(backup_root, directory=True)
    # Also relocate backups made by older versions of the GUI.
    legacy_paths = sorted(target_tl.parent.glob(f"{language}_backup_*"))
    for legacy in legacy_paths:
        _check_destination(legacy, directory=True)
    old_paths = legacy_paths + [target_tl]
    if target_patch is not None:
        old_paths.extend([target_patch, target_patch.with_suffix(".rpyc")])
    moved = []
    installed = []
    backup_tl = None
    with tempfile.TemporaryDirectory(prefix=".rbb-deploy-", dir=game_dir.parent) as temp:
        stage = Path(temp)
        def ignore_compiled(directory, names):
            return [name for name in names if name.endswith(":Zone.Identifier") or
                    (name.endswith((".rpyc", ".rpymc")) and name[:-1] in names)]
        shutil.copytree(output_dir, stage / language, ignore=ignore_compiled)
        if patch_file is not None:
            shutil.copy2(patch_file, stage / patch_file.name)
        # A failed copy must leave both the installation and backup history alone.
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(
            prefix=datetime.now().strftime("%Y%m%d_%H%M%S_"), dir=backup_root))
        target_tl.parent.mkdir(parents=True, exist_ok=True)
        try:
            for old in old_paths:
                if old.exists():
                    saved = backup_dir / old.name
                    shutil.move(str(old), str(saved))
                    moved.append((old, saved))
                    if old == target_tl:
                        backup_tl = saved
            installed.append(target_tl)
            shutil.move(str(stage / language), str(target_tl))
            if target_patch is not None:
                installed.append(target_patch)
                shutil.move(str(stage / patch_file.name), str(target_patch))
        except Exception as install_error:
            recovery_errors = []
            for path in reversed(installed):
                try:
                    if path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
                except OSError as error:
                    recovery_errors.append(f"无法清理 {path}: {error}")
            for old, saved in reversed(moved):
                try:
                    # Never merge a saved directory into a partial installation.
                    if old.exists() or old.is_symlink():
                        raise FileExistsError(f"目标仍然存在：{old}")
                    shutil.move(str(saved), str(old))
                except OSError as error:
                    recovery_errors.append(f"无法恢复 {old}: {error}")
            if recovery_errors:
                raise RuntimeError(
                    f"部署失败（{install_error}），部分文件未能自动恢复。"
                    f"剩余原文件保存在：{backup_dir}\n" + "\n".join(recovery_errors)
                ) from install_error
            raise
    return target_tl, target_patch, backup_tl
