"""Validate the public generic workflow without requiring a graphical display."""

import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from app.gui import BilingualBuilderApp, ETERNUM_PROFILE, GENERIC_PROFILE, PATCH_FILE, RESOURCE_ROOT, REPORT_FIELDS
    from app.runtime import RuntimePaths
except ImportError as exc:
    if (exc.name or "").split(".")[0] in {"tkinter", "_tkinter", "customtkinter"}:
        raise unittest.SkipTest("GUI tests require tkinter and customtkinter.") from exc
    raise


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class HeadlessGenericApp(BilingualBuilderApp):
    def __init__(self, root):
        self.paths = RuntimePaths(RESOURCE_ROOT, root / "user-data")
        self.chinese_tl_dir = Value(str(root / "translation"))
        self.original_english_dir = Value("")
        self.output_dir = Value(str(root / "output"))
        self.game_dir = Value(str(root / "game"))
        self.language = Value("")
        self.profile = Value(GENERIC_PROFILE)
        self.profile_help = Value("")
        self.language_menu = Mock()
        self.build_button = Mock()
        self.deploy_button = Mock()
        self.ui_queue = queue.Queue()
        self.worker = None
        self.task_active = False
        self.build_succeeded = False
        self.built_output_dir = None
        self.built_settings = None
        self.last_report_path = root / "previous.json"
        for method in ("_set_status", "_set_summary", "_append_log", "_clear_log", "after"):
            setattr(self, method, Mock())


class GenericGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "translation"
        self.source.mkdir()
        (self.source / "chapter_any_name.rpy").write_text(
            'translate spanish welcome_123:\n    # guide "Hello!"\n    guide "Hola!"\n', encoding="utf-8")
        self.output = self.root / "output"
        self.output.mkdir()
        (self.root / "game").mkdir()
        self.app = HeadlessGenericApp(self.root)

    def mark_built(self):
        self.app.language.set("spanish")
        self.app.build_succeeded = True
        self.app.built_output_dir = self.output.resolve()
        self.app.built_settings = self.app._current_settings()

    def test_discovers_actual_header_language_and_accepts_optional_original(self):
        self.assertEqual(self.app._refresh_languages(), ["spanish"])
        self.assertEqual(self.app.language.get(), "spanish")
        with patch("app.gui.messagebox.showerror") as error, patch("app.gui.messagebox.showwarning") as warning:
            self.assertTrue(self.app._validate_build_inputs())
        error.assert_not_called()
        warning.assert_not_called()

    def test_sample_uses_resource_paths_and_separate_user_output(self):
        self.app.load_sample()
        self.assertEqual(Path(self.app.chinese_tl_dir.get()), RESOURCE_ROOT / "samples/demo/chinese")
        self.assertEqual(Path(self.app.original_english_dir.get()), RESOURCE_ROOT / "samples/demo/original")
        self.assertEqual(Path(self.app.output_dir.get()), self.app.paths.output / "demo/tl/chinese")
        self.assertTrue(self.app._validate_build_inputs())
        self.assertTrue(self.app._is_demo_source())

    def test_relative_paths_resolve_against_user_data(self):
        self.assertEqual(self.app._resolve_entry_path("relative/output"), self.app.paths.data / "relative/output")
        self.app.output_dir.set(str(RESOURCE_ROOT / "accidental-output"))
        with patch("app.gui.messagebox.showerror") as error:
            self.assertFalse(self.app._validate_build_inputs())
        self.assertIn("程序资源", error.call_args.args[1])

    def test_source_mode_output_cannot_replace_selected_game(self):
        self.app.output_dir.set(self.app.game_dir.get())
        with patch("app.gui.messagebox.showerror") as error:
            self.assertFalse(self.app._validate_build_inputs())
        self.assertIn("输出不能覆盖游戏", error.call_args.args[1])

    def test_source_mode_cannot_relocate_module_with_unknown_game_relative_path(self):
        self.mark_built()
        (self.output / "optional.rpym").write_text('translate spanish module:\n    "Hello\\nHola"\n', encoding="utf-8")
        with patch("app.gui.messagebox.showerror") as error:
            self.assertIsNone(self.app._validate_deploy_inputs())
        self.assertIn("加载路径", error.call_args.args[1])

    def test_multiple_languages_require_selection(self):
        (self.source / "japanese.rpy").write_text('translate japanese hello:\n    "Hello"\n')
        self.assertEqual(self.app._refresh_languages(), ["japanese", "spanish"])
        self.assertEqual(self.app.language.get(), "")
        with patch("app.gui.messagebox.showerror") as error:
            self.assertFalse(self.app._validate_build_inputs())
        error.assert_called_once()
        self.app.language.set("spanish")
        self.assertTrue(self.app._validate_build_inputs())

    def test_profile_does_not_allow_eternum_ui_for_other_languages(self):
        self.app.language.set("spanish")
        self.app.profile.set(ETERNUM_PROFILE)
        with patch("app.gui.messagebox.showerror") as error:
            self.assertFalse(self.app._validate_build_inputs())
        self.assertIn("仅适用于 chinese", error.call_args.args[1])

    def test_input_language_and_profile_changes_invalidate_success(self):
        for variable, replacement in (
            (self.app.language, "japanese"), (self.app.profile, ETERNUM_PROFILE),
            (self.app.chinese_tl_dir, str(self.root / "new_source")),
            (self.app.original_english_dir, str(self.root / "new_original")),
        ):
            with self.subTest(replacement=replacement):
                self.mark_built()
                old = variable.get()
                variable.set(replacement)
                self.assertFalse(self.app._has_deployable_output())
                self.app._on_settings_changed()
                self.assertFalse(self.app.build_succeeded)
                self.app.deploy_button.configure.assert_called_with(state="disabled")
                variable.set(old)

    def test_settings_edited_during_worker_cannot_enable_deployment(self):
        self.app.language.set("spanish")
        settings = self.app._current_settings()
        self.app.task_active = True
        self.app.profile.set(ETERNUM_PROFILE)
        self.app._queue_build_succeeded(self.output, self.root / "report.json", settings)
        self.app._queue_buttons(True)
        self.app._drain_ui_queue()
        self.assertFalse(self.app._has_deployable_output())
        self.app._set_status.assert_called_with("构建完成，但输入、语言或游戏配置已更改，请重新构建")

    def test_report_cannot_claim_success_for_another_language(self):
        report = self.root / "report.json"
        payload = {field: 0 for field in REPORT_FIELDS}
        payload.update(destination=str(self.output), language="chinese", diagnostics=[])
        report.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "翻译语言"):
            self.app._load_report_summary(report, self.output, expected_language="spanish")
        self.assertTrue(self.app.ui_queue.empty())

    def test_real_generic_build_without_original_then_deployment(self):
        self.assertTrue(self.app._validate_build_inputs())
        settings = self.app._current_settings()
        report = self.root / "report.json"
        self.app._run_build(str(self.source), "", str(self.output), report,
                            language="spanish", settings=settings)
        with patch("app.gui.messagebox.showerror") as error:
            self.app._drain_ui_queue()
        error.assert_not_called()
        self.assertTrue(self.app._has_deployable_output())
        self.assertIn('guide "Hello!\\nHola!"', (self.output / "chapter_any_name.rpy").read_text())
        target, target_patch, backup = self.app._deploy_to_game(self.output, self.root / "game")
        self.assertEqual(target, self.root / "game/tl/spanish")
        self.assertIsNone(target_patch)
        self.assertIsNone(backup)
        self.assertFalse((self.root / "game" / PATCH_FILE.name).exists())

    def test_deployment_captures_selected_profile_and_language_before_worker(self):
        self.mark_built()
        with patch("app.gui.messagebox.askyesno", return_value=True) as confirmation:
            with patch("app.gui.threading.Thread") as thread:
                self.app.start_deploy()
        self.assertIn(str(self.root / "game/tl/spanish"), confirmation.call_args.args[1])
        self.assertEqual(thread.call_args.kwargs["args"], (self.output, self.root / "game", "spanish", None))

    def test_demo_build_succeeds_but_cannot_enable_or_start_game_installation(self):
        self.app.chinese_tl_dir.set(str(RESOURCE_ROOT / "samples/demo/chinese"))
        self.app.language.set("chinese")
        settings = self.app._current_settings()
        self.app._queue_build_succeeded(self.output, self.root / "demo_report.json", settings)
        self.app._queue_buttons(True)
        self.app._drain_ui_queue()
        self.assertTrue(self.app._has_deployable_output())
        self.app._set_status.assert_called_with("构建完成")
        self.app.deploy_button.configure.assert_called_with(state="disabled")
        with patch("app.gui.messagebox.showerror") as error, patch("app.gui.threading.Thread") as thread:
            self.app.start_deploy()
        self.assertIn("示例仅供构建体验", error.call_args.args[1])
        thread.assert_not_called()
        self.assertFalse((self.root / "game/tl").exists())


if __name__ == "__main__":
    unittest.main()
