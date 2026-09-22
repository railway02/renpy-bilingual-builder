from pathlib import Path
import tempfile
import unittest

from tools.build_bilingual import (
    build_original_statement_data,
    extract_block_spans,
    parse_dialogue_statement,
    process_block,
    process_target_file,
)


class ParserSafetyTests(unittest.TestCase):
    def assert_preserved(self, source, reason):
        lines = source.splitlines(keepends=True)
        result, stats = process_block(lines, [], True)
        self.assertEqual(result, lines)
        self.assertEqual(stats.processed_statements, 0)
        self.assertEqual(stats.skipped_unsupported_blocks, 1)
        self.assertEqual(stats.diagnostics[0]["reason"], reason)
        self.assertEqual(stats.diagnostics[0]["action"], "kept_original_block")
        return stats

    def test_triple_quoted_dialogue_is_preserved_as_a_block(self):
        self.assert_preserved(
            'translate chinese example:\n'
            '    # e "Hello"\n'
            '    e """你好"""\n'
            '    # e "Another line"\n'
            '    e "另一句"\n',
            "unsupported_triple_quoted_string",
        )

    def test_multiline_contents_cannot_be_rewritten_as_dialogue(self):
        self.assert_preserved(
            'translate chinese example:\n'
            '    # e "Hello"\n'
            '    e """你好\n'
            '    # e "This is part of the monologue"\n'
            '    e "这也是独白内容"\n'
            '    """\n',
            "unsupported_triple_quoted_string",
        )

    def test_single_backtick_and_raw_literals_are_reported_without_rewriting(self):
        for literal, reason in (
            ("'你好'", "unsupported_quote_delimiter"),
            ("`你好`", "unsupported_quote_delimiter"),
            ('r"你好"', "unsupported_raw_string"),
        ):
            with self.subTest(literal=literal):
                self.assert_preserved(
                    f'translate chinese example:\n    # e "Hello"\n    e {literal}\n',
                    reason,
                )

    def test_quoted_speaker_name_is_not_rewritten_as_dialogue(self):
        self.assert_preserved(
            'translate chinese example:\n'
            '    # "Alice" "Hello"\n'
            '    "爱丽丝" "你好"\n',
            "unsupported_quoted_speaker",
        )
        self.assertIsNone(parse_dialogue_statement('    "Alice" "Hello"', 0))

    def test_unterminated_single_line_literal_is_preserved(self):
        self.assert_preserved(
            'translate chinese example:\n'
            '    # e "Hello"\n'
            '    e "你好\n'
            '    世界"\n',
            "unsupported_multiline_or_unterminated_string",
        )

    def test_headers_inside_multiline_text_are_not_real_blocks(self):
        lines = (
            'translate chinese example:\n'
            '    e """你好\n'
            'translate chinese fake:\n'
            '    # e "Fake"\n'
            '    e "虚假的块"\n'
            '    """\n'
            'translate chinese real:\n'
            '    # e "Real"\n'
            '    e "真实的块"\n'
        ).splitlines(keepends=True)
        spans = extract_block_spans(lines, "script.rpy")
        self.assertEqual([span.block_id for span in spans], ["example", "real"])
        first, first_stats = process_block(lines[:spans[0].end_index], [], True)
        self.assertEqual(first, lines[:spans[0].end_index])
        self.assertEqual(first_stats.skipped_unsupported_blocks, 1)
        second, second_stats = process_block(lines[spans[1].start_index:], [], True)
        self.assertEqual(second_stats.processed_statements, 1)
        self.assertIn('e "Real\\n真实的块"', "".join(second))

    def test_fallback_index_excludes_menu_choices_and_multiline_contents(self):
        lines = (
            'label example:\n'
            '    menu:\n'
            '        "Open the door":\n'
            '            pass\n'
            '        "Wait" if ready: # conditional choice\n'
            '            pass\n'
            '    e """Monologue\n'
            '    "This is inside the monologue"\n'
            '    """\n'
            '    "Actual narration"\n'
        ).splitlines(keepends=True)
        statements = build_original_statement_data(lines)
        self.assertEqual([statement.text for statement in statements], ["Actual narration"])

    def test_supported_escaped_strings_and_suffixes_keep_their_behavior(self):
        lines = [
            'translate chinese example:\n',
            '    # e "Say \\"Hello\\" to Alice"\n',
            '    e "说 \\"你好\\"" with dissolve # leave this comment\n',
        ]
        result, stats = process_block(lines, [], True)
        self.assertEqual(stats.skipped_unsupported_blocks, 0)
        self.assertEqual(stats.processed_statements, 1)
        self.assertEqual(
            result[2],
            '    e "Say \\"Hello\\" to Alice\\n说 \\"你好\\"" with dissolve # leave this comment\n',
        )

    def test_report_points_to_actual_file_line_and_following_blocks_work(self):
        source = (
            '# source file\n'
            'translate chinese unsupported:\n'
            '    # e "Hello"\n'
            "    e '你好'\n"
            '\n'
            'translate chinese supported:\n'
            '    # e "World"\n'
            '    e "世界"\n'
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original, output = root / "script.rpy", root / "output.rpy"
            original.write_text(source, encoding="utf-8")
            stats = process_target_file(original, None, output, "script.rpy")
            self.assertEqual(stats.skipped_unsupported_blocks, 1)
            self.assertEqual(stats.processed_statements, 1)
            self.assertEqual(stats.diagnostics[0]["line"], 4)
            self.assertEqual(stats.diagnostics[0]["block_id"], "unsupported")
            self.assertIn("    e '你好'\n", output.read_text(encoding="utf-8"))
            self.assertIn('e "World\\n世界"', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
