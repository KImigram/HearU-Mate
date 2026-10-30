from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop.history_view import HistoryRow, HistoryTranscriptView
from desktop.transcript_view import TranscriptRow
from meeting.summary_service import ActionItem, MeetingSummary


class HistoryViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_long_history_is_rendered_in_one_document(self) -> None:
        view = HistoryTranscriptView()
        view.resize(760, 320)
        rows = [
            HistoryRow(
                speaker=f"Speaker {index % 3 + 1:02d}",
                timestamp=f"00:{index // 60:02d}:{index % 60:02d}",
                text=f"第 {index + 1} 条长会议正文。" * 3,
                corrected=index == 149,
            )
            for index in range(150)
        ]
        summary = MeetingSummary(
            overview="这是会议概览。",
            key_points=["第一个要点"],
            decisions=["一项决定"],
            action_items=[ActionItem("完成测试", "张三", "明天")],
            open_questions=["一个待确认问题"],
            keywords=["会议", "测试"],
        )

        view.set_meeting_content(
            rows,
            summary=summary,
            summary_meta="test-model · 2026-10-30 18:00:00",
        )
        view.show()
        self.app.processEvents()

        plain_text = view.document().toPlainText()
        self.assertIn("这是会议概览。", plain_text)
        self.assertIn("第 1 条长会议正文。", plain_text)
        self.assertIn("第 150 条长会议正文。", plain_text)
        self.assertIn("AI 已根据完整上下文校对", plain_text)
        self.assertEqual(view.findChildren(TranscriptRow), [])
        self.assertGreater(view.verticalScrollBar().maximum(), 0)

    def test_meeting_text_is_html_escaped(self) -> None:
        view = HistoryTranscriptView()
        view.set_meeting_content([
            HistoryRow(
                speaker="<Speaker>",
                timestamp="00:00:01",
                text="小于号 < 与大于号 > 应作为正文显示。",
            )
        ])

        plain_text = view.document().toPlainText()
        self.assertIn("<Speaker>", plain_text)
        self.assertIn("小于号 < 与大于号 >", plain_text)


if __name__ == "__main__":
    unittest.main()
