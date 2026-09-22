import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.build_bilingual import BuildRecoveryError, build


class BuildTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src, self.original, self.dst = [self.root / name for name in ("src", "original", "dst")]
        for path in (self.src, self.original, self.dst):
            path.mkdir()
        (self.src / "script.rpy").write_text('translate chinese hello:\n    # e "Hello"\n    e "你好"\n')
        (self.dst / "script.rpy").write_text("previous successful output")
        self.report, self.csv = self.root / "report.json", self.root / "report.csv"
        self.report.write_text("previous report")
        self.csv.write_text("previous csv")

    def run_build(self):
        return build(self.src, self.original, self.dst, self.report, self.csv)

    def assert_previous_untouched(self):
        self.assertEqual((self.dst / "script.rpy").read_text(), "previous successful output")
        self.assertEqual(self.report.read_text(), "previous report")
        self.assertEqual(self.csv.read_text(), "previous csv")
        self.assertEqual(list(self.root.glob(".rbb-*")), [])

    def test_invalid_source_preserves_last_success(self):
        (self.src / "script.rpy").write_bytes(b"\xffnot utf8")
        with self.assertRaises(UnicodeDecodeError):
            self.run_build()
        self.assert_previous_untouched()

    def test_original_game_scripts_are_not_published_as_translation(self):
        (self.src / "script.rpy").write_text('label start:\n    e "English game script"\n')
        with self.assertRaisesRegex(ValueError, "translation directory"):
            self.run_build()
        self.assert_previous_untouched()

    def test_asset_copy_failure_preserves_last_success(self):
        with patch("tools.build_bilingual.shutil.copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_build()
        self.assert_previous_untouched()

    def test_output_publish_failure_restores_last_success(self):
        replace = Path.replace

        def fail_new_output(source, destination):
            if source.name == "new" and destination == self.dst:
                raise OSError("directory locked")
            return replace(source, destination)

        with patch.object(Path, "replace", fail_new_output):
            with self.assertRaises(OSError):
                self.run_build()
        self.assert_previous_untouched()

    def test_second_report_failure_restores_output_and_first_report(self):
        replace = Path.replace

        def fail_csv(source, destination):
            if source.name == "new" and destination == self.csv:
                raise OSError("CSV is locked by another application")
            return replace(source, destination)

        with patch.object(Path, "replace", fail_csv):
            with self.assertRaises(OSError):
                self.run_build()
        self.assert_previous_untouched()

    def test_interrupted_publish_restores_last_success(self):
        replace = Path.replace

        def interrupt(source, destination):
            if source.name == "new" and destination == self.report:
                raise KeyboardInterrupt()
            return replace(source, destination)

        with patch.object(Path, "replace", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_build()
        self.assert_previous_untouched()

    def test_first_build_failure_does_not_leave_partial_output(self):
        (self.dst / "script.rpy").unlink()
        self.dst.rmdir()
        with patch("tools.build_bilingual.process_target_file", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_build()
        self.assertFalse(self.dst.exists())
        self.assertEqual(self.report.read_text(), "previous report")

    def test_interruption_immediately_after_report_rename_restores_it(self):
        replace = Path.replace

        def interrupt_after_rename(source, destination):
            result = replace(source, destination)
            if source.name == "new" and destination == self.report:
                raise KeyboardInterrupt()
            return result

        with patch.object(Path, "replace", interrupt_after_rename):
            with self.assertRaises(KeyboardInterrupt):
                self.run_build()
        self.assert_previous_untouched()

    def test_interruption_immediately_after_output_rename_restores_it(self):
        replace = Path.replace

        def interrupt_after_rename(source, destination):
            result = replace(source, destination)
            if source.name == "new" and destination == self.dst:
                raise KeyboardInterrupt()
            return result

        with patch.object(Path, "replace", interrupt_after_rename):
            with self.assertRaises(KeyboardInterrupt):
                self.run_build()
        self.assert_previous_untouched()

    def test_interrupted_recovery_never_deletes_saved_output(self):
        replace = Path.replace

        def interrupt_recovery(source, destination):
            if source.name == "new" and destination == self.dst:
                raise OSError("publish failed")
            if source.name == "previous-output" and destination == self.dst:
                raise KeyboardInterrupt()
            return replace(source, destination)

        with patch.object(Path, "replace", interrupt_recovery):
            with self.assertRaises(BuildRecoveryError):
                self.run_build()
        previous = list(self.root.glob(".rbb-build-*/previous-output/script.rpy"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0].read_text(), "previous successful output")

    def test_recovery_failure_keeps_original_output_for_manual_recovery(self):
        replace = Path.replace

        def fail_publish_and_restore(source, destination):
            if source.name in ("new", "previous-output") and destination == self.dst:
                raise OSError("directory locked")
            return replace(source, destination)

        with patch.object(Path, "replace", fail_publish_and_restore):
            with self.assertRaises(BuildRecoveryError) as raised:
                self.run_build()
        previous = list(self.root.glob(".rbb-build-*/previous-output/script.rpy"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0].read_text(), "previous successful output")
        self.assertIn(str(previous[0].parent.parent), str(raised.exception))

    def test_reports_inside_output_and_csv_chinese_values(self):
        (self.src / "script.rpy").write_text('translate chinese hello:\n    e "你好"\n')
        report, csv_path = self.dst / "report.json", self.dst / "diagnostics.csv"
        summary = build(self.src, self.original, self.dst, report, csv_path)
        self.assertEqual(json.loads(report.read_text()), summary)
        self.assertEqual(summary["diagnostics_csv"], str(csv_path))
        self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["file"], "script.rpy")
        self.assertEqual(rows[0]["line"], "2")
        self.assertEqual(rows[0]["reason"], "no_reliable_english")
        self.assertEqual(list(self.root.glob(".rbb-*")), [])

    def test_report_cannot_overwrite_source_or_copied_asset(self):
        original = (self.src / "script.rpy").read_bytes()
        for report in (self.src / "script.rpy", self.original / "data.json", self.dst / "script.rpy"):
            with self.assertRaises(ValueError):
                build(self.src, self.original, self.dst, report)
        self.assertEqual((self.src / "script.rpy").read_bytes(), original)
        self.assert_previous_untouched()

    def test_report_paths_cannot_collide(self):
        with self.assertRaises(ValueError):
            build(self.src, self.original, self.dst, self.report, self.report)
        self.assert_previous_untouched()

    def test_success_replaces_output_and_reports_together(self):
        messages = []
        summary = build(self.src, self.original, self.dst, self.report, self.csv, messages.append)
        self.assertEqual(summary["processed_statements"], 1)
        self.assertIn('e "Hello\\n你好"', (self.dst / "script.rpy").read_text())
        self.assertEqual(json.loads(self.report.read_text()), summary)
        self.assertTrue(any("script.rpy" in message for message in messages))
        self.assertEqual(list(self.root.glob(".rbb-*")), [])


if __name__ == "__main__":
    unittest.main()
