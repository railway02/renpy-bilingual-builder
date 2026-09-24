import hashlib
import json
from pathlib import Path
import pickle
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from app.archive import ImportProblem, RpaArchive, safe_relative
from app.decompile import decode_file, decompile, read_slots
from app.import_pipeline import import_inputs, build_imported
from app.package_deployment import deploy_package
from tools.build_bilingual import build


FIXTURES = Path(__file__).parent / "fixtures/import_game"


def rpa(path, files, version=3, prefix=False):
    key = 0x42424242 if version == 3 else 0
    placeholder = b"RPA-3.0 0000000000000000 42424242\n" if version == 3 else b"RPA-2.0 0000000000000000\n"
    data, index = bytearray(placeholder), {}
    for name, content in files.items():
        head = content[:3] if prefix else b""
        body = content[len(head):]
        index[name] = [(len(data) ^ key, len(body) ^ key, head)] if version == 3 else [(len(data), len(body))]
        data.extend(body)
    offset = len(data)
    data.extend(zlib.compress(pickle.dumps(index, protocol=2)))
    header = (f"RPA-3.0 {offset:016x} {key:08x}\n" if version == 3 else f"RPA-2.0 {offset:016x}\n").encode()
    data[:len(placeholder)] = header
    path.write_bytes(data)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class ImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.game = self.root / "game"
        self.game.mkdir()
        self.package = self.root / "汉化 包.rpa"
        self.output = self.root / "out"
        self.report = self.root / "report.json"

    def game_and_package(self, *, module=True):
        originals = {"script.rpyc": (FIXTURES / "original.rpyc.bin").read_bytes(),
                     "images/resident.png": b"resident game image"}
        if module:
            originals["extras/optional.rpymc"] = (FIXTURES / "module.rpymc.bin").read_bytes()
        rpa(self.game / "scripts.rpa", originals)
        files = {"tl/chinese/new_name.rpyc": (FIXTURES / "translation.rpyc.bin").read_bytes(),
                 "fonts/demo.ttf": b"font dependency", "styles.rpy": b'define gui.text_font = "fonts/demo.ttf"\n'}
        if module:
            files["extras/optional.rpymc"] = (FIXTURES / "module.rpymc.bin").read_bytes()
        rpa(self.package, files, prefix=True)

    def session(self, *, package=True):
        session = import_inputs(self.game, self.package if package else None, self.root / "work")
        self.addCleanup(session.close)
        return session

    def build_session(self, session):
        self.assertEqual(len(session.candidates), 1)
        return build_imported(session, session.candidates[0].id, self.output, self.report)

    def test_rpa_two_and_three_prefixes_are_exact(self):
        for version in (2, 3):
            source = self.root / f"v{version}.rpa"
            rpa(source, {"目录/file.bin": b"abcdef\x00\xff"}, version, prefix=version == 3)
            target = self.root / f"extracted{version}"
            RpaArchive(source).copy_entry("目录/file.bin", target)
            self.assertEqual(target.read_bytes(), b"abcdef\x00\xff")

    def test_archive_path_traversal_devices_ads_and_case_collisions_rejected(self):
        for name in ("../outside", "/absolute", "C:/file", "a\\b", "a:stream", "nul.txt", "a./b", "a//b"):
            with self.subTest(name=name), self.assertRaises(ImportProblem):
                safe_relative(name)
        rpa(self.package, {"A.rpy": b"a", "a.rpy": b"b"})
        with self.assertRaisesRegex(ImportProblem, "冲突"):
            RpaArchive(self.package)

    def test_malicious_pickle_in_rpa_does_not_execute(self):
        marker = self.root / "executed"
        class Payload:
            def __reduce__(self):
                return eval, (f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')",)
        data = zlib.compress(pickle.dumps(Payload(), protocol=2))
        self.package.write_bytes(b"RPA-3.0 0000000000000022 00000000\n" + data)
        with self.assertRaises(ImportProblem):
            RpaArchive(self.package)
        self.assertFalse(marker.exists())

    def test_malicious_pickle_in_rpyc_does_not_execute(self):
        marker = self.root / "executed"
        class Payload:
            def __reduce__(self):
                return eval, (f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')",)
        compiled = self.root / "evil.rpyc"
        compiled.write_bytes(zlib.compress(pickle.dumps(({}, [Payload()]), protocol=2)))
        with self.assertRaisesRegex(ImportProblem, "无法完整恢复"):
            decompile(compiled, self.root / "decoder")
        self.assertFalse(marker.exists())

    def test_invalid_archive_and_bounded_inflation(self):
        self.package.write_bytes(b"RPA-9.0 encrypted")
        with self.assertRaisesRegex(ImportProblem, "RPA 2/3"):
            RpaArchive(self.package)
        from app.archive import inflate
        with self.assertRaises(ImportProblem):
            inflate(zlib.compress(b"a" * 1000), 32)

    def test_truncated_or_overlapping_rpyc_slots_fail(self):
        compiled = self.root / "bad.rpyc"
        for data in (b"RENPY RPC2", b"RENPY RPC2" + struct.pack("<III", 1, 10, 8) + bytes(12)):
            compiled.write_bytes(data)
            with self.assertRaises(ImportProblem):
                read_slots(compiled)

    def test_real_compiled_archives_ids_dependencies_and_modules(self):
        self.game_and_package()
        original_game, original_package = snapshot(self.game), self.package.read_bytes()
        session = self.session()
        self.assertIsNotNone(session.originals["stable_welcome"])
        summary = self.build_session(session)
        self.assertEqual(summary["processed_statements"], 3)
        self.assertEqual(summary["unmatched_statements"], 1)
        self.assertTrue(summary["needs_review"])
        source = (self.output / "game/tl/chinese/new_name.rpy").read_text(encoding="utf-8")
        self.assertIn('Hello from the original.\\n原作中的你好。', source)
        self.assertIn('guide "没有可靠原文。"', source)
        module = self.output / "game/extras/optional.rpym"
        self.assertIn('An optional module line.\\n可选模块中的一句话。', module.read_text(encoding="utf-8"))
        self.assertFalse(module.with_suffix(".rpy").exists())
        self.assertEqual((self.output / "game/fonts/demo.ttf").read_bytes(), b"font dependency")
        self.assertTrue((self.output / "game/styles.rpy").is_file())
        self.assertFalse(list((self.output / "game").rglob("*.rpyc")))
        self.assertFalse(list((self.output / "game").rglob("*.rpymc")))
        self.assertEqual(snapshot(self.game), original_game)
        self.assertEqual(self.package.read_bytes(), original_package)
        provenance = json.loads((self.output / "provenance.json").read_text(encoding="utf-8"))
        self.assertTrue(any(r["member"].endswith(".rpymc") and r["recovered"] for r in provenance["files"]))
        self.assertIn("source", summary["diagnostics"][0])

    def test_missing_original_never_guesses_by_line_number(self):
        (self.game / "story.rpy").write_text('label start:\n    guide "WRONG nearby text"\n', encoding="utf-8")
        translated = b'# game/story.rpy:2\ntranslate chinese unknown:\n    guide "translated"\n'
        rpa(self.package, {"tl/chinese/story.rpy": translated})
        session = self.session()
        self.output.mkdir()
        (self.output / "sentinel").write_text("previous output")
        self.report.write_text("previous report")
        with self.assertRaisesRegex(ValueError, "没有生成任何可靠") as error:
            self.build_session(session)
        self.assertEqual((self.output / "sentinel").read_text(), "previous output")
        self.assertEqual(self.report.read_text(), "previous report")
        failed = json.loads(error.exception.report_path.read_text(encoding="utf-8"))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["diagnostics"][0]["file"], "tl/chinese/story.rpy")
        self.assertEqual(failed["diagnostics"][0]["line"], 3)
        self.assertEqual(failed["diagnostics"][0]["source"], str(self.package))

    def test_multiple_languages_or_packages_require_explicit_candidate(self):
        rpa(self.game / "one.rpa", {"tl/chinese/a.rpy": b'translate chinese a:\n    # "Hello"\n    "Hi"\n'})
        rpa(self.game / "two.rpa", {"tl/spanish/b.rpy": b'translate spanish b:\n    # "Hello"\n    "Hola"\n'})
        session = self.session(package=False)
        self.assertEqual(len(session.candidates), 2)
        with self.assertRaisesRegex(ImportProblem, "请选择"):
            build_imported(session, "", self.output, self.report)
        self.assertFalse(self.output.exists())

    def test_duplicate_original_id_is_reported_and_translation_kept(self):
        (self.game / "a.rpy").write_text('label start:\n    guide "A" id ambiguous\n', encoding="utf-8")
        (self.game / "b.rpy").write_text('label another:\n    guide "B" id ambiguous\n', encoding="utf-8")
        rpa(self.package, {"tl/chinese/a.rpy": b'translate chinese ambiguous:\n    guide "keep"\ntranslate chinese good:\n    # guide "Hello"\n    guide "Hi"\n'})
        summary = self.build_session(self.session())
        self.assertEqual(summary["processed_statements"], 1)
        self.assertEqual(summary["diagnostics"][0]["reason"], "ambiguous_original_id")

    def test_plain_rpym_remains_module_and_old_module_cache_is_removed(self):
        source = self.root / "source"
        source.mkdir()
        (source / "optional.rpym").write_text('translate chinese module:\n    # "Hello"\n    "你好"\n', encoding="utf-8")
        (source / "optional.rpymc").write_bytes(b"old")
        build(source, dst=self.output)
        self.assertIn('Hello\\n你好', (self.output / "optional.rpym").read_text(encoding="utf-8"))
        self.assertFalse((self.output / "optional.rpymc").exists())
        self.assertFalse((self.output / "optional.rpy").exists())

    def test_import_failure_cleans_work_and_preserves_inputs(self):
        (self.game / "broken.rpyc").write_bytes(b"broken")
        before = snapshot(self.game)
        with self.assertRaises(ImportProblem):
            self.session(package=False)
        self.assertEqual(snapshot(self.game), before)
        self.assertEqual(list((self.root / "work").iterdir()), [])

    def test_unknown_decompiler_node_cannot_publish_placeholder(self):
        from vendor.unrpyc.decompiler import magic
        from vendor.unrpyc.decompiler.renpycompat import CLASS_FACTORY
        node = CLASS_FACTORY("FutureUnknownStatement", "renpy.ast")()
        node.linenumber = 1
        data = magic.safe_dumps(({}, [node]), protocol=4)
        compiled = self.root / "unknown.rpyc"
        compiled.write_bytes(zlib.compress(data))
        with self.assertRaisesRegex(ImportProblem, "无法完整恢复"):
            decompile(compiled, self.root / "decoder")

    def test_flat_translation_cannot_replace_original_story_with_same_name(self):
        (self.game / "script.rpy").write_text('label start:\n    "Original"\n', encoding="utf-8")
        rpa(self.package, {"script.rpy": b'translate chinese good:\n    # "Original"\n    "translation"\n'})
        with self.assertRaisesRegex(ImportProblem, "同名原文"):
            self.build_session(self.session())

    def test_overlay_install_keeps_rpa_backs_up_fonts_and_compiled_modules(self):
        self.game_and_package()
        (self.game / "fonts").mkdir()
        (self.game / "fonts/demo.ttf").write_bytes(b"previous font")
        (self.game / "extras").mkdir()
        (self.game / "extras/optional.rpymc").write_bytes((FIXTURES / "module.rpymc.bin").read_bytes())
        session = self.session()
        self.build_session(session)
        archive = (self.game / "scripts.rpa").read_bytes()
        backup = deploy_package(self.output, self.game)
        self.assertEqual((self.game / "scripts.rpa").read_bytes(), archive)
        self.assertEqual((backup / "original/fonts/demo.ttf").read_bytes(), b"previous font")
        self.assertTrue((backup / "original/extras/optional.rpymc").is_file())
        self.assertFalse((self.game / "extras/optional.rpymc").exists())
        self.assertTrue((self.game / "extras/optional.rpym").is_file())
        self.assertFalse((self.game / "extras/optional.rpy").exists())
        self.assertTrue((backup / "restore-manifest.json").is_file())

    def test_install_failure_restores_all_targets(self):
        self.game_and_package()
        (self.game / "styles.rpy").write_text("# previous style\n", encoding="utf-8")
        self.build_session(self.session())
        before = snapshot(self.game)
        replace = Path.replace
        def fail(source, target):
            if ".rbb-deploy-" in str(source) and str(target).endswith("styles.rpy"):
                raise OSError("simulated locked file")
            return replace(source, target)
        with patch.object(Path, "replace", fail), self.assertRaisesRegex(OSError, "locked"):
            deploy_package(self.output, self.game)
        self.assertEqual(snapshot(self.game), before)

    def test_output_tampering_and_game_change_block_install(self):
        self.game_and_package()
        self.build_session(self.session())
        (self.output / "game/styles.rpy").write_text("tampered", encoding="utf-8")
        before = snapshot(self.game)
        with self.assertRaisesRegex(ImportProblem, "已改变"):
            deploy_package(self.output, self.game)
        self.assertEqual(snapshot(self.game), before)
        self.build_session(self.session())
        with (self.game / "scripts.rpa").open("ab") as stream:
            stream.write(b"game update")
        with self.assertRaisesRegex(ImportProblem, "游戏文件已改变"):
            deploy_package(self.output, self.game)

    def test_demo_plan_cannot_install(self):
        self.game_and_package()
        session = self.session()
        session.demo = True
        self.build_session(session)
        before = snapshot(self.game)
        with self.assertRaisesRegex(ImportProblem, "示例"):
            deploy_package(self.output, self.game)
        self.assertEqual(snapshot(self.game), before)

    def test_output_and_reports_cannot_overwrite_archive_or_translation_directory(self):
        self.game_and_package()
        session = self.session()
        before = self.package.read_bytes()
        for output in (self.package, self.root, self.game / "output"):
            with self.subTest(output=output), self.assertRaises(ImportProblem):
                build_imported(session, session.candidates[0].id, output, self.report)
        with self.assertRaises(ImportProblem):
            build_imported(session, session.candidates[0].id, self.output, self.game / "report.json")
        self.assertEqual(self.package.read_bytes(), before)
        translation = self.root / "translation"
        translation.mkdir()
        (translation / "hello.rpy").write_text('translate chinese hi:\n    # "Hello"\n    "Hi"\n', encoding="utf-8")
        other = import_inputs(self.game, translation, self.root / "work")
        self.addCleanup(other.close)
        for output in (translation, translation / "output"):
            with self.assertRaises(ImportProblem):
                build_imported(other, other.candidates[0].id, output, self.report)
        self.assertTrue((translation / "hello.rpy").is_file())

    def test_interruption_after_backup_rename_restores_original(self):
        self.game_and_package()
        (self.game / "styles.rpy").write_text("# previous style", encoding="utf-8")
        self.build_session(self.session())
        before = snapshot(self.game)
        replace = Path.replace
        def interrupt(source, target):
            result = replace(source, target)
            if source == self.game / "styles.rpy":
                raise KeyboardInterrupt()
            return result
        with patch.object(Path, "replace", interrupt), self.assertRaises(KeyboardInterrupt):
            deploy_package(self.output, self.game)
        self.assertEqual(snapshot(self.game), before)

    def test_failed_rollback_keeps_backup_and_reports_location(self):
        self.game_and_package()
        (self.game / "styles.rpy").write_text("# previous style", encoding="utf-8")
        self.build_session(self.session())
        replace = Path.replace
        def fail(source, target):
            if str(target).endswith("styles.rpy") and (".rbb-deploy-" in str(source) or "renpy_bilingual_backups" in str(source)):
                raise OSError("locked")
            return replace(source, target)
        with patch.object(Path, "replace", fail), self.assertRaisesRegex(RuntimeError, "自动恢复未完成") as error:
            deploy_package(self.output, self.game)
        backups = list((self.root / "renpy_bilingual_backups").glob("*/original/styles.rpy"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "# previous style")
        self.assertIn(str(backups[0].parent.parent), str(error.exception))

    def test_new_game_script_requires_recheck(self):
        self.game_and_package()
        self.build_session(self.session())
        for name in ("new.rpy", "new_ren.py"):
            with self.subTest(name=name):
                path = self.game / name
                path.write_text("# installed after scan", encoding="utf-8")
                with self.assertRaisesRegex(ImportProblem, "新增"):
                    deploy_package(self.output, self.game)
                path.unlink()

    def test_legacy_executable_backups_move_outside_game(self):
        self.game_and_package()
        old = self.game / "tl/chinese_backup_20200101"
        old.mkdir(parents=True)
        (old / "new_name.rpyc").write_bytes((FIXTURES / "translation.rpyc.bin").read_bytes())
        self.build_session(self.session())
        backup = deploy_package(self.output, self.game)
        self.assertFalse(old.exists())
        self.assertTrue((backup / "legacy/chinese_backup_20200101/new_name.rpyc").is_file())

    def test_display_patch_matches_user_verified_version(self):
        patch_file = Path(__file__).resolve().parents[1] / "patches/zz_bilingual_ui_patch.rpy"
        self.assertEqual(hashlib.sha256(patch_file.read_bytes()).hexdigest(),
                         "75ad08b7a350e64bf368cca57ab3bad581949cfb902edaf41befad822719e14b")

    def test_python_style_source_precedence_cannot_produce_ineffective_success(self):
        rpa(self.package, {"hello.rpy": b'translate chinese hello:\n    # "Hello"\n    "Hi"\n',
                           "hello_ren.py": b"# Python-style Ren'Py source takes precedence\n"})
        with self.assertRaisesRegex(ImportProblem, "优先加载"):
            self.build_session(self.session())
        self.assertFalse(self.output.exists())

    def test_separate_font_and_style_archive_is_dependency_not_language_choice(self):
        folder = self.root / "translation-folder"
        folder.mkdir()
        rpa(folder / "dialogue.rpa", {"tl/chinese/hello.rpy": b'translate chinese hello:\n    # "Hello"\n    "Hi"\n'})
        rpa(folder / "fonts.rpa", {"fonts/demo.ttf": b"font", "tl/chinese/style.rpy":
            b'translate chinese python:\n    gui.text_font = "fonts/demo.ttf"\n'})
        session = import_inputs(self.game, folder, self.root / "work")
        self.addCleanup(session.close)
        self.build_session(session)
        self.assertEqual((self.output / "game/fonts/demo.ttf").read_bytes(), b"font")
        self.assertIn('gui.text_font', (self.output / "game/tl/chinese/style.rpy").read_text())
