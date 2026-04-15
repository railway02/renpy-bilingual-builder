#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# Only these dialogue files are processed for v2.
TARGET_FILE_NAMES = {
    "script.rpy",
    "script2.rpy",
    "script3.rpy",
    "script4.rpy",
    "script5.rpy",
    "script6.rpy",
    "script7.rpy",
    "script8.rpy",
    "script9.rpy",
    "gallery_replay.rpy",
}

# translate chinese xxx:
BLOCK_HEADER_RE = re.compile(
    r"^(?P<indent>[ \t]*)translate\s+chinese\s+(?P<block_id>[A-Za-z0-9_]+)\s*:\s*$"
)

# translate chinese strings:
STRINGS_HEADER_RE = re.compile(r"^[ \t]*translate\s+chinese\s+strings\s*:\s*$")

# Any translate header used as a safe boundary while scanning blocks.
ANY_TRANSLATE_HEADER_RE = re.compile(r"^[ \t]*translate\s+\w+\s+\w+\s*:\s*$")

# # mc "English"
COMMENT_QUOTED_RE = re.compile(
    r'^(?P<indent>[ \t]*)#\s*(?P<prefix>[^"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)

# mc "中文" / "中文" / extend "中文" / centered "中文"
QUOTED_STATEMENT_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>[^#"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"\s*$'
)

SPEAKER_PREFIX_RE = re.compile(r"^[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*$")


@dataclass
class Statement:
    line_index: int
    indent: str
    raw_prefix: str
    normalized_prefix: str
    kind: str
    text: str


@dataclass
class BlockStats:
    has_dialogue_candidates: bool = False
    processed_statements: int = 0
    unmatched_statements: int = 0
    skipped_already_bilingual: int = 0


@dataclass
class FileStats:
    file: str
    target_file: bool
    blocks_total: int = 0
    processed_blocks: int = 0
    processed_statements: int = 0
    unmatched_blocks: int = 0
    unmatched_statements: int = 0
    skipped_already_bilingual: int = 0


def normalize_prefix(prefix: str) -> str:
    return re.sub(r"\s+", " ", prefix.strip())


def is_target_dialogue_file(path: Path) -> bool:
    return path.name.lower() in TARGET_FILE_NAMES


def is_already_bilingual(text: str) -> bool:
    return "\\n" in text


def build_bilingual_text(english: str, chinese: str) -> str:
    return f"{english}\\n{chinese}"


def classify_prefix(prefix: str) -> Tuple[Optional[str], str]:
    normalized = normalize_prefix(prefix)

    if normalized == "":
        return "narrator", ""
    if normalized == "extend":
        return "extend", ""
    if normalized == "centered":
        return "centered", ""

    if SPEAKER_PREFIX_RE.match(normalized):
        return "say", normalized

    return None, normalized


def parse_english_comment(line: str, idx: int) -> Optional[Statement]:
    match = COMMENT_QUOTED_RE.match(line)
    if not match:
        return None

    kind, normalized_prefix = classify_prefix(match.group("prefix"))
    if kind is None:
        return None

    return Statement(
        line_index=idx,
        indent=match.group("indent"),
        raw_prefix=match.group("prefix"),
        normalized_prefix=normalized_prefix,
        kind=kind,
        text=match.group("text"),
    )


def parse_chinese_statement(line: str, idx: int) -> Optional[Statement]:
    if line.lstrip().startswith("#"):
        return None

    match = QUOTED_STATEMENT_RE.match(line)
    if not match:
        return None

    kind, normalized_prefix = classify_prefix(match.group("prefix"))
    if kind is None:
        return None

    return Statement(
        line_index=idx,
        indent=match.group("indent"),
        raw_prefix=match.group("prefix"),
        normalized_prefix=normalized_prefix,
        kind=kind,
        text=match.group("text"),
    )


def is_compatible(english_stmt: Statement, chinese_stmt: Statement) -> bool:
    if english_stmt.kind != chinese_stmt.kind:
        return False

    if english_stmt.kind == "say":
        return english_stmt.normalized_prefix == chinese_stmt.normalized_prefix

    return True


def align_block_statements(
    english_statements: List[Statement],
    chinese_statements: List[Statement],
) -> List[Tuple[Optional[Statement], Statement]]:
    pairs: List[Tuple[Optional[Statement], Statement]] = []
    eng_idx = 0

    for chinese_stmt in chinese_statements:
        matched_english: Optional[Statement] = None

        while eng_idx < len(english_statements):
            candidate = english_statements[eng_idx]
            eng_idx += 1
            if is_compatible(candidate, chinese_stmt):
                matched_english = candidate
                break

        pairs.append((matched_english, chinese_stmt))

    return pairs


def process_translate_block(block_lines: List[str]) -> Tuple[List[str], BlockStats]:
    rewritten = list(block_lines)
    stats = BlockStats()

    english_statements: List[Statement] = []
    chinese_statements: List[Statement] = []

    # Skip block header at line index 0.
    for idx in range(1, len(block_lines)):
        stripped = block_lines[idx].rstrip("\n")

        english = parse_english_comment(stripped, idx)
        if english is not None:
            english_statements.append(english)
            continue

        chinese = parse_chinese_statement(stripped, idx)
        if chinese is not None:
            chinese_statements.append(chinese)

    stats.has_dialogue_candidates = len(chinese_statements) > 0

    if not chinese_statements:
        return rewritten, stats

    aligned_pairs = align_block_statements(english_statements, chinese_statements)

    for english_stmt, chinese_stmt in aligned_pairs:
        if is_already_bilingual(chinese_stmt.text):
            stats.skipped_already_bilingual += 1
            continue

        if english_stmt is None:
            stats.unmatched_statements += 1
            continue

        bilingual_text = build_bilingual_text(english_stmt.text, chinese_stmt.text)
        rewritten_line = f'{chinese_stmt.indent}{chinese_stmt.raw_prefix}"{bilingual_text}"\n'
        rewritten[chinese_stmt.line_index] = rewritten_line
        stats.processed_statements += 1

    return rewritten, stats


def collect_rpy_files(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("*.rpy") if path.is_file())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def process_target_file(src_file: Path, dst_file: Path, rel_file: str) -> FileStats:
    stats = FileStats(file=rel_file, target_file=True)

    source_text = src_file.read_text(encoding="utf-8")
    source_lines = source_text.splitlines(keepends=True)

    out_lines: List[str] = []
    i = 0
    total_lines = len(source_lines)

    while i < total_lines:
        stripped = source_lines[i].rstrip("\n")

        if STRINGS_HEADER_RE.match(stripped):
            # Keep strings block untouched.
            start = i
            i += 1
            while i < total_lines and not ANY_TRANSLATE_HEADER_RE.match(source_lines[i].rstrip("\n")):
                i += 1
            out_lines.extend(source_lines[start:i])
            continue

        if BLOCK_HEADER_RE.match(stripped):
            start = i
            i += 1
            while i < total_lines and not ANY_TRANSLATE_HEADER_RE.match(source_lines[i].rstrip("\n")):
                i += 1

            block_lines = source_lines[start:i]
            rewritten_block, block_stats = process_translate_block(block_lines)

            stats.blocks_total += 1
            stats.processed_statements += block_stats.processed_statements
            stats.unmatched_statements += block_stats.unmatched_statements
            stats.skipped_already_bilingual += block_stats.skipped_already_bilingual

            if block_stats.processed_statements > 0:
                stats.processed_blocks += 1
            if block_stats.unmatched_statements > 0:
                stats.unmatched_blocks += 1

            out_lines.extend(rewritten_block)
            continue

        out_lines.append(source_lines[i])
        i += 1

    write_text(dst_file, "".join(out_lines))
    return stats


def build(src: Path, dst: Path, report_path: Optional[Path]) -> dict:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src}")

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    all_file_stats: List[FileStats] = []
    rpy_files = collect_rpy_files(src)

    for src_file in rpy_files:
        rel = src_file.relative_to(src)
        rel_str = str(rel).replace("\\", "/")
        dst_file = dst / rel

        if is_target_dialogue_file(src_file):
            stats = process_target_file(src_file, dst_file, rel_str)
        else:
            stats = FileStats(file=rel_str, target_file=False)

        all_file_stats.append(stats)

    summary = {
        "source": str(src),
        "destination": str(dst),
        "files_processed": sum(1 for s in all_file_stats if s.target_file),
        "processed_blocks": sum(s.processed_blocks for s in all_file_stats),
        "processed_statements": sum(s.processed_statements for s in all_file_stats),
        "unmatched_blocks": sum(s.unmatched_blocks for s in all_file_stats),
        "unmatched_statements": sum(s.unmatched_statements for s in all_file_stats),
        "files": [asdict(s) for s in all_file_stats],
    }

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build bilingual Ren'Py dialogue files with block-level alignment."
    )
    parser.add_argument("--src", required=True, help="Source chinese_tl directory")
    parser.add_argument("--dst", required=True, help="Output tl/chinese directory")
    parser.add_argument(
        "--report-json",
        default="",
        help="Path to write build_report_v2.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    report_path = Path(args.report_json).resolve() if args.report_json else None

    summary = build(src=src, dst=dst, report_path=report_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
