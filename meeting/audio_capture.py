from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from .audio_utils import AudioChunk, normalize_audio


logger = logging.getLogger(__name__)


class AudioCaptureError(RuntimeError):
    pass


@dataclass(slots=True)
class AudioDevice:
    id: str
    name: str
    is_default: bool = False
    is_loopback: bool = True


class AudioCapture(ABC):
    @abstractmethod
    def list_devices(self) -> list[AudioDevice]: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def read_chunk(self) -> AudioChunk: ...

    @abstractmethod
    def stop(self) -> None: ...

    def chunks(self) -> Iterator[AudioChunk]:
        while True:
            yield self.read_chunk()


class WasapiLoopbackCapture(AudioCapture):
    """Windows system-audio capture through SoundCard/WASAPI loopback.

    The desktop app preloads SoundCard on its long-lived main thread. Every
    worker that calls this class must also own a thread-scoped COM apartment
    for the complete enumeration or recording lifecycle. No microphone
    fallback is performed: a missing loopback device is reported explicitly
    to protect user expectations and privacy.
    """

    def __init__(
        self,
        device_id: str | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 100,
    ):
        self.device_id = device_id
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_duration_ms = int(chunk_duration_ms)
        self._microphone = None
        self._recorder_context = None
        self._recorder = None
        self._source_rate = None
        self._started_at = None
        self._sample_cursor = 0

    @staticmethod
    def _soundcard():
        try:
            import soundcard as soundcard
        except ImportError as exc:
            raise AudioCaptureError(
                "缺少可选依赖 SoundCard。安装会议模块音频依赖后再运行。"
            ) from exc
        return soundcard

    def _loopback_devices(self):
        soundcard = self._soundcard()
        return list(soundcard.all_microphones(include_loopback=True))

    def list_devices(self) -> list[AudioDevice]:
        soundcard = self._soundcard()
        default_speaker = soundcard.default_speaker()
        default_name = getattr(default_speaker, "name", "")
        devices = []
        for microphone in self._loopback_devices():
            if not getattr(microphone, "isloopback", False):
                continue
            name = str(getattr(microphone, "name", "Unknown Loopback"))
            identifier = str(getattr(microphone, "id", name))
            devices.append(AudioDevice(
                id=identifier,
                name=name,
                is_default=bool(default_name and default_name in name),
            ))
        return devices

    def _select_device(self):
        devices = [
            item for item in self._loopback_devices()
            if getattr(item, "isloopback", False)
        ]
        if not devices:
            raise AudioCaptureError(
                "没有找到 Windows WASAPI Loopback 设备，请检查默认扬声器。"
            )
        if self.device_id:
            for device in devices:
                identifier = str(getattr(device, "id", ""))
                name = str(getattr(device, "name", ""))
                if self.device_id in {identifier, name}:
                    return device
            raise AudioCaptureError(f"找不到指定的 Loopback 设备：{self.device_id}")

        soundcard = self._soundcard()
        default_name = str(getattr(soundcard.default_speaker(), "name", ""))
        for device in devices:
            if default_name and default_name in str(getattr(device, "name", "")):
                return device
        return devices[0]

    def start(self) -> None:
        if self._recorder is not None:
            return
        self._microphone = self._select_device()
        # WASAPI commonly accepts 48 kHz reliably; normalization happens after read.
        self._source_rate = 48000
        self._recorder_context = self._microphone.recorder(
            samplerate=self._source_rate,
            channels=max(1, self.channels),
        )
        self._recorder = self._recorder_context.__enter__()
        self._started_at = time.monotonic()
        self._sample_cursor = 0
        logger.info("Audio device: %s", getattr(self._microphone, "name", "unknown"))

    def read_chunk(self) -> AudioChunk:
        if self._recorder is None or self._started_at is None:
            raise AudioCaptureError("AudioCapture 尚未启动")
        source_frames = max(1, round(
            self._source_rate * self.chunk_duration_ms / 1000
        ))
        raw = self._recorder.record(numframes=source_frames)
        samples = normalize_audio(raw, self._source_rate, self.sample_rate)
        start_time = self._sample_cursor / self.sample_rate
        self._sample_cursor += samples.size
        end_time = self._sample_cursor / self.sample_rate
        return AudioChunk(samples, self.sample_rate, start_time, end_time)

    def stop(self) -> None:
        if self._recorder_context is not None:
            self._recorder_context.__exit__(None, None, None)
        self._recorder = None
        self._recorder_context = None
        self._microphone = None
        logger.info("Audio capture stopped")


class WasapiMicrophoneCapture(WasapiLoopbackCapture):
    """Physical microphone capture kept separate from loopback audio."""

    def _physical_devices(self):
        soundcard = self._soundcard()
        return [
            item
            for item in soundcard.all_microphones(include_loopback=False)
            if not getattr(item, "isloopback", False)
        ]

    def list_devices(self) -> list[AudioDevice]:
        soundcard = self._soundcard()
        default = soundcard.default_microphone()
        default_id = str(getattr(default, "id", ""))
        default_name = str(getattr(default, "name", ""))
        devices = []
        for microphone in self._physical_devices():
            name = str(getattr(microphone, "name", "Unknown Microphone"))
            identifier = str(getattr(microphone, "id", name))
            devices.append(AudioDevice(
                id=identifier,
                name=name,
                is_default=(
                    bool(default_id and identifier == default_id)
                    or bool(default_name and name == default_name)
                ),
                is_loopback=False,
            ))
        return devices

    def _select_device(self):
        devices = self._physical_devices()
        if not devices:
            raise AudioCaptureError("没有找到可用的麦克风设备。")
        if self.device_id:
            for device in devices:
                identifier = str(getattr(device, "id", ""))
                name = str(getattr(device, "name", ""))
                if self.device_id in {identifier, name}:
                    return device
            raise AudioCaptureError(f"找不到指定的麦克风：{self.device_id}")

        default = self._soundcard().default_microphone()
        default_id = str(getattr(default, "id", ""))
        for device in devices:
            if default_id and str(getattr(device, "id", "")) == default_id:
                return device
        return devices[0]
