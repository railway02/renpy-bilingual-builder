from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_generic_gui import HeadlessGenericApp, Value
from app.import_pipeline import Candidate, ImportSession


class ImportGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = HeadlessGenericApp(self.root)
        self.app.chinese_tl_dir.set("")
        self.app.input_path = Value(str(self.root / "patch.rpa"))
        self.app.candidate_choice = Value("")
        self.app.candidate_menu = Mock()
        self.app.candidate_frame = Mock()
        self.app.import_session = None
        self.app.import_key = None
        self.app.built_package = False
        self.app.needs_review = False

    def session(self, count=1):
        return ImportSession(self.root / "work", self.root / "game", [], [
            Candidate(str(index), str(index), "chinese", ("tl/chinese/test.rpy",), f"汉化 {index}")
            for index in range(count)
        ], {}, {}, [])

    def test_multiple_candidates_do_not_autoselect_or_build(self):
        session = self.session(2)
        self.app._accept_import(self.app._input_key(), session)
        self.assertEqual(self.app.candidate_choice.get(), "")
        self.app.after.assert_not_called()
        with patch("app.gui.threading.Thread") as thread, patch("app.gui.messagebox.showinfo") as info:
            self.app.start_build()
        thread.assert_not_called()
        info.assert_called_once()
        self.assertFalse(self.app.build_succeeded)

    def test_input_change_discards_stale_import_result(self):
        session = self.session()
        session.close = Mock()
        key = self.app._input_key()
        self.app.input_path.set(str(self.root / "other.rpa"))
        self.app._accept_import(key, session)
        session.close.assert_called_once()
        self.assertIsNone(self.app.import_session)
        self.app.after.assert_not_called()

    def test_single_candidate_continues_only_for_same_inputs(self):
        session = self.session()
        key = self.app._input_key()
        self.app._accept_import(key, session)
        self.assertEqual(self.app.candidate_choice.get(), "汉化 0")
        self.app.after.assert_called_once()
        with patch.object(self.app, "start_build") as build:
            self.app._on_import_input_changed()
            self.app._continue_single_import(key, session)
        build.assert_not_called()

    def test_candidate_worker_binds_game_input_and_choice_before_thread(self):
        session = self.session()
        self.app.import_session = session
        self.app.import_key = self.app._input_key()
        self.app.candidate_choice.set("汉化 0")
        with patch("app.gui.threading.Thread") as thread:
            self.app.start_build()
        settings = thread.call_args.kwargs["args"][-1]
        self.assertEqual(settings.imported_input, self.app.input_path.get())
        self.assertEqual(settings.imported_game, self.app.game_dir.get())
        self.assertEqual(settings.candidate, "汉化 0")
        self.assertIsNone(self.app.import_key)
        self.assertFalse(self.app.build_succeeded)

    def test_import_failure_never_reenables_old_install(self):
        self.app.build_succeeded = True
        self.app.built_output_dir = self.root / "output"
        with patch("app.gui.threading.Thread"):
            self.app.start_build()
        self.assertFalse(self.app.build_succeeded)
        with patch("app.gui.import_inputs", side_effect=ValueError("bad archive")), self.assertLogs("rbb", level="ERROR"):
            self.app._run_import(self.app._input_key())
        with patch("app.gui.messagebox.showerror"):
            self.app._drain_ui_queue()
        self.assertFalse(self.app.task_active)
        self.app.deploy_button.configure.assert_called_with(state="disabled")

    def test_select_game_after_sample_switches_to_import_mode(self):
        self.app.input_path.set("")
        self.app.chinese_tl_dir.set(str(self.app.paths.resources / "samples/demo/chinese"))
        self.app.original_english_dir.set(str(self.app.paths.resources / "samples/demo/original"))
        self.app.game_dir.set(str(self.root / "new-game"))
        self.app._on_import_input_changed()
        self.assertEqual(self.app.chinese_tl_dir.get(), "")
        self.assertEqual(self.app.original_english_dir.get(), "")
        self.assertTrue(self.app._import_mode())

    def test_imported_settings_do_not_inherit_hidden_sample_source(self):
        self.app.chinese_tl_dir.set(str(self.app.paths.resources / "samples/demo/chinese"))
        settings = self.app._current_settings()
        self.assertEqual(settings.source, "")
        self.assertEqual(settings.imported_input, self.app.input_path.get())
