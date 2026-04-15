#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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

BLOCK_HEADER_RE = re.compile(
    r"^(?P<indent>[ \t]*)translate\s+chinese\s+(?P<block_id>[A-Za-z0-9_]+)\s*:\s*$"
)
STRINGS_HEADER_RE = re.compile(r"^[ \t]*translate\s+chinese\s+strings\s*:\s*$")
ANY_TRANSLATE_HEADER_RE = re.compile(r"^[ \t]*translate\s+\w+\s+\w+\s*:\s*$")

SOURCE_REF_RE = re.compile(
    r"^[ \t]*#\s*game/(?P<source_file>[^:]+):(?P<line_no>\d+)\s*$"
)

COMMENT_QUOTED_RE = re.compile(
    r'^(?P<indent>[ \t]*)#\s*(?P<prefix>[^"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"(?P<suffix>[^\n]*)$'
)
QUOTED_STATEMENT_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>[^#"\n]*?)"(?P<text>(?:[^"\\]|\\.)*)"(?P<suffix>[^\n]*)$'
)

SPEAKER_PREFIX_RE = re.compile(r"^[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*$")


@dataclass
class Statement:
    line_index: int
    line_no: int
    indent: str
    raw_prefix: str
    normalized_prefix: str
    kind: str
    text: str
    suffix: str


@dataclass
class BlockSpan:
    start_index: int
    end_index: int
    block_id: str
    source_line_no: Optional[int]


@dataclass
class BlockStats:
    processed_statements: int = 0
    unmatched_statements: int = 0
    skipped_already_bilingual: int = 0
    fallback_english_from_original_statements: int = 0
    missing_original_statements: int = 0
    used_original_fallback: bool = False
    missing_original_block: bool = False


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
    fallback_english_from_original_blocks: int = 0
    fallback_english_from_original_statements: int = 0
    missing_original_blocks: int = 0
    missing_original_statements: int = 0


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


def parse_comment_statement(line: str, idx: int) -> Optional[Statement]:
    match = COMMENT_QUOTED_RE.match(line)
    if not match:
        return None

    kind, normalized_prefix = classify_prefix(match.group("prefix"))
    if kind is None:
        return None

    return Statement(
        line_index=idx,
        line_no=idx + 1,
        indent=match.group("indent"),
        raw_prefix=match.group("prefix"),
        normalized_prefix=normalized_prefix,
        kind=kind,
        text=match.group("text"),
        suffix=match.group("suffix"),
    )


def parse_dialogue_statement(line: str, idx: int) -> Optional[Statement]:
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
        line_no=idx + 1,
        indent=match.group("indent"),
        raw_prefix=match.group("prefix"),
        normalized_prefix=normalized_prefix,
        kind=kind,
        text=match.group("text"),
        suffix=match.group("suffix"),
    )


def statements_compatible(english_stmt: Statement, chinese_stmt: Statement) -> bool:
    if english_stmt.kind != chinese_stmt.kind:
        return False

    if english_stmt.kind == "say":
        return english_stmt.normalized_prefix == chinese_stmt.normalized_prefix

    return True


def align_statements(
    english_statements: List[Statement],
    chinese_statements: List[Statement],
) -> List[Tuple[Optional[Statement], Statement]]:
    pairs: List[Tuple[Optional[Statement], Statement]] = []
    english_idx = 0

    for chinese_stmt in chinese_statements:
        matched: Optional[Statement] = None

        while english_idx < len(english_statements):
            candidate = english_statements[english_idx]
            english_idx += 1
            if statements_compatible(candidate, chinese_stmt):
                matched = candidate
                break

        pairs.append((matched, chinese_stmt))

    return pairs


def parse_source_ref_line_no(lines: List[str], block_start_idx: int, expected_file_name: str) -> Optional[int]:
    idx = block_start_idx - 1

    while idx >= 0:
        stripped = lines[idx].rstrip("\n")
        if stripped.strip() == "":
            idx -= 1
            continue

        match = SOURCE_REF_RE.match(stripped)
        if not match:
            return None

        source_file_name = Path(match.group("source_file")).name.lower()
        if source_file_name != expected_file_name.lower():
            return None

        return int(match.group("line_no"))

    return None


def extract_block_spans(lines: List[str], file_name: str) -> List[BlockSpan]:
    spans: List[BlockSpan] = []
    i = 0
    total = len(lines)

    while i < total:
        stripped = lines[i].rstrip("\n")
        block_match = BLOCK_HEADER_RE.match(stripped)
        if block_match:
            start = i
            block_id = block_match.group("block_id")
            source_line_no = parse_source_ref_line_no(lines, start, file_name)

            i += 1
            while i < total:
                next_stripped = lines[i].rstrip("\n")
                if ANY_TRANSLATE_HEADER_RE.match(next_stripped):
                    break
                i += 1

            spans.append(
                BlockSpan(
                    start_index=start,
                    end_index=i,
                    block_id=block_id,
                    source_line_no=source_line_no,
                )
            )
            continue

        i += 1

    return spans


def build_original_statement_data(original_lines: List[str]) -> List[Statement]:
    statements: List[Statement] = []
    for idx, raw_line in enumerate(original_lines):
        stripped = raw_line.rstrip("\n")
        stmt = parse_dialogue_statement(stripped, idx)
        if stmt is not None:
            statements.append(stmt)
    return statements


def extract_original_block_statements_by_id(original_lines: List[str]) -> Dict[str, List[Statement]]:
    blocks: Dict[str, List[Statement]] = {}

    i = 0
    total = len(original_lines)

    while i < total:
        stripped = original_lines[i].rstrip("\n")
        block_match = BLOCK_HEADER_RE.match(stripped)
        if not block_match:
            i += 1
            continue

        block_id = block_match.group("block_id")
        i += 1
        start = i
        while i < total:
            next_stripped = original_lines[i].rstrip("\n")
            if ANY_TRANSLATE_HEADER_RE.match(next_stripped):
                break
            i += 1

        block_lines = original_lines[start:i]
        block_statements: List[Statement] = []
        for rel_idx, raw_line in enumerate(block_lines):
            original_idx = start + rel_idx
            stmt = parse_dialogue_statement(raw_line.rstrip("\n"), original_idx)
            if stmt is not None:
                block_statements.append(stmt)

        blocks[block_id] = block_statements

    return blocks


def get_next_source_line_no(spans: List[BlockSpan], current_idx: int) -> Optional[int]:
    for idx in range(current_idx + 1, len(spans)):
        if spans[idx].source_line_no is not None:
            return spans[idx].source_line_no
    return None


def select_original_statements_for_block(
    block: BlockSpan,
    block_idx: int,
    all_blocks: List[BlockSpan],
    original_block_by_id: Dict[str, List[Statement]],
    original_all_statements: List[Statement],
) -> Tuple[List[Statement], bool]:
    """
    Returns (statements, original_block_missing)
    """
    if block.block_id in original_block_by_id:
        return original_block_by_id[block.block_id], False

    if block.source_line_no is None:
        return [], True

    start_line = block.source_line_no
    next_source_line = get_next_source_line_no(all_blocks, block_idx)

    if next_source_line is None:
        selected = [stmt for stmt in original_all_statements if stmt.line_no >= start_line]
    else:
        selected = [
            stmt
            for stmt in original_all_statements
            if start_line <= stmt.line_no < next_source_line
        ]

    if not selected:
        return [], True

    return selected, False


def process_block(
    block_lines: List[str],
    original_block_statements: List[Statement],
    original_block_missing: bool,
) -> Tuple[List[str], BlockStats]:
    rewritten = list(block_lines)
    stats = BlockStats()

    english_from_comments: List[Statement] = []
    chinese_statements: List[Statement] = []

    for idx in range(1, len(block_lines)):
        stripped = block_lines[idx].rstrip("\n")

        comment_stmt = parse_comment_statement(stripped, idx)
        if comment_stmt is not None:
            english_from_comments.append(comment_stmt)
            continue

        chinese_stmt = parse_dialogue_statement(stripped, idx)
        if chinese_stmt is not None:
            chinese_statements.append(chinese_stmt)

    if not chinese_statements:
        return rewritten, stats

    comment_pairs = align_statements(english_from_comments, chinese_statements)
    original_pairs = align_statements(original_block_statements, chinese_statements)

    block_used_original_fallback = False
    block_missing_original = False

    for idx, chinese_stmt in enumerate(chinese_statements):
        if is_already_bilingual(chinese_stmt.text):
            stats.skipped_already_bilingual += 1
            continue

        comment_english, _ = comment_pairs[idx]
        original_english, _ = original_pairs[idx]

        selected_english: Optional[Statement] = None

        if comment_english is not None:
            selected_english = comment_english
        else:
            if original_english is not None:
                selected_english = original_english
                stats.fallback_english_from_original_statements += 1
                block_used_original_fallback = True
            else:
                stats.missing_original_statements += 1
                block_missing_original = block_missing_original or original_block_missing

        if selected_english is None:
            stats.unmatched_statements += 1
            continue

        bilingual_text = build_bilingual_text(selected_english.text, chinese_stmt.text)
        rewritten_line = (
            f'{chinese_stmt.indent}{chinese_stmt.raw_prefix}"{bilingual_text}"{chinese_stmt.suffix}\n'
        )
        rewritten[chinese_stmt.line_index] = rewritten_line
        stats.processed_statements += 1

    stats.used_original_fallback = block_used_original_fallback
    stats.missing_original_block = block_missing_original and stats.missing_original_statements > 0

    return rewritten, stats


def collect_rpy_files(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("*.rpy") if path.is_file())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def process_target_file(
    src_file: Path,
    src_original_file: Optional[Path],
    dst_file: Path,
    rel_file: str,
) -> FileStats:
    stats = FileStats(file=rel_file, target_file=True)

    source_lines = src_file.read_text(encoding="utf-8").splitlines(keepends=True)
    block_spans = extract_block_spans(source_lines, src_file.name)

    original_lines: List[str] = []
    if src_original_file is not None and src_original_file.exists():
        original_lines = src_original_file.read_text(encoding="utf-8").splitlines(keepends=True)

    original_block_by_id = extract_original_block_statements_by_id(original_lines)
    original_all_statements = build_original_statement_data(original_lines)

    out_lines: List[str] = []
    i = 0
    span_idx = 0

    while i < len(source_lines):
        stripped = source_lines[i].rstrip("\n")

        if STRINGS_HEADER_RE.match(stripped):
            # Keep strings block untouched.
            start = i
            i += 1
            while i < len(source_lines) and not ANY_TRANSLATE_HEADER_RE.match(source_lines[i].rstrip("\n")):
                i += 1
            out_lines.extend(source_lines[start:i])
            continue

        if span_idx < len(block_spans) and i == block_spans[span_idx].start_index:
            block = block_spans[span_idx]
            block_lines = source_lines[block.start_index:block.end_index]

            original_block_statements: List[Statement] = []
            original_block_missing = True

            if original_lines:
                (
                    original_block_statements,
                    original_block_missing,
                ) = select_original_statements_for_block(
                    block=block,
                    block_idx=span_idx,
                    all_blocks=block_spans,
                    original_block_by_id=original_block_by_id,
                    original_all_statements=original_all_statements,
                )

            rewritten_block, block_stats = process_block(
                block_lines=block_lines,
                original_block_statements=original_block_statements,
                original_block_missing=original_block_missing,
            )

            stats.blocks_total += 1
            stats.processed_statements += block_stats.processed_statements
            stats.unmatched_statements += block_stats.unmatched_statements
            stats.skipped_already_bilingual += block_stats.skipped_already_bilingual
            stats.fallback_english_from_original_statements += (
                block_stats.fallback_english_from_original_statements
            )
            stats.missing_original_statements += block_stats.missing_original_statements

            if block_stats.processed_statements > 0:
                stats.processed_blocks += 1
            if block_stats.unmatched_statements > 0:
                stats.unmatched_blocks += 1
            if block_stats.used_original_fallback:
                stats.fallback_english_from_original_blocks += 1
            if block_stats.missing_original_block:
                stats.missing_original_blocks += 1

            out_lines.extend(rewritten_block)
            i = block.end_index
            span_idx += 1
            continue

        out_lines.append(source_lines[i])
        i += 1

    write_text(dst_file, "".join(out_lines))
    return stats


def build(src: Path, src_original: Path, dst: Path, report_path: Optional[Path]) -> dict:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src}")
    if not src_original.exists() or not src_original.is_dir():
        raise FileNotFoundError(f"Original source directory not found: {src_original}")

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
            src_original_file = src_original / rel
            stats = process_target_file(
                src_file=src_file,
                src_original_file=src_original_file if src_original_file.exists() else None,
                dst_file=dst_file,
                rel_file=rel_str,
            )
        else:
            stats = FileStats(file=rel_str, target_file=False)

        all_file_stats.append(stats)

    summary = {
        "source": str(src),
        "source_original": str(src_original),
        "destination": str(dst),
        "files_processed": sum(1 for s in all_file_stats if s.target_file),
        "processed_blocks": sum(s.processed_blocks for s in all_file_stats),
        "processed_statements": sum(s.processed_statements for s in all_file_stats),
        "unmatched_blocks": sum(s.unmatched_blocks for s in all_file_stats),
        "unmatched_statements": sum(s.unmatched_statements for s in all_file_stats),
        "fallback_english_from_original_blocks": sum(
            s.fallback_english_from_original_blocks for s in all_file_stats
        ),
        "fallback_english_from_original_statements": sum(
            s.fallback_english_from_original_statements for s in all_file_stats
        ),
        "missing_original_blocks": sum(s.missing_original_blocks for s in all_file_stats),
        "missing_original_statements": sum(
            s.missing_original_statements for s in all_file_stats
        ),
        "files": [asdict(s) for s in all_file_stats],
    }

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build bilingual Ren'Py dialogue files with block-level alignment and original fallback (v2.5)."
    )
    parser.add_argument("--src", required=True, help="Source chinese_tl directory")
    parser.add_argument(
        "--src-original",
        required=True,
        help="Source original_english directory",
    )
    parser.add_argument("--dst", required=True, help="Output tl/chinese directory")
    parser.add_argument(
        "--report-json",
        default="",
        help="Path to write build_report_v25.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    src = Path(args.src).resolve()
    src_original = Path(args.src_original).resolve()
    dst = Path(args.dst).resolve()
    report_path = Path(args.report_json).resolve() if args.report_json else None

    summary = build(src=src, src_original=src_original, dst=dst, report_path=report_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
