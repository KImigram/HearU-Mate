from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from desktop.main_window import MainWindow


class RecordingNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_active_recording_can_be_reopened_after_viewing_history(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with patch("desktop.main_window.QTimer.singleShot"):
                window = MainWindow(folder, simulation_mode=True)
            self.assertTrue(window.current_meeting_button.isHidden())

            window._thread = object()  # type: ignore[assignment]
            window.current_meeting_button.setVisible(True)
            window.pages.setCurrentWidget(window.detail_page)

            window.show_current_meeting()

            self.assertIs(
                window.pages.currentWidget(),
                window.recording_page,
            )
            self.assertFalse(window.current_meeting_button.isHidden())
            window._thread = None
            window.close()

    def test_new_meeting_button_returns_to_active_recording(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with patch("desktop.main_window.QTimer.singleShot"):
                window = MainWindow(folder, simulation_mode=True)
            window._thread = object()  # type: ignore[assignment]
            window.pages.setCurrentWidget(window.detail_page)

            window.show_new_meeting()

            self.assertIs(
                window.pages.currentWidget(),
                window.recording_page,
            )
            window._thread = None
            window.close()


if __name__ == "__main__":
    unittest.main()
