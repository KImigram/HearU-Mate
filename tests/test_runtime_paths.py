from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from meeting.runtime_paths import (
    PROJECT_ROOT,
    REQUIRED_MODEL_FILES,
    get_runtime_paths,
    missing_runtime_files,
)


class RuntimePathsTests(unittest.TestCase):
    def test_development_mode_keeps_project_data_and_external_models(self) -> None:
        with patch.object(sys, "frozen", False, create=True), patch.dict(
            os.environ,
            {},
            clear=False,
        ):
            for name in (
                "HEARU_DATA_DIR",
                "HEARU_MODELS_DIR",
                "HEARU_SETTINGS_DIR",
            ):
                os.environ.pop(name, None)
            paths = get_runtime_paths()
        self.assertFalse(paths.frozen)
        self.assertEqual(paths.settings_dir, PROJECT_ROOT)
        self.assertEqual(paths.data_dir, PROJECT_ROOT / "data" / "meetings")
        self.assertEqual(paths.models_root, Path("D:/models/sherpa-onnx"))

    def test_frozen_mode_uses_install_models_and_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder).resolve()
            executable = root / "install" / "HearU Mate.exe"
            resources = root / "install" / "_internal"
            local_app_data = root / "local"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys,
                "executable",
                str(executable),
            ), patch.object(
                sys,
                "_MEIPASS",
                str(resources),
                create=True,
            ), patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=False,
            ):
                for name in (
                    "HEARU_DATA_DIR",
                    "HEARU_MODELS_DIR",
                    "HEARU_SETTINGS_DIR",
                ):
                    os.environ.pop(name, None)
                paths = get_runtime_paths()
            self.assertTrue(paths.frozen)
            self.assertEqual(paths.app_root, executable.parent)
            self.assertEqual(paths.resource_root, resources)
            self.assertEqual(paths.models_root, executable.parent / "models")
            self.assertEqual(paths.data_dir, local_app_data / "HearU Mate")
            self.assertEqual(paths.settings_dir, local_app_data / "HearU Mate")

    def test_self_check_reports_missing_models_without_loading_them(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder).resolve()
            resources = root / "resources"
            models = root / "models"
            (resources / "desktop").mkdir(parents=True)
            (resources / "assets").mkdir(parents=True)
            (resources / "desktop" / "styles.qss").write_text("")
            (resources / "assets" / "check.svg").write_text("")
            (resources / "assets" / "down_arrow.svg").write_text("")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys,
                "executable",
                str(root / "HearU Mate.exe"),
            ), patch.object(
                sys,
                "_MEIPASS",
                str(resources),
                create=True,
            ), patch.dict(
                os.environ,
                {"HEARU_MODELS_DIR": str(models)},
                clear=False,
            ):
                paths = get_runtime_paths()
                missing = missing_runtime_files(paths)
            self.assertEqual(
                {path.relative_to(models).as_posix() for path in missing},
                set(REQUIRED_MODEL_FILES),
            )


if __name__ == "__main__":
    unittest.main()
