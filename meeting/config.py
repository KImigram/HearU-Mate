from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_paths


def _installed_model_path(relative_path: str) -> str:
    return str(get_runtime_paths().models_root / relative_path)


@dataclass(frozen=True, slots=True)
class SpeakerEmbeddingProfile:
    label: str
    relative_path: str
    clustering_threshold: float


SPEAKER_EMBEDDING_PROFILES = {
    "3dspeaker_eres2net": SpeakerEmbeddingProfile(
        label="3D-Speaker ERes2Net（原模型）",
        relative_path="speaker-diarization/3dspeaker-eres2net.onnx",
        clustering_threshold=0.85,
    ),
    "wespeaker_cnceleb_resnet34_lm": SpeakerEmbeddingProfile(
        label="WeSpeaker 中文 ResNet34-LM（新模型）",
        relative_path=(
            "speaker-diarization/"
            "wespeaker-cnceleb-resnet34-LM-sherpa.onnx"
        ),
        clustering_threshold=0.85,
    ),
}


@dataclass(slots=True)
class AudioConfig:
    source: str = "system"
    device_id: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    chunk_duration_ms: int = 100


@dataclass(slots=True)
class VADConfig:
    backend: str = "sherpa_onnx_silero"
    model: str = field(default_factory=lambda: _installed_model_path(
        "silero-vad/silero_vad.onnx"
    ))
    threshold: float = 0.5
    min_speech_duration: float = 0.25
    min_silence_duration: float = 0.65
    max_speech_duration: float = 12.0
    window_size: int = 512
    num_threads: int = 1


@dataclass(slots=True)
class ASRConfig:
    backend: str = "sherpa_onnx_paraformer"
    model_dir: str = field(default_factory=lambda: _installed_model_path(
        "paraformer-streaming-int8"
    ))
    encoder: str = "encoder.int8.onnx"
    decoder: str = "decoder.int8.onnx"
    tokens: str = "tokens.txt"
    num_threads: int = 2
    provider: str = "cpu"
    endpoint_silence: float = 1.2
    max_utterance_seconds: float = 12.0


@dataclass(slots=True)
class SpeakerConfig:
    backend: str = "sherpa_onnx_offline"
    embedding_profile: str = "3dspeaker_eres2net"
    segmentation_model: str = field(default_factory=lambda: _installed_model_path(
        "speaker-diarization/pyannote-segmentation/model.int8.onnx"
    ))
    embedding_model: str = field(default_factory=lambda: _installed_model_path(
        "speaker-diarization/3dspeaker-eres2net.onnx"
    ))
    num_threads: int = 2
    num_speakers: int = -1
    # In automatic mode, a larger distance threshold merges more embeddings
    # into the same speaker. 0.5 over-splits ordinary loopback recordings.
    clustering_threshold: float = 0.85
    min_duration_on: float = 0.3
    min_duration_off: float = 0.5

    def select_embedding_profile(
        self,
        profile_name: str,
        models_root: str | Path | None = None,
    ) -> None:
        try:
            profile = SPEAKER_EMBEDDING_PROFILES[profile_name]
        except KeyError as exc:
            supported = ", ".join(SPEAKER_EMBEDDING_PROFILES)
            raise ValueError(
                f"未知说话人模型 {profile_name!r}；可选值：{supported}"
            ) from exc
        self.embedding_profile = profile_name
        root = (
            Path(models_root).resolve()
            if models_root is not None
            else get_runtime_paths().models_root
        )
        self.embedding_model = str(
            root / profile.relative_path
        )
        self.clustering_threshold = profile.clustering_threshold


@dataclass(slots=True)
class OutputConfig:
    root_dir: str = field(default_factory=lambda: str(
        get_runtime_paths().data_dir
    ))
    save_raw_audio: bool = False


@dataclass(slots=True)
class ReadabilityConfig:
    enabled: bool = True
    merge_gap_seconds: float = 1.8
    internal_punctuation_min_chars: int = 36
    max_paragraph_chars: int = 90


@dataclass(slots=True)
class CorrectionConfig:
    enabled: bool = True
    backend: str = "openai_compatible"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 90.0
    max_segments_per_request: int = 20
    max_chars_per_request: int = 6000
    context_chars: int = 800
    minimum_similarity: float = 0.45


@dataclass(slots=True)
class MeetingConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    readability: ReadabilityConfig = field(default_factory=ReadabilityConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)

    def use_model_root(self, models_root: str | Path) -> None:
        root = Path(models_root).expanduser().resolve()
        self.vad.model = str(root / "silero-vad" / "silero_vad.onnx")
        self.asr.model_dir = str(root / "paraformer-streaming-int8")
        self.speaker.segmentation_model = str(
            root
            / "speaker-diarization"
            / "pyannote-segmentation"
            / "model.int8.onnx"
        )
        self.speaker.select_embedding_profile(
            self.speaker.embedding_profile,
            root,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "MeetingConfig":
        if path is None:
            return cls()
        config_path = Path(path).expanduser().resolve()
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            audio=AudioConfig(**payload.get("audio", {})),
            vad=VADConfig(**payload.get("vad", {})),
            asr=ASRConfig(**payload.get("asr", {})),
            speaker=SpeakerConfig(**payload.get("speaker", {})),
            output=OutputConfig(**payload.get("output", {})),
            readability=ReadabilityConfig(**payload.get("readability", {})),
            correction=CorrectionConfig(**payload.get("correction", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
