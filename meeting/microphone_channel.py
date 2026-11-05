from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QThread

from .asr_service import ASRResult, ASRService, create_asr_service
from .audio_capture import WasapiMicrophoneCapture
from .audio_utils import AudioChunk
from .config import MeetingConfig
from .vad import VoiceActivityDetector, create_vad
from .windows_com import WindowsComApartment


logger = logging.getLogger(__name__)


class MicrophoneChannel(QThread):
    """Optional microphone pipeline isolated from the system-audio recorder."""

    def __init__(
        self,
        config: MeetingConfig,
        device_id: str | None,
        *,
        timeline_origin: float,
        result_handler: Callable[[ASRResult], None],
        status_handler: Callable[[bool, str], None],
        error_handler: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.config = config
        self.device_id = device_id
        self.timeline_origin = float(timeline_origin)
        self.result_handler = result_handler
        self.status_handler = status_handler
        self.error_handler = error_handler
        self._enabled = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self, *, enabled: bool = False) -> None:
        if self.isRunning():
            self.set_enabled(enabled)
            return
        self._stop.clear()
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()
        super().start()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()
        self._wake.set()

    def stop(self) -> None:
        self._enabled.clear()
        self._stop.set()
        self._wake.set()
        if self.isRunning() and QThread.currentThread() is not self:
            if not self.wait(5000):
                logger.warning("Microphone channel did not stop within timeout")

    def run(self) -> None:
        capture = None
        vad: VoiceActivityDetector | None = None
        asr: ASRService | None = None
        try:
            with WindowsComApartment():
                while not self._stop.is_set():
                    if not self._enabled.is_set():
                        self._wake.wait(0.25)
                        self._wake.clear()
                        continue
                    try:
                        if vad is None:
                            vad = create_vad(
                                self.config.vad,
                                self.config.audio.sample_rate,
                            )
                        if asr is None:
                            asr = create_asr_service(
                                self.config.asr,
                                self.config.audio.sample_rate,
                            )
                            asr.start()
                        vad.reset()
                        asr.reset()
                        capture = WasapiMicrophoneCapture(
                            device_id=self.device_id,
                            sample_rate=self.config.audio.sample_rate,
                            channels=1,
                            chunk_duration_ms=self.config.audio.chunk_duration_ms,
                        )
                        capture.start()
                        offset = max(
                            0.0,
                            time.monotonic() - self.timeline_origin,
                        )
                        self.status_handler(True, "本人麦克风已开启")
                        last_end = offset
                        while (
                            self._enabled.is_set()
                            and not self._stop.is_set()
                        ):
                            chunk = capture.read_chunk()
                            shifted = AudioChunk(
                                chunk.samples,
                                chunk.sample_rate,
                                offset + chunk.start_time,
                                offset + chunk.end_time,
                            )
                            last_end = shifted.end_time
                            self._process_chunk(shifted, vad, asr, offset)
                        final = asr.finalize_utterance(last_end)
                        if final is not None:
                            self.result_handler(final)
                    except Exception as exc:
                        self._enabled.clear()
                        message = f"{type(exc).__name__}: {exc}"
                        logger.exception("Microphone channel failed")
                        self.error_handler(message)
                    finally:
                        if capture is not None:
                            try:
                                capture.stop()
                            except Exception:
                                logger.exception("Failed to close microphone")
                            capture = None
                        self.status_handler(False, "本人麦克风已关闭")
        finally:
            if capture is not None:
                try:
                    capture.stop()
                except Exception:
                    pass
            if asr is not None:
                try:
                    asr.stop()
                except Exception:
                    pass

    def _process_chunk(
        self,
        chunk: AudioChunk,
        vad: VoiceActivityDetector,
        asr: ASRService,
        offset: float,
    ) -> None:
        decision = vad.accept(chunk)
        if decision.audio_samples is not None:
            for result in asr.feed_audio(
                decision.audio_samples,
                (
                    decision.audio_start + offset
                    if decision.speech_started
                    and decision.audio_start is not None
                    else decision.audio_start
                    if decision.audio_start is not None
                    else chunk.start_time
                ),
                (
                    decision.audio_end
                    if decision.audio_end is not None
                    else chunk.end_time
                ),
            ):
                self.result_handler(result)
        if decision.speech_ended:
            final = asr.finalize_utterance(
                (
                    decision.segment_end
                    if decision.segment_end is not None
                    else chunk.end_time
                ) + (
                    offset if decision.segment_end is not None else 0.0
                )
            )
            if final is not None:
                self.result_handler(final)
