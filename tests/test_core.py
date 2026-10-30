from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from meeting.audio_utils import normalize_audio
from meeting.alignment import align_speaker
from meeting.config import MeetingConfig
from meeting.recorder import MeetingRecorder
from meeting.store import MeetingStore
from meeting.speaker_service import SpeakerSegment
from meeting.transcript import MeetingTranscript, TranscriptSegment


class CoreTests(unittest.TestCase):
    def test_auto_speaker_clustering_uses_conservative_threshold(self) -> None:
        self.assertEqual(MeetingConfig().speaker.clustering_threshold, 0.85)

    def test_alignment_returns_one_dominant_speaker_not_a_combination(self) -> None:
        transcript = TranscriptSegment(
            start_time=0.0,
            end_time=10.0,
            text="测试",
        )
        diarization = [
            SpeakerSegment(0.0, 6.0, "Speaker_01"),
            SpeakerSegment(4.5, 10.0, "Speaker_02"),
        ]
        self.assertEqual(
            align_speaker(transcript, diarization),
            "Speaker_01",
        )

    def test_recorder_construction_does_not_load_models(self) -> None:
        recorder = MeetingRecorder(MeetingConfig())
        self.assertIsNone(recorder.vad)
        self.assertIsNone(recorder.asr)
        self.assertIsNone(recorder.speaker)
        self.assertIsNone(recorder.audio_capture)

    def test_audio_normalization_is_16khz_mono(self) -> None:
        stereo = np.ones((4800, 2), dtype=np.float32)
        normalized = normalize_audio(stereo, 48000, 16000)
        self.assertEqual(normalized.dtype, np.float32)
        self.assertEqual(normalized.shape, (1600,))

    def test_store_preserves_raw_and_corrected_text(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            store = MeetingStore(root / "history.db")
            transcript = MeetingTranscript.create(meeting_id="meeting-1")
            transcript.add_segment(
                TranscriptSegment(
                    start_time=0.0,
                    end_time=1.5,
                    text="原始 文本",
                    corrected_text="原始文本",
                    speaker="Speaker_01",
                )
            )
            transcript.finish()
            output_dir = transcript.save(root / "meetings")
            store.save_transcript(transcript, output_dir)
            meeting = store.get_meeting("meeting-1")
            self.assertIsNotNone(meeting)
            segment = meeting["segments"][0]
            self.assertEqual(segment["raw_text"], "原始 文本")
            self.assertEqual(segment["corrected_text"], "原始文本")
            payload = json.loads(
                (output_dir / "transcript.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["segments"][0]["text"], "原始 文本")
            self.assertEqual(
                payload["segments"][0]["corrected_text"],
                "原始文本",
            )
            markdown = (output_dir / "transcript.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("# 会议纪要", markdown)
            self.assertIn("## 会议正文", markdown)
            self.assertIn("### 00:00:00 · Speaker 01", markdown)
            self.assertIn("原始文本", markdown)
            self.assertIn(
                "### 00:00:00 · Speaker 01\n\n\n原始文本。",
                markdown,
            )

            store.update_speaker_names(
                "meeting-1",
                {"Speaker_01": "张三"},
            )
            renamed = store.get_meeting("meeting-1")
            self.assertEqual(
                renamed["speaker_names"],
                {"Speaker_01": "张三"},
            )
            self.assertEqual(
                renamed["segments"][0]["speaker"],
                "Speaker_01",
            )
            self.assertEqual(
                renamed["segments"][0]["display_speaker"],
                "张三",
            )
            renamed_json = json.loads(
                (output_dir / "transcript.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                renamed_json["segments"][0]["speaker"],
                "Speaker_01",
            )
            self.assertEqual(
                renamed_json["segments"][0]["speaker_name"],
                "张三",
            )
            self.assertEqual(
                renamed_json["metadata"]["speaker_names"],
                {"Speaker_01": "张三"},
            )
            renamed_markdown = (
                output_dir / "transcript.md"
            ).read_text(encoding="utf-8")
            self.assertIn("### 00:00:00 · 张三", renamed_markdown)


if __name__ == "__main__":
    unittest.main()

