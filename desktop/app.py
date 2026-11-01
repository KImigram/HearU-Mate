from __future__ import annotations

import sys
import multiprocessing
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from meeting.windows_com import preload_soundcard
from meeting.runtime_paths import RuntimePaths, get_runtime_paths

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from desktop.main_window import MainWindow
    from desktop.env_store import load_project_environment
else:
    from .main_window import MainWindow
    from .env_store import load_project_environment


def create_app(paths: RuntimePaths | None = None) -> QApplication:
    paths = paths or get_runtime_paths()
    # The Qt GUI thread must remain STA: QApplication's Windows backend calls
    # OleInitialize. SoundCard 0.4.6 requests MTA during its first import, so
    # importing it first would make Qt report RPC_E_CHANGED_MODE (0x80010106).
    app = QApplication.instance() or QApplication(sys.argv)
    # Import SoundCard only after Qt owns the main-thread COM apartment.
    # SoundCard accepts RPC_E_CHANGED_MODE here and leaves that apartment
    # untouched. Device and recorder workers initialize their own MTA scopes.
    preload_soundcard()
    app.setApplicationName("HearU Mate · 听会儿")
    app.setOrganizationName("MeetingRecorderDesktop")
    app_font = QFont("Microsoft YaHei")
    app_font.setPointSize(10)
    app_font.setWeight(QFont.Weight.Normal)
    app.setFont(app_font)
    style_path = paths.resource_root / "desktop" / "styles.qss"
    check_icon = paths.resource_root / "assets" / "check.svg"
    down_arrow_icon = paths.resource_root / "assets" / "down_arrow.svg"
    style = style_path.read_text(encoding="utf-8").replace(
        "__CHECK_ICON__",
        f'url("{check_icon.as_posix()}")',
    ).replace(
        "__DOWN_ARROW_ICON__",
        f'url("{down_arrow_icon.as_posix()}")',
    )
    app.setStyleSheet(style)
    return app


def main() -> int:
    # Speaker diarization runs in a spawned process so a native sherpa-onnx
    # crash cannot terminate the desktop UI. Required by frozen Windows apps.
    multiprocessing.freeze_support()
    paths = get_runtime_paths()
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.settings_dir.mkdir(parents=True, exist_ok=True)
    load_project_environment(paths.settings_dir)
    app = create_app(paths)
    window = MainWindow(
        paths.settings_dir,
        simulation_mode=False,
        data_dir=paths.data_dir,
        models_root=paths.models_root,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

