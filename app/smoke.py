"""Exercise the actual frozen Tk UI and worker; used by packaging verification."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
import sys
import tempfile
import time
import traceback
import zlib

from app.runtime import RuntimePaths


def run(paths: RuntimePaths, result_path: Path) -> None:
    from app.gui import BilingualBuilderApp

    result_path = result_path.resolve()
    paths.validate_output(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    failures = []

    class SmokeApp(BilingualBuilderApp):
        def _queue_message(self, kind, title, body):
            if kind == "error":
                failures.append(f"{title}: {body}")
            self._queue_log(f"{title}: {body}")

        def report_callback_exception(self, exc_type, exc_value, tb):
            failures.append("".join(traceback.format_exception(exc_type, exc_value, tb)))

    app = None
    result = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        assert (paths.resources / "patches/zz_bilingual_ui_patch.rpy").is_file()
        # A fresh work directory prevents smoke tests from replacing user output.
        with tempfile.TemporaryDirectory(prefix="rbb-smoke-", dir=result_path.parent) as work:
            app = SmokeApp(paths)
            app.withdraw()
            app.load_sample()
            app.original_english_dir.set("")  # Comments must work without original scripts.
            output = Path(work) / "中文 输出/tl/chinese"
            app.output_dir.set(str(output))
            app.start_build()
            deadline = time.monotonic() + 90
            while app._is_worker_running():
                app.update()
                if failures:
                    raise AssertionError("\n".join(failures))
                if time.monotonic() > deadline:
                    raise TimeoutError("GUI build did not finish within 90 seconds")
                time.sleep(0.02)
            assert not failures, failures
            assert app.build_succeeded
            assert app.deploy_button.cget("state") == "disabled"
            report = json.loads(app.last_report_path.read_text(encoding="utf-8"))
            assert report["processed_statements"] == 4, report
            assert report["unmatched_statements"] == 0, report
            assert app.last_report_path.with_suffix(".csv").is_file()
            text = (output / "chapter_demo.rpy").read_text(encoding="utf-8")
            assert 'Welcome, [player_name]!\\n欢迎你，[player_name]！' in text
            assert (paths.logs / "builder.log").is_file()
            result.update(ok=True, processed_statements=4, language=report["language"],
                          resources=str(paths.resources), data=str(paths.data),
                          report=str(app.last_report_path), tk=app.tk.call("info", "patchlevel"))
            # Exercise the same EXE's decoder helper and ordinary three-step UI.
            from app.package_deployment import deploy_package
            fixtures = paths.resources / "samples/import_demo"
            if not fixtures.is_dir() and not getattr(sys, "frozen", False):
                fixtures = paths.resources / "tests/fixtures/import_game"
            synthetic = Path(work) / "自动导入 游戏/game"
            synthetic.mkdir(parents=True)
            package = Path(work) / "汉化 包.rpa"

            def archive(path, files):
                data = bytearray(b"RPA-3.0 0000000000000000 00000000\n")
                index = {}
                for name, content in files.items():
                    index[name] = [(len(data), len(content), b"")]
                    data.extend(content)
                offset = len(data)
                data.extend(zlib.compress(pickle.dumps(index, protocol=4)))
                data[:34] = f"RPA-3.0 {offset:016x} 00000000\n".encode()
                path.write_bytes(data)

            archive(synthetic / "original.rpa", {
                "script.rpyc": (fixtures / "original.rpyc.bin").read_bytes(),
                "extras/optional.rpymc": (fixtures / "module.rpymc.bin").read_bytes(),
            })
            archive(package, {
                "tl/chinese/different_name.rpyc": (fixtures / "translation.rpyc.bin").read_bytes(),
                "extras/optional.rpymc": (fixtures / "module.rpymc.bin").read_bytes(),
                "fonts/demo.ttf": b"synthetic font dependency",
                "styles.rpy": b'define gui.text_font = "fonts/demo.ttf"\n',
            })
            original_archive = (synthetic / "original.rpa").read_bytes()
            package_bytes = package.read_bytes()
            app.chinese_tl_dir.set("")
            app.game_dir.set(str(synthetic))
            app.input_path.set(str(package))
            package_output = Path(work) / "导入输出"
            app.output_dir.set(str(package_output))
            app.start_build()
            deadline = time.monotonic() + 90
            while not app.build_succeeded:
                app.update()
                assert not failures, failures
                if time.monotonic() > deadline:
                    raise TimeoutError("Archive GUI flow did not finish")
                time.sleep(0.02)
            imported = json.loads(app.last_report_path.read_text(encoding="utf-8"))
            assert imported["processed_statements"] == 3, imported
            assert imported["unmatched_statements"] == 1, imported
            assert app.needs_review and app.built_package
            assert "部分完成" in app.status_text.get()
            assert (package_output / "game/extras/optional.rpym").is_file()
            assert not (package_output / "game/extras/optional.rpy").exists()
            backup = deploy_package(package_output, synthetic)
            assert (backup / "restore-manifest.json").is_file()
            assert (synthetic / "fonts/demo.ttf").read_bytes() == b"synthetic font dependency"
            assert (synthetic / "original.rpa").read_bytes() == original_archive
            assert package.read_bytes() == package_bytes
            result.update(archive_processed=3, unmatched_preserved=1, module_extension_preserved=True,
                          dependencies_preserved=True, archive_install_backup=True)
            # A zero-match attempt must expose diagnostics and keep the previous package.
            previous_output = {p.relative_to(package_output).as_posix(): p.read_bytes()
                               for p in package_output.rglob("*") if p.is_file()}
            unsupported_match = Path(work) / "缺少原文.rpa"
            archive(unsupported_match, {"tl/spanish/unknown.rpy":
                b'translate spanish unknown_identifier:\n    guide "No original available"\n'})
            app.input_path.set(str(unsupported_match))
            app.start_build()
            deadline = time.monotonic() + 90
            while not failures or app._is_worker_running():
                app.update()
                if time.monotonic() > deadline:
                    raise TimeoutError("Zero-match failure was not reported")
                time.sleep(0.02)
            assert len(failures) == 1, failures
            assert not app.build_succeeded
            assert app.deploy_button.cget("state") == "disabled"
            failed_report = json.loads(app.last_report_path.read_text(encoding="utf-8"))
            assert failed_report["status"] == "failed" and failed_report["unmatched_statements"] == 1
            assert failed_report["diagnostics"][0]["block_id"] == "unknown_identifier"
            assert previous_output == {p.relative_to(package_output).as_posix(): p.read_bytes()
                                       for p in package_output.rglob("*") if p.is_file()}
            assert (synthetic / "original.rpa").read_bytes() == original_archive
            result.update(zero_match_blocked=True, failure_report=True, previous_output_preserved=True)
    except Exception:
        result["error"] = traceback.format_exc()
        raise
    finally:
        if app is not None:
            # Do not clean up while a non-daemon build worker still owns files.
            if app.worker is not None:
                app.worker.join(timeout=5)
            if app.import_session is not None:
                app.import_session.close()
            app.destroy()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
