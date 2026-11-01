from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from meeting.runtime_paths import (
    REQUIRED_MODEL_FILES,
    RuntimePaths,
    get_runtime_paths,
    missing_runtime_files,
)


class RuntimePathsTests(unittest.TestCase):
    def test_paths_always_use_installed_layout(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder).resolve()
            executable = root / "install" / "HearU Mate.exe"
            local_app_data = root / "local"
            with patch.object(
                sys,
                "executable",
                str(executable),
            ), patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=False,
            ):
                paths = get_runtime_paths()
            self.assertEqual(paths.app_root, executable.parent)
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
            (resources / "assets" / "hearu_mate.ico").write_bytes(b"ico")
            paths = RuntimePaths(
                app_root=root,
                resource_root=resources,
                models_root=models,
                data_dir=root / "data",
                settings_dir=root / "data",
            )
            missing = missing_runtime_files(paths)
            self.assertEqual(
                {path.relative_to(models).as_posix() for path in missing},
                set(REQUIRED_MODEL_FILES),
            )


if __name__ == "__main__":
    unittest.main()
