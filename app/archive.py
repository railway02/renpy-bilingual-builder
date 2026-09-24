"""Bounded, read-only RPA 2/3 reader. Archive pickle globals never execute."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path, PurePosixPath
import pickle
import pickletools
import re
import zlib


MAX_INDEX = 32 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024 * 1024
MAX_FILES = 100_000


class ImportProblem(ValueError):
    """An actionable input error; no output is eligible for installation."""


def safe_relative(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ImportProblem(f"包内路径不安全：{name!r}。请换用原版标准汉化包。")
    parts = name.split("/")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if (PurePosixPath(name).is_absolute() or len(name) > 1000 or any(
        part in ("", ".", "..") or part.endswith((" ", "."))
        or part.split(".")[0].lower() in reserved
        or re.search(r'[<>:"|?*\x00-\x1f]', part) for part in parts
    )):
        raise ImportProblem(f"包内路径不安全：{name!r}。请换用原版标准汉化包。")
    return name


def inflate(data: bytes, limit: int) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, limit + 1)
    except zlib.error as exc:
        raise ImportProblem("压缩数据损坏或经过加密。请重新下载标准格式的文件。") from exc
    if len(result) > limit or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise ImportProblem("压缩数据不完整、超出安全大小或格式不标准。请换用未加密的脚本包。")
    return result


def legacy_bytes(value, encoding="latin1"):
    # Protocol 2 pickles represent bytes with this reduction. Never dispatch a codec.
    if type(value) is not str or encoding not in ("latin1", "latin-1"):
        raise pickle.UnpicklingError("Unsupported byte encoding")
    return value.encode("latin1")


def inert_bytes(value=b""):
    if type(value) is not bytes:
        raise pickle.UnpicklingError("Only literal bytes are allowed")
    return value


class IndexUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ("_codecs", "encode"):
            return legacy_bytes
        if module in ("builtins", "__builtin__") and name == "bytes":
            return inert_bytes
        raise pickle.UnpicklingError(f"Forbidden archive object: {module}.{name}")

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("Persistent references are not supported")


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    chunks: tuple[tuple[int, int, bytes], ...]
    size: int


class RpaArchive:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, ArchiveEntry] = {}
        with path.open("rb") as stream:
            size = path.stat().st_size
            header = stream.readline(128)
            match = re.fullmatch(rb"RPA-3\.0 ([0-9a-fA-F]{16}) ([0-9a-fA-F]{8})\r?\n", header)
            if match:
                offset, key = int(match[1], 16), int(match[2], 16)
            else:
                match = re.fullmatch(rb"RPA-2\.0 ([0-9a-fA-F]{16})\r?\n", header)
                if not match:
                    raise ImportProblem(f"{path.name} 不是支持的 RPA 2/3 标准包。请提供未加密的 RPA 或 .rpy 源文件。")
                offset, key = int(match[1], 16), 0
            if not len(header) <= offset < size or size - offset > MAX_INDEX:
                raise ImportProblem(f"{path.name} 的索引位置或大小异常。请重新获取完整文件。")
            stream.seek(offset)
            raw_index = inflate(stream.read(MAX_INDEX + 1), MAX_INDEX)
        try:
            handle = io.BytesIO(raw_index)
            if any(op.name in {"EXT1", "EXT2", "EXT4", "PERSID", "BINPERSID"}
                   for op, _, _ in pickletools.genops(raw_index)):
                raise ValueError("External pickle references are not permitted")
            index = IndexUnpickler(handle, encoding="bytes").load()
            if handle.read(1):
                raise ValueError("Trailing index data")
        except Exception as exc:
            raise ImportProblem(f"{path.name} 的索引不安全或无法读取。请换用标准包；原文件未修改。") from exc
        if type(index) is not dict or not 0 < len(index) <= MAX_FILES:
            raise ImportProblem("包索引为空或文件数量超出限制。请提供完整的标准汉化包。")
        seen = set()
        for name, chunks in index.items():
            if type(name) is bytes:
                name = name.decode("utf-8")
            name = safe_relative(name)
            folded = name.casefold()
            if folded in seen:
                raise ImportProblem(f"包内存在大小写冲突路径：{name}。请让汉化作者修复后重试。")
            seen.add(folded)
            if type(chunks) not in (list, tuple) or not 0 < len(chunks) <= 10000:
                raise ImportProblem(f"包内文件索引无效：{name}")
            validated, length = [], 0
            for chunk in chunks:
                if type(chunk) not in (list, tuple) or len(chunk) not in (2, 3):
                    raise ImportProblem(f"包内文件分段无效：{name}")
                start, count = chunk[:2]
                prefix = chunk[2] if len(chunk) == 3 else b""
                if prefix is None:
                    prefix = b""
                if type(prefix) is str:
                    prefix = prefix.encode("latin1")
                if type(start) is not int or type(count) is not int or type(prefix) is not bytes:
                    raise ImportProblem(f"包内文件类型无效：{name}")
                start, count = start ^ key, count ^ key
                # Ren'Py concatenates the index prefix and dlen bytes from the file.
                stored = count
                if stored < 0 or start < len(header) or start + stored > offset:
                    raise ImportProblem(f"包内文件越界或已损坏：{name}")
                length += count + len(prefix)
                validated.append((start, stored, prefix))
            self.entries[name] = ArchiveEntry(name, tuple(validated), length)
        # A file and a directory must not claim the same Windows path.
        for name in seen:
            if any(str(parent) in seen for parent in PurePosixPath(name).parents if str(parent) != "."):
                raise ImportProblem(f"包内文件与目录冲突：{name}")

    def copy_entry(self, name: str, destination: Path) -> None:
        entry = self.entries[name]
        if entry.size > MAX_FILE:
            raise ImportProblem(f"需提取的文件超过 512 MB 限制：{name}。请选择较小的汉化包。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("rb") as source, destination.open("xb") as target:
            for start, count, prefix in entry.chunks:
                target.write(prefix)
                source.seek(start)
                while count:
                    data = source.read(min(count, 1024 * 1024))
                    if not data:
                        raise ImportProblem(f"包在读取期间被修改或不完整：{self.path.name}")
                    target.write(data)
                    count -= len(data)
