from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Iterable

import customtkinter as ctk


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATCH_FILE = PROJECT_ROOT / "patches" / "zz_bilingual_ui_patch.rpy"
REPORT_PATH = PROJECT_ROOT / "output" / "reports" / "build_report_gui.json"
BUILD_SCRIPT_CANDIDATES = (
    PROJECT_ROOT / "tools" / "build_bilingual.py",
    PROJECT_ROOT / "tools" / "bulid_bilingual.py",
)
SOFT_REQUIRED_RPY_FILES = ("script.rpy", "script2.rpy", "gallery_replay.rpy")
REPORT_FIELDS = (
    "processed_statements",
    "unmatched_statements",
    "fallback_english_from_original_statements",
    "missing_original_statements",
)


class BilingualBuilderApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Ren'Py Bilingual Builder")
        self.geometry("980x720")
        self.minsize(860, 620)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_report_path = REPORT_PATH

        self._build_variables()
        self._build_layout()
        self.after(100, self._drain_ui_queue)

    def _build_variables(self) -> None:
        self.chinese_tl_dir = ctk.StringVar(value=str(PROJECT_ROOT / "input" / "chinese_tl"))
        self.original_english_dir = ctk.StringVar(
            value=str(PROJECT_ROOT / "input" / "original_english")
        )
        self.output_dir = ctk.StringVar(value=str(PROJECT_ROOT / "output" / "tl" / "chinese"))
        self.game_dir = ctk.StringVar(value="")
        self.status_text = ctk.StringVar(value="状态：未开始")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkLabel(
            self,
            text="Ren'Py Bilingual Builder",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="w")

        path_frame = ctk.CTkFrame(self)
        path_frame.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        path_frame.grid_columnconfigure(1, weight=1)

        self._add_path_row(
            path_frame,
            0,
            "中文翻译目录 chinese_tl",
            self.chinese_tl_dir,
            lambda: self._choose_directory(self.chinese_tl_dir),
        )
        self._add_path_row(
            path_frame,
            1,
            "原始英文目录 original_english",
            self.original_english_dir,
            lambda: self._choose_directory(self.original_english_dir),
        )
        self._add_path_row(
            path_frame,
            2,
            "输出目录 output/tl/chinese",
            self.output_dir,
            lambda: self._choose_directory(self.output_dir),
        )
        self._add_path_row(
            path_frame,
            3,
            "游戏 game 目录",
            self.game_dir,
            lambda: self._choose_directory(self.game_dir),
        )

        actions = ctk.CTkFrame(self)
        actions.grid(row=2, column=0, padx=20, pady=8, sticky="ew")

        self.build_button = ctk.CTkButton(actions, text="开始构建", command=self.start_build)
        self.build_button.grid(row=0, column=0, padx=10, pady=12)

        self.deploy_button = ctk.CTkButton(actions, text="一键部署", command=self.start_deploy)
        self.deploy_button.grid(row=0, column=1, padx=10, pady=12)

        self.open_output_button = ctk.CTkButton(
            actions,
            text="打开输出目录",
            command=self.open_output_dir,
        )
        self.open_output_button.grid(row=0, column=2, padx=10, pady=12)

        self.open_report_button = ctk.CTkButton(actions, text="打开报告", command=self.open_report)
        self.open_report_button.grid(row=0, column=3, padx=10, pady=12)

        body = ctk.CTkFrame(self)
        body.grid(row=3, column=0, padx=20, pady=(8, 20), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        status = ctk.CTkLabel(body, textvariable=self.status_text, anchor="w")
        status.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")

        self.summary_box = ctk.CTkTextbox(body, height=104)
        self.summary_box.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self._set_summary({})

        self.log_box = ctk.CTkTextbox(body)
        self.log_box.grid(row=2, column=0, padx=12, pady=(6, 12), sticky="nsew")

    def _add_path_row(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: ctk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row,
            column=0,
            padx=12,
            pady=8,
            sticky="w",
        )
        ctk.CTkEntry(parent, textvariable=variable).grid(
            row=row,
            column=1,
            padx=12,
            pady=8,
            sticky="ew",
        )
        ctk.CTkButton(parent, text="选择", width=84, command=command).grid(
            row=row,
            column=2,
            padx=12,
            pady=8,
        )

    def _choose_directory(self, variable: ctk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def start_build(self) -> None:
        if self._is_worker_running():
            messagebox.showinfo("正在运行", "当前已有任务在运行。")
            return

        build_script = self._validate_build_inputs()
        if build_script is None:
            return

        src_dir = self.chinese_tl_dir.get()
        original_dir = self.original_english_dir.get()
        dst_dir = self.output_dir.get()

        self._clear_log()
        self._set_status("构建中")
        self._set_buttons_enabled(False)
        self.last_report_path = REPORT_PATH

        self.worker = threading.Thread(
            target=self._run_build,
            args=(build_script, src_dir, original_dir, dst_dir),
            daemon=True,
        )
        self.worker.start()

    def start_deploy(self) -> None:
        if self._is_worker_running():
            messagebox.showinfo("正在运行", "当前已有任务在运行。")
            return

        deploy_paths = self._validate_deploy_inputs()
        if deploy_paths is None:
            return

        _, game_dir = deploy_paths
        target_tl = game_dir / "tl" / "chinese"
        confirmed = messagebox.askyesno(
            "确认部署",
            f"一键部署将覆盖：\n{target_tl}\n\n"
            "如果该目录已存在，会先自动备份为 chinese_backup_YYYYMMDD_HHMMSS。\n\n"
            "是否继续？",
        )
        if not confirmed:
            return

        self._set_status("部署中")
        self._set_buttons_enabled(False)
        self.worker = threading.Thread(target=self._run_deploy, args=deploy_paths, daemon=True)
        self.worker.start()

    def _run_build(
        self,
        build_script: Path,
        src_dir: str,
        original_dir: str,
        dst_dir: str,
    ) -> None:
        report_path = REPORT_PATH

        cmd = [
            sys.executable,
            "-u",
            str(build_script),
            "--src",
            src_dir,
            "--src-original",
            original_dir,
            "--dst",
            dst_dir,
            "--report-json",
            str(report_path),
        ]

        self._queue_log("执行命令：")
        self._queue_log(" ".join(cmd))
        self._queue_log("-" * 72)

        try:
            process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                self._queue_log(line.rstrip("\n"))

            return_code = process.wait()
            if return_code != 0:
                self._queue_status("构建失败")
                self._queue_message("error", "构建失败", f"构建命令退出码：{return_code}")
                return

            self._queue_status("构建完成")
            self._queue_log("-" * 72)
            self._queue_log(f"报告已生成：{report_path}")
            self._load_report_summary(report_path)
        except Exception as exc:
            self._queue_status("构建异常")
            self._queue_log(f"[异常] {exc}")
            self._queue_message("error", "构建异常", str(exc))
        finally:
            self._queue_buttons(True)

    def _run_deploy(self, output_dir: Path, game_dir: Path) -> None:
        try:
            target_tl, target_patch, backup_tl = self._deploy_to_game(output_dir, game_dir)
            self._queue_status("部署完成")
            if backup_tl is not None:
                self._queue_log(f"已备份原目录到：{backup_tl}")
            self._queue_log(f"已复制输出目录到：{target_tl}")
            self._queue_log(f"已复制 UI patch 到：{target_patch}")
            self._queue_message("info", "部署完成", "一键部署完成。")
        except Exception as exc:
            self._queue_status("部署失败")
            self._queue_log(f"[部署失败] {exc}")
            self._queue_message("error", "部署失败", str(exc))
        finally:
            self._queue_buttons(True)

    def _deploy_to_game(self, output_dir: Path, game_dir: Path) -> tuple[Path, Path, Path | None]:
        target_tl = game_dir / "tl" / "chinese"
        target_patch = game_dir / PATCH_FILE.name
        backup_tl: Path | None = None

        target_tl.parent.mkdir(parents=True, exist_ok=True)
        if target_tl.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_tl = target_tl.with_name(f"chinese_backup_{timestamp}")
            if backup_tl.exists():
                raise FileExistsError(f"备份目录已存在：{backup_tl}")
            shutil.move(str(target_tl), str(backup_tl))
        shutil.copytree(output_dir, target_tl)
        shutil.copy2(PATCH_FILE, target_patch)
        return target_tl, target_patch, backup_tl

    def _validate_build_inputs(self) -> Path | None:
        chinese_dir = Path(self.chinese_tl_dir.get()).expanduser()
        original_dir = Path(self.original_english_dir.get()).expanduser()

        if not self._require_directory(chinese_dir, "中文翻译目录 chinese_tl"):
            return None
        if not self._require_directory(original_dir, "原始英文目录 original_english"):
            return None

        build_script = self._find_build_script()
        if build_script is None:
            expected = "\n".join(str(path) for path in BUILD_SCRIPT_CANDIDATES)
            messagebox.showerror("缺少构建器", f"未找到构建脚本：\n{expected}")
            return None

        if not PATCH_FILE.exists():
            messagebox.showerror("缺少 patch 文件", f"未找到：\n{PATCH_FILE}")
            return None

        output_parent = Path(self.output_dir.get()).expanduser().parent
        output_parent.mkdir(parents=True, exist_ok=True)
        self._warn_missing_dialogue_files((chinese_dir, original_dir))

        if build_script.name == "bulid_bilingual.py":
            messagebox.showwarning(
                "构建脚本文件名",
                "未找到 tools/build_bilingual.py，将使用当前仓库中的 tools/bulid_bilingual.py。",
            )

        return build_script.resolve()

    def _validate_deploy_inputs(self) -> tuple[Path, Path] | None:
        output_dir = Path(self.output_dir.get()).expanduser()
        game_dir = Path(self.game_dir.get()).expanduser()

        if not self._require_directory(output_dir, "输出目录 output/tl/chinese"):
            return None
        if not self._require_directory(game_dir, "游戏 game 目录"):
            return None
        if not PATCH_FILE.exists():
            messagebox.showerror("缺少 patch 文件", f"未找到：\n{PATCH_FILE}")
            return None
        return output_dir.resolve(), game_dir.resolve()

    def _warn_missing_dialogue_files(self, directories: Iterable[Path]) -> None:
        warnings: list[str] = []
        for directory in directories:
            missing = [name for name in SOFT_REQUIRED_RPY_FILES if not (directory / name).exists()]
            if missing:
                warnings.append(f"{directory} 缺少：{', '.join(missing)}")

        if warnings:
            messagebox.showwarning("文件提醒", "\n".join(warnings))

    def _require_directory(self, path: Path, label: str) -> bool:
        if not path.exists() or not path.is_dir():
            messagebox.showerror("路径不存在", f"{label} 不存在：\n{path}")
            return False
        return True

    def _find_build_script(self) -> Path | None:
        for candidate in BUILD_SCRIPT_CANDIDATES:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _load_report_summary(self, report_path: Path) -> None:
        if not report_path.exists():
            self._queue_log("未找到报告文件，无法显示摘要。")
            return

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.ui_queue.put(("summary", {field: data.get(field, "-") for field in REPORT_FIELDS}))
        except Exception as exc:
            self._queue_log(f"读取报告失败：{exc}")

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_dir.get()).expanduser()
        if not output_dir.exists():
            messagebox.showwarning("路径不存在", f"输出目录不存在：\n{output_dir}")
            return
        self._open_path(output_dir)

    def open_report(self) -> None:
        report_path = self.last_report_path
        if not report_path.exists():
            messagebox.showwarning("报告不存在", f"报告文件不存在：\n{report_path}")
            return
        self._open_path(report_path)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def _is_worker_running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def _set_summary(self, values: dict[str, object]) -> None:
        lines = [f"{field}: {values.get(field, '-')}" for field in REPORT_FIELDS]
        self.summary_box.configure(state="normal")
        self.summary_box.delete("1.0", "end")
        self.summary_box.insert("1.0", "\n".join(lines))
        self.summary_box.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text.set(f"状态：{text}")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.build_button.configure(state=state)
        self.deploy_button.configure(state=state)

    def _queue_log(self, text: str) -> None:
        self.ui_queue.put(("log", text))

    def _queue_status(self, text: str) -> None:
        self.ui_queue.put(("status", text))

    def _queue_buttons(self, enabled: bool) -> None:
        self.ui_queue.put(("buttons", enabled))

    def _queue_message(self, kind: str, title: str, body: str) -> None:
        self.ui_queue.put(("message", (kind, title, body)))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                action, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if action == "log":
                self._append_log(str(payload))
            elif action == "status":
                self._set_status(str(payload))
            elif action == "summary":
                self._set_summary(payload)  # type: ignore[arg-type]
            elif action == "buttons":
                self._set_buttons_enabled(bool(payload))
            elif action == "message":
                kind, title, body = payload  # type: ignore[misc]
                if kind == "error":
                    messagebox.showerror(title, body)
                else:
                    messagebox.showinfo(title, body)

        self.after(100, self._drain_ui_queue)


def main() -> None:
    app = BilingualBuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
