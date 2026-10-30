from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from .alignment import align_transcript
from .asr_service import ASRResult, ASRService, create_asr_service
from .audio_capture import AudioCapture, WasapiLoopbackCapture
from .config import MeetingConfig
from .correction_service import (
    TranscriptCorrectionService,
    create_correction_service,
)
from .speaker_service import (
    SpeakerDiarizationService,
    create_speaker_service,
)
from .transcript import MeetingTranscript, TranscriptSegment
from .vad import VoiceActivityDetector, create_vad


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecorderEvent:
    type: str
    text: str = ""
    start_time: float | None = None
    end_time: float | None = None
    speaker: str | None = None


class MeetingRecorder:
    def __init__(
        self,
        config: MeetingConfig | None = None,
        audio_capture: AudioCapture | None = None,
        vad: VoiceActivityDetector | None = None,
        asr: ASRService | None = None,
        speaker: SpeakerDiarizationService | None = None,
        correction: TranscriptCorrectionService | None = None,
        event_handler: Callable[[RecorderEvent], None] | None = None,
        meeting_id: str | None = None,
        correction_api_key: str | None = None,
    ):
        self.config = config or MeetingConfig()
        # Services are created lazily in start(). Constructing a recorder must
        # never load a local model or open an audio device.
        self.audio_capture = audio_capture
        self.vad = vad
        self.asr = asr
        self.speaker = speaker
        self.correction = correction
        self.correction_api_key = correction_api_key
        self.event_handler = event_handler
        self.meeting_id = meeting_id
        self.transcript: MeetingTranscript | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_audio_end = 0.0

    def _emit(self, event: RecorderEvent) -> None:
        if self.event_handler:
            self.event_handler(event)

    def start(self) -> MeetingTranscript:
        if self._running:
            raise RuntimeError("MeetingRecorder 已经在运行")
        if self.config.output.save_raw_audio:
            raise NotImplementedError(
                "原始音频调试保存尚未实现；为保护会议隐私，当前必须保持关闭。"
            )
        self.audio_capture = self.audio_capture or WasapiLoopbackCapture(
            device_id=self.config.audio.device_id,
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
            chunk_duration_ms=self.config.audio.chunk_duration_ms,
        )
        self.vad = self.vad or create_vad(
            self.config.vad,
            self.config.audio.sample_rate,
        )
        self.asr = self.asr or create_asr_service(
            self.config.asr,
            self.config.audio.sample_rate,
        )
        self.speaker = self.speaker or create_speaker_service(
            self.config.speaker
        )
        metadata = {
            "audio_source": self.config.audio.source,
            "sample_rate": self.config.audio.sample_rate,
            "asr_backend": self.config.asr.backend,
            "asr_model_dir": self.config.asr.model_dir,
            "speaker_backend": self.config.speaker.backend,
            "speaker_segmentation_model": (
                self.config.speaker.segmentation_model
            ),
            "speaker_embedding_model": self.config.speaker.embedding_model,
            "raw_audio_saved": self.config.output.save_raw_audio,
            "correction_backend": (
                self.config.correction.backend
                if self.config.correction.enabled else None
            ),
            "correction_model": (
                self.config.correction.model
                if self.config.correction.enabled else None
            ),
        }
        self.transcript = MeetingTranscript.create(
            metadata,
            meeting_id=self.meeting_id,
        )
        self._stop_event.clear()
        assert self.audio_capture is not None
        assert self.asr is not None
        assert self.speaker is not None
        started = []
        try:
            self.asr.start()
            started.append(self.asr)
            self.speaker.start()
            started.append(self.speaker)
            self.audio_capture.start()
            started.append(self.audio_capture)
        except Exception:
            for service in reversed(started):
                service.stop()
            raise
        self._running = True
        self._emit(RecorderEvent("status", "recording"))
        return self.transcript

    def run(self) -> MeetingTranscript:
        if not self._running:
            self.start()
        assert self.transcript is not None
        assert self.audio_capture is not None
        assert self.vad is not None
        assert self.asr is not None
        assert self.speaker is not None
        try:
            while not self._stop_event.is_set():
                chunk = self.audio_capture.read_chunk()
                self._last_audio_end = chunk.end_time
                self.speaker.feed_audio(
                    chunk.samples,
                    chunk.sample_rate,
                    chunk.start_time,
                    chunk.end_time,
                )
                decision = self.vad.accept(chunk)
                if decision.audio_samples is not None:
                    for result in self.asr.feed_audio(
                        decision.audio_samples,
                        (
                            decision.audio_start
                            if decision.audio_start is not None
                            else chunk.start_time
                        ),
                        (
                            decision.audio_end
                            if decision.audio_end is not None
                            else chunk.end_time
                        ),
                    ):
                        self._handle_asr_result(result)
                if decision.speech_ended:
                    final = self.asr.finalize_utterance(
                        (
                            decision.segment_end
                            if decision.segment_end is not None
                            else chunk.end_time
                        )
                    )
                    if final:
                        self._handle_asr_result(final)
        finally:
            self.stop()
        return self.transcript

    def _handle_asr_result(self, result: ASRResult) -> None:
        if not result.text.strip():
            return
        if not result.is_final:
            self._emit(RecorderEvent(
                "partial",
                result.text,
                result.start_time,
                result.end_time,
            ))
            return
        segment = TranscriptSegment(
            start_time=result.start_time,
            end_time=result.end_time,
            text=result.text,
            is_final=True,
        )
        assert self.transcript is not None
        self.transcript.add_segment(segment)
        self._emit(RecorderEvent(
            "final",
            segment.text,
            segment.start_time,
            segment.end_time,
            segment.speaker,
        ))

    def request_stop(self) -> None:
        self._stop_event.set()

    def stop(self) -> None:
        if not self._running:
            return
        assert self.audio_capture is not None
        assert self.asr is not None
        assert self.speaker is not None
        errors = []
        try:
            final = self.asr.finalize_utterance(self._last_audio_end)
            if final:
                self._handle_asr_result(final)
        except Exception as exc:
            errors.append(exc)
            logger.exception("Failed to finalize ASR stream")
        try:
            self._emit(RecorderEvent("status", "processing"))
            speaker_segments = self.speaker.get_segments()
        except Exception as exc:
            speaker_segments = []
            errors.append(exc)
            logger.exception("Failed to collect speaker segments")
        for service in (self.audio_capture, self.asr, self.speaker):
            try:
                service.stop()
            except Exception as exc:
                errors.append(exc)
                logger.exception("Failed to stop %s", type(service).__name__)
        self._running = False
        assert self.transcript is not None
        align_transcript(
            self.transcript.segments,
            speaker_segments,
        )
        self._correct_transcript()
        self.transcript.finish()
        self._emit(RecorderEvent("status", "stopped"))
        if errors:
            self.transcript.metadata["processing_warnings"] = [
                type(error).__name__ for error in errors
            ]
            logger.warning(
                "会议已保留，但停止或会后处理期间发生 %d 个非致命错误",
                len(errors),
            )

    def _correct_transcript(self) -> None:
        assert self.transcript is not None
        if not self.config.correction.enabled:
            self.transcript.metadata["correction_status"] = "disabled"
            return
        try:
            self._emit(RecorderEvent("status", "correcting"))
            logger.info(
                "正在调用会后文本校对服务：%s",
                self.config.correction.model,
            )
            service = self.correction or create_correction_service(
                self.config.correction,
                api_key=self.correction_api_key,
            )
            results = service.correct(self.transcript.segments)
            if len(results) != len(self.transcript.segments):
                raise RuntimeError("校对结果数量与原始片段不一致")
            for segment, result in zip(self.transcript.segments, results):
                segment.corrected_text = result.corrected_text
                if result.corrected_text != segment.text:
                    segment.corrections = [{
                        "original": segment.text,
                        "corrected": result.corrected_text,
                        "reason": result.reason,
                    }]
            failed_batches = int(getattr(service, "failed_batches", 0))
            total_batches = int(getattr(service, "total_batches", 0))
            if failed_batches:
                self.transcript.metadata["correction_error"] = (
                    getattr(service, "last_error_type", None)
                    or "CorrectionBatchError"
                )
                self.transcript.metadata["correction_failed_batches"] = (
                    failed_batches
                )
                self.transcript.metadata["correction_total_batches"] = (
                    total_batches
                )
                self.transcript.metadata["correction_status"] = (
                    "fallback"
                    if failed_batches == total_batches
                    else "partial"
                )
                logger.warning(
                    "AI校对有 %d/%d 个批次失败，失败部分保留原文",
                    failed_batches,
                    total_batches,
                )
            else:
                self.transcript.metadata["correction_status"] = "success"
                logger.info("会后文本校对完成")
        except Exception as exc:
            self.transcript.metadata["correction_status"] = "fallback"
            self.transcript.metadata["correction_error"] = type(exc).__name__
            logger.warning(
                "会后文本校对失败，已回退原始文本：%s: %s",
                type(exc).__name__,
                exc,
            )

    def save(self):
        if self.transcript is None:
            raise RuntimeError("当前没有可保存的会议记录")
        if self.transcript.end_time is None:
            self.transcript.finish()
        path = self.transcript.save(
            self.config.output.root_dir,
            readable=self.config.readability.enabled,
            merge_gap_seconds=self.config.readability.merge_gap_seconds,
            internal_punctuation_min_chars=(
                self.config.readability.internal_punctuation_min_chars
            ),
            max_paragraph_chars=self.config.readability.max_paragraph_chars,
        )
        self._emit(RecorderEvent("saved", str(path)))
        return path
