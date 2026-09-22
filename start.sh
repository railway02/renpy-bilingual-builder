#!/bin/sh
# Run from the source directory, including when launched from another directory.
set -u
RBB_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$RBB_ROOT" || exit 1
export PYTHONUTF8=1

fail() {
    printf '\n错误：%s\n' "$*" >&2
    exit 1
}

[ -f app/gui.py ] && [ -f requirements.txt ] ||
    fail '项目文件不完整。请解压完整源码，再运行 start.sh。'

RBB_VENV=.venv/bin/python
RBB_REBUILD=0
if [ -e .venv ] || [ -L .venv ]; then
    [ -f .venv/pyvenv.cfg ] ||
        fail '.venv 已存在，但不是虚拟环境。请先将这个目录移到别处，再重试。'
    if "$RBB_VENV" -c 'import sys; sys.exit(sys.version_info < (3, 10) or sys.prefix == sys.base_prefix)' >/dev/null 2>&1; then
        RBB_REBUILD=0
    else
        RBB_REBUILD=1
    fi
else
    RBB_REBUILD=1
fi

if [ "$RBB_REBUILD" -eq 1 ]; then
    RBB_PYTHON=
    for RBB_CANDIDATE in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python; do
        if command -v "$RBB_CANDIDATE" >/dev/null 2>&1 &&
            "$RBB_CANDIDATE" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            RBB_PYTHON=$RBB_CANDIDATE
            break
        fi
    done
    [ -n "$RBB_PYTHON" ] ||
        fail '需要 Python 3.10 或更高版本。请从 https://www.python.org/downloads/ 或系统软件包管理器安装后重试。'
    if [ -e .venv ] || [ -L .venv ]; then
        RBB_BACKUP=".venv.backup-$(date +%Y%m%d-%H%M%S)-$$"
        [ ! -e "$RBB_BACKUP" ] && [ ! -L "$RBB_BACKUP" ] ||
            fail "备份路径已存在：$RBB_BACKUP"
        mv .venv "$RBB_BACKUP" || fail '无法备份旧虚拟环境。请检查项目目录的写入权限。'
        printf '旧虚拟环境已失效，已保存在 %s。\n' "$RBB_BACKUP"
    fi
    printf '正在创建项目虚拟环境 .venv ...\n'
    "$RBB_PYTHON" -m venv .venv ||
        fail '创建虚拟环境失败。请检查上方错误，并确认当前 Python 安装包含 venv/ensurepip 组件。'
fi

if ! "$RBB_VENV" -m pip --version >/dev/null 2>&1; then
    "$RBB_VENV" -m ensurepip --upgrade || fail '无法准备 pip。请检查上方错误。'
fi
"$RBB_VENV" -c 'import tkinter' ||
    fail '当前 Python 缺少 Tk 图形组件。请安装系统对应的 Tk 支持，或使用包含 Tk 的 Python 安装包。'

printf '正在检查并安装界面依赖；首次运行需要联网。\n'
"$RBB_VENV" -m pip install --disable-pip-version-check -r requirements.txt ||
    fail '依赖安装失败。请检查上方网络或安装错误，修复后重新运行 start.sh。'

printf '正在启动 Ren\047Py Bilingual Builder ...\n'
"$RBB_VENV" app/gui.py ||
    fail '界面启动或运行失败。请保留上方错误信息；图形界面需要桌面会话，在纯终端中可使用 README 中的命令行构建方式。'
