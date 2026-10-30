from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from desktop.main_window import MainWindow
from meeting.config import CorrectionConfig
from meeting.store import MeetingStore
from meeting.summary_service import (
    OpenAICompatibleSummaryService,
)


SUMMARY_PAYLOAD = {
    "overview": "团队讨论了发布计划与当前风险。",
    "key_points": ["先完成桌面版稳定性验证"],
    "decisions": ["本周先进行内部测试"],
    "action_items": [
        {
            "task": "整理测试清单",
            "owner": "张三",
            "deadline": "未明确",
        }
    ],
    "open_questions": ["安装包签名方案待确认"],
    "keywords": ["桌面版", "测试"],
}


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(
            content=json.dumps(SUMMARY_PAYLOAD, ensure_ascii=False)
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )


class SummaryTests(unittest.TestCase):
    def test_summary_payload_is_validated_and_rendered(self) -> None:
        summary = OpenAICompatibleSummaryService.parse_payload(
            SUMMARY_PAYLOAD
        )
        self.assertIn("会议概览", summary.to_plain_text())
        self.assertIn("负责人：张三", summary.to_plain_text())
        self.assertIn("## AI 摘要", summary.to_markdown())

    def test_long_transcript_uses_chunk_and_consolidation_calls(self) -> None:
        service = OpenAICompatibleSummaryService(
            CorrectionConfig(),
            api_key="test-only",
            max_chars_per_request=1000,
        )
        completions = _FakeCompletions()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        service._create_client = lambda: client
        meeting = {
            "title": "长会议",
            "segments": [
                {
                    "start_time": index,
                    "speaker": "Speaker_01",
                    "raw_text": "会议内容" * 180,
                    "corrected_text": None,
                }
                for index in range(3)
            ],
        }

        summary = service.summarize(meeting)

        self.assertEqual(summary.overview, SUMMARY_PAYLOAD["overview"])
        self.assertEqual(len(completions.calls), 4)

    def test_summary_is_persisted_separately_from_transcript(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = MeetingStore(Path(folder) / "history.db")
            store.create_meeting("meeting-summary", datetime.now())
            store.save_summary(
                "meeting-summary",
                SUMMARY_PAYLOAD,
                model="deepseek-test",
            )

            meeting = store.get_meeting("meeting-summary")

            self.assertEqual(meeting["summary"], SUMMARY_PAYLOAD)
            self.assertEqual(meeting["summary_model"], "deepseek-test")
            self.assertIsNotNone(meeting["summary_generated_at"])

    def test_markdown_export_includes_summary_before_transcript(self) -> None:
        class ExportHarness:
            _summary_from_payload = staticmethod(
                MainWindow._summary_from_payload
            )

            @staticmethod
            def _read_meeting_markdown(meeting):
                return "# 会议纪要\n\n## 会议正文\n\n正文。\n"

        markdown = MainWindow._build_export_markdown(
            ExportHarness(),
            {"summary": SUMMARY_PAYLOAD},
        )

        self.assertLess(
            markdown.index("## AI 摘要"),
            markdown.index("## 会议正文"),
        )
        self.assertIn("整理测试清单", markdown)


if __name__ == "__main__":
    unittest.main()
