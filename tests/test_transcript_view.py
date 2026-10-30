from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from desktop.main_window import MainWindow
from desktop.transcript_view import TranscriptList


class TranscriptViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_partial_updates_the_same_row_and_final_removes_cursor(self) -> None:
        transcript = TranscriptList()
        row = transcript.add_row(
            "识别中",
            "00:06",
            partial=True,
        )

        row.set_text("第一段")
        self.assertEqual(transcript._layout.count(), 2)
        self.assertIn("第一段", row.text_label.text())
        self.assertTrue(row.text_label.text().endswith("▎"))

        row.set_text("第一段实时识别")
        self.assertEqual(transcript._layout.count(), 2)
        row.finalize("第一段实时识别", "00:05")
        self.assertEqual(row.text_label.text(), "第一段实时识别")
        self.assertEqual(row.time_label.text(), "00:05")

    def test_growing_partial_does_not_create_an_oversized_blank_row(self) -> None:
        transcript = TranscriptList()
        transcript.resize(760, 320)
        row = transcript.add_row("识别中", "00:06", partial=True)
        transcript.show()
        for length in range(20, 241, 20):
            row.set_text("这是一段持续增长的实时识别文本" * length)
            self.app.processEvents()
        self.assertLess(row.height(), 3000)

    def test_scroll_following_stops_when_user_leaves_the_bottom(self) -> None:
        transcript = TranscriptList()
        transcript.resize(640, 240)
        for index in range(30):
            transcript.add_row(
                "识别中",
                f"00:{index:02d}",
                "用于产生滚动区域的会议文本。" * 3,
            )
        transcript.show()
        self.app.processEvents()
        bar = transcript.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.assertTrue(transcript.is_near_bottom())
        bar.setValue(max(0, bar.maximum() // 2))
        self.assertFalse(transcript.is_near_bottom())

    def test_summary_and_transcript_share_one_scroll_area(self) -> None:
        transcript = TranscriptList()
        transcript.resize(640, 260)
        summary = QLabel("摘要内容\n" * 30)
        summary.setWordWrap(True)
        transcript.add_top_widget(summary)
        for index in range(12):
            transcript.add_row(
                "Speaker 01",
                f"00:{index:02d}",
                "会议正文内容。" * 8,
            )
        transcript.show()
        self.app.processEvents()

        self.assertGreater(transcript.verticalScrollBar().maximum(), 0)
        self.assertIs(transcript._layout.itemAt(0).widget(), summary)

        transcript.clear_rows()
        self.app.processEvents()
        self.assertIs(transcript._layout.itemAt(0).widget(), summary)
        self.assertEqual(transcript._layout.count(), 2)

    def test_corrected_note_is_only_shown_for_changed_text(self) -> None:
        transcript = TranscriptList()
        unchanged = transcript.add_row("Speaker 01", "00:01", "原文")
        corrected = transcript.add_row(
            "Speaker 02",
            "00:04",
            "校对文本",
            corrected=True,
        )

        self.assertFalse(unchanged.corrected_note.isVisible())
        corrected.show()
        self.assertFalse(corrected.corrected_note.isHidden())

    def test_saved_markdown_is_parsed_into_two_column_rows(self) -> None:
        markdown = """# 会议纪要

## 会议正文

### 00:00:06 · Speaker 01

第一段正文

### 00:00:10 · 张三

第二段正文
"""
        self.assertEqual(
            MainWindow._parse_markdown_rows(markdown),
            [
                ("00:00:06", "Speaker 01", "第一段正文"),
                ("00:00:10", "张三", "第二段正文"),
            ],
        )

    def test_summary_subheadings_are_not_parsed_as_transcript_rows(self) -> None:
        markdown = """# 会议纪要

## AI 摘要

### 核心要点

- 摘要内容

## 会议正文

### 00:00:06 · Speaker 01

真实正文
"""
        self.assertEqual(
            MainWindow._parse_markdown_rows(markdown),
            [("00:00:06", "Speaker 01", "真实正文")],
        )

    def test_merged_markdown_row_inherits_ai_correction_note(self) -> None:
        self.assertTrue(
            MainWindow._row_contains_correction(
                "00:00:06",
                "00:00:20",
                {13},
            )
        )
        self.assertFalse(
            MainWindow._row_contains_correction(
                "00:00:20",
                "00:00:30",
                {13},
            )
        )


if __name__ == "__main__":
    unittest.main()
