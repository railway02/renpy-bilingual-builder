from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.deployment import deploy_to_game


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "Eternum" / "game"
        self.target = self.game / "tl" / "chinese"
        self.target.mkdir(parents=True)
        (self.target / "script.rpy").write_text("old translation")
        self.output = self.root / "output"
        self.output.mkdir()
        (self.output / "script.rpy").write_text("new translation")
        (self.output / "script.rpyc").write_bytes(b"stale")
        self.patch = self.root / "zz_bilingual_ui_patch.rpy"
        self.patch.write_text("new patch")
        (self.game / self.patch.name).write_text("old patch")
        (self.game / self.patch.with_suffix(".rpyc").name).write_bytes(b"old patch compiled")

    def test_backups_and_stale_bytecode_are_outside_game(self):
        legacy = self.target.with_name("chinese_backup_20260428_120000")
        legacy.mkdir()
        (legacy / "script.rpy").write_text("legacy backup")
        _, target_patch, backup = deploy_to_game(self.output, self.game, self.patch)
        self.assertNotIn(self.game, backup.parents)
        self.assertEqual((backup / "script.rpy").read_text(), "old translation")
        self.assertEqual((backup.parent / legacy.name / "script.rpy").read_text(), "legacy backup")
        self.assertEqual((backup.parent / self.patch.name).read_text(), "old patch")
        self.assertFalse(legacy.exists())
        self.assertFalse(target_patch.with_suffix(".rpyc").exists())
        self.assertFalse((self.target / "script.rpyc").exists())
        self.assertEqual((self.target / "script.rpy").read_text(), "new translation")
        _, _, next_backup = deploy_to_game(self.output, self.game, self.patch)
        self.assertNotEqual(backup.parent, next_backup.parent)

    def test_failed_install_restores_previous_files(self):
        move = shutil.move

        def fail_patch_install(src, dst):
            if ".rbb-deploy-" in src and src.endswith(self.patch.name):
                raise OSError("simulated disk error")
            return move(src, dst)

        with patch("app.deployment.shutil.move", side_effect=fail_patch_install):
            with self.assertRaises(OSError):
                deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
        self.assertEqual((self.game / self.patch.name).read_text(), "old patch")
        self.assertTrue((self.game / self.patch.with_suffix(".rpyc").name).exists())

    def test_partial_translation_install_is_removed_before_restore(self):
        move = shutil.move

        def fail_partial_install(src, dst):
            if ".rbb-deploy-" in src and Path(src).name == "chinese":
                Path(dst).mkdir()
                (Path(dst) / "partial.rpy").write_text("incomplete new translation")
                raise OSError("partial copy failed")
            return move(src, dst)

        with patch("app.deployment.shutil.move", side_effect=fail_partial_install):
            with self.assertRaisesRegex(OSError, "partial copy failed"):
                deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
        self.assertFalse((self.target / "partial.rpy").exists())
        self.assertEqual((self.game / self.patch.name).read_text(), "old patch")

    def test_first_install_without_translation_directory(self):
        shutil.rmtree(self.target.parent)
        (self.game / self.patch.name).unlink()
        (self.game / self.patch.with_suffix(".rpyc").name).unlink()
        target, target_patch, backup = deploy_to_game(self.output, self.game, self.patch)
        self.assertIsNone(backup)
        self.assertEqual((target / "script.rpy").read_text(), "new translation")
        self.assertEqual(target_patch.read_text(), "new patch")

    def test_empty_or_compiled_only_output_is_rejected_before_changes(self):
        (self.output / "script.rpy").unlink()
        for source_content in (None, " \n\t"):
            with self.subTest(source_content=source_content):
                if source_content is not None:
                    (self.output / "script.rpy").write_text(source_content)
                with self.assertRaisesRegex(ValueError, r"\.rpy"):
                    deploy_to_game(self.output, self.game, self.patch)
                self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
                self.assertEqual((self.game / self.patch.name).read_text(), "old patch")
                self.assertFalse((self.game.parent / "renpy_bilingual_backups").exists())

    def test_nonexistent_game_is_not_created(self):
        missing_game = self.root / "missing" / "game"
        with self.assertRaises(NotADirectoryError):
            deploy_to_game(self.output, missing_game, self.patch)
        self.assertFalse(missing_game.parent.exists())

    def _link(self, link, target, *, directory=True):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def test_linked_translation_parent_cannot_modify_external_files(self):
        external = self.root / "external_translations"
        self.target.parent.rename(external)
        self._link(self.target.parent, external)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((external / "chinese" / "script.rpy").read_text(), "old translation")
        self.assertFalse((self.game.parent / "renpy_bilingual_backups").exists())

    def test_linked_translation_target_is_rejected(self):
        external = self.root / "external_chinese"
        self.target.rename(external)
        self._link(self.target, external)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            deploy_to_game(self.output, self.game, self.patch)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((external / "script.rpy").read_text(), "old translation")

    def test_linked_patch_target_is_rejected(self):
        target_patch = self.game / self.patch.name
        external = self.root / "external_patch.rpy"
        target_patch.rename(external)
        self._link(target_patch, external, directory=False)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual(external.read_text(), "old patch")
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")

    def test_linked_backup_directory_is_rejected(self):
        external = self.root / "external_backups"
        external.mkdir()
        self._link(self.game.parent / "renpy_bilingual_backups", external)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")

    def test_unexpected_target_type_is_rejected(self):
        target_patch = self.game / self.patch.name
        target_patch.unlink()
        target_patch.mkdir()
        with self.assertRaisesRegex(ValueError, "必须是文件"):
            deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")

    def test_staging_failure_does_not_create_backups(self):
        with patch("app.deployment.shutil.copytree", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
        self.assertEqual((self.game / self.patch.name).read_text(), "old patch")
        self.assertFalse((self.game.parent / "renpy_bilingual_backups").exists())
        self.assertEqual(list(self.game.parent.glob(".rbb-deploy-*")), [])

    def test_backup_failure_restores_translation_and_legacy_backups(self):
        legacy = self.target.with_name("chinese_backup_old")
        legacy.mkdir()
        (legacy / "script.rpy").write_text("legacy translation")
        move = shutil.move

        def fail_patch_backup(src, dst):
            if src == str(self.game / self.patch.name):
                raise OSError("backup failed")
            return move(src, dst)

        with patch("app.deployment.shutil.move", side_effect=fail_patch_backup):
            with self.assertRaisesRegex(OSError, "backup failed"):
                deploy_to_game(self.output, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
        self.assertEqual((legacy / "script.rpy").read_text(), "legacy translation")
        self.assertEqual((self.game / self.patch.name).read_text(), "old patch")

    def test_failed_restore_still_restores_other_files_and_reports_backup(self):
        move = shutil.move

        def fail_patch_install_and_restore(src, dst):
            if ".rbb-deploy-" in src and src.endswith(self.patch.name):
                raise OSError("install failed")
            if "renpy_bilingual_backups" in src and src.endswith(self.patch.name):
                raise OSError("restore failed")
            return move(src, dst)

        with patch("app.deployment.shutil.move", side_effect=fail_patch_install_and_restore):
            with self.assertRaisesRegex(RuntimeError, "renpy_bilingual_backups") as raised:
                deploy_to_game(self.output, self.game, self.patch)
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")
        self.assertTrue((self.game / self.patch.with_suffix(".rpyc").name).exists())
        saved_patches = list((self.game.parent / "renpy_bilingual_backups").glob("*/" + self.patch.name))
        self.assertEqual(len(saved_patches), 1)
        self.assertEqual(saved_patches[0].read_text(), "old patch")

    def test_game_cannot_contain_output_copy(self):
        with self.assertRaises(ValueError):
            deploy_to_game(self.target, self.game, self.patch)
        self.assertEqual((self.target / "script.rpy").read_text(), "old translation")


if __name__ == "__main__":
    unittest.main()
