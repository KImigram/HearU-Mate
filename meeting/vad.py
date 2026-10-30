from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio_utils import AudioChunk
from .config import VADConfig


class VADServiceError(RuntimeError):
    pass


class VoiceActivityDetector(ABC):
    @abstractmethod
    def accept(self, chunk: AudioChunk) -> "VADDecision": ...

    @abstractmethod
    def reset(self) -> None: ...


@dataclass(slots=True)
class VADDecision:
    is_speech: bool
    speech_started: bool = False
    speech_ended: bool = False
    segment_samples: np.ndarray | None = None
    segment_start: float | None = None
    segment_end: float | None = None
    audio_samples: np.ndarray | None = None
    audio_start: float | None = None
    audio_end: float | None = None


class SherpaOnnxSileroVAD(VoiceActivityDetector):
    """Streaming Silero VAD backed by sherpa-onnx without PyTorch."""

    def __init__(self, config: VADConfig, sample_rate: int = 16000):
        model_path = Path(config.model).expanduser()
        if not model_path.is_file():
            raise VADServiceError(f"Silero VAD模型不存在：{model_path}")
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise VADServiceError("meeting_onnx环境中缺少sherpa-onnx") from exc

        silero = sherpa_onnx.SileroVadModelConfig(
            model=str(model_path),
            threshold=config.threshold,
            min_silence_duration=config.min_silence_duration,
            min_speech_duration=config.min_speech_duration,
            window_size=config.window_size,
            max_speech_duration=config.max_speech_duration,
        )
        model_config = sherpa_onnx.VadModelConfig(
            silero_vad=silero,
            sample_rate=sample_rate,
            num_threads=config.num_threads,
            provider="cpu",
            debug=False,
        )
        self._vad = sherpa_onnx.VoiceActivityDetector(
            model_config,
            buffer_size_in_seconds=max(60, config.max_speech_duration * 2),
        )
        self.sample_rate = int(sample_rate)
        self.window_size = int(config.window_size)
        self._pending = np.empty(0, dtype=np.float32)
        self._was_speech = False

    def reset(self) -> None:
        self._vad.reset()
        self._pending = np.empty(0, dtype=np.float32)
        self._was_speech = False

    def accept(self, chunk: AudioChunk) -> VADDecision:
        self._pending = np.concatenate((self._pending, chunk.samples))
        while self._pending.size >= self.window_size:
            window = self._pending[:self.window_size]
            self._pending = self._pending[self.window_size:]
            self._vad.accept_waveform(window)

        detected = bool(self._vad.is_speech_detected())
        started = detected and not self._was_speech
        ended = False
        segment_samples = None
        segment_start = None
        segment_end = None

        if not self._vad.empty():
            segment = self._vad.front
            segment_samples = np.asarray(segment.samples, dtype=np.float32).copy()
            segment_start = float(segment.start) / self.sample_rate
            segment_end = segment_start + segment_samples.size / self.sample_rate
            self._vad.pop()
            ended = True
            detected = False

        audio_samples = None
        audio_start = None
        if started:
            current = self._vad.current_segment
            audio_samples = np.asarray(current.samples, dtype=np.float32).copy()
            audio_start = float(current.start) / self.sample_rate
        elif self._was_speech or detected:
            audio_samples = chunk.samples
            audio_start = chunk.start_time

        self._was_speech = detected
        return VADDecision(
            is_speech=detected,
            speech_started=started,
            speech_ended=ended,
            segment_samples=segment_samples,
            segment_start=segment_start,
            segment_end=segment_end,
            audio_samples=audio_samples,
            audio_start=audio_start,
            audio_end=chunk.end_time,
        )

    def flush(self) -> VADDecision:
        if self._pending.size:
            padding = self.window_size - self._pending.size
            self._vad.accept_waveform(np.pad(self._pending, (0, padding)))
            self._pending = np.empty(0, dtype=np.float32)
        self._vad.flush()
        if self._vad.empty():
            return VADDecision(False)
        segment = self._vad.front
        samples = np.asarray(segment.samples, dtype=np.float32).copy()
        start = float(segment.start) / self.sample_rate
        self._vad.pop()
        return VADDecision(
            False,
            speech_ended=True,
            segment_samples=samples,
            segment_start=start,
            segment_end=start + samples.size / self.sample_rate,
        )


def create_vad(config: VADConfig, sample_rate: int) -> VoiceActivityDetector:
    if config.backend == "sherpa_onnx_silero":
        return SherpaOnnxSileroVAD(config, sample_rate)
    raise VADServiceError(f"不支持的VAD backend：{config.backend}")
