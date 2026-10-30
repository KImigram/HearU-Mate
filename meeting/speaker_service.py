from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import SpeakerConfig


class SpeakerServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class SpeakerSegment:
    start_time: float
    end_time: float
    speaker: str
    confidence: float | None = None


class SpeakerDiarizationService(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def feed_audio(
        self,
        samples: np.ndarray,
        sample_rate: int,
        start_time: float,
        end_time: float,
    ) -> None: ...

    @abstractmethod
    def get_segments(self) -> list[SpeakerSegment]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class SherpaOnnxSpeakerDiarizationService(SpeakerDiarizationService):
    """Final-pass speaker diarization using native sherpa-onnx models."""

    def __init__(self, config: SpeakerConfig):
        self.config = config
        self._diarizer = None
        self._chunks: list[np.ndarray] = []

    def start(self) -> None:
        segmentation = Path(self.config.segmentation_model).expanduser()
        embedding = Path(self.config.embedding_model).expanduser()
        missing = [str(path) for path in (segmentation, embedding) if not path.is_file()]
        if missing:
            raise SpeakerServiceError(
                "Speaker模型尚未配置，缺少：" + ", ".join(missing)
            )
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise SpeakerServiceError("meeting_onnx环境中缺少sherpa-onnx") from exc

        segmentation_config = sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(segmentation),
                window_shift_ratio=0.1,
            ),
            num_threads=self.config.num_threads,
            provider="cpu",
            debug=False,
        )
        embedding_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=self.config.num_threads,
            provider="cpu",
            debug=False,
        )
        clustering = sherpa_onnx.FastClusteringConfig(
            num_clusters=self.config.num_speakers,
            threshold=self.config.clustering_threshold,
        )
        diarization_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=segmentation_config,
            embedding=embedding_config,
            clustering=clustering,
            min_duration_on=self.config.min_duration_on,
            min_duration_off=self.config.min_duration_off,
        )
        self._diarizer = sherpa_onnx.OfflineSpeakerDiarization(
            diarization_config
        )
        self._chunks.clear()

    def feed_audio(self, samples, sample_rate, start_time, end_time) -> None:
        if self._diarizer is None:
            raise SpeakerServiceError("SpeakerService 尚未启动")
        if sample_rate != self._diarizer.sample_rate:
            raise SpeakerServiceError(
                f"Speaker模型要求{self._diarizer.sample_rate}Hz，收到{sample_rate}Hz"
            )
        self._chunks.append(np.asarray(samples, dtype=np.float32).copy())

    def get_segments(self) -> list[SpeakerSegment]:
        if self._diarizer is None or not self._chunks:
            return []
        samples = np.concatenate(self._chunks)
        result = self._diarizer.process(samples)
        return [
            SpeakerSegment(
                start_time=float(item.start),
                end_time=float(item.end),
                speaker=f"Speaker_{int(item.speaker) + 1:02d}",
                confidence=(
                    float(item.confidence)
                    if getattr(item, "confidence", None) is not None else None
                ),
            )
            for item in result.sort_by_start_time()
        ]

    def reset(self) -> None:
        self._chunks.clear()

    def stop(self) -> None:
        self._diarizer = None
        self._chunks.clear()


def create_speaker_service(config: SpeakerConfig) -> SpeakerDiarizationService:
    if config.backend == "sherpa_onnx_offline":
        return SherpaOnnxSpeakerDiarizationService(config)
    raise SpeakerServiceError(
        f"说话人后端 {config.backend!r} 尚未接入；需要先确定并配置本地模型。"
    )
