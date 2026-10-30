from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from desktop.correction_worker import HistoricalCorrectionWorker
from meeting.correction_service import CorrectionResult
from meeting.store import MeetingStore
from meeting.summary_service import MeetingSummary
from meeting.transcript import MeetingTranscript, TranscriptSegment


class _SuccessfulCorrectionService:
    failed_batches = 0
    total_batches = 1
    last_error_type = None
    last_error_message = None

    @staticmethod
    def correct(segments):
        return [
            CorrectionResult(
                segment_id=index,
                corrected_text=segment.text.replace("原是", "原始"),
                reason="修复同音字",
            )
            for index, segment in enumerate(segments)
        ]


class HistoricalCorrectionWorkerTests(unittest.TestCase):
    def test_retry_preserves_raw_text_speaker_names_and_summary(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            db_path = root / "meeting_history.db"
            store = MeetingStore(db_path)
            transcript = MeetingTranscript.create(meeting_id="retry-meeting")
            transcript.add_segment(TranscriptSegment(
                start_time=0.0,
                end_time=2.0,
                text="原是文本",
                speaker="Speaker_01",
            ))
            transcript.metadata["correction_status"] = "fallback"
            transcript.metadata["correction_error_message"] = "旧错误"
            transcript.finish()
            output_dir = transcript.save(root)
            store.save_transcript(transcript, output_dir)
            store.update_speaker_names(
                transcript.meeting_id,
                {"Speaker_01": "张三"},
            )
            store.save_summary(
                transcript.meeting_id,
                MeetingSummary(overview="已有摘要").to_dict(),
                model="test-summary-model",
            )
            meeting = store.get_meeting(transcript.meeting_id)
            completed = []
            errors = []
            worker = HistoricalCorrectionWorker(
                meeting,
                db_path,
                base_url="https://example.invalid",
                model="test-correction-model",
                correction_service=_SuccessfulCorrectionService(),
            )
            worker.completed.connect(
                lambda meeting_id, status, reason: completed.append(
                    (meeting_id, status, reason)
                )
            )
            worker.error.connect(errors.append)

            worker.run()

            self.assertFalse(errors)
            self.assertEqual(
                completed,
                [("retry-meeting", "success", "")],
            )
            updated = MeetingStore(db_path).get_meeting("retry-meeting")
            self.assertEqual(updated["correction_status"], "success")
            self.assertIsNone(updated["correction_error"])
            self.assertEqual(updated["segments"][0]["raw_text"], "原是文本")
            self.assertEqual(
                updated["segments"][0]["corrected_text"],
                "原始文本",
            )
            self.assertEqual(
                updated["segments"][0]["display_speaker"],
                "张三",
            )
            self.assertEqual(updated["summary"]["overview"], "已有摘要")
            markdown = Path(updated["markdown_path"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("张三", markdown)
            self.assertIn("原始文本", markdown)


if __name__ == "__main__":
    unittest.main()
