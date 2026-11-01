from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import multiprocessing
import os
from pathlib import Path
import tempfile
from typing import BinaryIO, Callable

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


def _diarize_child(
    config_payload: dict,
    audio_path: str,
    sample_count: int,
    connection,
) -> None:
    """Run native sherpa-onnx code outside the desktop process.

    A native access violation cannot be caught by Python. Keeping all model
    construction and processing in this spawned process lets the desktop
    recover, save the transcript, and report a useful warning instead.
    """
    samples = None
    try:
        import sherpa_onnx

        segmentation_config = sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=config_payload["segmentation_model"],
                window_shift_ratio=0.1,
            ),
            num_threads=config_payload["num_threads"],
            provider="cpu",
            debug=False,
        )
        embedding_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=config_payload["embedding_model"],
            num_threads=config_payload["num_threads"],
            provider="cpu",
            debug=False,
        )
        clustering = sherpa_onnx.FastClusteringConfig(
            num_clusters=config_payload["num_speakers"],
            threshold=config_payload["clustering_threshold"],
        )
        diarization_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=segmentation_config,
            embedding=embedding_config,
            clustering=clustering,
            min_duration_on=config_payload["min_duration_on"],
            min_duration_off=config_payload["min_duration_off"],
        )
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(diarization_config)
        samples = np.memmap(
            audio_path,
            dtype=np.float32,
            mode="r",
            shape=(sample_count,),
        )
        result = diarizer.process(samples)
        connection.send({
            "ok": True,
            "segments": [
                (
                    float(item.start),
                    float(item.end),
                    int(item.speaker),
                    (
                        float(item.confidence)
                        if getattr(item, "confidence", None) is not None
                        else None
                    ),
                )
                for item in result.sort_by_start_time()
            ],
        })
    except BaseException as exc:
        connection.send({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        })
    finally:
        if samples is not None:
            mapping = getattr(samples, "_mmap", None)
            if mapping is not None:
                mapping.close()
        connection.close()


def _run_diarization_subprocess(
    config_payload: dict,
    audio_path: str,
    sample_count: int,
) -> list[tuple[float, float, int, float | None]]:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_diarize_child,
        args=(config_payload, audio_path, sample_count, send),
        name="HearUMateSpeakerDiarization",
    )
    process.start()
    send.close()
    message = None
    try:
        while process.is_alive():
            if receive.poll(0.2):
                try:
                    message = receive.recv()
                except EOFError:
                    message = None
                break
        process.join()
        if message is None and receive.poll():
            try:
                message = receive.recv()
            except EOFError:
                message = None
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
            process.join()

    if process.exitcode != 0:
        code = process.exitcode
        unsigned = code & 0xFFFFFFFF if code is not None else 0
        raise SpeakerServiceError(
            "说话人区分子进程异常退出"
            f"（exit={code}, Windows=0x{unsigned:08X}）"
        )
    if not message:
        raise SpeakerServiceError("说话人区分子进程未返回结果")
    if not message.get("ok"):
        raise SpeakerServiceError(str(message.get("error") or "未知错误"))
    return list(message.get("segments") or [])


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

    def __init__(
        self,
        config: SpeakerConfig,
        *,
        process_runner: Callable | None = None,
    ):
        self.config = config
        self._audio_spool: BinaryIO | None = None
        self._audio_spool_path: Path | None = None
        self._sample_count = 0
        self._started = False
        self._process_runner = process_runner or _run_diarization_subprocess

    def _open_audio_spool(self) -> None:
        self._close_audio_spool()
        # A named file can be reopened by the isolated Windows child process.
        # It still keeps long meetings out of Python memory and is deleted by
        # stop(), including all normal error paths.
        spool = tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix="meeting_recorder_speaker_",
            suffix=".f32",
            delete=False,
        )
        self._audio_spool = spool
        self._audio_spool_path = Path(spool.name)
        self._sample_count = 0

    def _close_audio_spool(self) -> None:
        if self._audio_spool is not None:
            self._audio_spool.close()
        path = self._audio_spool_path
        self._audio_spool = None
        self._audio_spool_path = None
        self._sample_count = 0
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def start(self) -> None:
        segmentation = Path(self.config.segmentation_model).expanduser()
        embedding = Path(self.config.embedding_model).expanduser()
        missing = [str(path) for path in (segmentation, embedding) if not path.is_file()]
        if missing:
            raise SpeakerServiceError(
                "Speaker模型尚未配置，缺少：" + ", ".join(missing)
            )
        self._open_audio_spool()
        self._started = True

    def feed_audio(self, samples, sample_rate, start_time, end_time) -> None:
        if not self._started:
            raise SpeakerServiceError("SpeakerService 尚未启动")
        if self._audio_spool is None:
            raise SpeakerServiceError("SpeakerService 临时音频文件未初始化")
        if sample_rate != 16000:
            raise SpeakerServiceError(
                f"Speaker模型要求16000Hz，收到{sample_rate}Hz"
            )
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        self._audio_spool.write(audio.tobytes(order="C"))
        self._sample_count += int(audio.size)

    def get_segments(self) -> list[SpeakerSegment]:
        if (
            not self._started
            or self._audio_spool is None
            or self._audio_spool_path is None
            or self._sample_count == 0
        ):
            return []
        self._audio_spool.flush()
        os.fsync(self._audio_spool.fileno())
        payload = {
            "segmentation_model": str(
                Path(self.config.segmentation_model).expanduser()
            ),
            "embedding_model": str(
                Path(self.config.embedding_model).expanduser()
            ),
            "num_threads": self.config.num_threads,
            "num_speakers": self.config.num_speakers,
            "clustering_threshold": self.config.clustering_threshold,
            "min_duration_on": self.config.min_duration_on,
            "min_duration_off": self.config.min_duration_off,
        }
        result = self._process_runner(
            payload,
            str(self._audio_spool_path),
            self._sample_count,
        )
        return [
            SpeakerSegment(
                start_time=float(item[0]),
                end_time=float(item[1]),
                speaker=f"Speaker_{int(item[2]) + 1:02d}",
                confidence=item[3],
            )
            for item in result
        ]

    def reset(self) -> None:
        if self._audio_spool is None:
            self._open_audio_spool()
            return
        self._audio_spool.seek(0)
        self._audio_spool.truncate(0)
        self._sample_count = 0

    def stop(self) -> None:
        self._started = False
        self._close_audio_spool()


def create_speaker_service(config: SpeakerConfig) -> SpeakerDiarizationService:
    if config.backend == "sherpa_onnx_offline":
        return SherpaOnnxSpeakerDiarizationService(config)
    raise SpeakerServiceError(
        f"说话人后端 {config.backend!r} 尚未接入；需要先确定并配置本地模型。"
    )
