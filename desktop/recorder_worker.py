from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from meeting.config import MeetingConfig
from meeting.audio_capture import WasapiLoopbackCapture
from meeting.recorder import MeetingRecorder, RecorderEvent
from meeting.store import MeetingStore
from meeting.transcript import MeetingTranscript, TranscriptSegment
from meeting.windows_com import WindowsComApartment


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecorderOptions:
    device_id: str | None
    device_name: str
    expected_speakers: int
    correction_enabled: bool
    base_url: str
    model: str
    simulation: bool = False
    models_enabled: bool = True
    simulation_delay: float = 0.12


class RecorderWorker(QObject):
    """Owns the complete recorder lifecycle inside one QThread."""

    partial = Signal(str)
    final = Signal(str, float, float)
    status = Signal(str)
    completed = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        options: RecorderOptions,
        project_root: str | Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.options = options
        self.project_root = Path(project_root).resolve()
        self._stop_event = threading.Event()
        self._recorder: MeetingRecorder | None = None
        self._meeting_id: str | None = None
        self._active_store: MeetingStore | None = None
        self._live_segment_sequence = 0

    @Slot()
    def run(self) -> None:
        try:
            if self.options.simulation:
                try:
                    meeting_id = self._run_simulation()
                finally:
                    self._release()
            else:
                if not self.options.models_enabled:
                    raise RuntimeError(
                        "本地模型加载尚未获得确认，真实录制入口保持关闭。"
                    )
                # Keep COM initialized for the entire SoundCard lifecycle.
                # Recorder/audio cleanup runs before this context exits.
                with WindowsComApartment():
                    try:
                        meeting_id = self._run_real_recorder()
                    finally:
                        self._release()
            self.status.emit("已完成")
            self.completed.emit(meeting_id)
        except Exception as exc:
            self._mark_failed(str(exc))
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def request_stop(self) -> None:
        """Thread-safe stop request callable from the GUI thread."""
        if not self._stop_event.is_set():
            self.status.emit("正在停止录音")
        self._stop_event.set()
        if self._active_store is not None and self._meeting_id:
            try:
                self._active_store.update_status(
                    self._meeting_id,
                    "stopping",
                )
            except Exception:
                pass
        if self._recorder is not None:
            self._recorder.request_stop()

    def _new_config(self) -> MeetingConfig:
        config = MeetingConfig()
        config.audio.device_id = self.options.device_id
        config.speaker.num_speakers = self.options.expected_speakers
        config.correction.enabled = self.options.correction_enabled
        config.correction.base_url = self.options.base_url
        config.correction.model = self.options.model
        config.output.root_dir = str(self.project_root / "data" / "meetings")
        return config

    def _store(self) -> MeetingStore:
        return MeetingStore(
            self.project_root / "data" / "meetings" / "meeting_history.db"
        )

    def _run_real_recorder(self) -> str:
        config = self._new_config()
        meeting_id = uuid.uuid4().hex
        self._meeting_id = meeting_id
        self._live_segment_sequence = 0
        store = self._store()
        self._active_store = store
        store.create_meeting(
            meeting_id,
            datetime.now(),
            device_name=self.options.device_name,
        )

        self.status.emit("正在加载本地语音与说话人模型")
        self._recorder = MeetingRecorder(
            config=config,
            event_handler=self._handle_event,
            meeting_id=meeting_id,
        )
        transcript = self._recorder.run()
        self.status.emit("正在保存")
        output_dir = self._recorder.save()
        store.save_transcript(transcript, output_dir)
        return meeting_id

    def _run_simulation(self) -> str:
        """Exercise the UI and persistence pipeline without loading any model."""
        config = self._new_config()
        meeting_id = uuid.uuid4().hex
        self._meeting_id = meeting_id
        self._live_segment_sequence = 0
        store = self._store()
        self._active_store = store
        transcript = MeetingTranscript.create(
            {
                "mode": "development_simulation",
                "audio_source": "none",
                "raw_audio_saved": False,
                "correction_status": "disabled_in_simulation",
            },
            meeting_id=meeting_id,
        )
        store.create_meeting(
            meeting_id,
            transcript.start_time,
            device_name=self.options.device_name,
        )
        store.update_status(meeting_id, "recording")
        self.status.emit("录制中 · 开发模拟模式（未加载模型）")

        samples = [
            "这是第一段实时识别示例，Partial 会在同一行逐步增长。",
            "会议结束后将依次执行说话人区分、文本校对与保存状态。",
        ]
        cursor = 0.0
        for sentence in samples:
            if self._stop_event.is_set():
                break
            step = max(1, len(sentence) // 8)
            for end in range(step, len(sentence) + step, step):
                if self._stop_event.wait(self.options.simulation_delay):
                    break
                self.partial.emit(sentence[: min(end, len(sentence))])
            if self._stop_event.is_set():
                break
            duration = max(1.0, len(sentence) * 0.08)
            segment = TranscriptSegment(
                start_time=cursor,
                end_time=cursor + duration,
                text=sentence,
                speaker="Speaker_01",
                is_final=True,
            )
            transcript.add_segment(segment)
            self._save_live_segment(
                sentence,
                segment.start_time,
                segment.end_time,
            )
            self.final.emit(sentence, segment.start_time, segment.end_time)
            cursor = segment.end_time + 0.4

        self.status.emit("正在停止录音")
        self._pause()
        self.status.emit("正在区分说话人")
        self._pause()
        if self.options.correction_enabled:
            self.status.emit("正在进行AI文本校对")
            self._pause()
        transcript.finish()
        self.status.emit("正在保存")
        output_dir = transcript.save(
            config.output.root_dir,
            readable=config.readability.enabled,
            merge_gap_seconds=config.readability.merge_gap_seconds,
            internal_punctuation_min_chars=(
                config.readability.internal_punctuation_min_chars
            ),
            max_paragraph_chars=config.readability.max_paragraph_chars,
        )
        store.save_transcript(transcript, output_dir)
        return meeting_id

    def _pause(self) -> None:
        time.sleep(min(self.options.simulation_delay, 0.08))

    def _handle_event(self, event: RecorderEvent) -> None:
        if event.type == "partial":
            self.partial.emit(event.text)
        elif event.type == "final":
            self._save_live_segment(
                event.text,
                float(event.start_time or 0.0),
                float(event.end_time or 0.0),
            )
            self.final.emit(
                event.text,
                float(event.start_time or 0.0),
                float(event.end_time or 0.0),
            )
        elif event.type == "status":
            labels = {
                "recording": "录制中",
                "processing": "正在区分说话人",
                "correcting": "正在进行AI文本校对",
                "stopped": "正在保存",
            }
            if self._active_store is not None and self._meeting_id:
                database_status = {
                    "recording": "recording",
                    "processing": "processing",
                    "correcting": "processing",
                    "stopped": "processing",
                }.get(event.text)
                if database_status:
                    self._active_store.update_status(
                        self._meeting_id,
                        database_status,
                    )
            self.status.emit(labels.get(event.text, event.text))

    def _save_live_segment(
        self,
        text: str,
        start_time: float,
        end_time: float,
    ) -> None:
        if self._active_store is None or not self._meeting_id:
            return
        try:
            self._active_store.save_live_segment(
                self._meeting_id,
                self._live_segment_sequence,
                start_time,
                end_time,
                text,
            )
            self._live_segment_sequence += 1
        except Exception:
            # A transient checkpoint failure must not stop audio capture. The
            # final save still has another opportunity to persist everything.
            logger.exception("Failed to checkpoint live transcript segment")

    def _mark_failed(self, message: str) -> None:
        if not self._meeting_id:
            return
        try:
            self._store().update_status(
                self._meeting_id,
                "failed",
                error_message=message,
            )
        except Exception:
            pass

    def _release(self) -> None:
        recorder = self._recorder
        self._recorder = None
        self._active_store = None
        if recorder is not None:
            recorder.request_stop()
            for service in (
                recorder.audio_capture,
                recorder.asr,
                recorder.speaker,
            ):
                if service is None:
                    continue
                try:
                    service.stop()
                except Exception:
                    pass


class DeviceDiscoveryWorker(QObject):
    """Enumerates WASAPI loopback devices outside the GUI thread."""

    devices_ready = Signal(object)
    error = Signal(str)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        try:
            with WindowsComApartment():
                devices = WasapiLoopbackCapture().list_devices()
                payload = [
                    {
                        "id": device.id,
                        "name": device.name,
                        "is_default": device.is_default,
                    }
                    for device in devices
                ]
                self.devices_ready.emit(payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

