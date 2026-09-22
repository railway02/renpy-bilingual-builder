#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


LANGUAGE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}
BLOCK_HEADER_RE = re.compile(
    r"^(?P<indent>[ \t]*)translate\s+(?P<language>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<block_id>[A-Za-z0-9_]+)\s*:\s*(?:#.*)?$"
)
ANY_TRANSLATE_HEADER_RE = re.compile(r"^[ \t]*translate\s+\w+\s+.*:\s*(?:#.*)?$")
NON_DIALOGUE_BLOCKS = {"strings", "python", "style"}
NON_SPEAKERS = {
    "voice", "play", "queue", "stop", "scene", "show", "hide",
    "image", "define", "default", "text", "textbutton", "label", "jump", "call",
    "return", "pause", "window", "with", "if", "elif", "else", "menu", "python",
}

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
    skipped_unsupported_blocks: int = 0
    fallback_english_from_original_statements: int = 0
    missing_original_statements: int = 0
    used_original_fallback: bool = False
    missing_original_block: bool = False
    diagnostics: list = field(default_factory=list)


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
    skipped_unsupported_blocks: int = 0
    fallback_english_from_original_blocks: int = 0
    fallback_english_from_original_statements: int = 0
    missing_original_blocks: int = 0
    missing_original_statements: int = 0
    diagnostics: list = field(default_factory=list)


def normalize_prefix(prefix: str) -> str:
    return re.sub(r"\s+", " ", prefix.strip())


def validate_language(language: str) -> str:
    """Accept a Ren'Py identifier that is also safe as a Windows directory."""
    if (not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language)
            or language == "None" or language.lower() in WINDOWS_RESERVED_NAMES):
        raise ValueError(
            "Language must be an ASCII identifier such as chinese, schinese, "
            "japanese or spanish; None and Windows reserved folder names are not supported."
        )
    return language


def discover_languages(root: Path) -> List[str]:
    """Find languages in actual translation headers, ignoring literal contents."""
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Source directory not found: {root}")
    languages = set()
    for path in collect_rpy_files(root):
        lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        continuation_lines, _ = multiline_string_lines(lines)
        for index, line in enumerate(lines):
            if index in continuation_lines:
                continue
            match = BLOCK_HEADER_RE.match(line.rstrip("\n"))
            if match and match.group("language") != "None":
                languages.add(match.group("language"))
    return sorted(languages)


def is_already_bilingual(text: str, english: Optional[str] = None) -> bool:
    # A translation can contain a natural newline. Only a matching English
    # prefix is evidence that it is an output from this builder.
    return english is not None and text.startswith(english + "\\n")


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

    if normalized.split(" ", 1)[0] in NON_SPEAKERS:
        return None, normalized

    if SPEAKER_PREFIX_RE.match(normalized):
        return "say", normalized

    return None, normalized


def multiline_string_lines(lines: List[str]) -> Tuple[set, set]:
    """Locate physical continuation lines without interpreting string contents.

    A line that looks like a statement or translation header can be text inside
    a multiline literal. Keep those lines out of the single-line parser.
    """
    continuation_lines, opening_lines = set(), set()
    quote = None
    opening_line = None
    for line_no, line in enumerate(lines):
        if quote is not None:
            continuation_lines.add(line_no)
            opening_lines.add(opening_line)
        i = 0
        while i < len(line):
            if quote is not None:
                if line[i] == "\\":
                    i += 2
                elif line.startswith(quote, i):
                    i += len(quote)
                    quote = None
                else:
                    i += 1
            elif line[i] == "#":
                break
            elif line[i] in "\"'`":
                quote = line[i] * (3 if line.startswith(line[i] * 3, i) else 1)
                opening_line = line_no
                i += len(quote)
            else:
                i += 1
    if quote is not None:
        opening_lines.add(opening_line)
    return continuation_lines, opening_lines


def unsupported_dialogue_reason(line: str) -> Optional[str]:
    """Recognize literal forms the single-double-quoted parser cannot rewrite."""
    content = line.lstrip()
    if content.startswith("#"):
        content = content[1:].lstrip()
    match = re.search(r"[\"'`]", content)
    if match is None:
        return None
    start = match.start()
    prefix = content[:start]
    # Raw literals require different escaping and newline handling.
    raw = prefix.endswith("r") and (len(prefix) == 1 or prefix[-2].isspace())
    kind, _ = classify_prefix(prefix[:-1] if raw else prefix)
    if kind is None:
        return None
    if raw:
        return "unsupported_raw_string"
    delimiter = content[start]
    if content.startswith(delimiter * 3, start):
        return "unsupported_triple_quoted_string"
    if delimiter != '"':
        return "unsupported_quote_delimiter"
    literal = re.match(r'"(?:[^"\\\r\n]|\\.)*"', content[start:])
    if literal is None:
        return "unsupported_multiline_or_unterminated_string"
    suffix = content[start + literal.end():].lstrip()
    if re.match(r"r?[\"'`]", suffix):
        # In `"Alice" "Hello"`, the first string is the speaker name.
        return "unsupported_quoted_speaker"
    return None


def is_menu_choice_suffix(suffix: str) -> bool:
    # Menu choices must not enter the narrator fallback index. A stale source
    # line reference could otherwise pair option text with unrelated dialogue.
    return bool(re.match(r"^\s*(?::|if\s+.*:)(?:\s*#.*)?\s*$", suffix))


def parse_comment_statement(line: str, idx: int) -> Optional[Statement]:
    if unsupported_dialogue_reason(line) is not None:
        return None
    match = COMMENT_QUOTED_RE.match(line)
    if not match:
        return None

    kind, normalized_prefix = classify_prefix(match.group("prefix"))
    if kind is None:
        return None
    if is_menu_choice_suffix(match.group("suffix")):
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
    if unsupported_dialogue_reason(line) is not None:
        return None

    match = QUOTED_STATEMENT_RE.match(line)
    if not match:
        return None

    kind, normalized_prefix = classify_prefix(match.group("prefix"))
    if kind is None:
        return None
    if is_menu_choice_suffix(match.group("suffix")):
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
    # Do not consume later dialogue looking for a matching speaker. Translation
    # blocks may reorder or add lines; guessing shifts every subsequent pair.
    same_count = len(english_statements) == len(chinese_statements)
    for idx, chinese_stmt in enumerate(chinese_statements):
        candidate = english_statements[idx] if same_count else None
        matched = candidate if candidate and statements_compatible(candidate, chinese_stmt) else None
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

        source_file_name = match.group("source_file").replace("\\", "/").lower()
        if source_file_name != expected_file_name.replace("\\", "/").lower():
            return None

        return int(match.group("line_no"))

    return None


def extract_block_spans(
    lines: List[str], file_name: str, language: str = "chinese",
) -> List[BlockSpan]:
    spans: List[BlockSpan] = []
    i = 0
    total = len(lines)
    continuation_lines, _ = multiline_string_lines(lines)

    while i < total:
        stripped = lines[i].rstrip("\n")
        block_match = BLOCK_HEADER_RE.match(stripped) if i not in continuation_lines else None
        if (block_match and block_match.group("language") == language
                and block_match.group("block_id") not in NON_DIALOGUE_BLOCKS):
            start = i
            block_id = block_match.group("block_id")
            source_line_no = parse_source_ref_line_no(lines, start, file_name)

            i += 1
            while i < total:
                if i in continuation_lines:
                    i += 1
                    continue
                next_stripped = lines[i].rstrip("\n")
                if (ANY_TRANSLATE_HEADER_RE.match(next_stripped) or
                        (next_stripped.strip() and not next_stripped.lstrip().startswith("#")
                         and len(next_stripped) - len(next_stripped.lstrip()) <= len(block_match.group("indent")))):
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
    continuation_lines, opening_lines = multiline_string_lines(original_lines)
    for idx, raw_line in enumerate(original_lines):
        if idx in continuation_lines or idx in opening_lines:
            continue
        stripped = raw_line.rstrip("\n")
        stmt = parse_dialogue_statement(stripped, idx)
        if stmt is not None:
            statements.append(stmt)
    return statements


def extract_original_block_statements_by_id(
    original_lines: List[str], language: str = "chinese",
) -> Dict[str, List[Statement]]:
    blocks: Dict[str, List[Statement]] = {}
    for block in extract_block_spans(original_lines, "", language):
        block_statements: List[Statement] = []
        block_lines = original_lines[block.start_index + 1:block.end_index]
        _, multiline_openings = multiline_string_lines(block_lines)
        if multiline_openings or any(unsupported_dialogue_reason(line) for line in block_lines):
            continue
        for idx in range(block.start_index + 1, block.end_index):
            stmt = parse_dialogue_statement(original_lines[idx].rstrip("\n"), idx)
            if stmt is not None:
                block_statements.append(stmt)
        blocks[block.block_id] = block_statements
    return blocks


def select_original_statements_for_block(
    block: BlockSpan,
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

    # Source line references can be stale after a game update. Never scan into
    # another scene (especially from the final block through the rest of a file).
    selected = [stmt for stmt in original_all_statements if stmt.line_no == block.source_line_no]

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

    continuation_lines, multiline_openings = multiline_string_lines(block_lines)
    for idx in range(1, len(block_lines)):
        if idx in continuation_lines:
            continue
        reason = unsupported_dialogue_reason(block_lines[idx])
        if reason is None and idx in multiline_openings:
            reason = "unsupported_multiline_string"
        if reason is not None:
            # Keeping the complete block also protects lines inside a multiline
            # string that happen to resemble ordinary dialogue.
            stats.skipped_unsupported_blocks = 1
            stats.diagnostics.append({
                "line": idx + 1,
                "reason": reason,
                "action": "kept_original_block",
            })
            return rewritten, stats

    comment_pairs: List[Tuple[Optional[Statement], Statement]] = []
    chinese_statements: List[Statement] = []
    pending_comment: Optional[Statement] = None

    for idx in range(1, len(block_lines)):
        stripped = block_lines[idx].rstrip("\n")

        comment_stmt = parse_comment_statement(stripped, idx)
        if comment_stmt is not None:
            pending_comment = comment_stmt
            continue

        chinese_stmt = parse_dialogue_statement(stripped, idx)
        if chinese_stmt is not None:
            chinese_statements.append(chinese_stmt)
            matched = pending_comment if pending_comment and statements_compatible(pending_comment, chinese_stmt) else None
            comment_pairs.append((matched, chinese_stmt))
            pending_comment = None
        elif stripped.strip():
            pending_comment = None

    if not chinese_statements:
        return rewritten, stats

    original_pairs = align_statements(original_block_statements, chinese_statements)

    block_used_original_fallback = False
    block_missing_original = False

    for idx, chinese_stmt in enumerate(chinese_statements):
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
            stats.diagnostics.append({"line": chinese_stmt.line_no, "reason": "no_reliable_english", "action": "kept_original_translation"})
            continue

        if is_already_bilingual(chinese_stmt.text, selected_english.text):
            stats.skipped_already_bilingual += 1
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
    language: str = "chinese",
) -> FileStats:
    source_lines = src_file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    block_spans = extract_block_spans(source_lines, rel_file, language)
    stats = FileStats(file=rel_file, target_file=bool(block_spans))
    if not block_spans:
        # Preserve BOMs, newline conventions and non-dialogue contents exactly.
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        return stats

    original_lines: List[str] = []
    if src_original_file is not None and src_original_file.exists():
        original_lines = src_original_file.read_text(encoding="utf-8-sig").splitlines(keepends=True)

    original_block_by_id = extract_original_block_statements_by_id(original_lines, language)
    original_all_statements = build_original_statement_data(original_lines)

    out_lines: List[str] = []
    i = 0
    span_idx = 0

    while i < len(source_lines):
        if span_idx < len(block_spans) and i == block_spans[span_idx].start_index:
            block = block_spans[span_idx]
            block_lines = source_lines[block.start_index:block.end_index]

            original_block_statements: List[Statement] = []
            original_block_missing = True

            rewritten_block, block_stats = process_block(block_lines, [], True)
            if original_lines and block_stats.unmatched_statements:
                (
                    original_block_statements,
                    original_block_missing,
                ) = select_original_statements_for_block(
                    block=block,
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
            stats.skipped_unsupported_blocks += block_stats.skipped_unsupported_blocks
            stats.fallback_english_from_original_statements += (
                block_stats.fallback_english_from_original_statements
            )
            stats.missing_original_statements += block_stats.missing_original_statements
            for diagnostic in block_stats.diagnostics:
                stats.diagnostics.append(dict(diagnostic, line=block.start_index + diagnostic["line"], block_id=block.block_id))

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


class BuildRecoveryError(RuntimeError):
    """Keep the transaction directory when recovery itself needs intervention."""


def _commit_build(work: Path, dst: Path, reports: Dict[Path, str]) -> None:
    """Publish complete output and reports, restoring old versions on failure."""
    prepared = []
    published = []
    previous = work / "previous-output"
    output_attempted = False
    keep_recovery_files = False
    try:
        for report, content in reports.items():
            if dst in report.parents:
                write_text(work / "new" / report.relative_to(dst), content)
                continue
            report.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix=".rbb-report-", dir=report.parent))
            prepared.append((report, temp))
            write_text(temp / "new", content)
            if report.exists():
                shutil.copy2(report, temp / "previous")

        # An interruption can occur immediately after a successful rename.
        # Preserve recovery files until commit or rollback fully completes.
        keep_recovery_files = True
        if dst.exists():
            dst.replace(previous)
        output_attempted = True
        (work / "new").replace(dst)
        for report, temp in prepared:
            published.append((report, temp))
            (temp / "new").replace(report)
        keep_recovery_files = False
    except BaseException as error:
        keep_recovery_files = True
        recovery_errors = []
        for report, temp in reversed(published):
            if (temp / "new").exists():
                continue  # replace did not complete; the old report is intact.
            try:
                if (temp / "previous").exists():
                    (temp / "previous").replace(report)
                else:
                    report.unlink(missing_ok=True)
            except BaseException as restore_error:
                recovery_errors.append(repr(restore_error))
        try:
            if output_attempted and not (work / "new").exists() and dst.exists():
                shutil.rmtree(dst)
            if previous.exists():
                previous.replace(dst)
        except BaseException as restore_error:
            recovery_errors.append(repr(restore_error))
        if recovery_errors:
            keep_recovery_files = True
            locations = [str(work)] + [str(temp) for _, temp in prepared]
            raise BuildRecoveryError(
                "Build failed and automatic recovery was incomplete. Recovery files: "
                + ", ".join(locations) + ". Errors: " + "; ".join(recovery_errors)
            ) from error
        keep_recovery_files = False
        raise
    finally:
        if not keep_recovery_files:
            for _, temp in prepared:
                shutil.rmtree(temp, ignore_errors=True)


def _diagnostics_csv(diagnostics: list) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["file", "line", "block_id", "reason", "action"])
    writer.writeheader()
    writer.writerows(diagnostics)
    # Excel on Windows detects Chinese reliably with a UTF-8 BOM.
    return "\ufeff" + output.getvalue()


def build(
    src: Path, src_original: Optional[Path] = None, dst: Optional[Path] = None,
    report_path: Optional[Path] = None,
    csv_path: Optional[Path] = None, progress: Optional[Callable[[str], None]] = None,
    language: Optional[str] = None,
) -> dict:
    if dst is None:
        raise ValueError("An output directory is required.")
    if dst.is_symlink():
        raise ValueError("Output directory must not be a symbolic link.")
    src, dst = src.resolve(), dst.resolve()
    src_original = src_original.resolve() if src_original is not None else None
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src}")
    if src_original is not None and not src_original.is_dir():
        raise FileNotFoundError(f"Original source directory not found: {src_original}")

    input_dirs = [root for root in (src, src_original) if root is not None]
    for input_dir in input_dirs:
        if dst == input_dir or dst in input_dir.parents or input_dir in dst.parents:
            raise ValueError("Output directory must not overlap either input directory.")
    if dst.exists() and not dst.is_dir():
        raise ValueError(f"Output path is not a directory: {dst}")

    report_paths = []
    for report in (report_path, csv_path):
        if report is None:
            report_paths.append(None)
            continue
        if report.is_symlink():
            raise ValueError(f"Report path must not be a symbolic link: {report}")
        report = report.resolve()
        if report == dst or report in dst.parents or (report.exists() and report.is_dir()):
            raise ValueError(f"Report path must be a file separate from output directories: {report}")
        if any(report == root or root in report.parents for root in input_dirs):
            raise ValueError("Reports must not overwrite input files.")
        if dst in report.parents and (src / report.relative_to(dst)).exists():
            raise ValueError("Report path conflicts with a copied source file.")
        report_paths.append(report)
    report_path, csv_path = report_paths
    if report_path is not None and report_path == csv_path:
        raise ValueError("JSON and CSV reports must have different paths.")
    rpy_files = collect_rpy_files(src)
    if language is None:
        languages = discover_languages(src)
        if not languages:
            raise ValueError(
                "No translation language found in .rpy files; choose the translation directory "
                "containing translate <language> blocks, not the original game scripts."
            )
        if len(languages) > 1:
            raise ValueError(
                "Multiple translation languages found: " + ", ".join(languages)
                + ". Select a single translation directory or specify --language."
            )
        language = languages[0]
    language = validate_language(language)

    dst.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".rbb-build-", dir=dst.parent))
    preserve_work = False
    committed = False
    try:
        if progress:
            progress("正在准备临时输出；上一次成功的输出会保留到本次构建完成。")
        shutil.copytree(src, work / "new", ignore=ignore_generated_files)
        all_file_stats: List[FileStats] = []
        for index, src_file in enumerate(rpy_files, 1):
            rel = src_file.relative_to(src)
            rel_str = rel.as_posix()
            if progress:
                progress(f"[{index}/{len(rpy_files)}] {rel_str}")
            src_original_file = src_original / rel if src_original is not None else None
            stats = process_target_file(
                src_file=src_file,
                src_original_file=src_original_file,
                dst_file=work / "new" / rel,
                rel_file=rel_str,
                language=language,
            )
            all_file_stats.append(stats)

        if not any(stats.blocks_total for stats in all_file_stats):
            raise ValueError(
                f"No supported translate {language} dialogue blocks found; choose the translation "
                "directory, not the original game scripts. Strings, python and style blocks are preserved."
            )
        summary = summarize_build(src, src_original, dst, all_file_stats, language)
        if csv_path is not None:
            summary["diagnostics_csv"] = str(csv_path)
        reports = {}
        if report_path is not None:
            reports[report_path] = json.dumps(summary, ensure_ascii=False, indent=2)
        if csv_path is not None:
            reports[csv_path] = _diagnostics_csv(summary["diagnostics"])
        _commit_build(work, dst, reports)
        committed = True
        return summary
    except BuildRecoveryError:
        preserve_work = True
        raise
    finally:
        # Never delete the sole previous output on an interrupted rollback.
        if not preserve_work and (committed or not (work / "previous-output").exists()):
            shutil.rmtree(work, ignore_errors=True)


def summarize_build(
    src: Path, src_original: Optional[Path], dst: Path,
    all_file_stats: List[FileStats], language: str = "chinese",
) -> dict:
    return {
        "source": str(src),
        "source_original": str(src_original) if src_original is not None else None,
        "destination": str(dst),
        "language": language,
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
        "skipped_already_bilingual": sum(s.skipped_already_bilingual for s in all_file_stats),
        "skipped_unsupported_blocks": sum(s.skipped_unsupported_blocks for s in all_file_stats),
        "diagnostics": [dict(item, file=s.file) for s in all_file_stats for item in s.diagnostics],
        "files": [asdict(s) for s in all_file_stats],
    }

def ignore_generated_files(directory: str, names: List[str]) -> List[str]:
    # Keep compiled-only modules, but let Ren'Py compile every supplied source.
    return [name for name in names if name.endswith(":Zone.Identifier") or
            (name.endswith(".rpyc") and name[:-1] in names)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build bilingual Ren'Py dialogue with conservative matching and recoverable output replacement."
    )
    parser.add_argument("--src", required=True, help="One game's translation language directory containing .rpy files")
    parser.add_argument(
        "--src-original",
        help="Optional original script directory for conservative fallback when source comments are missing",
    )
    parser.add_argument("--dst", required=True, help="Output translation directory")
    parser.add_argument("--language", help="Target Ren'Py language identifier; auto-detect when the input has one language")
    parser.add_argument(
        "--report-json",
        default="",
        help="Path to write the JSON build report",
    )
    parser.add_argument("--report-csv", default="", help="Optional UTF-8 CSV of diagnostic locations")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    src = Path(args.src).resolve()
    src_original = Path(args.src_original).resolve() if args.src_original else None
    dst = Path(args.dst)
    report_path = Path(args.report_json) if args.report_json else None
    csv_path = Path(args.report_csv) if args.report_csv else None

    summary = build(src=src, src_original=src_original, dst=dst, report_path=report_path,
                    csv_path=csv_path, language=args.language,
                    progress=lambda message: print(message, file=sys.stderr, flush=True))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
