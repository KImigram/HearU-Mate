from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import ASRConfig


class ASRServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class ASRResult:
    text: str
    start_time: float
    end_time: float
    is_final: bool


class ASRService(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def feed_audio(
        self,
        samples: np.ndarray,
        start_time: float,
        end_time: float,
    ) -> list[ASRResult]: ...

    @abstractmethod
    def finalize_utterance(self, end_time: float) -> ASRResult | None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class SherpaOnnxParaformerASR(ASRService):
    """Streaming Paraformer adapter; model files are intentionally not bundled."""

    def __init__(self, config: ASRConfig, sample_rate: int = 16000):
        self.config = config
        self.sample_rate = sample_rate
        self._recognizer = None
        self._stream = None
        self._utterance_start = 0.0
        self._last_partial = ""
        self._has_audio = False

    def _model_paths(self):
        root = Path(self.config.model_dir).expanduser()
        return (
            root / self.config.encoder,
            root / self.config.decoder,
            root / self.config.tokens,
        )

    def start(self) -> None:
        encoder, decoder, tokens = self._model_paths()
        missing = [str(path) for path in (encoder, decoder, tokens) if not path.is_file()]
        if missing:
            raise ASRServiceError(
                "Paraformer Streaming 模型尚未配置，缺少：" + ", ".join(missing)
            )
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ASRServiceError("缺少 sherpa-onnx runtime，当前未自动安装。") from exc
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            num_threads=self.config.num_threads,
            sample_rate=self.sample_rate,
            feature_dim=80,
            provider=self.config.provider,
            enable_endpoint_detection=True,
            rule2_min_trailing_silence=self.config.endpoint_silence,
            rule3_min_utterance_length=self.config.max_utterance_seconds,
        )
        self._stream = self._recognizer.create_stream()

    def feed_audio(self, samples, start_time, end_time) -> list[ASRResult]:
        if self._recognizer is None or self._stream is None:
            raise ASRServiceError("ASRService 尚未启动")
        if not self._has_audio:
            self._utterance_start = start_time
            self._has_audio = True
        self._stream.accept_waveform(self.sample_rate, samples)
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
        text = self._recognizer.get_result(self._stream).strip()
        results = []
        if text and text != self._last_partial:
            self._last_partial = text
            results.append(ASRResult(text, self._utterance_start, end_time, False))
        if self._recognizer.is_endpoint(self._stream):
            final = self.finalize_utterance(end_time)
            if final:
                results.append(final)
        return results

    def finalize_utterance(self, end_time: float) -> ASRResult | None:
        if self._recognizer is None or self._stream is None:
            return None
        tail = np.zeros(round(self.sample_rate * 0.5), dtype=np.float32)
        self._stream.accept_waveform(self.sample_rate, tail)
        self._stream.input_finished()
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
        text = self._recognizer.get_result(self._stream).strip() or self._last_partial
        result = (
            ASRResult(text, self._utterance_start, end_time, True)
            if text else None
        )
        self._stream = self._recognizer.create_stream()
        self._last_partial = ""
        self._has_audio = False
        return result

    def reset(self) -> None:
        if self._recognizer is not None:
            self._stream = self._recognizer.create_stream()
        self._last_partial = ""
        self._has_audio = False

    def stop(self) -> None:
        self._stream = None
        self._recognizer = None
        self._last_partial = ""
        self._has_audio = False


def create_asr_service(config: ASRConfig, sample_rate: int) -> ASRService:
    if config.backend == "sherpa_onnx_paraformer":
        return SherpaOnnxParaformerASR(config, sample_rate)
    raise ASRServiceError(f"尚未实现的 ASR backend：{config.backend}")
