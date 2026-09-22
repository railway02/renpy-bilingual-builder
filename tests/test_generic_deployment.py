"""Exercise language-specific deployment without changing an unrelated game UI."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.deployment import OWNED_UI_PATCH, deploy_to_game


class GenericDeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "OtherGame" / "game"
        self.target = self.game / "tl" / "spanish"
        self.target.mkdir(parents=True)
        (self.target / "chapter.rpy").write_text("old spanish")
        (self.game / "screens.rpy").write_text("game's original screens")
        chinese = self.game / "tl" / "chinese"
        chinese.mkdir()
        (chinese / "chapter.rpy").write_text("unrelated language")
        self.output = self.root / "output"
        self.output.mkdir()
        (self.output / "chapter.rpy").write_text("new spanish bilingual")
        (self.output / "chapter.rpyc").write_bytes(b"stale compiled file")

    def test_generic_installs_selected_language_and_preserves_ui_and_other_languages(self):
        target, ui_patch, backup = deploy_to_game(self.output, self.game, language="spanish")
        self.assertEqual(target, self.target)
        self.assertIsNone(ui_patch)
        self.assertEqual((target / "chapter.rpy").read_text(), "new spanish bilingual")
        self.assertFalse((target / "chapter.rpyc").exists())
        self.assertEqual((backup / "chapter.rpy").read_text(), "old spanish")
        self.assertNotIn(self.game, backup.parents)
        self.assertEqual((self.game / "screens.rpy").read_text(), "game's original screens")
        self.assertEqual((self.game / "tl/chinese/chapter.rpy").read_text(), "unrelated language")
        self.assertFalse((self.game / OWNED_UI_PATCH).exists())

    def test_generic_rejects_old_eternum_patch_before_any_changes(self):
        for name in (OWNED_UI_PATCH, str(Path(OWNED_UI_PATCH).with_suffix(".rpyc"))):
            with self.subTest(name=name):
                installed = self.game / name
                installed.write_text("old Eternum patch")
                with self.assertRaisesRegex(ValueError, "旧版永恒世界 UI 补丁"):
                    deploy_to_game(self.output, self.game, language="spanish")
                self.assertEqual(installed.read_text(), "old Eternum patch")
                self.assertEqual((self.target / "chapter.rpy").read_text(), "old spanish")
                self.assertFalse((self.game.parent / "renpy_bilingual_backups").exists())
                installed.unlink()

    def test_language_cannot_escape_translation_folder_or_use_reserved_name(self):
        for language in ("../elsewhere", "/tmp/other", "a/b", "a\\b", "", "None", "CON", "LPT1", None):
            with self.subTest(language=language), self.assertRaises(ValueError):
                deploy_to_game(self.output, self.game, language=language)
        self.assertEqual((self.target / "chapter.rpy").read_text(), "old spanish")
        self.assertFalse((self.game.parent / "renpy_bilingual_backups").exists())

    def test_eternum_patch_requires_chinese(self):
        source_patch = self.root / OWNED_UI_PATCH
        source_patch.write_text("Eternum UI")
        with self.assertRaisesRegex(ValueError, "只适用于 chinese"):
            deploy_to_game(self.output, self.game, source_patch, language="spanish")
        self.assertEqual((self.target / "chapter.rpy").read_text(), "old spanish")

    def test_arbitrary_folder_is_rejected_without_creating_files(self):
        arbitrary = self.root / "Documents"
        arbitrary.mkdir()
        with self.assertRaisesRegex(ValueError, "未识别"):
            deploy_to_game(self.output, arbitrary, language="spanish")
        self.assertEqual(list(arbitrary.iterdir()), [])

    def test_generic_partial_failure_restores_selected_language(self):
        move = shutil.move

        def fail_partial_copy(source, target):
            if ".rbb-deploy-" in source and Path(source).name == "spanish":
                Path(target).mkdir()
                (Path(target) / "partial.rpy").write_text("partial")
                raise OSError("simulated partial install")
            return move(source, target)

        with patch("app.deployment.shutil.move", side_effect=fail_partial_copy):
            with self.assertRaisesRegex(OSError, "partial install"):
                deploy_to_game(self.output, self.game, language="spanish")
        self.assertEqual((self.target / "chapter.rpy").read_text(), "old spanish")
        self.assertFalse((self.target / "partial.rpy").exists())
        self.assertEqual((self.game / "screens.rpy").read_text(), "game's original screens")


if __name__ == "__main__":
    unittest.main()
