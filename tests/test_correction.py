from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from meeting.config import CorrectionConfig
from meeting.correction_service import OpenAICompatibleCorrectionService
from meeting.correction_service import CorrectionResult
from meeting.recorder import MeetingRecorder
from meeting.transcript import MeetingTranscript, TranscriptSegment


class _SequencedCompletions:
    def __init__(self, responses: list[str | None]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if response is None:
            payload = json.loads(kwargs["messages"][1]["content"])
            response = json.dumps({
                "segments": [
                    {
                        "id": item["id"],
                        "corrected_text": item["text"] + "。",
                        "reason": "补充标点",
                    }
                    for item in payload["segments"]
                ]
            }, ensure_ascii=False)
        message = SimpleNamespace(content=response)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )


class CorrectionTests(unittest.TestCase):
    @staticmethod
    def _service(responses, *, batch_size=20):
        config = CorrectionConfig(max_segments_per_request=batch_size)
        service = OpenAICompatibleCorrectionService(
            config,
            api_key="test-only",
        )
        completions = _SequencedCompletions(responses)
        service._create_client = lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        return service, completions

    def test_invalid_response_is_retried_once(self) -> None:
        service, completions = self._service(["not-json", None])
        segments = [TranscriptSegment(0.0, 1.0, "第一段")]

        results = service.correct(segments)

        self.assertEqual(completions.calls, 2)
        self.assertEqual(results[0].corrected_text, "第一段。")
        self.assertEqual(service.failed_batches, 0)

    def test_failed_batch_keeps_original_and_continues(self) -> None:
        service, completions = self._service(
            ["bad", "still-bad", None],
            batch_size=1,
        )
        segments = [
            TranscriptSegment(0.0, 1.0, "第一段"),
            TranscriptSegment(1.0, 2.0, "第二段"),
        ]

        results = service.correct(segments)

        self.assertEqual(completions.calls, 3)
        self.assertEqual(results[0].corrected_text, "第一段")
        self.assertEqual(results[1].corrected_text, "第二段。")
        self.assertEqual(service.failed_batches, 1)
        self.assertEqual(service.total_batches, 2)
        self.assertIn("合法JSON", service.last_error_message)

    def test_recorder_marks_partial_correction_status(self) -> None:
        class PartialCorrectionService:
            failed_batches = 1
            total_batches = 2
            last_error_type = "CorrectionServiceError"

            @staticmethod
            def correct(segments):
                return [
                    CorrectionResult(0, "第一段。", "补充标点"),
                    CorrectionResult(1, "第二段", "失败后保留原文"),
                ]

        recorder = MeetingRecorder(
            correction=PartialCorrectionService(),
        )
        recorder.transcript = MeetingTranscript.create(
            meeting_id="partial-correction"
        )
        recorder.transcript.segments = [
            TranscriptSegment(0.0, 1.0, "第一段"),
            TranscriptSegment(1.0, 2.0, "第二段"),
        ]

        recorder._correct_transcript()

        self.assertEqual(
            recorder.transcript.metadata["correction_status"],
            "partial",
        )
        self.assertEqual(
            recorder.transcript.metadata["correction_failed_batches"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
