from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import BinaryIO

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
        self._audio_spool: BinaryIO | None = None
        self._sample_count = 0

    def _open_audio_spool(self) -> None:
        self._close_audio_spool()
        # TemporaryFile is deleted by Windows when its handle closes, including
        # normal interpreter shutdown. It avoids retaining an entire long
        # meeting as thousands of Python/NumPy objects in memory.
        self._audio_spool = tempfile.TemporaryFile(
            mode="w+b",
            prefix="meeting_recorder_speaker_",
            suffix=".f32",
        )
        self._sample_count = 0

    def _close_audio_spool(self) -> None:
        if self._audio_spool is not None:
            self._audio_spool.close()
        self._audio_spool = None
        self._sample_count = 0

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
        self._open_audio_spool()

    def feed_audio(self, samples, sample_rate, start_time, end_time) -> None:
        if self._diarizer is None:
            raise SpeakerServiceError("SpeakerService 尚未启动")
        if self._audio_spool is None:
            raise SpeakerServiceError("SpeakerService 临时音频文件未初始化")
        if sample_rate != self._diarizer.sample_rate:
            raise SpeakerServiceError(
                f"Speaker模型要求{self._diarizer.sample_rate}Hz，收到{sample_rate}Hz"
            )
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        self._audio_spool.write(audio.tobytes(order="C"))
        self._sample_count += int(audio.size)

    def get_segments(self) -> list[SpeakerSegment]:
        if (
            self._diarizer is None
            or self._audio_spool is None
            or self._sample_count == 0
        ):
            return []
        self._audio_spool.flush()
        samples = np.memmap(
            self._audio_spool,
            dtype=np.float32,
            mode="r",
            offset=0,
            shape=(self._sample_count,),
        )
        try:
            result = self._diarizer.process(samples)
        finally:
            mapping = getattr(samples, "_mmap", None)
            if mapping is not None:
                mapping.close()
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
        if self._audio_spool is None:
            self._open_audio_spool()
            return
        self._audio_spool.seek(0)
        self._audio_spool.truncate(0)
        self._sample_count = 0

    def stop(self) -> None:
        self._diarizer = None
        self._close_audio_spool()


def create_speaker_service(config: SpeakerConfig) -> SpeakerDiarizationService:
    if config.backend == "sherpa_onnx_offline":
        return SherpaOnnxSpeakerDiarizationService(config)
    raise SpeakerServiceError(
        f"说话人后端 {config.backend!r} 尚未接入；需要先确定并配置本地模型。"
    )
