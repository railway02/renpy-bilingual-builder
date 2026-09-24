"""Frozen resources, writable paths and logs must not depend on the launch cwd."""

import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.runtime import RuntimePaths, configure_logging, resource_root


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_frozen_resources_use_bundle_root(self):
        bundle = self.root / "只读程序/运行依赖文件"
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", str(bundle), create=True):
            self.assertEqual(resource_root(), bundle)

    def test_windows_paths_use_writable_profile_not_program(self):
        with patch("sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            paths = RuntimePaths.create()
        self.assertEqual(paths.data, self.root / "RenPyBilingualBuilder")
        for path in (paths.output, paths.logs, paths.reports):
            self.assertTrue(path.is_dir())

    def test_unwritable_profile_falls_back(self):
        blocked = self.root / "blocked"
        blocked.write_text("not a directory")
        with patch("sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": str(blocked)}):
            with patch("pathlib.Path.home", return_value=self.root / "fallback"):
                paths = RuntimePaths.create()
        self.assertEqual(paths.data, self.root / "fallback/AppData/Local/RenPyBilingualBuilder")
        self.assertTrue(paths.logs.is_dir())

    def test_environment_cannot_redirect_writes_inside_bundle(self):
        bundle = self.root / "program"
        with patch("sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": str(bundle)}):
            with patch("app.runtime.protected_directories", return_value=(bundle,)):
                with patch("pathlib.Path.home", return_value=self.root / "user"):
                    paths = RuntimePaths.create()
        self.assertFalse(bundle.exists())
        self.assertNotIn(bundle, paths.data.parents)

    def test_output_cannot_replace_resources_or_own_logs(self):
        paths = RuntimePaths(self.root / "bundle", self.root / "user")
        for output in (paths.resources, paths.resources / "output", paths.resources.parent,
                       paths.logs, paths.data, paths.reports / "output"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                paths.validate_output(output)
        paths.validate_output(paths.output / "bilingual")

    def test_log_written_as_utf8_and_exception_is_preserved(self):
        paths = RuntimePaths(self.root / "bundle", self.root / "user")
        paths.logs.mkdir(parents=True)
        logger = logging.getLogger("rbb")
        previous = logger.handlers[:]
        logger.handlers.clear()
        previous_propagate, previous_level = logger.propagate, logger.level
        try:
            log_path = configure_logging(paths)
            try:
                raise ValueError("中文错误")
            except ValueError:
                logger.exception("构建失败")
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("ValueError: 中文错误", content)
            self.assertIn("Traceback", content)
        finally:
            for handler in logger.handlers:
                handler.close()
            logger.handlers[:] = previous
            logger.propagate, logger.level = previous_propagate, previous_level
