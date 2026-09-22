import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.build_bilingual import build, discover_languages, validate_language


def dialogue(language="schinese", block="hello", translated="你好"):
    return f'translate {language} {block}:\n    # e "Hello"\n    e "{translated}"\n'


class GenericBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src, self.dst = self.root / "translation", self.root / "output"
        self.src.mkdir()

    def write(self, relative, content):
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_any_filename_and_nested_directory_are_discovered(self):
        self.write("chapters/ep_10/day_2.rpy", dialogue())
        self.write("characters/side_story.rpy", dialogue(block="side_story"))
        summary = build(self.src, dst=self.dst)
        self.assertEqual(summary["language"], "schinese")
        self.assertIsNone(summary["source_original"])
        self.assertEqual(summary["processed_statements"], 2)
        self.assertEqual(summary["files_processed"], 2)
        self.assertIn('e "Hello\\n你好"', (self.dst / "chapters/ep_10/day_2.rpy").read_text())

    def test_auto_detection_does_not_depend_on_folder_name(self):
        self.write("epilogue.rpy", dialogue("spanish", translated="Hola"))
        self.assertEqual(discover_languages(self.src), ["spanish"])
        summary = build(self.src, dst=self.dst)
        self.assertEqual(summary["language"], "spanish")
        self.assertIn('e "Hello\\nHola"', (self.dst / "epilogue.rpy").read_text())

    def test_multiple_languages_require_a_selection_before_output_changes(self):
        self.write("one.rpy", dialogue("japanese", translated="こんにちは"))
        self.write("two.rpy", dialogue("schinese"))
        self.dst.mkdir()
        sentinel = self.dst / "previous.txt"
        sentinel.write_text("last success")
        self.assertEqual(discover_languages(self.src), ["japanese", "schinese"])
        with self.assertRaisesRegex(ValueError, "Multiple translation languages.*japanese, schinese"):
            build(self.src, dst=self.dst)
        self.assertEqual(sentinel.read_text(), "last success")
        self.assertEqual(list(self.root.glob(".rbb-*")), [])

    def test_explicit_language_preserves_other_language_files_byte_for_byte(self):
        self.write("local.rpy", dialogue())
        other = self.src / "japanese.rpy"
        untouched = b"\xef\xbb\xbf" + dialogue("japanese", translated="こんにちは").replace("\n", "\r\n").encode("utf-8")
        other.write_bytes(untouched)
        self.write("font.rpy", 'define gui.text_font = "font.ttf"\n')
        summary = build(self.src, dst=self.dst, language="schinese")
        self.assertEqual(summary["processed_statements"], 1)
        self.assertEqual(summary["files_processed"], 1)
        self.assertEqual((self.dst / other.name).read_bytes(), untouched)
        self.assertEqual((self.dst / "font.rpy").read_bytes(), (self.src / "font.rpy").read_bytes())

    def test_selected_language_only_within_a_mixed_file(self):
        untouched = (
            dialogue("japanese", translated="こんにちは")
            + 'translate schinese strings:\n    old "Hello"\n    new "你好"\n'
            + 'translate schinese python:\n    config.name = "名称"\n'
            + 'translate schinese style default:\n    font "font.ttf"\n'
        )
        self.write("all.rpy", dialogue() + untouched)
        summary = build(self.src, dst=self.dst, language="schinese")
        self.assertEqual(summary["processed_statements"], 1)
        self.assertTrue((self.dst / "all.rpy").read_text().endswith(untouched))

    def test_none_and_headers_inside_multiline_literals_are_not_languages(self):
        self.write("story.rpy", (
            'define sample = """\ntranslate fake hidden:\n    e "Hidden"\n"""\n'
            + dialogue("None", translated="Original") + dialogue()
        ))
        self.assertEqual(discover_languages(self.src), ["schinese"])
        summary = build(self.src, dst=self.dst)
        self.assertEqual(summary["processed_statements"], 1)
        self.assertIn(dialogue("None", translated="Original"), (self.dst / "story.rpy").read_text())

    def test_header_comments_are_supported(self):
        self.write("chapter.rpy", dialogue().replace("hello:\n", "hello: # generated translation\n"))
        self.assertEqual(discover_languages(self.src), ["schinese"])
        self.assertEqual(build(self.src, dst=self.dst)["processed_statements"], 1)

    def test_no_translation_language_is_actionable(self):
        self.write("chapter.rpy", 'label start:\n    e "Original"\n')
        with self.assertRaisesRegex(ValueError, "translation directory"):
            build(self.src, dst=self.dst)
        self.assertFalse(self.dst.exists())

    def test_language_with_only_strings_is_not_a_dialogue_build(self):
        self.write("gui.rpy", 'translate spanish strings:\n    old "Start"\n    new "Inicio"\n')
        with self.assertRaisesRegex(ValueError, "No supported translate spanish dialogue blocks"):
            build(self.src, dst=self.dst)
        self.assertFalse(self.dst.exists())

    def test_nonexistent_selected_language_does_not_publish_output(self):
        self.write("chapter.rpy", dialogue())
        with self.assertRaisesRegex(ValueError, "No supported translate spanish dialogue blocks"):
            build(self.src, dst=self.dst, language="spanish")
        self.assertFalse(self.dst.exists())

    def test_language_names_cannot_escape_or_break_windows_folders(self):
        for language in ("", "../chinese", "../", "/tmp/test", "chinese/other", "chinese\\other",
                         "chinese ", "中文", "2chinese", "None", "CON", "aux", "Lpt1", "COM9", None):
            with self.subTest(language=language):
                with self.assertRaises(ValueError):
                    validate_language(language)
        for language in ("chinese", "schinese", "tchinese", "pt_BR", "_custom", "fr2"):
            self.assertEqual(validate_language(language), language)

    def test_omitted_original_preserves_unmatched_dialogue_with_diagnostic(self):
        content = 'translate spanish unmatched:\n    e "Hola"\n'
        self.write("later.rpy", content)
        summary = build(self.src, dst=self.dst)
        self.assertEqual((self.dst / "later.rpy").read_text(), content)
        self.assertEqual(summary["unmatched_statements"], 1)
        self.assertEqual(summary["diagnostics"][0]["file"], "later.rpy")

    def test_nested_original_fallback_matches_the_complete_source_path(self):
        self.write("chapters/day.rpy", '# game/chapters/day.rpy:2\ntranslate schinese intro:\n    e "你好"\n')
        original = self.root / "original"
        (original / "chapters").mkdir(parents=True)
        (original / "chapters/day.rpy").write_text('label start:\n    e "Hello"\n')
        summary = build(self.src, original, self.dst)
        self.assertEqual(summary["fallback_english_from_original_statements"], 1)
        self.assertIn('e "Hello\\n你好"', (self.dst / "chapters/day.rpy").read_text())

    def test_same_basename_in_different_chapter_is_not_a_source_match(self):
        content = '# game/other/day.rpy:2\ntranslate schinese intro:\n    e "你好"\n'
        self.write("chapters/day.rpy", content)
        original = self.root / "original"
        (original / "chapters").mkdir(parents=True)
        (original / "chapters/day.rpy").write_text('label start:\n    e "Wrong chapter"\n')
        summary = build(self.src, original, self.dst)
        self.assertEqual(summary["processed_statements"], 0)
        self.assertEqual((self.dst / "chapters/day.rpy").read_text(), content)

    def test_generic_language_rebuild_is_idempotent(self):
        self.write("chapter.rpy", dialogue("spanish", translated="Hola"))
        build(self.src, dst=self.dst)
        rebuilt = self.root / "rebuilt"
        summary = build(self.dst, dst=rebuilt)
        self.assertEqual(summary["skipped_already_bilingual"], 1)
        self.assertEqual((self.dst / "chapter.rpy").read_bytes(), (rebuilt / "chapter.rpy").read_bytes())

    def test_cli_accepts_language_and_optional_original_directory(self):
        self.write("chapter.rpy", dialogue("spanish", translated="Hola"))
        script = Path(__file__).resolve().parents[1] / "tools/build_bilingual.py"
        result = subprocess.run(
            [sys.executable, str(script), "--src", str(self.src), "--dst", str(self.dst), "--language", "spanish"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["language"], "spanish")
        self.assertIn('e "Hello\\nHola"', (self.dst / "chapter.rpy").read_text())


if __name__ == "__main__":
    unittest.main()
