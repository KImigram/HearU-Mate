from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from meeting.audio_utils import normalize_audio
from meeting.alignment import align_speaker
from meeting.config import MeetingConfig, SPEAKER_EMBEDDING_PROFILES
from meeting.recorder import MeetingRecorder
from meeting.store import MeetingStore
from meeting.speaker_service import SpeakerSegment
from meeting.speaker_service import SherpaOnnxSpeakerDiarizationService
from meeting.transcript import MeetingTranscript, TranscriptSegment


class CoreTests(unittest.TestCase):
    def test_auto_speaker_clustering_uses_conservative_threshold(self) -> None:
        self.assertEqual(MeetingConfig().speaker.clustering_threshold, 0.85)

    def test_speaker_embedding_profiles_switch_without_loading_models(self) -> None:
        config = MeetingConfig().speaker
        config.select_embedding_profile("wespeaker_cnceleb_resnet34_lm")
        profile = SPEAKER_EMBEDDING_PROFILES[
            "wespeaker_cnceleb_resnet34_lm"
        ]
        self.assertEqual(
            config.embedding_profile,
            "wespeaker_cnceleb_resnet34_lm",
        )
        self.assertEqual(config.embedding_model, profile.model_path)
        self.assertEqual(
            config.clustering_threshold,
            profile.clustering_threshold,
        )

    def test_unknown_speaker_embedding_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MeetingConfig().speaker.select_embedding_profile("unknown")

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

    def test_speaker_audio_is_spooled_to_temporary_file(self) -> None:
        received = []

        def fake_runner(config, audio_path, sample_count):
            received.append(np.fromfile(audio_path, dtype=np.float32))
            self.assertEqual(sample_count, 3200)
            return []

        service = SherpaOnnxSpeakerDiarizationService(
            MeetingConfig().speaker,
            process_runner=fake_runner,
        )
        service._open_audio_spool()
        service._started = True
        spool = service._audio_spool
        spool_path = service._audio_spool_path

        service.feed_audio(
            np.arange(1600, dtype=np.float32),
            16000,
            0.0,
            0.1,
        )
        service.feed_audio(
            np.arange(1600, 3200, dtype=np.float32),
            16000,
            0.1,
            0.2,
        )
        self.assertEqual(service._sample_count, 3200)
        self.assertFalse(hasattr(service, "_chunks"))

        self.assertEqual(service.get_segments(), [])
        np.testing.assert_array_equal(
            received[0],
            np.arange(3200, dtype=np.float32),
        )
        service.stop()
        self.assertTrue(spool.closed)
        self.assertFalse(spool_path.exists())

    def test_speaker_failure_falls_back_and_does_not_lose_transcript(self) -> None:
        class FakeAudio:
            @staticmethod
            def stop():
                return None

        class FakeAsr:
            @staticmethod
            def finalize_utterance(end_time):
                return None

            @staticmethod
            def stop():
                return None

        class CrashedSpeaker:
            @staticmethod
            def get_segments():
                raise RuntimeError("native child exited 0xC0000005")

            @staticmethod
            def stop():
                return None

        config = MeetingConfig()
        config.correction.enabled = False
        transcript = MeetingTranscript.create(meeting_id="fallback-speaker")
        transcript.add_segment(TranscriptSegment(
            start_time=0.0,
            end_time=2.0,
            text="这段文字必须保留",
        ))
        recorder = MeetingRecorder(
            config=config,
            audio_capture=FakeAudio(),
            asr=FakeAsr(),
            speaker=CrashedSpeaker(),
        )
        recorder.transcript = transcript
        recorder._running = True

        recorder.stop()

        self.assertEqual(transcript.segments[0].speaker, "Speaker_01")
        self.assertEqual(transcript.metadata["speaker_status"], "fallback")
        self.assertEqual(transcript.metadata["correction_status"], "disabled")
        self.assertIsNotNone(transcript.end_time)

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

    def test_live_segments_survive_an_interrupted_recording(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            db_path = Path(folder) / "history.db"
            store = MeetingStore(db_path)
            transcript = MeetingTranscript.create(meeting_id="live-meeting")
            store.create_meeting("live-meeting", transcript.start_time)
            store.update_status("live-meeting", "recording")
            store.save_live_segment(
                "live-meeting",
                0,
                0.0,
                2.5,
                "已经完成识别的第一句话",
            )

            recovered = MeetingStore(db_path).get_meeting("live-meeting")

            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(len(recovered["segments"]), 1)
            self.assertEqual(
                recovered["segments"][0]["raw_text"],
                "已经完成识别的第一句话",
            )

    def test_meeting_can_be_renamed_and_fully_deleted(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            meetings_root = Path(folder) / "meetings"
            store = MeetingStore(meetings_root / "meeting_history.db")
            transcript = MeetingTranscript.create(meeting_id="delete-me")
            transcript.add_segment(TranscriptSegment(
                start_time=0.0,
                end_time=1.0,
                text="需要删除的会议正文",
                speaker="Speaker_01",
            ))
            transcript.finish()
            output_dir = transcript.save(meetings_root)
            store.save_transcript(transcript, output_dir)
            store.save_summary(
                transcript.meeting_id,
                {"overview": "待删除摘要"},
                model="test-model",
            )
            store.update_speaker_names(
                transcript.meeting_id,
                {"Speaker_01": "张三"},
            )

            store.rename_meeting(transcript.meeting_id, "产品周会")
            # A later final/re-correction save must preserve the custom title.
            store.save_transcript(transcript, output_dir)
            self.assertEqual(
                store.get_meeting(transcript.meeting_id)["title"],
                "产品周会",
            )

            self.assertTrue(store.delete_meeting(transcript.meeting_id))
            self.assertIsNone(store.get_meeting(transcript.meeting_id))
            self.assertFalse(output_dir.exists())

    def test_delete_refuses_export_directory_outside_meetings_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            store = MeetingStore(root / "data" / "meeting_history.db")
            transcript = MeetingTranscript.create(meeting_id="unsafe-path")
            transcript.add_segment(TranscriptSegment(
                start_time=0.0,
                end_time=1.0,
                text="安全检查",
            ))
            transcript.finish()
            output_dir = transcript.save(root / "outside")
            store.save_transcript(transcript, output_dir)

            with self.assertRaises(ValueError):
                store.delete_meeting(transcript.meeting_id)

            self.assertIsNotNone(store.get_meeting(transcript.meeting_id))
            self.assertTrue(output_dir.exists())


if __name__ == "__main__":
    unittest.main()

