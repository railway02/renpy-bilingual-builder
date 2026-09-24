"""Read-only application resources and per-user writable data locations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile


APP_ID = "RenPyBilingualBuilder"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent


def protected_directories() -> tuple[Path, ...]:
    roots = [resource_root()]
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    return tuple(roots)


def overlaps(first: Path, second: Path) -> bool:
    first, second = first.resolve(), second.resolve()
    return first == second or first in second.parents or second in first.parents


@dataclass(frozen=True)
class RuntimePaths:
    resources: Path
    data: Path

    @property
    def output(self) -> Path:
        return self.data / "output"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def reports(self) -> Path:
        return self.data / "reports"

    @property
    def work(self) -> Path:
        return self.data / "work"

    @classmethod
    def create(cls) -> RuntimePaths:
        candidates = []
        if sys.platform == "win32":
            if os.environ.get("LOCALAPPDATA"):
                candidates.append(Path(os.environ["LOCALAPPDATA"]) / APP_ID)
            candidates.append(Path.home() / "AppData" / "Local" / APP_ID)
        else:
            if os.environ.get("XDG_DATA_HOME"):
                candidates.append(Path(os.environ["XDG_DATA_HOME"]) / APP_ID)
            candidates.append(Path.home() / ".local" / "share" / APP_ID)
        # Last resort for restricted profiles; never fall back to the EXE directory.
        candidates.append(Path(tempfile.gettempdir()) / APP_ID)
        errors = []
        for candidate in candidates:
            if not candidate.is_absolute() or any(overlaps(candidate, root) for root in protected_directories()):
                continue
            paths = cls(resource_root(), candidate.resolve())
            try:
                for directory in (paths.logs, paths.reports, paths.output, paths.work):
                    directory.mkdir(parents=True, exist_ok=True)
                    # os.access does not reliably reflect Windows ACLs.
                    with tempfile.TemporaryFile(dir=directory):
                        pass
                return paths
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
        raise OSError("无法创建可写的日志和工作目录。\n" + "\n".join(errors))

    def validate_output(self, output: Path) -> None:
        protected = (*protected_directories(), self.resources, self.logs, self.reports, self.work)
        if any(overlaps(output, root) for root in protected):
            raise ValueError("输出目录不能覆盖程序资源、日志或报告。请选择单独的双语输出文件夹。")


def configure_logging(paths: RuntimePaths) -> Path:
    log_path = paths.logs / "builder.log"
    logger = logging.getLogger("rbb")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("启动；资源目录=%s；用户目录=%s", paths.resources, paths.data)
    return log_path
