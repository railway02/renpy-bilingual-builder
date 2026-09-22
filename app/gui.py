from __future__ import annotations

import json
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

if __package__:
    from .deployment import check_generic_profile, deploy_to_game, validate_game_directory
else:
    from deployment import check_generic_profile, deploy_to_game, validate_game_directory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Also support the documented `python app/gui.py` entry point.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tools.build_bilingual import discover_languages, validate_language

PATCH_FILE = PROJECT_ROOT / "patches" / "zz_bilingual_ui_patch.rpy"
REPORT_PATH = PROJECT_ROOT / "output" / "reports" / "build_report_gui.json"
BUILD_SCRIPT_CANDIDATES = (
    PROJECT_ROOT / "tools" / "build_bilingual.py",
    PROJECT_ROOT / "tools" / "bulid_bilingual.py",
)
GENERIC_PROFILE = "通用 Ren'Py（保留游戏界面）"
ETERNUM_PROFILE = "永恒世界 0.9.5（中文排版修复）"
PROFILES = (GENERIC_PROFILE, ETERNUM_PROFILE)


@dataclass(frozen=True)
class BuildSettings:
    source: str
    original: str
    language: str
    profile: str


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
    "no_reliable_english": "未找到可靠英文，已保留原翻译",
    "unsupported_raw_string": "原始字符串语法暂不支持，已保留原翻译块",
    "unsupported_triple_quoted_string": "三引号字符串语法暂不支持，已保留原翻译块",
    "unsupported_quote_delimiter": "字符串引号格式暂不支持，已保留原翻译块",
    "unsupported_multiline_or_unterminated_string": "字符串跨行或引号未闭合，已保留原翻译块",
    "unsupported_multiline_string": "实际跨行字符串暂不支持，已保留原翻译块",
    "unsupported_quoted_speaker": "带引号的说话人语法暂不支持，已保留原翻译块",
}


class BilingualBuilderApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Ren'Py Bilingual Builder")
        self.geometry("1040x760")
        self.minsize(920, 650)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.task_active = False
        self.last_report_path = REPORT_PATH
        self.build_succeeded = False
        self.built_output_dir: Path | None = None
        self.built_settings: BuildSettings | None = None

        self._build_variables()
        self._build_layout()
        self.output_dir.trace_add("write", self._on_output_changed)
        for variable in (self.chinese_tl_dir, self.original_english_dir, self.language, self.profile):
            variable.trace_add("write", self._on_settings_changed)
        self.after(100, self._drain_ui_queue)

    def _build_variables(self) -> None:
        self.chinese_tl_dir = ctk.StringVar(value="")
        self.original_english_dir = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value="output/bilingual")
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
            text="Ren'Py Bilingual Builder",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="将已有翻译与原文合并为双语对白。支持标准 Ren'Py 翻译脚本；本工具不提供或自动翻译游戏文本。",
            anchor="w",
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")

        path_frame = ctk.CTkScrollableFrame(self, height=355)
        path_frame.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        path_frame.grid_columnconfigure(1, weight=1)

        self._add_path_row(
            path_frame,
            0,
            "1. 选择已有翻译",
            self.chinese_tl_dir,
            self._choose_translation_directory,
        )
        ctk.CTkLabel(path_frame, text="选 game/tl/下的语言文件夹（如 chinese），需含 .rpy 文件；仅有 .rpa/.rpyc 不能直接构建。", anchor="w").grid(
            row=1, column=1, columnspan=2, padx=12, pady=(0, 5), sticky="w")
        ctk.CTkLabel(path_frame, text="翻译语言标识", anchor="w").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.language_menu = ctk.CTkOptionMenu(path_frame, variable=self.language, values=[""], width=260)
        self.language_menu.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        ctk.CTkButton(path_frame, text="识别语言", width=84, command=self._refresh_languages).grid(row=2, column=2, padx=12, pady=6)
        self._add_path_row(
            path_frame,
            3,
            "原文目录（可选）",
            self.original_english_dir,
            lambda: self._choose_directory(self.original_english_dir),
        )
        self._add_path_row(
            path_frame,
            5,
            "2. 双语输出目录",
            self.output_dir,
            lambda: self._choose_directory(self.output_dir),
        )
        self._add_path_row(
            path_frame,
            8,
            "3. 游戏目录（部署用）",
            self.game_dir,
            self._choose_game_directory,
        )
        ctk.CTkLabel(path_frame, text="翻译注释中已有原文时可留空；缺少注释时，选择含原始 .rpy 脚本的 game 目录作为补充。", anchor="w").grid(
            row=4, column=1, columnspan=2, padx=12, pady=(0, 5), sticky="w")
        ctk.CTkLabel(path_frame, text="游戏配置", anchor="w").grid(row=6, column=0, padx=12, pady=6, sticky="w")
        ctk.CTkOptionMenu(path_frame, variable=self.profile, values=list(PROFILES), width=350).grid(
            row=6, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        ctk.CTkLabel(path_frame, textvariable=self.profile_help, anchor="w").grid(
            row=7, column=1, columnspan=2, padx=12, pady=(0, 5), sticky="w")
        ctk.CTkLabel(path_frame, text="先关闭游戏；可选游戏根目录或 game 文件夹。只构建时可留空，首次使用建议先备份游戏。", anchor="w").grid(
            row=9, column=1, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        actions = ctk.CTkFrame(self)
        actions.grid(row=3, column=0, padx=20, pady=8, sticky="ew")

        self.build_button = ctk.CTkButton(actions, text="生成双语文件", command=self.start_build)
        self.build_button.grid(row=0, column=0, padx=10, pady=12)

        self.deploy_button = ctk.CTkButton(actions, text="备份并安装到游戏", command=self.start_deploy)
        self.deploy_button.grid(row=0, column=1, padx=10, pady=12)
        self.deploy_button.configure(state="disabled")

        self.open_output_button = ctk.CTkButton(
            actions,
            text="打开输出目录",
            command=self.open_output_dir,
        )
        self.open_output_button.grid(row=0, column=2, padx=10, pady=12)

        self.open_report_button = ctk.CTkButton(actions, text="打开报告", command=self.open_report)
        self.open_report_button.grid(row=0, column=3, padx=10, pady=12)
        self.sample_button = ctk.CTkButton(actions, text="试用内置示例", command=self.load_sample)
        self.sample_button.grid(row=0, column=4, padx=10, pady=12)

        body = ctk.CTkFrame(self)
        body.grid(row=4, column=0, padx=20, pady=(8, 20), sticky="nsew")
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

    def _choose_translation_directory(self) -> None:
        path = filedialog.askdirectory(title="选择 game/tl/下含 .rpy 的翻译语言文件夹")
        if path:
            self.chinese_tl_dir.set(path)
            self._refresh_languages()

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
            messagebox.showerror("未找到翻译", "目录中没有标准的 translate <语言> 翻译块。请选择已有翻译的 .rpy 所在目录。")
        elif len(languages) > 1:
            self._set_status("发现多个翻译语言，请在语言菜单中选择；建议直接选择对应的语言子目录")
        return languages

    def load_sample(self) -> None:
        if self._is_worker_running():
            return
        self.chinese_tl_dir.set("samples/demo/chinese")
        self.original_english_dir.set("samples/demo/original")
        self.output_dir.set("output/demo/tl/chinese")
        self.game_dir.set("")
        self.profile.set(GENERIC_PROFILE)
        self._refresh_languages()
        self._set_status("已载入原创示例，点击“生成双语文件”即可体验；无需游戏文件")

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
            normalized(self.chinese_tl_dir.get()), normalized(self.original_english_dir.get()),
            self._selected_language(), self._selected_profile(),
        )

    def _choose_game_directory(self) -> None:
        path = filedialog.askdirectory()
        if path:
            game_dir = self._normalize_game_dir(Path(path))
            self.game_dir.set(self._format_path_for_entry(game_dir))

    def start_build(self) -> None:
        if self._is_worker_running():
            messagebox.showinfo("正在运行", "当前已有任务在运行。")
            return

        build_script = self._validate_build_inputs()
        if build_script is None:
            return

        src_dir = str(self._resolve_entry_path(self.chinese_tl_dir.get()))
        original_dir = (str(self._resolve_entry_path(self.original_english_dir.get()))
                        if self.original_english_dir.get().strip() else "")
        dst_dir = str(self._resolve_entry_path(self.output_dir.get()).resolve())
        settings = self._current_settings()

        self.build_succeeded = False
        self.built_output_dir = None
        self.built_settings = None
        self.task_active = True
        self._clear_log()
        self._set_summary({})
        self._set_status("构建中")
        self._set_buttons_enabled(False)
        # Each attempt gets a new report, preserving the previous successful one.
        report_path = REPORT_PATH.with_name(f"{REPORT_PATH.stem}_{uuid.uuid4().hex}.json")

        self.worker = threading.Thread(
            target=self._run_build,
            args=(build_script, src_dir, original_dir, dst_dir, report_path),
            kwargs={"language": settings.language, "settings": settings},
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
        settings = self.__dict__.get("built_settings") or self._current_settings()
        target_tl = game_dir / "tl" / settings.language
        patch_file = PATCH_FILE if settings.profile == ETERNUM_PROFILE else None
        patch_notice = ("同时安装永恒世界 0.9.5 中文排版补丁。\n" if patch_file is not None
                        else "保留游戏原有界面和字号。\n")
        confirmed = messagebox.askyesno(
            "确认部署",
            f"一键部署将覆盖：\n{target_tl}\n\n"
            + patch_notice + "原翻译及需要替换的 UI 补丁会备份到 game 目录外的 renpy_bilingual_backups。\n"
            "请确认游戏已完全关闭。\n\n"
            "是否继续？",
        )
        if not confirmed:
            return

        self._set_status("部署中")
        self.task_active = True
        self._set_buttons_enabled(False)
        self.worker = threading.Thread(target=self._run_deploy, args=(*deploy_paths, settings.language, patch_file), daemon=True)
        self.worker.start()

    def _run_build(
        self,
        build_script: Path,
        src_dir: str,
        original_dir: str,
        dst_dir: str,
        report_path: Path,
        *,
        language: str | None = None,
        settings: BuildSettings | None = None,
    ) -> None:
        cmd = [
            sys.executable,
            "-X", "utf8",
            "-u",
            str(build_script),
            "--src",
            src_dir,
            "--dst",
            dst_dir,
            "--report-json",
            str(report_path),
        ]
        if original_dir:
            cmd.extend(("--src-original", original_dir))
        if language:
            cmd.extend(("--language", language))
        if build_script.name == "build_bilingual.py":
            cmd.extend(("--report-csv", str(report_path.with_suffix(".csv"))))

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
            try:
                for line in process.stdout:
                    self._queue_log(line.rstrip("\n"))
                return_code = process.wait()
            finally:
                close_stream = getattr(process.stdout, "close", None)
                if close_stream is not None:
                    close_stream()
            if return_code != 0:
                self._queue_status("构建失败")
                self._queue_message("error", "构建失败", f"构建命令退出码：{return_code}")
                return

            self._load_report_summary(report_path, Path(dst_dir), expected_language=language)
            self._queue_log("-" * 72)
            self._queue_log(f"报告已生成：{report_path}")
            self._queue_build_succeeded(Path(dst_dir), report_path, settings)
        except Exception as exc:
            self._queue_status("构建异常")
            self._queue_log(f"[异常] {exc}")
            self._queue_message("error", "构建异常", str(exc))
        finally:
            self._queue_buttons(True)

    def _run_deploy(self, output_dir: Path, game_dir: Path, language: str = "chinese", patch_file: Path | None = None) -> None:
        try:
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
            self._queue_status("部署失败")
            self._queue_log(f"[部署失败] {exc}")
            self._queue_message("error", "部署失败", str(exc))
        finally:
            self._queue_buttons(True)

    def _deploy_to_game(self, output_dir: Path, game_dir: Path) -> tuple[Path, Path | None, Path | None]:
        settings = self.__dict__.get("built_settings") or self._current_settings()
        patch_file = PATCH_FILE if settings.profile == ETERNUM_PROFILE else None
        return deploy_to_game(output_dir, game_dir, patch_file, language=settings.language)

    def _validate_build_inputs(self) -> Path | None:
        if not self.output_dir.get().strip():
            messagebox.showerror("路径为空", "请选择输出目录。")
            return None

        chinese_dir = self._entry_directory(self.chinese_tl_dir.get(), "已有翻译目录")
        if chinese_dir is None:
            return None
        if self.original_english_dir.get().strip():
            original_dir = self._entry_directory(self.original_english_dir.get(), "原文目录")
            if original_dir is None:
                return None
        try:
            languages = discover_languages(chinese_dir)
            if not languages:
                raise ValueError("所选目录没有标准的 translate 翻译块。请提供含已有翻译的 .rpy 文件。")
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
            return None

        build_script = self._find_build_script()
        if build_script is None:
            expected = "\n".join(str(path) for path in BUILD_SCRIPT_CANDIDATES)
            messagebox.showerror("缺少构建器", f"未找到构建脚本：\n{expected}")
            return None

        if self._selected_profile() == ETERNUM_PROFILE and not PATCH_FILE.is_file():
            messagebox.showerror("缺少 patch 文件", f"未找到：\n{PATCH_FILE}")
            return None

        if build_script.name == "bulid_bilingual.py":
            messagebox.showwarning(
                "构建脚本文件名",
                "未找到 tools/build_bilingual.py，将使用当前仓库中的 tools/bulid_bilingual.py。",
            )

        return build_script.resolve()

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
            path = PROJECT_ROOT / path
        return path

    def _normalize_game_dir(self, path: Path) -> Path:
        game_child = path / "game"
        if game_child.exists() and game_child.is_dir():
            return game_child
        return path

    def _format_path_for_entry(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)

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
        self.summary_box.insert("1.0", "\n".join(lines))
        self.summary_box.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text.set(f"状态：{text}")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.build_button.configure(state="normal" if enabled else "disabled")
        deploy_enabled = enabled and self._has_deployable_output() and not self._is_demo_source()
        self.deploy_button.configure(state="normal" if deploy_enabled else "disabled")

    def _is_demo_source(self) -> bool:
        settings = self.__dict__.get("built_settings")
        source_text = settings.source if settings is not None else self.chinese_tl_dir.get()
        if not source_text.strip():
            return False
        source = self._resolve_entry_path(source_text).resolve()
        demo = (PROJECT_ROOT / "samples" / "demo").resolve()
        return source == demo or demo in source.parents

    def _queue_log(self, text: str) -> None:
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
                if payload:
                    self.task_active = False
                self._set_buttons_enabled(bool(payload))
            elif action == "build_succeeded":
                self.built_output_dir, self.last_report_path, self.built_settings = payload  # type: ignore[misc]
                self.build_succeeded = True
                if self._has_deployable_output():
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


def main() -> None:
    app = BilingualBuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
