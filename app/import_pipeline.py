"""Read-only import snapshots, explicit translation selection and game-relative output."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable

from app.archive import ImportProblem, MAX_FILE, MAX_FILES, MAX_TOTAL, RpaArchive, safe_relative
from app.decompile import decompile
from app.reporting import save_failure_report
from tools.build_bilingual import (
    BLOCK_HEADER_RE, NON_DIALOGUE_BLOCKS, build, extract_block_spans,
    build_original_statement_data, multiline_string_lines, parse_dialogue_statement, validate_language,
    NoReliableDialogueError,
)


SCRIPTS = {".rpy", ".rpym"}
COMPILED = {".rpyc", ".rpymc"}
IGNORED_DIRS = {"saves", "cache", "renpy_bilingual_backups", ".git", "__pycache__"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def normalize_game(path: Path) -> Path:
    if path.is_file() and path.suffix.lower() == ".exe":
        path = path.parent
    if (path / "game").is_dir():
        path = path / "game"
    if not path.is_dir():
        raise ImportProblem("未找到游戏目录。请选择游戏所在文件夹或其中的 game 文件夹。")
    return path.resolve()


def script_languages(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    continuations, _ = multiline_string_lines(lines)
    languages = set()
    for index, line in enumerate(lines):
        match = BLOCK_HEADER_RE.match(line.rstrip("\n")) if index not in continuations else None
        if match and match["language"] != "None":
            try:
                languages.add(validate_language(match["language"]))
            except ValueError as exc:
                raise ImportProblem(f"汉化语言标识 {match['language']} 不能安全用于 Windows 文件夹。请让作者改用 chinese 等标准标识。") from exc
    return languages


@dataclass
class FileRecord:
    relative: str
    origin: str
    member: str
    stored: Path | None
    recovered: bool = False
    languages: set[str] = field(default_factory=set)

    def provenance(self):
        return {"path": self.relative, "source": self.origin, "member": self.member,
                "recovered": self.recovered}


@dataclass
class Container:
    id: str
    label: str
    external: bool
    files: dict[str, FileRecord] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    id: str
    container: str
    language: str
    paths: tuple[str, ...]
    label: str


@dataclass
class ImportSession:
    work: Path
    game: Path | None
    containers: list[Container]
    candidates: list[Candidate]
    originals: dict
    original_sources: dict
    warnings: list[str]
    demo: bool = False
    game_files: dict = field(default_factory=dict)
    inputs: tuple[Path, ...] = ()

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)


def _loose_files(root: Path):
    count, folded = 0, set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if (name in IGNORED_DIRS or name.startswith(".rbb-")
                    or (Path(directory).name == "tl" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*_backup_", name))):
                dirs.remove(name)
            elif path.is_symlink() or path.resolve() != path.absolute():
                raise ImportProblem(f"输入目录含符号链接或目录联接：{path}。请使用实际文件夹副本。")
        for name in sorted(files):
            path = Path(directory) / name
            if name.endswith(":Zone.Identifier"):
                continue
            if path.is_symlink() or path.resolve() != path.absolute():
                raise ImportProblem(f"输入含符号链接：{path}。请使用实际文件。")
            relative = safe_relative(path.relative_to(root).as_posix())
            if relative.casefold() in folded:
                raise ImportProblem(f"输入存在大小写冲突：{relative}。请先修复文件名。")
            folded.add(relative.casefold())
            size = path.stat().st_size
            count += 1
            if count > MAX_FILES:
                raise ImportProblem("目录文件数量过多。请选择游戏的 game 文件夹或独立汉化包。")
            yield relative, path, size


def import_inputs(game: Path | None, translation: Path | None, workspace: Path,
                  progress: Callable[[str], None] = lambda _: None, *, demo=False) -> ImportSession:
    """All writes are in a unique workspace; input paths are only opened for reading."""
    if game is None and translation is None:
        raise ImportProblem("请先选择游戏文件夹或汉化包。")
    game = normalize_game(game) if game is not None else None
    translation = translation.resolve() if translation is not None else None
    if translation is not None and not translation.exists():
        raise ImportProblem("汉化文件已移动或不存在，请重新选择。")
    for source in (game, translation):
        if source is not None and (source == workspace.resolve() or source in workspace.resolve().parents):
            raise ImportProblem("工作目录不能放在游戏或汉化目录内。请将输入移到单独的文件夹。")
    workspace.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="import-", dir=workspace)).resolve()
    containers, candidates, originals, original_sources, warnings = [], [], {}, {}, []
    total_copied = 0
    game_files = {}

    def add_original(identifier, lines, provenance):
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            return
        statements = [parse_dialogue_statement("    " + line.strip(), i) for i, line in enumerate(lines)]
        if not statements or any(stmt is None for stmt in statements):
            return
        signature = [(s.kind, s.normalized_prefix, s.text) for s in statements]
        if identifier in originals:
            previous = originals[identifier]
            if previous is None or signature != [(s.kind, s.normalized_prefix, s.text) for s in previous]:
                originals[identifier] = None
        else:
            originals[identifier] = statements
        original_sources.setdefault(identifier, []).append(provenance)

    def register(origin: Path, members: list, external: bool, archive=None, prefix=""):
        nonlocal total_copied
        container = Container(f"source-{len(containers) + 1:03d}", origin.name, external)
        containers.append(container)
        raw = work / "sources" / container.id / "raw"
        recovered_root = work / "sources" / container.id / "recovered"
        indexed_from_compiled = set()
        for member, physical, size in members:
            relative = safe_relative(prefix + member)
            suffix = Path(relative).suffix
            if suffix == ".rpa":
                if archive is not None:
                    raise ImportProblem(f"{origin.name} 内含嵌套 RPA，无法确认完整依赖。请提供展开后的标准汉化目录。")
                continue
            if (external and size > MAX_FILE) or (suffix in SCRIPTS | COMPILED and size > 64 * 1024 * 1024):
                raise ImportProblem(f"文件超过 512 MB 导入限制：{relative}。请选择较小的汉化包。")
            should_copy = external or suffix in SCRIPTS | COMPILED
            stored = raw / relative if should_copy else None
            if stored is not None:
                total_copied += size
                if total_copied > MAX_TOTAL:
                    raise ImportProblem("导入内容超过 8 GB。请选择独立汉化包后重试。")
                if archive is not None:
                    archive.copy_entry(member, stored)
                else:
                    stored.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(physical, stored)
            container.files[relative] = FileRecord(relative, str(origin if archive else physical), member, stored)

        # Source files win over adjacent stale compiled files, while valid paired
        # original RPYC slot 2 provides stable IDs lost in decompiled line numbers.
        for relative, record in list(container.files.items()):
            if Path(relative).suffix not in COMPILED:
                continue
            source_relative = relative[:-1]
            paired = container.files.get(source_relative)
            use_ids = not external and paired is not None and paired.stored is not None
            if paired is not None:
                if not use_ids:
                    continue
                if record.stored.stat().st_size < 16:
                    warnings.append(f"{record.member} 的旧编译副本损坏，使用已有源文件。")
                    continue
                source_md5 = hashlib.md5(paired.stored.read_bytes()).digest()
                with record.stored.open("rb") as stream:
                    stream.seek(-16, 2)
                    if stream.read() != source_md5:
                        warnings.append(f"{record.member} 的编译副本已过期，未使用其中的原文标识。")
                        continue
            progress(f"正在恢复脚本：{relative}")
            result = decompile(record.stored, work / "decoder")
            python_source = source_relative[:-4] + "_ren.py" if source_relative.endswith(".rpy") else None
            if python_source in container.files:
                warnings.append(f"{python_source} 优先于编译副本加载，未使用可能过期的编译原文标识。")
            else:
                for item in result["originals"]:
                    add_original(item["id"], item["lines"], record.provenance())
            if paired is not None and result["originals"]:
                indexed_from_compiled.add(source_relative)
            if paired is None:
                recovered = recovered_root / source_relative
                recovered.parent.mkdir(parents=True, exist_ok=True)
                recovered.write_text(result["text"], encoding="utf-8")
                container.files[source_relative] = FileRecord(source_relative, record.origin, record.member, recovered, True)

        language_paths = {}
        for relative, record in container.files.items():
            if Path(relative).suffix not in SCRIPTS:
                continue
            record.languages = script_languages(record.stored)
            script_lines = record.stored.read_text(encoding="utf-8-sig").splitlines(keepends=True)
            for language in record.languages:
                if extract_block_spans(script_lines, relative, language):
                    language_paths.setdefault(language, []).append(relative)
            if not record.recovered and relative not in indexed_from_compiled:
                lines = record.stored.read_text(encoding="utf-8-sig").splitlines(keepends=True)
                translated_lines = set()
                for language in record.languages:
                    for block in extract_block_spans(lines, relative, language):
                        translated_lines.update(range(block.start_index, block.end_index))
                for block in extract_block_spans(lines, relative, "None"):
                    block_lines = lines[block.start_index + 1:block.end_index]
                    add_original(block.block_id, block_lines, record.provenance())
                for stmt in build_original_statement_data(lines):
                    if stmt.line_index in translated_lines:
                        continue
                    explicit = re.search(r"\bid\s+([A-Za-z_][A-Za-z0-9_]*)\b", stmt.suffix)
                    if explicit:
                        add_original(explicit[1], [lines[stmt.line_index]], record.provenance())
        for language, paths in sorted(language_paths.items()):
            identity = f"{container.id}:{language}"
            location = "游戏内脚本" if origin == game else (
                origin.relative_to(game).as_posix() if game is not None and game in origin.parents
                else f"{origin.parent.name}/{origin.name}")
            candidates.append(Candidate(identity, container.id, language, tuple(sorted(paths)),
                                        f"{language} — {location}（{len(paths)} 个脚本，候选 {len(candidates) + 1}）"))

    def scan_root(root: Path, external: bool, prefix=""):
        members = list(_loose_files(root))
        if not external:
            for _, physical, _ in members:
                if physical.suffix in SCRIPTS | COMPILED | {".rpa"} or physical.name.endswith("_ren.py"):
                    stat = physical.stat()
                    game_files[str(physical)] = [stat.st_size, stat.st_mtime_ns]
        loose = [(relative, physical, size) for relative, physical, size in members if physical.suffix != ".rpa"]
        if loose:
            register(root, loose, external, prefix=prefix)
        for relative, physical, _ in members:
            if physical.suffix == ".rpa":
                progress(f"正在读取汉化包：{physical.name}")
                archive = RpaArchive(physical)
                register(physical, [(name, None, entry.size) for name, entry in archive.entries.items()], external, archive)

    try:
        if game is not None:
            progress("正在读取游戏，自动查找原文和汉化")
            scan_root(game, False)
        if translation is not None and translation != game:
            # If the user picked a file already in game, use its existing container
            # instead of manufacturing a second, ambiguous copy.
            already_in_game = game is not None and game in translation.parents
            if translation.is_dir():
                root = translation / "game" if (translation / "game").is_dir() else translation
                prefix = ""
                if root.parent.name == "tl":
                    prefix = f"tl/{validate_language(root.name)}/"
                if not already_in_game:
                    scan_root(root, True, prefix)
            elif translation.suffix == ".rpa":
                if not already_in_game:
                    progress(f"正在读取汉化包：{translation.name}")
                    archive = RpaArchive(translation)
                    register(translation, [(name, None, e.size) for name, e in archive.entries.items()], True, archive)
            elif translation.suffix in SCRIPTS | COMPILED:
                if not already_in_game:
                    prefix = f"tl/{translation.parent.name}/" if translation.parent.parent.name == "tl" else ""
                    register(translation, [(translation.name, translation, translation.stat().st_size)], True, prefix=prefix)
                    warnings.append("本次只选择了单个脚本；字体和其他依赖须已在游戏中。若缺少依赖，请改选完整汉化包或目录。")
            else:
                raise ImportProblem("请选择 .rpa、.rpy、.rpyc、.rpym、.rpymc 文件或汉化文件夹。ZIP 请先解压外层压缩包。")
            if already_in_game:
                requested = str(translation)
                candidates = [c for c in candidates if any(
                    r.origin == requested or (translation.is_dir() and Path(r.origin).is_relative_to(translation))
                    for container in containers if container.id == c.container for r in container.files.values())]
            else:
                external_ids = {container.id for container in containers if container.external}
                candidates = [candidate for candidate in candidates if candidate.container in external_ids]
        if not candidates:
            raise ImportProblem("没有找到可转换的标准对白翻译块（菜单和样式不算对白）。请选择已安装汉化的游戏或完整汉化包；直接替换式、加密或非标准补丁暂不支持。")
        progress("读取完成，正在检查汉化和语言候选")
        for filename, expected in game_files.items():
            stat = Path(filename).stat()
            if [stat.st_size, stat.st_mtime_ns] != expected:
                raise ImportProblem("游戏文件在读取期间发生变化，请关闭游戏后重新检查。")
        return ImportSession(work, game, containers, candidates, originals, original_sources, warnings,
                             demo, game_files, tuple(p for p in (game, translation) if p is not None))
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def build_imported(session: ImportSession, candidate_id: str, output: Path, report: Path,
                   progress: Callable[[str], None] = lambda _: None) -> dict:
    candidate = next((candidate for candidate in session.candidates if candidate.id == candidate_id), None)
    if candidate is None:
        raise ImportProblem("请选择要处理的汉化和语言，再点击“检查并生成双语”。")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ImportProblem("输出必须是独立的文件夹，不能选择文件或目录链接。")
    if report.is_symlink() or report.with_suffix(".csv").is_symlink():
        raise ImportProblem("报告不能使用符号链接，请选择新的报告文件。")
    output, report = output.resolve(), report.resolve()
    for source in (*session.inputs, session.game, session.work):
        if source is not None and (output.resolve() == source or source in output.resolve().parents or output.resolve() in source.parents):
            raise ImportProblem("输出不能覆盖游戏、汉化输入或导入工作目录。请选择单独的输出文件夹。")
        for destination in (report, report.with_suffix(".csv")):
            if source is not None and (destination == source or source in destination.parents):
                raise ImportProblem("报告不能写入游戏或汉化输入目录。请选择独立报告位置。")
    if (report.suffix != ".json" or output == report or output in report.parents or report in output.parents
            or report.is_symlink() or (report.exists() and not report.is_file())):
        raise ImportProblem("请将 JSON 报告保存在双语输出文件夹之外。")
    chosen = next(c for c in session.containers if c.id == candidate.container)
    for relative in candidate.paths:
        python_source = relative[:-4] + "_ren.py" if relative.endswith(".rpy") else None
        if python_source and any(python_source in c.files for c in session.containers):
            raise ImportProblem(f"游戏会优先加载 {python_source}，本版不能安全替换这类翻译。请向作者获取标准 .rpy 翻译包。")
    prepared = session.work / "prepared"
    shutil.rmtree(prepared, ignore_errors=True)
    prepared.mkdir()
    selected, folded = {}, {}
    candidate_containers = {c.container for c in session.candidates}
    for container in session.containers:
        for relative, record in container.files.items():
            source_suffix = Path(relative).suffix
            if source_suffix in COMPILED and relative[:-1] in container.files:
                continue
            include = False
            if chosen.external:
                include = container.external and (container.id == chosen.id or container.id not in candidate_containers)
            else:
                include = container.id == chosen.id and (
                    relative in candidate.paths or relative.startswith(f"tl/{candidate.language}/"))
            if not include:
                continue
            if Path(relative).suffix.lower() in (".exe", ".rpa", ".rpi"):
                raise ImportProblem(f"汉化目录包含安装程序或不支持的归档：{relative}。请改选其中的 game 内容或标准 RPA 汉化包。")
            if record.stored is None:
                # Resident game assets remain at their original path; do not relocate them.
                continue
            key = relative.casefold()
            if key in folded:
                previous = selected[folded[key]]
                if relative != folded[key] or digest(previous.stored) != digest(record.stored):
                    raise ImportProblem(f"多个来源对 {relative} 提供了不同文件。请只选择一个完整汉化包，避免覆盖错误版本。")
                continue
            folded[key] = relative
            selected[relative] = record
            target = prepared / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record.stored, target)
    # Different files defining the same language + ID would conflict in Ren'Py.
    identifiers = {}
    for relative, record in selected.items():
        if Path(relative).suffix not in SCRIPTS:
            continue
        lines = record.stored.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        for block in extract_block_spans(lines, relative, candidate.language):
            if block.block_id in identifiers:
                raise ImportProblem(f"翻译标识重复：{block.block_id}（{identifiers[block.block_id]}、{relative}）。请换用单一版本的汉化。")
            identifiers[block.block_id] = relative
    for container in session.containers:
        if container.external:
            continue
        for relative, record in container.files.items():
            if Path(relative).suffix not in SCRIPTS:
                continue
            if relative in selected and candidate.language in selected[relative].languages and not record.languages:
                # A flat translated script called script.rpy must not replace the
                # original story script with the same name.
                raise ImportProblem(f"汉化中的 {relative} 会覆盖同名原文脚本。请使用保留 tl/语言/ 目录结构的汉化包。")
            if candidate.language not in record.languages or relative in selected:
                continue
            lines = record.stored.read_text(encoding="utf-8-sig").splitlines(keepends=True)
            for block in extract_block_spans(lines, relative, candidate.language):
                if block.block_id in identifiers:
                    raise ImportProblem(f"游戏中另一份汉化 {relative} 使用相同标识 {block.block_id}。请在原版游戏副本上仅安装所选汉化，避免两份翻译同时加载。")
    manifest = {
        "version": 1, "language": candidate.language, "candidate": candidate.label,
        "game": str(session.game) if session.game else None, "demo": session.demo,
        "warnings": session.warnings,
        "files": [record.provenance() for record in selected.values()],
        "original_identifiers": session.original_sources,
        "matching": "translation_identifier_or_source_comment; no_line_fallback",
        "resident_resources": [dict(source=container.label, files=len(container.files))
                               for container in session.containers if not container.external],
    }
    progress("正在匹配原文并生成双语；无法可靠配对的对白将保留译文")
    # Build inside a private transaction before publishing the package and plan together.
    stage = session.work / "package-stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    internal_report = stage / "build-report.json"
    try:
        summary = build(prepared, dst=stage / "game", report_path=internal_report,
                        csv_path=stage / "diagnostics.csv", language=candidate.language,
                        original_index=session.originals, allow_line_fallback=False,
                        input_manifest=manifest, require_changes=True, progress=progress)
    except NoReliableDialogueError as exc:
        save_failure_report(exc, report, output)
        raise
    summary["destination"] = str(output.resolve())
    summary["diagnostics_csv"] = str(report.with_suffix(".csv").resolve())
    summary["package"] = True
    for item in summary["diagnostics"]:
        item["source"] = selected[item["file"]].origin
        item["member"] = selected[item["file"]].member
    plan = {"version": 1, "language": candidate.language, "demo": session.demo,
            "game": str(session.game) if session.game else None,
            "game_files": session.game_files,
            "needs_review": summary["needs_review"],
            "files": {p.relative_to(stage / "game").as_posix(): digest(p) for p in (stage / "game").rglob("*") if p.is_file()}}
    (stage / "install-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (stage / "provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    internal_report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # Reuse the existing recoverable output/report commit on the destination volume.
    from tools.build_bilingual import _commit_build, BuildRecoveryError
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    publish = Path(tempfile.mkdtemp(prefix=".rbb-build-", dir=output.parent))
    preserve = False
    try:
        shutil.copytree(stage, publish / "new")
        _commit_build(publish, output, {report.resolve(): json.dumps(summary, ensure_ascii=False, indent=2),
                                      report.with_suffix(".csv").resolve(): (stage / "diagnostics.csv").read_text(encoding="utf-8")})
    except BuildRecoveryError:
        preserve = True
        raise
    finally:
        if not preserve and not (publish / "previous-output").exists():
            shutil.rmtree(publish, ignore_errors=True)
    return summary
