from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from meeting.config import MeetingConfig
from meeting.recorder import MeetingRecorder
from meeting.store import MeetingStore
from meeting.transcript import MeetingTranscript, TranscriptSegment


class HistoricalCorrectionWorker(QObject):
    """Re-run AI correction for a saved meeting without loading local models."""

    completed = Signal(str, str, str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        meeting: dict,
        db_path: str | Path,
        *,
        base_url: str,
        model: str,
        correction_service=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.meeting = meeting
        self.db_path = Path(db_path)
        self.base_url = base_url
        self.model = model
        self.correction_service = correction_service

    def _transcript(self) -> MeetingTranscript:
        start_time = datetime.fromisoformat(str(self.meeting["start_time"]))
        end_value = self.meeting.get("end_time")
        return MeetingTranscript(
            meeting_id=str(self.meeting["meeting_id"]),
            start_time=start_time,
            end_time=(
                datetime.fromisoformat(str(end_value))
                if end_value else None
            ),
            metadata={
                "correction_backend": "openai_compatible",
                "correction_model": self.model,
                "raw_audio_saved": False,
            },
            segments=[
                TranscriptSegment(
                    start_time=float(segment.get("start_time") or 0.0),
                    end_time=float(segment.get("end_time") or 0.0),
                    text=str(segment.get("raw_text") or ""),
                    speaker=segment.get("speaker"),
                    is_final=True,
                )
                for segment in self.meeting.get("segments", [])
            ],
        )

    @Slot()
    def run(self) -> None:
        try:
            config = MeetingConfig()
            config.correction.enabled = True
            config.correction.base_url = self.base_url
            config.correction.model = self.model
            transcript = self._transcript()
            recorder = MeetingRecorder(
                config=config,
                correction=self.correction_service,
            )
            recorder.transcript = transcript
            recorder._correct_transcript()

            json_path = self.meeting.get("json_path")
            root_dir = (
                Path(str(json_path)).resolve().parent.parent
                if json_path
                else self.db_path.parent
            )
            output_dir = transcript.save(
                root_dir,
                readable=config.readability.enabled,
                merge_gap_seconds=config.readability.merge_gap_seconds,
                internal_punctuation_min_chars=(
                    config.readability.internal_punctuation_min_chars
                ),
                max_paragraph_chars=(
                    config.readability.max_paragraph_chars
                ),
            )
            store = MeetingStore(self.db_path)
            store.save_transcript(transcript, output_dir)
            speaker_names = dict(self.meeting.get("speaker_names") or {})
            if speaker_names:
                store.update_speaker_names(
                    transcript.meeting_id,
                    speaker_names,
                )

            status = str(
                transcript.metadata.get("correction_status") or "fallback"
            )
            reason = str(
                transcript.metadata.get("correction_error_message") or ""
            )
            self.completed.emit(transcript.meeting_id, status, reason)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
