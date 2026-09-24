from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

# Also support the documented `python app/gui.py` entry point.
if not __package__ and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.deployment import check_generic_profile, deploy_to_game, validate_game_directory
from app.runtime import RuntimePaths, resource_root
from app.archive import ImportProblem
from app.import_pipeline import import_inputs, build_imported, normalize_game
from app.package_deployment import deploy_package, read_plan
from app.reporting import save_failure_report
from tools.build_bilingual import build, discover_languages, validate_language, NoReliableDialogueError

RESOURCE_ROOT = resource_root()
PATCH_FILE = RESOURCE_ROOT / "patches" / "zz_bilingual_ui_patch.rpy"
LOGGER = logging.getLogger("rbb")
GENERIC_PROFILE = "通用 Ren'Py（保留游戏界面）"
ETERNUM_PROFILE = "永恒世界 0.9.5（中文排版修复）"
PROFILES = (GENERIC_PROFILE, ETERNUM_PROFILE)


@dataclass(frozen=True)
class BuildSettings:
    source: str
    original: str
    language: str
    profile: str
    imported_input: str = ""
    imported_game: str = ""
    candidate: str = ""


REPORT_FIELDS = (
    "processed_statements",
    "unmatched_statements",
    "fallback_english_from_original_statements",
    "missing_original_statements",
)
REPORT_FIELD_LABELS = {
    "processed_statements": "已处理对白",
    "unmatched_statements": "未匹配对白",
    "fallback_english_from_original_statements": "英文兜底",
    "missing_original_statements": "缺失原文",
}
DIAGNOSTIC_REASON_LABELS = {
    "ambiguous_original_id": "同一翻译标识对应多个不同原文，已保留译文",
    "no_reliable_english": "未找到可靠英文，已保留原翻译",
    "unsupported_raw_string": "原始字符串语法暂不支持，已保留原翻译块",
    "unsupported_triple_quoted_string": "三引号字符串语法暂不支持，已保留原翻译块",
    "unsupported_quote_delimiter": "字符串引号格式暂不支持，已保留原翻译块",
    "unsupported_multiline_or_unterminated_string": "字符串跨行或引号未闭合，已保留原翻译块",
    "unsupported_multiline_string": "实际跨行字符串暂不支持，已保留原翻译块",
    "unsupported_quoted_speaker": "带引号的说话人语法暂不支持，已保留原翻译块",
}


class BilingualBuilderApp(ctk.CTk):
    def __init__(self, paths: RuntimePaths | None = None) -> None:
        self.paths = paths or RuntimePaths.create()
        super().__init__()

        self.title("RenPy 双语工具")
        self.geometry("1040x760")
        self.minsize(920, 650)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.task_active = False
        self.last_report_path: Path | None = None
        self.build_succeeded = False
        self.built_output_dir: Path | None = None
        self.built_settings: BuildSettings | None = None
        self.import_session = None
        self.import_key = None
        self.built_package = False
        self.needs_review = False
        self.report_is_current = False

        self._build_variables()
        self._build_layout()
        self.output_dir.trace_add("write", self._on_output_changed)
        for variable in (self.chinese_tl_dir, self.original_english_dir, self.language, self.profile):
            variable.trace_add("write", self._on_settings_changed)
        for variable in (self.input_path, self.game_dir):
            variable.trace_add("write", self._on_import_input_changed)
        self.candidate_choice.trace_add("write", self._on_candidate_changed)
        self.after(100, self._drain_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._append_log(f"日志目录：{self.paths.logs}")

    def _build_variables(self) -> None:
        self.chinese_tl_dir = ctk.StringVar(value="")
        self.input_path = ctk.StringVar(value="")
        self.candidate_choice = ctk.StringVar(value="")
        self.original_english_dir = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value=str(self.paths.output / "bilingual"))
        self.language = ctk.StringVar(value="")
        self.profile = ctk.StringVar(value=GENERIC_PROFILE)
        self.profile_help = ctk.StringVar(value="通用模式只生成双语对白，沿用游戏原有字号和界面。")
        self.game_dir = ctk.StringVar(value="")
        self.status_text = ctk.StringVar(value="状态：未开始")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkLabel(
            self,
            text="RenPy 双语工具",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="选择游戏或汉化 → 检查并生成双语 → 备份并安装。已有原文自动匹配；本工具不自动翻译。",
            anchor="w",
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")

        path_frame = ctk.CTkScrollableFrame(self, height=300)
        path_frame.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        path_frame.grid_columnconfigure(1, weight=1)
        self._add_path_row(path_frame, 0, "1. 选择游戏", self.game_dir, self._choose_game_directory)
        ctk.CTkLabel(path_frame, text="选择游戏所在文件夹，工具会自动寻找原文和已安装的汉化。", anchor="w").grid(
            row=1, column=1, columnspan=2, padx=12, sticky="w")
        self._add_path_row(path_frame, 2, "另选汉化（可选）", self.input_path, self._choose_package)
        ctk.CTkButton(path_frame, text="选择汉化文件夹", width=140,
                      command=lambda: self._choose_directory(self.input_path)).grid(row=3, column=2, padx=12, pady=6)
        ctk.CTkLabel(path_frame, text="支持标准 RPA 包和 RPY / RPYC / RPYM / RPYMC；无需手动解包。", anchor="w").grid(
            row=3, column=1, padx=12, sticky="w")
        self.candidate_frame = ctk.CTkFrame(path_frame)
        self.candidate_frame.grid(row=4, column=0, columnspan=3, padx=12, pady=8, sticky="ew")
        self.candidate_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.candidate_frame, text="选择汉化与语言").grid(row=0, column=0, padx=10, pady=8)
        self.candidate_menu = ctk.CTkOptionMenu(self.candidate_frame, variable=self.candidate_choice, values=[""], width=560)
        self.candidate_menu.grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        self.candidate_frame.grid_remove()

        self.advanced_frame = ctk.CTkFrame(path_frame)
        self.advanced_frame.grid(row=5, column=0, columnspan=3, padx=8, pady=8, sticky="ew")
        self.advanced_frame.grid_columnconfigure(1, weight=1)
        self._add_path_row(self.advanced_frame, 0, "输出目录", self.output_dir,
                           lambda: self._choose_directory(self.output_dir))
        ctk.CTkLabel(self.advanced_frame, text="游戏配置").grid(row=1, column=0, padx=12, pady=8, sticky="w")
        ctk.CTkOptionMenu(self.advanced_frame, variable=self.profile, values=list(PROFILES), width=350).grid(
            row=1, column=1, padx=12, pady=8, sticky="w")
        ctk.CTkLabel(self.advanced_frame, textvariable=self.profile_help, anchor="w").grid(
            row=2, column=1, columnspan=2, padx=12, pady=4, sticky="w")
        self._add_path_row(self.advanced_frame, 3, "原脚本模式（可选）", self.chinese_tl_dir, self._choose_translation_directory)
        self._add_path_row(self.advanced_frame, 4, "原文目录（高级）", self.original_english_dir,
                           lambda: self._choose_directory(self.original_english_dir))
        self.language_menu = ctk.CTkOptionMenu(self.advanced_frame, variable=self.language, values=[""], width=260)
        self.language_menu.grid(row=5, column=1, padx=12, pady=8, sticky="w")
        ctk.CTkButton(self.advanced_frame, text="识别脚本语言", width=120, command=self._refresh_languages).grid(
            row=5, column=2, padx=12, pady=8)
        self.advanced_frame.grid_remove()

        actions = ctk.CTkFrame(self)
        actions.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        self.build_button = ctk.CTkButton(actions, text="2. 检查并生成双语", width=190, command=self.start_build)
        self.build_button.grid(row=0, column=0, padx=12, pady=12)
        self.deploy_button = ctk.CTkButton(actions, text="3. 备份并安装", width=190, command=self.start_deploy, state="disabled")
        self.deploy_button.grid(row=0, column=1, padx=12, pady=12)
        self.sample_button = ctk.CTkButton(actions, text="试用内置示例", width=120, command=self.load_sample)
        self.sample_button.grid(row=0, column=2, padx=12, pady=12)
        ctk.CTkButton(actions, text="更多选项", width=110, command=self._toggle_advanced).grid(row=0, column=3, padx=12, pady=12)

        body = ctk.CTkFrame(self)
        body.grid(row=4, column=0, padx=20, pady=(8, 20), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(body, textvariable=self.status_text, anchor="w", wraplength=850).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        self.summary_box = ctk.CTkTextbox(body, height=48)
        self.summary_box.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self._set_summary({})
        extra = ctk.CTkFrame(body, fg_color="transparent")
        extra.grid(row=2, column=0, sticky="w")
        self.open_output_button = ctk.CTkButton(extra, text="打开输出目录", width=120, command=self.open_output_dir)
        self.open_output_button.grid(row=0, column=0, padx=12, pady=8)
        self.open_report_button = ctk.CTkButton(extra, text="打开报告", width=110, command=self.open_report)
        self.open_report_button.grid(row=0, column=1, padx=12, pady=8)
        ctk.CTkButton(extra, text="查看详情", width=110, command=self._toggle_details).grid(row=0, column=2, padx=12, pady=8)
        ctk.CTkButton(extra, text="打开日志文件夹", width=130, command=lambda: self._open_path(self.paths.logs)).grid(
            row=0, column=3, padx=12, pady=8)
        self.log_box = ctk.CTkTextbox(body)
        self.log_box.grid(row=3, column=0, padx=12, pady=(6, 12), sticky="nsew")
        self.log_box.grid_remove()

    def _toggle_advanced(self):
        if self.advanced_frame.winfo_ismapped():
            self.advanced_frame.grid_remove()
        else:
            self.advanced_frame.grid()

    def _toggle_details(self):
        if self.log_box.winfo_ismapped():
            self.log_box.grid_remove()
        else:
            self.log_box.grid()

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
            if variable is self.__dict__.get("input_path"):
                self.chinese_tl_dir.set("")
                self.original_english_dir.set("")
            variable.set(path)

    def _choose_translation_directory(self) -> None:
        path = filedialog.askdirectory(title="选择 game/tl/下含 .rpy 的翻译语言文件夹")
        if path:
            if "input_path" in self.__dict__:
                self.input_path.set("")
            self.chinese_tl_dir.set(path)
            self._refresh_languages()

    def _choose_package(self) -> None:
        path = filedialog.askopenfilename(title="选择汉化包或脚本", filetypes=[
            ("Ren'Py 汉化包和脚本", "*.rpa *.rpy *.rpyc *.rpym *.rpymc"), ("所有文件", "*.*")])
        if path:
            self.chinese_tl_dir.set("")
            self.original_english_dir.set("")
            self.input_path.set(path)

    def _refresh_languages(self) -> list[str]:
        source = self._entry_directory(self.chinese_tl_dir.get(), "翻译目录")
        if source is None:
            return []
        try:
            languages = discover_languages(source)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法识别语言", str(exc))
            return []
        self.language_menu.configure(values=languages or [""])
        if len(languages) == 1:
            self.language.set(languages[0])
        elif self.language.get() not in languages:
            self.language.set("")
        if not languages:
            messagebox.showerror("未找到翻译", "请选择含 translate 翻译块的 .rpy/.rpym 目录。\n如果拿到的是 RPA 或编译脚本，请使用普通界面的“另选汉化”。")
        elif len(languages) > 1:
            self._set_status("发现多个翻译语言，请在语言菜单中选择；建议直接选择对应的语言子目录")
        return languages

    def load_sample(self) -> None:
        if self._is_worker_running():
            return
        if "input_path" in self.__dict__:
            self.input_path.set("")
        self.chinese_tl_dir.set(str(self.paths.resources / "samples/demo/chinese"))
        self.original_english_dir.set(str(self.paths.resources / "samples/demo/original"))
        self.output_dir.set(str(self.paths.output / "demo/tl/chinese"))
        self.game_dir.set("")
        self.profile.set(GENERIC_PROFILE)
        self._refresh_languages()
        self._set_status("已载入原创示例，点击“检查并生成双语”即可体验；无需游戏文件")

    def _selected_language(self) -> str:
        variable = self.__dict__.get("language")
        return variable.get().strip() if variable is not None else "chinese"

    def _selected_profile(self) -> str:
        variable = self.__dict__.get("profile")
        return variable.get() if variable is not None else GENERIC_PROFILE

    def _current_settings(self) -> BuildSettings:
        def normalized(value: str) -> str:
            return str(self._resolve_entry_path(value).resolve()) if value.strip() else ""
        return BuildSettings(
            normalized(self.chinese_tl_dir.get()) if not self._import_mode() else "",
            normalized(self.original_english_dir.get()) if not self._import_mode() else "",
            self._selected_language(), self._selected_profile(),
            normalized(self.input_path.get()) if "input_path" in self.__dict__ and self._import_mode() else "",
            normalized(self.game_dir.get()) if self._import_mode() else "",
            self.candidate_choice.get() if "candidate_choice" in self.__dict__ and self._import_mode() else "",
        )

    def _choose_game_directory(self) -> None:
        path = filedialog.askdirectory()
        if path:
            game_dir = self._normalize_game_dir(Path(path))
            self.game_dir.set(self._format_path_for_entry(game_dir))

    def _import_mode(self) -> bool:
        variable = self.__dict__.get("input_path")
        return bool(variable and variable.get().strip()) or not self.chinese_tl_dir.get().strip()

    def _input_key(self):
        def absolute(value):
            return str(self._resolve_entry_path(value)) if value.strip() else ""
        return absolute(self.game_dir.get()), absolute(self.input_path.get())

    def _on_import_input_changed(self, *_args):
        if self.game_dir.get().strip() and self._is_demo_source():
            self.chinese_tl_dir.set("")
            self.original_english_dir.set("")
        self.import_key = None
        self._on_settings_changed()

    def _on_candidate_changed(self, *_args):
        session = self.import_session
        if session is not None:
            candidate = next((c for c in session.candidates if c.label == self.candidate_choice.get()), None)
            if candidate is not None:
                self.language.set(candidate.language)
        self._on_settings_changed()

    def _import_progress(self, message):
        self._queue_log(message)
        visible = "正在生成双语文件" if message.startswith(("[", "正在准备临时")) else message
        self._queue_status(visible)

    @staticmethod
    def _friendly_error(exc):
        if isinstance(exc, PermissionError):
            return "文件无法读取、写入或正被占用。请关闭游戏，确认输入可读取，并选择自己的文档/下载文件夹作为输出后重试。"
        if isinstance(exc, UnicodeError):
            return "脚本编码无法读取。请向汉化作者获取 UTF-8 编码的原始脚本或标准汉化包。"
        if isinstance(exc, (ImportProblem, ValueError)):
            return str(exc).split("\n", 1)[0] + "\n如需技术原因，请点“查看详情”或打开日志。"
        return "本次操作未完成。请确认游戏已关闭、文件完整且磁盘空间充足，再重新选择输入。技术原因在“查看详情”中。"

    def _start_import_flow(self):
        key = self._input_key()
        if not any(key):
            messagebox.showerror("先选择输入", "请选择游戏文件夹，或通过“另选汉化”选择汉化包。")
            return
        try:
            output = self._resolve_entry_path(self.output_dir.get())
            self.paths.validate_output(output)
            if self._selected_profile() not in PROFILES:
                raise ImportProblem("请在“更多选项”中选择有效的游戏配置。")
        except (OSError, ValueError) as exc:
            messagebox.showerror("请检查设置", self._friendly_error(exc))
            return
        if self.import_key != key or self.import_session is None:
            if self.import_session is not None:
                self.import_session.close()
                self.import_session = None
            self.build_succeeded = False
            self.built_output_dir = None
            self.built_settings = None
            self.built_package = False
            self.task_active = True
            self._clear_log()
            self._set_summary({})
            self._set_status("正在读取游戏和汉化包")
            self._set_buttons_enabled(False)
            self.candidate_choice.set("")
            self.candidate_frame.grid_remove()
            self.worker = threading.Thread(target=self._run_import, args=(key,), daemon=False)
            self.worker.start()
            return
        candidate = next((c for c in self.import_session.candidates if c.label == self.candidate_choice.get()), None)
        if candidate is None:
            messagebox.showinfo("请选择汉化", "发现多个汉化或语言，请在“选择汉化与语言”中选择一项，再点击“检查并生成双语”。")
            return
        if self.profile.get() == ETERNUM_PROFILE and candidate.language != "chinese":
            messagebox.showerror("配置不适用", "永恒世界专用排版只适用于 chinese；请在“更多选项”改为通用模式。")
            return
        self.language.set(candidate.language)
        settings = self._current_settings()
        self.build_succeeded = False
        self.built_output_dir = None
        self.built_settings = None
        self.built_package = False
        self.needs_review = False
        self.task_active = True
        self._set_buttons_enabled(False)
        self._set_status("正在匹配原文")
        report = self.paths.reports / f"build_{uuid.uuid4().hex}.json"
        session = self.import_session
        self.import_key = None  # A subsequent build re-reads inputs, including changed files.
        self.worker = threading.Thread(target=self._run_imported_build,
                                       args=(session, candidate.id, output, report, settings), daemon=False)
        self.worker.start()

    def _run_import(self, key):
        try:
            game, translation = (Path(value) if value else None for value in key)
            demo_root = (self.paths.resources / "samples").resolve()
            demo = translation is not None and (translation == demo_root or demo_root in translation.parents)
            session = import_inputs(game, translation, self.paths.work, self._import_progress, demo=demo)
            self.ui_queue.put(("import_ready", (key, session)))
        except Exception as exc:
            LOGGER.exception("导入失败")
            self._queue_log(str(exc))
            self._queue_status("读取未完成，请检查输入；原游戏未修改")
            self._queue_message("error", "无法读取输入", self._friendly_error(exc))
        finally:
            self._queue_buttons(True)

    def _accept_import(self, key, session):
        if key != self._input_key():
            session.close()
            self._set_status("输入已更改，请重新检查")
            return
        self.import_session = session
        self.import_key = key
        self.candidate_menu.configure(values=[c.label for c in session.candidates])
        self.candidate_frame.grid()
        for warning in session.warnings:
            self._append_log(warning)
        if len(session.candidates) == 1:
            self.candidate_choice.set(session.candidates[0].label)
            self._set_status("已找到汉化，准备匹配原文")
            self.after(150, self._continue_single_import, key, session)
        else:
            self.candidate_choice.set("")
            self._set_status("发现多个汉化或语言，请选择一项，再点击“检查并生成双语”")

    def _continue_single_import(self, key, session):
        if self.import_key == key and self.import_session is session:
            if self._is_worker_running():
                self.after(100, self._continue_single_import, key, session)
            else:
                self.start_build()

    def _queue_failure_diagnostics(self, error, report, output, language):
        if not isinstance(error, NoReliableDialogueError):
            return
        try:
            failed = error.report_path or save_failure_report(error, report, output)
            self._load_report_summary(failed, output, expected_language=language)
            self.ui_queue.put(("failed_report", failed))
            self._queue_log(f"本次失败诊断报告：{failed}")
        except Exception:
            LOGGER.exception("无法保存或读取失败诊断报告")
            self._queue_log("诊断报告未能保存，请检查磁盘空间和日志文件。")

    def _run_imported_build(self, session, candidate_id, output, report, settings):
        try:
            self.paths.validate_output(output)
            summary = build_imported(session, candidate_id, output, report, self._import_progress)
            self._load_report_summary(report, output, expected_language=settings.language)
            self.ui_queue.put(("package_ready", summary["needs_review"]))
            self._queue_build_succeeded(output, report, settings)
        except Exception as exc:
            LOGGER.exception("导入后的双语生成失败")
            self._queue_failure_diagnostics(exc, report, output, settings.language)
            self._queue_log(str(exc))
            self._queue_status("未生成可安装结果，请查看原因；原游戏未修改")
            self._queue_message("error", "无法生成双语", self._friendly_error(exc))
        finally:
            self._queue_buttons(True)

    def start_build(self) -> None:
        if self._is_worker_running():
            messagebox.showinfo("正在运行", "当前已有任务在运行。")
            return

        self.build_succeeded = False
        self.built_output_dir = None
        self.built_settings = None
        self.built_package = False
        self.report_is_current = False
        self._set_buttons_enabled(True)

        if self._import_mode():
            self._start_import_flow()
            return

        if not self._validate_build_inputs():
            self._set_status("请检查输入设置后重试")
            return

        src_dir = str(self._resolve_entry_path(self.chinese_tl_dir.get()))
        original_dir = (str(self._resolve_entry_path(self.original_english_dir.get()))
                        if self.original_english_dir.get().strip() else "")
        dst_dir = str(self._resolve_entry_path(self.output_dir.get()).resolve())
        settings = self._current_settings()

        self.build_succeeded = False
        self.built_package = False
        self.built_output_dir = None
        self.built_settings = None
        self.task_active = True
        self._clear_log()
        self._set_summary({})
        self._set_status("构建中")
        self._set_buttons_enabled(False)
        # Each attempt gets a new report, preserving the previous successful one.
        report_path = self.paths.reports / f"build_{uuid.uuid4().hex}.json"

        self.worker = threading.Thread(
            target=self._run_build,
            args=(src_dir, original_dir, dst_dir, report_path),
            kwargs={"language": settings.language, "settings": settings},
            daemon=False,
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
        settings = self.__dict__.get("built_settings") or self._current_settings()
        package = self.__dict__.get("built_package", False)
        target_tl = game_dir if package else game_dir / "tl" / settings.language
        patch_file = PATCH_FILE if settings.profile == ETERNUM_PROFILE else None
        patch_notice = ("同时安装永恒世界 0.9.5 中文排版补丁。\n" if patch_file is not None
                        else "保留游戏原有界面和字号。\n")
        confirmed = messagebox.askyesno(
            "确认部署",
            f"一键部署将覆盖：\n{target_tl}\n\n"
            + patch_notice + ("本次存在保留原译文的对白，请先检查报告。\n" if self.__dict__.get("needs_review") else "")
            + "涉及的原文件会备份到 game 目录外的 renpy_bilingual_backups；RPA 保持原样。\n"
            "请确认游戏已完全关闭。\n\n"
            "是否继续？",
        )
        if not confirmed:
            return

        self._set_status("部署中")
        self.task_active = True
        self._set_buttons_enabled(False)
        self.worker = threading.Thread(target=self._run_deploy, args=(*deploy_paths, settings.language, patch_file), kwargs={"package": package}, daemon=False)
        self.worker.start()

    def _run_build(
        self,
        src_dir: str,
        original_dir: str,
        dst_dir: str,
        report_path: Path,
        *,
        language: str | None = None,
        settings: BuildSettings | None = None,
    ) -> None:
        try:
            self.paths.validate_output(Path(dst_dir))
            self._queue_log(f"翻译目录：{src_dir}")
            self._queue_log(f"输出目录：{dst_dir}")
            build(
                src=Path(src_dir), src_original=Path(original_dir) if original_dir else None,
                dst=Path(dst_dir), report_path=report_path,
                csv_path=report_path.with_suffix(".csv"), language=language,
                progress=self._queue_log,
                require_changes=True,
            )
            self._load_report_summary(report_path, Path(dst_dir), expected_language=language)
            self._queue_log("-" * 72)
            self._queue_log(f"报告已生成：{report_path}")
            self._queue_build_succeeded(Path(dst_dir), report_path, settings)
        except Exception as exc:
            LOGGER.exception("构建失败")
            self._queue_failure_diagnostics(exc, report_path, Path(dst_dir), language)
            self._queue_status("构建异常")
            self._queue_log(f"[异常] {exc}")
            self._queue_message("error", "构建异常", self._friendly_error(exc))
        finally:
            self._queue_buttons(True)

    def _run_deploy(self, output_dir: Path, game_dir: Path, language: str = "chinese", patch_file: Path | None = None, *, package=False) -> None:
        try:
            if package:
                backup = deploy_package(output_dir, game_dir, patch_file)
                self._queue_status("安装完成，可以启动游戏并选择对应语言")
                self._queue_log(f"备份与恢复说明：{backup}")
                self._queue_message("info", "安装完成", f"安装完成。原 RPA 保持原样。\n备份和恢复说明：{backup}")
                return
            target_tl, target_patch, backup_tl = deploy_to_game(output_dir, game_dir, patch_file, language=language)
            self._queue_status("部署完成")
            if backup_tl is not None:
                self._queue_log(f"已备份原目录到：{backup_tl}")
            self._queue_log(f"已复制输出目录到：{target_tl}")
            if target_patch is not None:
                self._queue_log(f"已复制 UI 补丁到：{target_patch}")
            else:
                self._queue_log("已保留游戏原有界面。")
            self._queue_log("如需恢复：关闭游戏，将备份中的原语言目录替换回 game/tl/，相关 UI 文件也一并恢复。")
            self._queue_message("info", "部署完成", "一键部署完成。")
        except Exception as exc:
            LOGGER.exception("部署失败")
            self._queue_status("部署失败")
            self._queue_log(f"[部署失败] {exc}")
            self._queue_message("error", "部署失败", self._friendly_error(exc))
        finally:
            self._queue_buttons(True)

    def _deploy_to_game(self, output_dir: Path, game_dir: Path) -> tuple[Path, Path | None, Path | None]:
        settings = self.__dict__.get("built_settings") or self._current_settings()
        patch_file = PATCH_FILE if settings.profile == ETERNUM_PROFILE else None
        return deploy_to_game(output_dir, game_dir, patch_file, language=settings.language)

    def _validate_build_inputs(self) -> bool:
        if not self.output_dir.get().strip():
            messagebox.showerror("路径为空", "请选择输出目录。")
            return False

        chinese_dir = self._entry_directory(self.chinese_tl_dir.get(), "已有翻译目录")
        if chinese_dir is None:
            return False
        if self.original_english_dir.get().strip():
            original_dir = self._entry_directory(self.original_english_dir.get(), "原文目录")
            if original_dir is None:
                return False
        try:
            output = self._resolve_entry_path(self.output_dir.get())
            self.paths.validate_output(output)
            if self.game_dir.get().strip():
                game = self._normalize_game_dir(self._resolve_entry_path(self.game_dir.get())).resolve()
                if output == game or output in game.parents or game in output.parents:
                    raise ImportProblem("输出不能覆盖游戏或放在游戏内。请选择单独的双语输出文件夹。")
            languages = discover_languages(chinese_dir)
            if not languages:
                raise ValueError("请提供含标准 translate 翻译块的 .rpy/.rpym 文件；RPA 或编译脚本请通过普通界面的“另选汉化”导入。")
            language = self._selected_language()
            if not language and len(languages) == 1:
                language = languages[0]
                self.language.set(language)
            if not language:
                raise ValueError("目录中包含多个翻译语言，请在“翻译语言标识”菜单中选择要生成的语言。")
            validate_language(language)
            if language not in languages:
                raise ValueError("选定语言不在翻译目录中。请点击“识别语言”后选择正确语言。")
            if self._selected_profile() not in PROFILES:
                raise ValueError("请选择有效的游戏配置。")
            if self._selected_profile() == ETERNUM_PROFILE and language != "chinese":
                raise ValueError("永恒世界 0.9.5 配置仅适用于 chinese；其他语言请选择通用 Ren'Py 配置。")
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法构建", str(exc))
            return False

        if self._selected_profile() == ETERNUM_PROFILE and not PATCH_FILE.is_file():
            messagebox.showerror("缺少 patch 文件", f"未找到：\n{PATCH_FILE}")
            return False

        return True

    def _validate_deploy_inputs(self) -> tuple[Path, Path] | None:
        if self._is_demo_source():
            messagebox.showerror("示例不能安装到游戏", "示例仅供构建体验，选择自己的游戏翻译后再安装。")
            return None
        if not self._has_deployable_output():
            messagebox.showerror("需要重新构建", "请先成功构建当前输出目录，再进行部署。")
            return None

        output_dir = self._entry_directory(self.output_dir.get(), "输出目录")
        selected_game_dir = self._entry_directory(self.game_dir.get(), "游戏目录")

        if output_dir is None:
            return None
        if selected_game_dir is None:
            return None

        game_dir = self._normalize_game_dir(selected_game_dir)
        try:
            if self.__dict__.get("built_package"):
                plan = read_plan(output_dir.resolve())
                if plan.get("game") is None or Path(plan["game"]).resolve() != game_dir.resolve():
                    raise ImportProblem("请选择安装目标游戏，再重新检查并生成双语。")
            elif any(output_dir.rglob("*.rpym")):
                settings = self.__dict__.get("built_settings") or self._current_settings()
                if Path(settings.source).resolve() != (game_dir / "tl" / settings.language).resolve():
                    raise ImportProblem("原脚本模式无法确认模块原来的加载路径。请通过普通界面选择游戏和完整汉化，重新生成后安装，避免移动 .rpym 模块。")
            validate_game_directory(game_dir)
            if self._selected_profile() == GENERIC_PROFILE:
                check_generic_profile(game_dir)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法部署", str(exc))
            return None

        self.game_dir.set(self._format_path_for_entry(game_dir))
        if self._selected_profile() == ETERNUM_PROFILE and not PATCH_FILE.is_file():
            messagebox.showerror("缺少 patch 文件", f"未找到：\n{PATCH_FILE}")
            return None
        return output_dir.resolve(), game_dir.resolve()

    def _entry_directory(self, text: str, label: str) -> Path | None:
        if not text.strip():
            messagebox.showerror("路径为空", f"请选择{label}。")
            return None

        path = self._resolve_entry_path(text)
        if not self._require_directory(path, label):
            return None
        return path

    def _resolve_entry_path(self, text: str) -> Path:
        if not text.strip():
            raise ValueError("目录不能为空。")
        path = Path(text.strip()).expanduser()
        if not path.is_absolute():
            path = self.paths.data / path
        return path.resolve()

    def _normalize_game_dir(self, path: Path) -> Path:
        game_child = path / "game"
        if game_child.exists() and game_child.is_dir():
            return game_child
        return path

    def _format_path_for_entry(self, path: Path) -> str:
        return str(path.resolve())

    def _require_directory(self, path: Path, label: str) -> bool:
        if not path.exists() or not path.is_dir():
            messagebox.showerror("路径不存在", f"{label} 不存在：\n{path}")
            return False
        return True

    def _load_report_summary(self, report_path: Path, output_dir: Path, *, expected_language: str | None = None) -> None:
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取本次构建报告，请重新构建：{exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("构建报告格式无效，请重新构建。")
        destination = data.get("destination")
        if not isinstance(destination, str) or not destination.strip():
            raise ValueError("构建报告缺少输出目录，请重新构建。")
        if Path(destination).resolve() != output_dir.resolve():
            raise ValueError("构建报告中的输出目录与本次任务不一致，请重新构建。")
        if expected_language is not None and data.get("language") != expected_language:
            raise ValueError("构建报告中的翻译语言与本次任务不一致，请重新构建。")
        if any(type(data.get(field)) is not int or data[field] < 0 for field in REPORT_FIELDS):
            raise ValueError("构建报告中的对白统计无效，请重新构建。")
        diagnostics = data.get("diagnostics", [])
        if not isinstance(diagnostics, list) or any(not isinstance(item, dict) for item in diagnostics):
            raise ValueError("构建报告中的诊断列表无效，请重新构建。")

        self.ui_queue.put(("summary", {field: data[field] for field in REPORT_FIELDS}))
        self.ui_queue.put(("review", bool(data.get("needs_review"))))
        skipped_blocks = data.get("skipped_unsupported_blocks", 0)
        if type(skipped_blocks) is int and skipped_blocks > 0:
            self._queue_log(f"有 {skipped_blocks} 个翻译块因复杂语法保留原样，详见诊断报告。")
        if diagnostics:
            self._queue_log(f"有 {len(diagnostics)} 条对白需要检查；完整记录请打开报告。")
            for item in diagnostics[:20]:
                reason = item.get("reason", "未知原因")
                reason = DIAGNOSTIC_REASON_LABELS.get(str(reason), reason)
                self._queue_log(f"[需检查] {item.get('file', '?')}:{item.get('line', '?')} — {reason}")
            if len(diagnostics) > 20:
                self._queue_log(f"其余 {len(diagnostics) - 20} 条请查看完整报告。")
        if data.get("diagnostics_csv"):
            self._queue_log(f"诊断表格：{data['diagnostics_csv']}")

    def open_output_dir(self) -> None:
        output_dir = self._entry_directory(self.output_dir.get(), "输出目录")
        if output_dir is None:
            return
        self._open_path(output_dir)

    def open_report(self) -> None:
        report_path = self.last_report_path
        if report_path is None or not report_path.exists():
            messagebox.showwarning("报告不存在", "请先完成一次构建，再打开报告。")
            return
        if not self.__dict__.get("report_is_current", False):
            messagebox.showinfo("此前的报告", "本次操作没有生成新报告；即将打开的是此前的报告。本次失败原因请查看详情。")
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
        # Keep the task active until its final queued UI update is consumed.
        return self.task_active or (self.worker is not None and self.worker.is_alive())

    def _has_deployable_output(self) -> bool:
        return (
            self.build_succeeded
            and self.built_output_dir is not None
            and bool(self.output_dir.get().strip())
            and self._resolve_entry_path(self.output_dir.get()).resolve() == self.built_output_dir
            and (self.__dict__.get("built_settings") is None or self.built_settings == self._current_settings())
        )

    def _on_output_changed(self, *_args: object) -> None:
        if self.build_succeeded and not self._has_deployable_output():
            self.build_succeeded = False
            self.built_output_dir = None
            self._set_status("输出目录已更改，请重新构建")
        self._set_buttons_enabled(not self._is_worker_running())

    def _on_settings_changed(self, *_args: object) -> None:
        profile_help = self.__dict__.get("profile_help")
        if profile_help is not None:
            profile_help.set(
                "永恒世界 0.9.5 / chinese 专用：安装已验证的中文字号与特效标签修复。"
                if self._selected_profile() == ETERNUM_PROFILE
                else "通用模式只生成双语对白，沿用游戏原有字号和界面。"
            )
        if self.build_succeeded:
            self.build_succeeded = False
            self.built_output_dir = None
            self.built_settings = None
            self._set_status("翻译输入、语言或游戏配置已更改，请重新构建")
        self._set_buttons_enabled(not self._is_worker_running())

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def _set_summary(self, values: dict[str, object]) -> None:
        lines = [
            f"{REPORT_FIELD_LABELS[field]}: {values.get(field, '-')}" for field in REPORT_FIELDS
        ]
        self.summary_box.configure(state="normal")
        self.summary_box.delete("1.0", "end")
        self.summary_box.insert("1.0", "    |    ".join(lines))
        self.summary_box.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text.set(f"状态：{text}")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.build_button.configure(state="normal" if enabled else "disabled")
        deploy_enabled = enabled and self._has_deployable_output() and not self._is_demo_source()
        self.deploy_button.configure(state="normal" if deploy_enabled else "disabled")

    def _is_demo_source(self) -> bool:
        session = self.__dict__.get("import_session")
        if self.__dict__.get("built_package") and session is not None and session.demo:
            return True
        settings = self.__dict__.get("built_settings")
        source_text = settings.source if settings is not None else self.chinese_tl_dir.get()
        if not source_text.strip():
            return False
        source = self._resolve_entry_path(source_text).resolve()
        demo = (self.paths.resources / "samples").resolve()
        return source == demo or demo in source.parents

    def _queue_log(self, text: str) -> None:
        LOGGER.info(text)
        self.ui_queue.put(("log", text))

    def _queue_status(self, text: str) -> None:
        self.ui_queue.put(("status", text))

    def _queue_buttons(self, enabled: bool) -> None:
        self.ui_queue.put(("buttons", enabled))

    def _queue_build_succeeded(self, output_dir: Path, report_path: Path, settings: BuildSettings | None = None) -> None:
        self.ui_queue.put(("build_succeeded", (output_dir.resolve(), report_path, settings)))

    def _queue_message(self, kind: str, title: str, body: str) -> None:
        self.ui_queue.put(("message", (kind, title, body)))

    def _drain_ui_queue(self) -> None:
        # Yield to Tk during large builds instead of draining indefinitely.
        for _ in range(200):
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
            elif action == "import_ready":
                self._accept_import(*payload)
            elif action == "package_ready":
                self.built_package = True
                self.needs_review = bool(payload)
            elif action == "review":
                self.needs_review = bool(payload)
            elif action == "failed_report":
                self.last_report_path = payload
                self.report_is_current = True
            elif action == "buttons":
                if payload:
                    self.task_active = False
                self._set_buttons_enabled(bool(payload))
            elif action == "build_succeeded":
                self.built_output_dir, self.last_report_path, self.built_settings = payload  # type: ignore[misc]
                self.build_succeeded = True
                self.report_is_current = True
                if self._has_deployable_output():
                    if self.__dict__.get("needs_review"):
                        self._set_status("部分完成：未匹配或复杂对白保留译文，请查看报告后再安装")
                    elif self.__dict__.get("built_package"):
                        self._set_status("双语生成完成，可以备份并安装")
                    else:
                        self._set_status("构建完成")
                    if self._is_demo_source():
                        self._append_log("示例仅供构建体验，选择自己的游戏翻译后再安装。")
                else:
                    self.build_succeeded = False
                    self.built_output_dir = None
                    if self.built_settings is not None and self.built_settings != self._current_settings():
                        self._set_status("构建完成，但输入、语言或游戏配置已更改，请重新构建")
                    else:
                        self._set_status("构建完成，但输出目录已更改，请重新构建")
                    self.built_settings = None
            elif action == "message":
                kind, title, body = payload  # type: ignore[misc]
                if kind == "error":
                    messagebox.showerror(title, body)
                else:
                    messagebox.showinfo(title, body)

        self.after(100, self._drain_ui_queue)

    def _on_close(self) -> None:
        if self._is_worker_running():
            messagebox.showinfo("任务正在运行", "请等待当前构建或安装完成后再关闭，避免中断文件恢复。")
            return
        session = self.__dict__.get("import_session")
        if session is not None:
            session.close()
        self.destroy()

    def report_callback_exception(self, exc_type, exc_value, traceback) -> None:
        LOGGER.error("界面操作失败", exc_info=(exc_type, exc_value, traceback))
        messagebox.showerror("操作失败", f"{exc_value}\n\n详细日志位于：{self.paths.logs}")


def main() -> None:
    from app.launcher import main as launch
    launch()


if __name__ == "__main__":
    main()
