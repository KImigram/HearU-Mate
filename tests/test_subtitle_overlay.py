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

    def test_two_line_subtitle_expands_without_clipping(self) -> None:
        overlay = SubtitleOverlay()
        initial_height = overlay.height()
        overlay.update_partial(
            "这是一段足够长的实时字幕，用来验证第二行出现以后窗口会自动增加高度，"
            "上下都保留完整的文字空间，而不会把文字压缩或裁掉。"
        )
        self.assertGreaterEqual(overlay.height(), initial_height)
        self.assertGreaterEqual(
            overlay.subtitle_label.maximumHeight(),
            overlay.subtitle_label.fontMetrics().height() * 2,
        )
        overlay.close()


if __name__ == "__main__":
    unittest.main()
