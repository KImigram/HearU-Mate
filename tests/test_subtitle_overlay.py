from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from desktop.subtitle_overlay import SubtitleOverlay


class SubtitleOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_partial_grows_and_next_sentence_replaces_final(self) -> None:
        overlay = SubtitleOverlay()
        overlay.update_partial("这是第一")
        self.assertEqual(overlay.text, "这是第一")
        overlay.update_partial("这是第一句话")
        self.assertEqual(overlay.text, "这是第一句话")

        overlay.update_final("这是第一句话。")
        self.assertEqual(overlay.text, "这是第一句话。")
        overlay.update_partial("这是第二句")
        self.assertEqual(overlay.text, "这是第二句")
        overlay.close()

    def test_overlay_is_always_on_top_and_close_button_updates_state(self) -> None:
        overlay = SubtitleOverlay()
        closed: list[bool] = []
        overlay.closed.connect(lambda: closed.append(True))
        self.assertTrue(
            overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )
        self.assertTrue(
            overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
        )
        overlay.show()
        self.app.processEvents()
        overlay.close_button.click()
        self.app.processEvents()
        self.assertEqual(closed, [True])
        self.assertFalse(overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
