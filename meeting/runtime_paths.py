from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


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
    app_root: Path
    resource_root: Path
    models_root: Path
    data_dir: Path
    settings_dir: Path


def get_runtime_paths() -> RuntimePaths:
    """Resolve the fixed installed layout used by the packaging branch."""
    app_root = Path(sys.executable).resolve().parent
    # In a PyInstaller onedir build, module __file__ paths resolve below the
    # _internal resource directory. This also keeps source-based tests simple.
    resource_root = Path(__file__).resolve().parent.parent
    local_app_data = Path(
        os.getenv("LOCALAPPDATA")
        or (Path.home() / "AppData" / "Local")
    ).resolve()
    settings_dir = local_app_data / "HearU Mate"
    return RuntimePaths(
        app_root=app_root,
        resource_root=resource_root,
        models_root=app_root / "models",
        data_dir=settings_dir,
        settings_dir=settings_dir,
    )


def missing_runtime_files(paths: RuntimePaths) -> list[Path]:
    required = [
        paths.resource_root / "desktop" / "styles.qss",
        paths.resource_root / "assets" / "check.svg",
        paths.resource_root / "assets" / "down_arrow.svg",
    ]
    required.extend(paths.models_root / item for item in REQUIRED_MODEL_FILES)
    return [path for path in required if not path.is_file()]
