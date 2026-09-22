from pathlib import Path
import tempfile
import unittest

from tools.build_bilingual import build, process_block, parse_dialogue_statement


class BuilderTests(unittest.TestCase):
    def test_natural_newline_is_translated_and_rebuild_is_idempotent(self):
        lines = ['translate chinese hello:\n', '    # mc "Hello."\n',
                 '    mc "第一行\\n第二行" with dissolve\n']
        result, stats = process_block(lines, [], True)
        self.assertIn('"Hello.\\n第一行\\n第二行" with dissolve', result[2])
        self.assertEqual(stats.processed_statements, 1)
        again, stats = process_block(result, [], True)
        self.assertEqual(again, result)
        self.assertEqual(stats.skipped_already_bilingual, 1)

    def test_missing_comment_does_not_shift_other_lines(self):
        lines = ['translate chinese hello:\n', '    mc "无英文"\n',
                 '    # mc "Second."\n', '    mc "第二句"\n']
        result, stats = process_block(lines, [], True)
        self.assertEqual(result[1], lines[1])
        self.assertIn('"Second.\\n第二句"', result[3])
        self.assertEqual(stats.unmatched_statements, 1)

    def test_non_dialogue_commands_are_not_speakers(self):
        for line in ['    voice "test.ogg"',
                     '    play sound "sound.ogg"', '    text "screen text"']:
            self.assertIsNone(parse_dialogue_statement(line, 0))

    def test_character_named_old_is_valid_outside_strings_block(self):
        lines = ['translate chinese example:\n', '    # old "Hello."\n', '    old "你好。"\n']
        result, stats = process_block(lines, [], True)
        self.assertEqual(stats.processed_statements, 1)
        self.assertIn('old "Hello.\\n你好。"', result[2])

    def test_strings_and_top_level_code_do_not_hide_later_dialogue(self):
        source = '''translate chinese first:
    # mc "One"
    mc "一"
translate chinese strings:
    old "Start"
    new "开始"
translate chinese second:
    # mc "Two"
    mc "二"
label untouched:
    mc "原样保留"
translate chinese python:
    value = "unchanged"
translate chinese third:
    # mc "Three"
    mc "三"
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, original, dst = root / "src", root / "original", root / "dst"
            src.mkdir(); original.mkdir()
            (src / "script.rpy").write_text(source, encoding="utf-8-sig")
            (src / "script.rpyc").write_bytes(b"old compiled data")
            (src / "script.rpy:Zone.Identifier").write_text("windows metadata")
            report = build(src, original, dst, None)
            result = (dst / "script.rpy").read_text()
            self.assertEqual(report["processed_statements"], 3)
            self.assertIn('mc "Two\\n二"', result)
            self.assertIn('mc "Three\\n三"', result)
            self.assertIn('new "开始"', result)
            self.assertIn('mc "原样保留"', result)
            self.assertFalse((dst / "script.rpyc").exists())
            self.assertFalse((dst / "script.rpy:Zone.Identifier").exists())

    def test_fallback_never_searches_later_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, original, dst = root / "src", root / "original", root / "dst"
            src.mkdir(); original.mkdir()
            (src / "script.rpy").write_text('# game/script.rpy:2\ntranslate chinese missing:\n    mc "原样"\n')
            (original / "script.rpy").write_text('label later:\n    scene black\n    mc "Wrong scene!"\n')
            report = build(src, original, dst, None)
            self.assertEqual(report["processed_statements"], 0)
            self.assertEqual(report["diagnostics"][0]["line"], 3)
            self.assertEqual(report["diagnostics"][0]["file"], "script.rpy")
            self.assertNotIn("Wrong scene", (dst / "script.rpy").read_text())

    def test_output_cannot_erase_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, original = root / "src", root / "original"
            src.mkdir(); original.mkdir()
            sentinel = src / "script.rpy"
            sentinel.write_text("# keep me")
            for dst in (src, original, root, src / "output"):
                with self.assertRaises(ValueError):
                    build(src, original, dst, None)
                self.assertEqual(sentinel.read_text(), "# keep me")


if __name__ == "__main__":
    unittest.main()
