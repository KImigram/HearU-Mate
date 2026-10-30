from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.env_store import (
    API_KEY_ENV,
    has_api_key,
    load_project_environment,
    save_project_api_key,
)


class EnvironmentStoreTests(unittest.TestCase):
    def test_key_is_saved_to_gitignored_project_env_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop(API_KEY_ENV, None)
                save_project_api_key(root, "test-key-not-real")
                env_text = (root / ".env").read_text(encoding="utf-8")
                self.assertIn("DEEPSEEK_API_KEY=", env_text)
                self.assertNotIn("api_key =", env_text.lower())
                os.environ.pop(API_KEY_ENV, None)
                self.assertTrue(load_project_environment(root))
                self.assertTrue(has_api_key())
                self.assertEqual(os.environ[API_KEY_ENV], "test-key-not-real")


if __name__ == "__main__":
    unittest.main()

