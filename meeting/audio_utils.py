from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class AudioChunk:
    samples: np.ndarray
    sample_rate: int
    start_time: float
    end_time: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


def to_float32(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples)
    if array.dtype == np.float32:
        return array
    if np.issubdtype(array.dtype, np.integer):
        info = np.iinfo(array.dtype)
        scale = float(max(abs(info.min), info.max))
        return array.astype(np.float32) / scale
    return array.astype(np.float32)


def downmix_mono(samples: np.ndarray) -> np.ndarray:
    array = to_float32(samples)
    if array.ndim == 1:
        return array
    if array.ndim != 2:
        raise ValueError(f"不支持的音频维度：{array.shape}")
    return array.mean(axis=1, dtype=np.float32)


def resample_linear(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int,
) -> np.ndarray:
    """Dependency-light resampling for the first capture pipeline.

    A production backend may replace this with scipy/samplerate. Keeping this
    implementation here makes the audio contract testable without ASR models.
    """
    mono = downmix_mono(samples)
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("采样率必须为正整数")
    if source_rate == target_rate or mono.size == 0:
        return mono.astype(np.float32, copy=False)
    output_size = max(1, round(mono.size * target_rate / source_rate))
    source_x = np.arange(mono.size, dtype=np.float64)
    target_x = np.linspace(0, mono.size - 1, output_size, dtype=np.float64)
    return np.interp(target_x, source_x, mono).astype(np.float32)


def normalize_audio(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int = 16000,
) -> np.ndarray:
    return np.ascontiguousarray(
        resample_linear(samples, source_rate, target_rate),
        dtype=np.float32,
    )


def rms_energy(samples: np.ndarray) -> float:
    array = to_float32(samples).reshape(-1)
    if array.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(array), dtype=np.float64)))
