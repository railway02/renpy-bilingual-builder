"""Exercise build/deploy coordination without creating a Tk window."""

import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from app.gui import BilingualBuilderApp, REPORT_FIELDS
except ImportError as exc:
    if (exc.name or "").split(".")[0] in {"tkinter", "_tkinter", "customtkinter"}:
        raise unittest.SkipTest("GUI tests require tkinter and customtkinter; build/deploy tests can run without them.") from exc
    raise


class EntryValue:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class HeadlessApp(BilingualBuilderApp):
    def __init__(self, output):
        # No super(): these tests exercise coordination, not Tk rendering.
        self.output_dir = EntryValue(str(output))
        self.chinese_tl_dir = EntryValue(str(output.parent / "chinese"))
        self.original_english_dir = EntryValue(str(output.parent / "english"))
        self.game_dir = EntryValue(str(output.parent / "game"))
        self.ui_queue = queue.Queue()
        self.worker = None
        self.task_active = False
        self.build_succeeded = False
        self.built_output_dir = None
        self.last_report_path = output.parent / "previous_report.json"
        self.build_button = Mock()
        self.deploy_button = Mock()
        self._set_status = Mock()
        self._set_summary = Mock()
        self._append_log = Mock()
        self._clear_log = Mock()
        self.after = Mock()


class GuiStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.report = self.root / "new_report.json"
        self.app = HeadlessApp(self.output)

    def valid_report(self, **overrides):
        data = {field: 0 for field in REPORT_FIELDS}
        data.update(destination=str(self.output), diagnostics=[])
        data.update(overrides)
        return data

    def mark_built(self):
        self.app.build_succeeded = True
        self.app.built_output_dir = self.output.resolve()

    def test_output_change_invalidates_success_and_deploy_guard(self):
        self.mark_built()
        self.app.output_dir.set(str(self.root / "unbuilt"))
        self.app._on_output_changed()
        self.assertFalse(self.app.build_succeeded)
        self.app.deploy_button.configure.assert_called_with(state="disabled")
        with patch("app.gui.messagebox.showerror") as error:
            self.assertIsNone(self.app._validate_deploy_inputs())
        error.assert_called_once()
        # Returning to the old entry must not silently restore deployment approval.
        self.app.output_dir.set(str(self.output))
        self.app._on_output_changed()
        self.assertFalse(self.app._has_deployable_output())

    def test_equivalent_output_path_remains_valid(self):
        self.mark_built()
        self.app.output_dir.set(str(self.output / ".." / "output"))
        self.app._on_output_changed()
        self.assertTrue(self.app._has_deployable_output())

    def test_output_changed_during_worker_cannot_enable_deploy(self):
        self.app.task_active = True
        self.app._queue_build_succeeded(self.output, self.report)
        self.app._queue_buttons(True)
        self.app.output_dir.set(str(self.root / "unbuilt"))
        self.app._on_output_changed()
        self.app._drain_ui_queue()
        self.assertFalse(self.app.build_succeeded)
        self.assertFalse(self.app.task_active)
        self.assertEqual(self.app.last_report_path, self.report)
        self.app.deploy_button.configure.assert_called_with(state="disabled")
        self.app._set_status.assert_called_with("构建完成，但输出目录已更改，请重新构建")

    def test_finished_worker_cannot_start_next_task_before_queue_drains(self):
        self.app.task_active = True
        self.app.worker = Mock()
        self.app.worker.is_alive.return_value = False
        with patch("app.gui.messagebox.showinfo") as info:
            self.app.start_build()
        info.assert_called_once()
        self.app._queue_buttons(True)
        self.app._drain_ui_queue()
        self.assertFalse(self.app._is_worker_running())

    def test_empty_output_is_rejected_before_build_or_open(self):
        self.app.output_dir.set("   ")
        with patch("app.gui.messagebox.showerror") as error:
            self.assertIsNone(self.app._validate_build_inputs())
            with patch.object(self.app, "_open_path") as open_path:
                self.app.open_output_dir()
            open_path.assert_not_called()
        self.assertEqual(error.call_count, 2)
        with self.assertRaises(ValueError):
            self.app._resolve_entry_path(" ")

    def test_report_must_be_valid_and_match_submitted_destination(self):
        invalid = [
            "not json",
            json.dumps([]),
            json.dumps(self.valid_report(destination=str(self.root / "other"))),
            json.dumps(self.valid_report(processed_statements=True)),
            json.dumps(self.valid_report(unmatched_statements=-1)),
            json.dumps(self.valid_report(diagnostics="bad")),
            json.dumps(self.valid_report(diagnostics=["bad"])),
        ]
        with self.assertRaisesRegex(ValueError, "无法读取"):
            self.app._load_report_summary(self.report, self.output)
        for content in invalid:
            with self.subTest(content=content):
                self.report.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.app._load_report_summary(self.report, self.output)
                self.assertTrue(self.app.ui_queue.empty())

    def test_successful_exit_without_report_does_not_validate_old_report(self):
        old_report = self.app.last_report_path
        old_content = json.dumps(self.valid_report())
        old_report.write_text(old_content, encoding="utf-8")
        self.app.task_active = True
        process = Mock(stdout=[])
        process.wait.return_value = 0
        with patch("app.gui.subprocess.Popen", return_value=process):
            self.app._run_build(Path("build_bilingual.py"), "src", "english", str(self.output), self.report)
        with patch("app.gui.messagebox.showerror") as error:
            self.app._drain_ui_queue()
        error.assert_called_once()
        self.assertFalse(self.app.build_succeeded)
        self.assertFalse(self.app.task_active)
        self.assertEqual(self.app.last_report_path, old_report)
        self.assertEqual(old_report.read_text(encoding="utf-8"), old_content)

    def test_valid_build_binds_success_to_actual_output_and_report(self):
        self.report.write_text(json.dumps(self.valid_report()), encoding="utf-8")
        process = Mock(stdout=[])
        process.wait.return_value = 0
        with patch("app.gui.subprocess.Popen", return_value=process) as popen:
            self.app._run_build(Path("build_bilingual.py"), "src", "english", str(self.output), self.report)
        self.app._drain_ui_queue()
        self.assertTrue(self.app._has_deployable_output())
        self.assertEqual(self.app.built_output_dir, self.output.resolve())
        self.assertEqual(self.app.last_report_path, self.report)
        self.assertIn("--report-csv", popen.call_args.args[0])
        self.assertEqual(popen.call_args.args[0][1:3], ["-X", "utf8"])
        self.app.deploy_button.configure.assert_called_with(state="normal")

    def test_each_attempt_gets_unique_report_and_preserves_last_success(self):
        old_report = self.app.last_report_path
        report_paths = []
        with patch.object(self.app, "_validate_build_inputs", return_value=Path("build_bilingual.py")):
            with patch("app.gui.threading.Thread") as thread:
                thread.return_value.is_alive.return_value = False
                for _ in range(2):
                    self.app.start_build()
                    report_paths.append(thread.call_args.kwargs["args"][-1])
                    self.app.task_active = False
        self.assertNotEqual(*report_paths)
        self.assertEqual(self.app.last_report_path, old_report)

    def test_report_logs_location_and_reason_with_bounded_preview(self):
        diagnostics = [dict(file="script8.rpy", line=47155 + i, reason="no_reliable_english") for i in range(25)]
        csv = str(self.report.with_suffix(".csv"))
        self.report.write_text(json.dumps(self.valid_report(diagnostics=diagnostics, diagnostics_csv=csv)), encoding="utf-8")
        self.app._load_report_summary(self.report, self.output)
        self.app._drain_ui_queue()
        logs = [call.args[0] for call in self.app._append_log.call_args_list]
        self.assertIn("[需检查] script8.rpy:47155 — 未找到可靠英文，已保留原翻译", logs)
        self.assertEqual(sum(line.startswith("[需检查]") for line in logs), 20)
        self.assertTrue(any("其余 5 条" in line for line in logs))
        self.assertIn(f"诊断表格：{csv}", logs)

    def test_unsupported_syntax_diagnostics_are_explained_in_chinese(self):
        reasons = [
            "unsupported_raw_string",
            "unsupported_triple_quoted_string",
            "unsupported_quote_delimiter",
            "unsupported_multiline_or_unterminated_string",
            "unsupported_quoted_speaker",
        ]
        diagnostics = [dict(file="script.rpy", line=i + 1, reason=reason) for i, reason in enumerate(reasons)]
        data = self.valid_report(diagnostics=diagnostics, skipped_unsupported_blocks=5)
        self.report.write_text(json.dumps(data), encoding="utf-8")
        self.app._load_report_summary(self.report, self.output)
        self.app._drain_ui_queue()
        logs = [call.args[0] for call in self.app._append_log.call_args_list]
        self.assertTrue(any("5 个翻译块因复杂语法保留原样" in line for line in logs))
        explained = [line for line in logs if line.startswith("[需检查]")]
        self.assertEqual(len(explained), 5)
        self.assertTrue(all("已保留原翻译块" in line for line in explained))
        self.assertFalse(any("unsupported_" in line for line in explained))


if __name__ == "__main__":
    unittest.main()
