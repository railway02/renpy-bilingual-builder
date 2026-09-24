"""Desktop entry point, including visible errors for windowed executables."""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from app.runtime import RuntimePaths, configure_logging


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--decode-worker":
        from app.decompile import worker
        worker(Path(sys.argv[2]))
        return
    log_path = None
    try:
        paths = RuntimePaths.create()
        log_path = configure_logging(paths)
        if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
            from app.smoke import run
            run(paths, Path(sys.argv[2]))
            return
        # Import after logging is ready: missing Tk/assets must leave diagnostics.
        from app.gui import BilingualBuilderApp

        app = BilingualBuilderApp(paths)
        app.mainloop()
    except Exception as exc:
        logging.getLogger("rbb").exception("桌面程序启动或运行失败")
        message = f"无法启动 RenPy 双语工具：\n{exc}"
        if log_path is not None:
            message += f"\n\n详细日志：{log_path}"
        if "--smoke-test" in sys.argv:
            pass  # Automated verification reports failure through its exit code and JSON.
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "RenPy 双语工具", 0x10)
        else:
            print(message, file=sys.stderr)
        raise SystemExit(1) from exc
