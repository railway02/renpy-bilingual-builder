"""Read RPYC data and render it, without importing Ren'Py or executing scripts."""

from __future__ import annotations

import collections
import io
import json
from pathlib import Path
import pickle
import pickletools
import re
import struct
import subprocess
import sys

from app.archive import ImportProblem, inflate, legacy_bytes, inert_bytes
from app.runtime import resource_root


MAX_SCRIPT = 64 * 1024 * 1024


def read_slots(path: Path) -> dict[int, bytes]:
    if path.stat().st_size > MAX_SCRIPT:
        raise ImportProblem(f"编译脚本过大：{path.name}。请提供 .rpy 源文件。")
    raw = path.read_bytes()
    if not raw.startswith(b"RENPY RPC2"):
        return {1: inflate(raw, MAX_SCRIPT)}
    spans = {}
    position = 10
    for _ in range(16):
        if position + 12 > len(raw):
            raise ImportProblem("编译脚本头部不完整，请重新获取原文件。")
        slot, start, length = struct.unpack_from("<III", raw, position)
        position += 12
        if slot == 0:
            break
        if slot in spans or slot not in (1, 2):
            raise ImportProblem("编译脚本使用了未知格式。请提供未混淆的 .rpy 源文件。")
        spans[slot] = (start, length)
    else:
        raise ImportProblem("编译脚本分段过多，已停止读取。")
    if 1 not in spans:
        raise ImportProblem("编译脚本缺少可恢复的语法数据。请提供 .rpy 源文件。")
    previous_end = position
    for start, length in sorted(spans.values()):
        if start < previous_end or length <= 0 or start + length > len(raw):
            raise ImportProblem("编译脚本数据越界或重叠。请重新获取完整的未混淆文件。")
        previous_end = start + length
    return {slot: inflate(raw[start:start + length], MAX_SCRIPT) for slot, (start, length) in spans.items()}


def load_ast(data: bytes):
    from vendor.unrpyc.decompiler.renpycompat import CLASS_FACTORY
    if any(op.name in {"EXT1", "EXT2", "EXT4", "PERSID", "BINPERSID"}
           for op, _, _ in pickletools.genops(data)):
        raise ImportProblem("编译脚本包含外部对象引用，已拒绝读取。")

    class AstUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module.startswith("renpy.") and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
                # These classes store inert state. No actual game/engine module is imported.
                return CLASS_FACTORY(name, module)
            allowed = {
                ("collections", "defaultdict"): collections.defaultdict,
                ("collections", "OrderedDict"): collections.OrderedDict,
                ("builtins", "set"): set, ("builtins", "frozenset"): frozenset,
                ("__builtin__", "set"): set, ("__builtin__", "frozenset"): frozenset,
                ("_codecs", "encode"): legacy_bytes,
                ("builtins", "bytes"): inert_bytes, ("__builtin__", "bytes"): inert_bytes,
            }
            for builtin in (list, dict, tuple, str, int, float, bool, object):
                for namespace in ("builtins", "__builtin__"):
                    allowed[namespace, builtin.__name__] = builtin
            if (module, name) in allowed:
                return allowed[module, name]
            raise pickle.UnpicklingError(f"禁止加载脚本对象：{module}.{name}")

        def persistent_load(self, pid):
            raise pickle.UnpicklingError("禁止外部对象引用")

    stream = io.BytesIO(data)
    value = AstUnpickler(stream, encoding="utf-8", errors="strict").load()
    if (stream.read(1) or type(value) is not tuple or len(value) != 2
            or type(value[0]) is not dict or type(value[1]) is not list):
        raise ImportProblem("编译脚本语法结构不标准。请提供原始 .rpy 文件。")
    return value[1]


def originals_from_ast(nodes) -> list[dict]:
    from vendor.unrpyc.decompiler.renpycompat import renpy
    from vendor.unrpyc.decompiler.util import say_get_code

    records, visited = [], set()
    def visit(value):
        if id(value) in visited:
            return
        visited.add(id(value))
        if len(visited) > 1_000_000:
            raise ImportProblem("脚本结构过大，已停止读取。")
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
            return
        if isinstance(value, renpy.ast.Translate) and value.language is None:
            block = value.block
            if block and all(isinstance(node, renpy.ast.Say) for node in block):
                codes = [say_get_code(node) for node in block]
                for identifier in (value.identifier, getattr(value, "alternate", None)):
                    if identifier:
                        records.append(dict(id=identifier, lines=codes))
        elif isinstance(value, renpy.ast.TranslateSay) and value.language is None:
            for identifier in (value.identifier, getattr(value, "alternate", None)):
                if identifier:
                    records.append(dict(id=identifier, lines=[say_get_code(value)]))
        # Only structural children; never follow next/parent pointers or evaluate expressions.
        for key in ("block", "entries", "items"):
            child = getattr(value, key, None)
            if isinstance(child, (list, tuple)):
                visit(child)
    visit(nodes)
    return records


class LimitedText(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > MAX_SCRIPT:
            raise ImportProblem("恢复后的脚本超出安全大小，请使用原始 .rpy 文件。")
        return super().write(value)


def decode_file(source: Path) -> dict:
    from vendor.unrpyc import decompiler
    slots = read_slots(source)
    ast = load_ast(slots[1])
    output, messages = LimitedText(), []
    decompiler.pprint(output, ast, decompiler.Options(log=messages, init_offset=True))
    text = output.getvalue()
    if messages or "<<<COULD NOT DECOMPILE" in text:
        raise ImportProblem("存在无法完整恢复的脚本语法，未生成可安装结果。请提供 .rpy 源文件。\n" + "\n".join(messages[:5]))
    original_nodes = load_ast(slots[2]) if 2 in slots else ast
    return {"text": text, "originals": originals_from_ast(original_nodes), "slots": sorted(slots)}


def worker(request: Path) -> None:
    payload = json.loads(request.read_text(encoding="utf-8"))
    result = Path(payload["result"])
    try:
        # A separate process also bounds pathological AST traversal/formatting.
        if sys.platform != "win32":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
        value = decode_file(Path(payload["source"]))
        value["ok"] = True
    except Exception as exc:
        value = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def decompile(source: Path, work: Path) -> dict:
    """Invoke a fixed helper entry, never a game interpreter or game executable."""
    work.mkdir(parents=True, exist_ok=True)
    request, result = work / "request.json", work / "result.json"
    result.unlink(missing_ok=True)
    request.write_text(json.dumps({"source": str(source.resolve()), "result": str(result.resolve())}), encoding="utf-8")
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--decode-worker", str(request.resolve())]
    else:
        command = [sys.executable, "-I", str(resource_root() / "decode_worker.py"), str(request.resolve())]
    try:
        subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if result.stat().st_size > MAX_SCRIPT * 4:
            raise ImportProblem("脚本恢复结果超出限制。请提供原始 .rpy 文件。")
        data = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ImportProblem(f"无法在限制时间内恢复 {source.name}。请使用未混淆的 .rpy 源文件，或在“查看详情”中查看日志。") from exc
    if not data.get("ok"):
        raise ImportProblem(f"无法完整恢复 {source.name}；原游戏未修改。请提供 .rpy 源文件。\n{data.get('error', '')}")
    return data
