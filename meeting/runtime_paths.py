from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEVELOPMENT_MODELS = Path("D:/models/sherpa-onnx")
REQUIRED_MODEL_FILES = (
    "silero-vad/silero_vad.onnx",
    "paraformer-streaming-int8/encoder.int8.onnx",
    "paraformer-streaming-int8/decoder.int8.onnx",
    "paraformer-streaming-int8/tokens.txt",
    "speaker-diarization/pyannote-segmentation/model.int8.onnx",
    "speaker-diarization/3dspeaker-eres2net.onnx",
    (
        "speaker-diarization/"
        "wespeaker-cnceleb-resnet34-LM-sherpa.onnx"
    ),
)


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    frozen: bool
    app_root: Path
    resource_root: Path
    models_root: Path
    data_dir: Path
    settings_dir: Path


def _resolved_env_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def get_runtime_paths() -> RuntimePaths:
    """Resolve writable data and read-only resources for dev or install mode."""
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        app_root = Path(sys.executable).resolve().parent
        resource_root = Path(
            getattr(sys, "_MEIPASS", app_root)
        ).resolve()
        local_app_data = Path(
            os.getenv("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        ).resolve()
        settings_dir = (
            _resolved_env_path("HEARU_SETTINGS_DIR")
            or local_app_data / "HearU Mate"
        )
        data_dir = _resolved_env_path("HEARU_DATA_DIR") or settings_dir
        models_root = (
            _resolved_env_path("HEARU_MODELS_DIR")
            or app_root / "models"
        )
    else:
        app_root = PROJECT_ROOT
        resource_root = PROJECT_ROOT
        settings_dir = (
            _resolved_env_path("HEARU_SETTINGS_DIR") or PROJECT_ROOT
        )
        data_dir = (
            _resolved_env_path("HEARU_DATA_DIR")
            or PROJECT_ROOT / "data" / "meetings"
        )
        models_root = (
            _resolved_env_path("HEARU_MODELS_DIR")
            or DEFAULT_DEVELOPMENT_MODELS
        )
    return RuntimePaths(
        frozen=frozen,
        app_root=app_root,
        resource_root=resource_root,
        models_root=models_root.resolve(),
        data_dir=data_dir.resolve(),
        settings_dir=settings_dir.resolve(),
    )


def missing_runtime_files(paths: RuntimePaths) -> list[Path]:
    required = [
        paths.resource_root / "desktop" / "styles.qss",
        paths.resource_root / "assets" / "check.svg",
        paths.resource_root / "assets" / "down_arrow.svg",
    ]
    required.extend(paths.models_root / item for item in REQUIRED_MODEL_FILES)
    return [path for path in required if not path.is_file()]
