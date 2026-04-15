#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple




# 例：

#   # mc "What the hell are you doing?"
#   # "I shouldn't have come here."
COMMENT_SAY_RE = re.compile(
    r'^(?P<indent>[ \t]*)#\s*(?P<prefix>[^"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)

# 例：
#   mc "你在搞什么鬼？"
#   "我就不该来这里。"
SAY_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>[^#"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)

STRINGS_BLOCK_RE = re.compile(
    r'^(?P<indent>[ \t]*)translate\s+\w+\s+strings\s*:\s*$'
)

OLD_RE = re.compile(
    r'^(?P<indent>[ \t]*)old\s+"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)

NEW_RE = re.compile(
    r'^(?P<indent>[ \t]*)new\s+"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)


@dataclass
class FileStats:
    file: str
    processed_dialogue_pairs: int = 0
    processed_string_pairs: int = 0
    skipped_already_bilingual: int = 0
    skipped_prefix_mismatch: int = 0
    skipped_indent_mismatch: int = 0
    suspicious_orphan_comment: int = 0
    long_bilingual_lines: int = 0


def normalize_prefix(prefix: str) -> str:
    return re.sub(r"\s+", " ", prefix.strip())


def build_bilingual_text(english: str, chinese: str) -> str:
    return f"{english}\\n{chinese}"

def is_already_bilingual(text: str) -> bool:
    return "\\n" in text


def should_process_strings_file(path: Path, allowlist: List[str]) -> bool:
    path_str = str(path).replace("\\", "/").lower()

    # 绝对不要碰的系统/UI文件
    black_list = [
        "screens.rpy",
        "options.rpy",
        "gui.rpy",
        "common.rpy",
        "style.rpy",
        "save_name.rpy",
    ]

    if any(skip in path_str for skip in black_list):
        return False

    # 如果你传了 allowlist，就只处理 allowlist 命中的文件
    if allowlist:
        return any(pattern.lower() in path_str for pattern in allowlist)

    # 默认：只要不是黑名单，就允许处理 strings
    return True

def process_lines(
    lines: List[str],
    file_path: Path,
    include_strings: bool,
    strings_allowlist: List[str],
) -> Tuple[List[str], FileStats]:
    stats = FileStats(file=str(file_path).replace("\\", "/"))
    out: List[str] = []
    i = 0
    in_strings_block = False
    allow_strings_here = include_strings and should_process_strings_file(file_path, strings_allowlist)

    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n")

        # 进入/退出 strings block
        if STRINGS_BLOCK_RE.match(stripped):
            in_strings_block = True
            out.append(line)
            i += 1
            continue

        # 如果进入了 translate block，遇到更外层/同层其它 translate，可以视为可能切换了上下文
        if in_strings_block and re.match(r'^[ \t]*translate\s+\w+\s+\w+', stripped) and not STRINGS_BLOCK_RE.match(stripped):
            in_strings_block = False

        # 1) 处理对白翻译块：注释英文 + 下一行中文对白
        comment_match = COMMENT_SAY_RE.match(stripped)
        if comment_match and i + 1 < len(lines):
            next_line = lines[i + 1]
            next_stripped = next_line.rstrip("\n")
            say_match = SAY_RE.match(next_stripped)

            if say_match:
                indent_a = comment_match.group("indent")
                indent_b = say_match.group("indent")
                prefix_a = comment_match.group("prefix")
                prefix_b = say_match.group("prefix")
                eng = comment_match.group("text")
                cn = say_match.group("text")

                if is_already_bilingual(cn):
                    stats.skipped_already_bilingual += 1
                    out.append(line)
                    out.append(next_line)
                    i += 2
                    continue

                if indent_a != indent_b:
                    stats.skipped_indent_mismatch += 1
                    out.append(line)
                    out.append(next_line)
                    i += 2
                    continue

                if normalize_prefix(prefix_a) != normalize_prefix(prefix_b):
                    stats.skipped_prefix_mismatch += 1
                    out.append(line)
                    out.append(next_line)
                    i += 2
                    continue

                bilingual = build_bilingual_text(eng, cn)
                new_line = f'{indent_b}{prefix_b}"{bilingual}"\n'

                if len(new_line) > 180:
                    stats.long_bilingual_lines += 1

                out.append(line)
                out.append(new_line)
                stats.processed_dialogue_pairs += 1
                i += 2
                continue
            else:
                stats.suspicious_orphan_comment += 1

        # 2) 可选处理 strings block：old/new
        if in_strings_block and allow_strings_here:
            old_match = OLD_RE.match(stripped)
            if old_match and i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.rstrip("\n")
                new_match = NEW_RE.match(next_stripped)

                if new_match:
                    indent_old = old_match.group("indent")
                    indent_new = new_match.group("indent")
                    eng = old_match.group("text")
                    cn = new_match.group("text")

                    if is_already_bilingual(cn):
                        stats.skipped_already_bilingual += 1
                        out.append(line)
                        out.append(next_line)
                        i += 2
                        continue

                    if indent_old != indent_new:
                        out.append(line)
                        out.append(next_line)
                        i += 2
                        continue

                    bilingual = build_bilingual_text(eng, cn)
                    new_line = f'{indent_new}new "{bilingual}"\n'

                    if len(new_line) > 180:
                        stats.long_bilingual_lines += 1

                    out.append(line)
                    out.append(new_line)
                    stats.processed_string_pairs += 1
                    i += 2
                    continue

        # 默认透传
        out.append(line)
        i += 1

    return out, stats


def collect_rpy_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*.rpy") if p.is_file()])


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def build(
    src: Path,
    dst: Path,
    include_strings: bool,
    strings_allowlist: List[str],
    dry_run: bool,
    report_path: Path | None,
) -> Dict:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src}")

    if dst.exists() and not dry_run:
        shutil.rmtree(dst)

    if not dry_run:
        shutil.copytree(src, dst)

    rpy_files = collect_rpy_files(src)
    all_stats: List[FileStats] = []

    for src_file in rpy_files:
        rel = src_file.relative_to(src)
        dst_file = dst / rel
        text = src_file.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)

        new_lines, stats = process_lines(
            lines=lines,
            file_path=rel,
            include_strings=include_strings,
            strings_allowlist=strings_allowlist,
        )
        all_stats.append(stats)

        if not dry_run:
            write_text(dst_file, "".join(new_lines))

    summary = {
        "source": str(src),
        "destination": str(dst),
        "dry_run": dry_run,
        "include_strings": include_strings,
        "strings_allowlist": strings_allowlist,
        "files_processed": len(all_stats),
        "totals": {
            "processed_dialogue_pairs": sum(s.processed_dialogue_pairs for s in all_stats),
            "processed_string_pairs": sum(s.processed_string_pairs for s in all_stats),
            "skipped_already_bilingual": sum(s.skipped_already_bilingual for s in all_stats),
            "skipped_prefix_mismatch": sum(s.skipped_prefix_mismatch for s in all_stats),
            "skipped_indent_mismatch": sum(s.skipped_indent_mismatch for s in all_stats),
            "suspicious_orphan_comment": sum(s.suspicious_orphan_comment for s in all_stats),
            "long_bilingual_lines": sum(s.long_bilingual_lines for s in all_stats),
        },
        "files": [asdict(s) for s in all_stats],
    }

    if report_path is not None and not dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a bilingual Ren'Py translation pack from a Chinese tl folder."
    )
    parser.add_argument(
        "--src",
        required=True,
        help="Source tl/chinese directory",
    )
    parser.add_argument(
        "--dst",
        required=True,
        help="Output directory for generated tl/chinese",
    )
    parser.add_argument(
        "--include-strings",
        action="store_true",
        help="Also process translate ... strings blocks (not recommended for v1).",
    )
    parser.add_argument(
        "--strings-allowlist",
        nargs="*",
        default=[],
        help="Only process strings in files whose relative path contains one of these substrings.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report only, do not write output.",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Optional path to write JSON report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    report_path = Path(args.report_json).resolve() if args.report_json else None

    summary = build(
        src=src,
        dst=dst,
        include_strings=args.include_strings,
        strings_allowlist=args.strings_allowlist,
        dry_run=args.dry_run,
        report_path=report_path,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()