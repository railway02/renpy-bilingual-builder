from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATCH_FILE = PROJECT_ROOT / "patches" / "zz_bilingual_ui_patch.rpy"
DEFAULT_BUILD_SCRIPT = PROJECT_ROOT / "tools" / "build_bilingual.py"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Ren'Py Bilingual Builder")
        self.geometry("980x720")
        self.minsize(900, 680)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.build_thread: threading.Thread | None = None
        self.last_report_path: Path | None = None

        self._build_variables()
        self._build_layout()

    def _build_variables(self) -> None:
        self.var_chinese_dir = ctk.StringVar(value=str(PROJECT_ROOT / "input" / "chinese_tl"))
        self.var_original_dir = ctk.StringVar(value=str(PROJECT_ROOT / "input" / "original_english"))
        self.var_output_dir = ctk.StringVar(value=str(PROJECT_ROOT / "output" / "tl" / "chinese"))
        self.var_game_dir = ctk.StringVar(value="")

        self.var_auto_deploy = ctk.BooleanVar(value=True)
        self.var_copy_patch = ctk.BooleanVar(value=True)
        self.var_open_output = ctk.BooleanVar(value=False)
        self.var_safe_mode = ctk.BooleanVar(value=True)

        self.var_status = ctk.StringVar(value="状态：未开始")
        self.var_summary = ctk.StringVar(
            value="processed_statements: -\nunmatched_statements: -\nfallback_from_original: -\nmissing_original: -"
        )

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        title = ctk.CTkLabel(
            self,
            text="Ren'Py Bilingual Builder",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        self.path_frame = ctk.CTkFrame(self)
        self.path_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.path_frame.grid_columnconfigure(1, weight=1)

        self._add_path_row(self.path_frame, 0, "中文翻译目录", self.var_chinese_dir, self._pick_chinese_dir)
        self._add_path_row(self.path_frame, 1, "原始英文目录", self.var_original_dir, self._pick_original_dir)
        self._add_path_row(self.path_frame, 2, "输出目录", self.var_output_dir, self._pick_output_dir)
        self._add_path_row(self.path_frame, 3, "游戏 game 目录", self.var_game_dir, self._pick_game_dir)

        self.option_frame = ctk.CTkFrame(self)
        self.option_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkCheckBox(self.option_frame, text="构建后自动部署", variable=self.var_auto_deploy).grid(
            row=0, column=0, padx=12, pady=12, sticky="w"
        )
        ctk.CTkCheckBox(self.option_frame, text="自动复制 UI patch", variable=self.var_copy_patch).grid(
            row=0, column=1, padx=12, pady=12, sticky="w"
        )
        ctk.CTkCheckBox(self.option_frame, text="构建后打开输出目录", variable=self.var_open_output).grid(
            row=0, column=2, padx=12, pady=12, sticky="w"
        )
        ctk.CTkCheckBox(self.option_frame, text="安全模式（预留）", variable=self.var_safe_mode).grid(
            row=0, column=3, padx=12, pady=12, sticky="w"
        )

        self.action_frame = ctk.CTkFrame(self)
        self.action_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        self.btn_build = ctk.CTkButton(self.action_frame, text="开始构建", command=self.start_build)
        self.btn_build.grid(row=0, column=0, padx=10, pady=12)

        self.btn_deploy = ctk.CTkButton(self.action_frame, text="一键部署", command=self.deploy_only)
        self.btn_deploy.grid(row=0, column=1, padx=10, pady=12)

        self.btn_open_output = ctk.CTkButton(self.action_frame, text="打开输出目录", command=self.open_output_dir)
        self.btn_open_output.grid(row=0, column=2, padx=10, pady=12)

        self.btn_open_report = ctk.CTkButton(self.action_frame, text="打开报告", command=self.open_report)
        self.btn_open_report.grid(row=0, column=3, padx=10, pady=12)

        self.info_frame = ctk.CTkFrame(self)
        self.info_frame.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
        self.info_frame.grid_columnconfigure(0, weight=1)
        self.info_frame.grid_rowconfigure(2, weight=1)

        self.status_label = ctk.CTkLabel(self.info_frame, textvariable=self.var_status, anchor="w")
        self.status_label.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")

        self.summary_box = ctk.CTkTextbox(self.info_frame, height=90)
        self.summary_box.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self.summary_box.insert("1.0", self.var_summary.get())
        self.summary_box.configure(state="disabled")

        self.log_box = ctk.CTkTextbox(self.info_frame)
        self.log_box.grid(row=2, column=0, padx=12, pady=(6, 12), sticky="nsew")

    def _add_path_row(self, parent, row: int, label: str, variable: ctk.StringVar, callback) -> None:
        ctk.CTkLabel(parent, text=label, width=120, anchor="w").grid(
            row=row, column=0, padx=12, pady=8, sticky="w"
        )
        ctk.CTkEntry(parent, textvariable=variable).grid(
            row=row, column=1, padx=12, pady=8, sticky="ew"
        )
        ctk.CTkButton(parent, text="浏览", width=80, command=callback).grid(
            row=row, column=2, padx=12, pady=8
        )

    def _pick_chinese_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.var_chinese_dir.set(path)

    def _pick_original_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.var_original_dir.set(path)

    def _pick_output_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.var_output_dir.set(path)

    def _pick_game_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.var_game_dir.set(path)

    def log(self, text: str) -> None:
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.update_idletasks()

    def set_status(self, text: str) -> None:
        self.var_status.set(f"状态：{text}")
        self.update_idletasks()

    def validate_paths(self) -> bool:
        chinese_dir = Path(self.var_chinese_dir.get())
        original_dir = Path(self.var_original_dir.get())
        output_dir = Path(self.var_output_dir.get())

        if not chinese_dir.exists():
            messagebox.showerror("错误", "中文翻译目录不存在")
            return False
        if not original_dir.exists():
            messagebox.showerror("错误", "原始英文目录不存在")
            return False
        if not output_dir.parent.exists():
            output_dir.parent.mkdir(parents=True, exist_ok=True)

        required_candidates = ["script.rpy", "script2.rpy", "gallery_replay.rpy"]
        missing = [f for f in required_candidates if not (chinese_dir / f).exists()]
        if missing:
            messagebox.showwarning("提示", f"中文目录里缺少部分目标文件：{', '.join(missing)}")

        if not DEFAULT_BUILD_SCRIPT.exists():
            messagebox.showerror("错误", f"未找到构建脚本：{DEFAULT_BUILD_SCRIPT}")
            return False

        return True

    def start_build(self) -> None:
        if self.build_thread and self.build_thread.is_alive():
            messagebox.showinfo("提示", "当前已有构建任务在运行")
            return

        if not self.validate_paths():
            return

        self.log_box.delete("1.0", "end")
        self.set_status("构建中")
        self.btn_build.configure(state="disabled")

        self.build_thread = threading.Thread(target=self._run_build, daemon=True)
        self.build_thread.start()

    def _run_build(self) -> None:
        chinese_dir = Path(self.var_chinese_dir.get())
        original_dir = Path(self.var_original_dir.get())
        output_dir = Path(self.var_output_dir.get())
        report_path = PROJECT_ROOT / "output" / "reports" / "build_report_gui.json"

        cmd = [
            "python",
            str(DEFAULT_BUILD_SCRIPT),
            "--src",
            str(chinese_dir),
            "--src-original",
            str(original_dir),
            "--dst",
            str(output_dir),
            "--report-json",
            str(report_path),
        ]

        self.last_report_path = report_path
        self.log("执行命令：")
        self.log(" ".join(cmd))
        self.log("-" * 60)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            assert proc.stdout is not None
            for line in proc.stdout:
                self.log(line.rstrip())

            code = proc.wait()

            if code != 0:
                self.set_status("构建失败")
                messagebox.showerror("构建失败", f"构建器退出码：{code}")
                return

            self.set_status("构建完成")
            self.load_report_summary(report_path)

            if self.var_auto_deploy.get():
                self.deploy_to_game()

            if self.var_open_output.get():
                self.open_output_dir()

        except Exception as e:
            self.set_status("构建异常")
            self.log(f"[EXCEPTION] {e}")
            messagebox.showerror("异常", str(e))
        finally:
            self.btn_build.configure(state="normal")

    def load_report_summary(self, report_path: Path) -> None:
        if not report_path.exists():
            self.log("未找到报告文件，无法显示摘要。")
            return

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            summary = (
                f"processed_statements: {data.get('processed_statements', '-')}\n"
                f"unmatched_statements: {data.get('unmatched_statements', '-')}\n"
                f"fallback_from_original: {data.get('fallback_english_from_original_statements', '-')}\n"
                f"missing_original: {data.get('missing_original_statements', '-')}"
            )
            self.var_summary.set(summary)
            self.summary_box.configure(state="normal")
            self.summary_box.delete("1.0", "end")
            self.summary_box.insert("1.0", summary)
            self.summary_box.configure(state="disabled")
        except Exception as e:
            self.log(f"读取报告失败：{e}")

    def deploy_only(self) -> None:
        try:
            self.deploy_to_game()
        except Exception as e:
            messagebox.showerror("部署失败", str(e))

    def deploy_to_game(self) -> None:
        game_dir = Path(self.var_game_dir.get().strip())
        output_dir = Path(self.var_output_dir.get().strip())

        if not game_dir.exists():
            raise FileNotFoundError("游戏 game 目录不存在")
        if not output_dir.exists():
            raise FileNotFoundError("输出目录不存在，请先构建")

        target_tl = game_dir / "tl" / "chinese"
        target_tl.parent.mkdir(parents=True, exist_ok=True)

        if target_tl.exists():
            shutil.rmtree(target_tl)
        shutil.copytree(output_dir, target_tl)

        self.log(f"已复制双语文件到：{target_tl}")

        if self.var_copy_patch.get():
            if not PATCH_FILE.exists():
                raise FileNotFoundError(f"未找到 UI patch：{PATCH_FILE}")
            shutil.copy2(PATCH_FILE, game_dir / PATCH_FILE.name)
            self.log(f"已复制 UI patch 到：{game_dir / PATCH_FILE.name}")

        self.set_status("已部署")
        messagebox.showinfo("完成", "部署完成")

    def open_output_dir(self) -> None:
        path = Path(self.var_output_dir.get().strip())
        if not path.exists():
            messagebox.showwarning("提示", "输出目录不存在")
            return

        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(["xdg-open", str(path)])

    def open_report(self) -> None:
        if not self.last_report_path or not self.last_report_path.exists():
            messagebox.showwarning("提示", "报告文件不存在，请先运行构建")
            return

        try:
            os.startfile(self.last_report_path)  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(["xdg-open", str(self.last_report_path)])


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()