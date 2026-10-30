from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from meeting.windows_com import preload_soundcard

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from desktop.main_window import MainWindow
    from desktop.env_store import load_project_environment
else:
    from .main_window import MainWindow
    from .env_store import load_project_environment


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> QApplication:
    # The Qt GUI thread must remain STA: QApplication's Windows backend calls
    # OleInitialize. SoundCard 0.4.6 requests MTA during its first import, so
    # importing it first would make Qt report RPC_E_CHANGED_MODE (0x80010106).
    app = QApplication.instance() or QApplication(sys.argv)
    # Import SoundCard only after Qt owns the main-thread COM apartment.
    # SoundCard accepts RPC_E_CHANGED_MODE here and leaves that apartment
    # untouched. Device and recorder workers initialize their own MTA scopes.
    preload_soundcard()
    app.setApplicationName("Meeting Recorder Desktop")
    app.setOrganizationName("MeetingRecorderDesktop")
    app_font = QFont("Microsoft YaHei")
    app_font.setPointSize(10)
    app_font.setWeight(QFont.Weight.Normal)
    app.setFont(app_font)
    style_path = Path(__file__).with_name("styles.qss")
    check_icon = PROJECT_ROOT / "assets" / "check.svg"
    down_arrow_icon = PROJECT_ROOT / "assets" / "down_arrow.svg"
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
    load_project_environment(PROJECT_ROOT)
    app = create_app()
    window = MainWindow(PROJECT_ROOT, simulation_mode=False)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

