from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, QThread, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from meeting.config import SPEAKER_EMBEDDING_PROFILES
from meeting.store import MeetingStore
from meeting.summary_service import MeetingSummary

from .correction_worker import HistoricalCorrectionWorker
from .env_store import has_api_key, load_project_environment
from .history_item import HistoryItemWidget
from .recorder_worker import (
    DeviceDiscoveryWorker,
    RecorderOptions,
    RecorderWorker,
)
from .settings_dialog import RuntimeSettings, SettingsDialog
from .speaker_names_dialog import SpeakerNamesDialog
from .subtitle_overlay import SubtitleOverlay
from .summary_worker import SummaryWorker
from .transcript_view import TranscriptList, TranscriptRow


class MainWindow(QMainWindow):
    def __init__(
        self,
        project_root: str | Path,
        *,
        simulation_mode: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        load_project_environment(self.project_root)
        self.simulation_mode = simulation_mode
        self.models_enabled = not simulation_mode
        self.store = MeetingStore(
            self.project_root / "data" / "meetings" / "meeting_history.db"
        )
        self.runtime_settings = SettingsDialog.load()
        self._thread: QThread | None = None
        self._worker: RecorderWorker | None = None
        self._device_thread: QThread | None = None
        self._device_worker: DeviceDiscoveryWorker | None = None
        self._summary_thread: QThread | None = None
        self._summary_worker: SummaryWorker | None = None
        self._summary_meeting_id: str | None = None
        self._correction_thread: QThread | None = None
        self._correction_worker: HistoricalCorrectionWorker | None = None
        self._correction_meeting_id: str | None = None
        self._partial_row: TranscriptRow | None = None
        self._microphone_partial_row: TranscriptRow | None = None
        self._microphone_requested = False
        self._microphone_enabled = False
        self._subtitle_overlay: SubtitleOverlay | None = None
        self._elapsed_seconds = 0
        self._close_after_finish = False
        self._current_meeting_id: str | None = None

        self.setWindowTitle("HearU Mate · 听会儿")
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)
        self._build_ui()
        self._connect_signals()
        self.refresh_history()

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._tick_elapsed)
        QTimer.singleShot(0, self._ensure_first_run_api_key)
        QTimer.singleShot(0, self.load_audio_devices)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(285)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 18, 16, 16)
        side_layout.setSpacing(12)

        brand_block = QWidget()
        brand_block.setObjectName("brandBlock")
        brand_layout = QVBoxLayout(brand_block)
        brand_layout.setContentsMargins(4, 4, 4, 10)
        brand_layout.setSpacing(1)
        brand = QLabel("HearU Mate")
        brand.setObjectName("brandLabel")
        brand_chinese = QLabel("听会儿")
        brand_chinese.setObjectName("brandChineseLabel")
        brand_layout.addWidget(brand)
        brand_layout.addWidget(brand_chinese)
        self.new_meeting_button = QPushButton("＋  新建会议")
        self.new_meeting_button.setObjectName("primaryButton")
        self.current_meeting_button = QPushButton("返回当前纪要")
        self.current_meeting_button.setObjectName("currentMeetingButton")
        self.current_meeting_button.setVisible(False)
        history_label = QLabel("历史会议")
        history_label.setObjectName("sectionLabel")
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderHidden(True)
        self.history_tree.setIndentation(14)
        self.history_tree.setObjectName("historyTree")
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setMinimumHeight(40)
        github_support = QLabel(
            '<a href="https://github.com/KImigram/HearU-Mate" '
            'style="color:#4b78a8; text-decoration:underline;">'
            'Like HearU Mate? Click to star on GitHub.</a>'
        )
        github_support.setObjectName("githubSupportLink")
        github_support.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_support.setOpenExternalLinks(True)
        github_support.setToolTip("Open GitHub and star HearU Mate")

        side_layout.addWidget(brand_block)
        side_layout.addWidget(self.new_meeting_button)
        side_layout.addWidget(self.current_meeting_button)
        side_layout.addSpacing(8)
        side_layout.addWidget(history_label)
        side_layout.addWidget(self.history_tree, 1)
        side_layout.addWidget(github_support)
        side_layout.addWidget(self.settings_button)

        self.pages = QStackedWidget()
        self.home_page = self._build_home_page()
        self.recording_page = self._build_recording_page()
        self.detail_page = self._build_detail_page()
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.recording_page)
        self.pages.addWidget(self.detail_page)

        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(54, 30, 54, 30)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("contentCard")
        card.setMaximumWidth(720)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 30, 40, 30)
        card_layout.setSpacing(13)

        title = QLabel("实时会议纪要")
        title.setObjectName("heroTitle")
        subtitle = QLabel("捕获 Windows 系统音频，实时生成可读会议记录。")
        subtitle.setObjectName("mutedText")

        device_label = QLabel("音频输出设备")
        device_label.setObjectName("fieldLabel")
        self.device_combo = QComboBox()
        self.device_combo.addItem("正在检测输出设备…", None)
        self.device_combo.setEnabled(False)

        microphone_label = QLabel("本人麦克风（可选）")
        microphone_label.setObjectName("fieldLabel")
        self.microphone_combo = QComboBox()
        self.microphone_combo.addItem("正在检测麦克风…", None)
        self.microphone_combo.setEnabled(False)
        self.microphone_start_check = QCheckBox(
            "会议开始时启用本人麦克风（默认关闭，建议佩戴耳机）"
        )
        self.microphone_start_check.setChecked(False)
        self.microphone_start_check.setEnabled(False)
        self.microphone_start_check.setToolTip(
            "建议佩戴耳机，避免扬声器声音被麦克风重复识别"
        )

        speaker_label = QLabel("预计说话人数")
        speaker_label.setObjectName("fieldLabel")
        self.speaker_combo = QComboBox()
        for label, value in [
            ("自动", -1),
            ("1人", 1),
            ("2人", 2),
            ("3人", 3),
            ("4人", 4),
        ]:
            self.speaker_combo.addItem(label, value)

        speaker_model_label = QLabel("说话人模型")
        speaker_model_label.setObjectName("fieldLabel")
        self.speaker_model_combo = QComboBox()
        for profile_name, profile in SPEAKER_EMBEDDING_PROFILES.items():
            self.speaker_model_combo.addItem(profile.label, profile_name)

        self.correction_check = QCheckBox("启用 AI 会后校对")
        self.correction_check.setChecked(
            self.runtime_settings.correction_enabled
        )

        self.mode_hint = QLabel(
            "首次开始会在后台加载本地模型，可能需要数秒；"
            "建议正式使用前提前开启。"
        )
        self.mode_hint.setObjectName("devHint")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setMinimumHeight(52)
        self.start_button = QPushButton("开始纪要")
        self.start_button.setObjectName("startButton")
        self.start_button.setMinimumHeight(48)
        self.start_button.setEnabled(False)

        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(8)
        card_layout.addWidget(device_label)
        card_layout.addWidget(self.device_combo)
        card_layout.addWidget(microphone_label)
        card_layout.addWidget(self.microphone_combo)
        card_layout.addWidget(self.microphone_start_check)
        card_layout.addWidget(speaker_label)
        card_layout.addWidget(self.speaker_combo)
        card_layout.addWidget(speaker_model_label)
        card_layout.addWidget(self.speaker_model_combo)
        card_layout.addWidget(self.correction_check)
        card_layout.addWidget(self.mode_hint)
        card_layout.addWidget(self.start_button)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(card)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(1)
        return page

    def _build_recording_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 38, 48, 32)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 22)
        left = QVBoxLayout()
        left.setSpacing(7)
        self.recording_title = QLabel("实时会议纪要")
        self.recording_title.setObjectName("pageTitle")
        left.addWidget(self.recording_title)

        submeta = QHBoxLayout()
        submeta.setSpacing(7)
        self.current_device_label = QLabel("系统默认输出设备")
        self.current_device_label.setObjectName("recordingSubmeta")
        separator = QLabel("·")
        separator.setObjectName("recordingSubmeta")
        microphone_separator = QLabel("·")
        microphone_separator.setObjectName("recordingSubmeta")
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setObjectName("recordingSubmeta")
        self.microphone_state_label = QLabel("本人麦克风已关闭")
        self.microphone_state_label.setObjectName("recordingSubmeta")
        submeta.addWidget(self.current_device_label)
        submeta.addWidget(microphone_separator)
        submeta.addWidget(self.elapsed_label)
        submeta.addWidget(separator)
        submeta.addWidget(self.microphone_state_label)
        submeta.addStretch(1)
        left.addLayout(submeta)

        self.recording_status = QLabel("●  准备中")
        self.recording_status.setObjectName("recordingStatus")
        self.recording_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addLayout(left)
        top.addStretch(1)
        top.addWidget(
            self.recording_status,
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        divider = QFrame()
        divider.setObjectName("meetingHeaderDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)

        self.transcript_list = TranscriptList()
        self.transcript_list.set_empty_message(
            "模型加载完成后，识别内容会实时显示在这里。"
        )
        self.stop_button = QPushButton("结束纪要")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setMinimumHeight(44)
        self.stop_button.setMaximumWidth(180)
        self.subtitle_toggle_button = QPushButton("开启悬浮字幕")
        self.subtitle_toggle_button.setObjectName("subtitleToggleButton")
        self.subtitle_toggle_button.setMinimumHeight(44)
        self.subtitle_toggle_button.setFixedWidth(150)
        self.microphone_toggle_button = QPushButton("开启本人麦克风")
        self.microphone_toggle_button.setObjectName(
            "microphoneToggleButton"
        )
        self.microphone_toggle_button.setMinimumHeight(44)
        self.microphone_toggle_button.setFixedWidth(160)
        self.microphone_toggle_button.setEnabled(False)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.microphone_toggle_button)
        bottom.addSpacing(10)
        bottom.addWidget(self.subtitle_toggle_button)
        bottom.addSpacing(10)
        bottom.addWidget(self.stop_button)

        layout.addLayout(top)
        layout.addWidget(divider)
        layout.addWidget(self.transcript_list, 1)
        layout.addSpacing(14)
        layout.addLayout(bottom)
        return page

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 32, 48, 24)
        layout.setSpacing(0)

        title_column = QVBoxLayout()
        title_column.setSpacing(7)
        self.detail_title = QLabel("会议纪要")
        self.detail_title.setObjectName("pageTitle")
        self.detail_meta = QLabel()
        self.detail_meta.setObjectName("recordingSubmeta")
        title_column.addWidget(self.detail_title)
        title_column.addWidget(self.detail_meta)
        self.speaker_names_button = QPushButton("命名说话人")
        self.speaker_names_button.setObjectName("speakerNamesButton")
        self.speaker_names_button.setMinimumHeight(38)
        self.speaker_names_button.setFixedWidth(124)
        self.speaker_names_button.setVisible(False)
        self.export_markdown_button = QPushButton("导出 Markdown")
        self.export_markdown_button.setObjectName("exportMarkdownButton")
        self.export_markdown_button.setMinimumHeight(38)
        self.export_markdown_button.setFixedWidth(162)
        self.export_markdown_button.setVisible(False)
        self.summary_button = QPushButton("生成 AI 摘要")
        self.summary_button.setObjectName("summaryButton")
        self.summary_button.setMinimumHeight(38)
        self.summary_button.setFixedWidth(148)
        self.summary_button.setVisible(False)
        self.retry_correction_button = QPushButton("重新 AI 校对")
        self.retry_correction_button.setObjectName("retryCorrectionButton")
        self.retry_correction_button.setMinimumHeight(38)
        self.retry_correction_button.setFixedWidth(148)
        self.retry_correction_button.setVisible(False)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addLayout(title_column, 1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(14)
        action_row.addStretch(1)
        action_row.addWidget(
            self.retry_correction_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        action_row.addWidget(
            self.summary_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        action_row.addWidget(
            self.export_markdown_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        action_row.addWidget(
            self.speaker_names_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        divider = QFrame()
        divider.setObjectName("meetingHeaderDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        action_divider = QFrame()
        action_divider.setObjectName("meetingHeaderDivider")
        action_divider.setFrameShape(QFrame.Shape.HLine)
        action_divider.setFixedHeight(1)

        self.summary_card = QFrame()
        self.summary_card.setObjectName("summaryCard")
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(22, 18, 22, 18)
        summary_layout.setSpacing(8)
        summary_header = QHBoxLayout()
        summary_title = QLabel("AI 会议摘要")
        summary_title.setObjectName("summaryTitle")
        self.summary_meta = QLabel()
        self.summary_meta.setObjectName("summaryMeta")
        self.summary_meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_header.addWidget(summary_title)
        summary_header.addStretch(1)
        summary_header.addWidget(self.summary_meta)
        self.summary_text = QLabel()
        self.summary_text.setObjectName("summaryText")
        self.summary_text.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.summary_text.setWordWrap(True)
        summary_layout.addLayout(summary_header)
        summary_layout.addWidget(self.summary_text)
        self.summary_card.setVisible(False)

        self.detail_transcript = TranscriptList()
        self.detail_transcript.add_top_widget(self.summary_card)

        layout.addLayout(header_row)
        layout.addSpacing(20)
        layout.addWidget(divider)
        layout.addWidget(self.detail_transcript, 1)
        layout.addWidget(action_divider)
        layout.addSpacing(12)
        layout.addLayout(action_row)
        return page

    def _connect_signals(self) -> None:
        self.new_meeting_button.clicked.connect(self.show_new_meeting)
        self.current_meeting_button.clicked.connect(
            self.show_current_meeting
        )
        self.settings_button.clicked.connect(self.open_settings)
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.subtitle_toggle_button.clicked.connect(
            self.toggle_subtitle_overlay
        )
        self.microphone_toggle_button.clicked.connect(
            self.toggle_microphone
        )
        self.history_tree.itemClicked.connect(self._history_clicked)
        self.speaker_names_button.clicked.connect(
            self.edit_speaker_names
        )
        self.export_markdown_button.clicked.connect(
            self.export_current_markdown
        )
        self.summary_button.clicked.connect(self.generate_current_summary)
        self.retry_correction_button.clicked.connect(
            self.retry_current_correction
        )

    def show_new_meeting(self) -> None:
        if self._thread is not None:
            self.show_current_meeting()
            return
        self.pages.setCurrentWidget(self.home_page)

    def show_current_meeting(self) -> None:
        if self._thread is not None:
            self.pages.setCurrentWidget(self.recording_page)

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.runtime_settings,
            self.project_root,
            parent=self,
        )
        if dialog.exec():
            self.runtime_settings = dialog.values()
            SettingsDialog.save_non_secret(self.runtime_settings)
            self.correction_check.setChecked(
                self.runtime_settings.correction_enabled
            )

    def _ensure_first_run_api_key(self) -> None:
        if has_api_key() or not self.runtime_settings.correction_enabled:
            return
        dialog = SettingsDialog(
            self.runtime_settings,
            self.project_root,
            require_api_key=True,
            parent=self,
        )
        dialog.setWindowTitle("首次使用：配置 AI 校对")
        if dialog.exec():
            self.runtime_settings = dialog.values()
            SettingsDialog.save_non_secret(self.runtime_settings)
            self.correction_check.setChecked(
                self.runtime_settings.correction_enabled
            )
            return
        self.runtime_settings.correction_enabled = False
        self.correction_check.setChecked(False)
        SettingsDialog.save_non_secret(self.runtime_settings)
        QMessageBox.information(
            self,
            "AI 校对已关闭",
            "未配置 API Key，AI 会后校对已关闭。可随时在设置中重新启用。",
        )

    def start_recording(self) -> None:
        if self._thread is not None:
            return
        if self.device_combo.currentData() is None:
            QMessageBox.warning(
                self,
                "未选择音频设备",
                "请等待设备检测完成，并选择一个 Windows 输出设备。",
            )
            return
        if self.correction_check.isChecked() and not has_api_key():
            QMessageBox.warning(
                self,
                "需要 API Key",
                "请先在设置中配置 API Key，或关闭 AI 会后校对。",
            )
            return
        self.transcript_list.clear_rows()
        self.transcript_list.set_empty_message(
            "模型加载完成后，识别内容会实时显示在这里。"
        )
        self._partial_row = None
        self._microphone_partial_row = None
        self._microphone_requested = bool(
            self.microphone_start_check.isChecked()
            and self.microphone_combo.currentData() is not None
        )
        self._microphone_enabled = False
        self._elapsed_seconds = 0
        self._update_elapsed()
        self.current_device_label.setText(self.device_combo.currentText())
        self.microphone_state_label.setText(
            "本人麦克风正在开启…"
            if self._microphone_requested
            else "本人麦克风已关闭"
        )
        self.microphone_toggle_button.setText(
            "正在开启麦克风…"
            if self._microphone_requested
            else "开启本人麦克风"
        )
        self.microphone_toggle_button.setEnabled(
            self.microphone_combo.currentData() is not None
            and not self._microphone_requested
        )
        self.recording_status.setText("● 正在启动")
        self.stop_button.setEnabled(True)
        self.current_meeting_button.setVisible(True)
        self.pages.setCurrentWidget(self.recording_page)

        options = RecorderOptions(
            device_id=self.device_combo.currentData(),
            device_name=self.device_combo.currentText(),
            expected_speakers=int(self.speaker_combo.currentData()),
            speaker_embedding_profile=str(
                self.speaker_model_combo.currentData()
            ),
            correction_enabled=self.correction_check.isChecked(),
            base_url=self.runtime_settings.base_url,
            model=self.runtime_settings.model,
            simulation=self.simulation_mode,
            models_enabled=self.models_enabled,
            microphone_device_id=self.microphone_combo.currentData(),
            microphone_device_name=self.microphone_combo.currentText(),
            microphone_enabled=self._microphone_requested,
        )
        thread = QThread(self)
        worker = RecorderWorker(options, self.project_root)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.partial.connect(self._on_partial)
        worker.final.connect(self._on_final)
        worker.status.connect(self._on_status)
        worker.completed.connect(self._on_completed)
        worker.error.connect(self._on_error)
        worker.microphone_partial.connect(self._on_microphone_partial)
        worker.microphone_final.connect(self._on_microphone_final)
        worker.microphone_status.connect(self._on_microphone_status)
        worker.microphone_error.connect(self._on_microphone_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.elapsed_timer.start()
        thread.start()

    def load_audio_devices(self) -> None:
        if self._device_thread is not None or self._thread is not None:
            return
        self.device_combo.clear()
        self.device_combo.addItem("正在检测输出设备…", None)
        self.device_combo.setEnabled(False)
        self.start_button.setEnabled(False)

        thread = QThread(self)
        worker = DeviceDiscoveryWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.devices_ready.connect(self._on_devices_ready)
        # Keep compatibility with lightweight discovery workers used by tests
        # and downstream integrations that only expose system-output signals.
        microphones_ready = getattr(worker, "microphones_ready", None)
        microphone_error = getattr(worker, "microphone_error", None)
        if microphones_ready is not None:
            microphones_ready.connect(self._on_microphones_ready)
        if microphone_error is not None:
            microphone_error.connect(self._on_microphone_device_error)
        worker.error.connect(self._on_device_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._device_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._device_thread = thread
        self._device_worker = worker
        thread.start()

    def _on_devices_ready(self, devices: list[dict]) -> None:
        self.device_combo.clear()
        default_index = 0
        for index, device in enumerate(devices):
            suffix = "（默认）" if device["is_default"] else ""
            self.device_combo.addItem(
                device["name"] + suffix,
                device["id"],
            )
            if device["is_default"]:
                default_index = index
        if devices:
            self.device_combo.setCurrentIndex(default_index)
            self.device_combo.setEnabled(True)
            self.start_button.setEnabled(True)
        else:
            self.device_combo.addItem("未检测到 Loopback 输出设备", None)

    def _on_device_error(self, message: str) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("输出设备检测失败", None)
        self.mode_hint.setText(
            "无法检测 Windows 输出设备：" + message
        )

    def _on_microphones_ready(self, devices: list[dict]) -> None:
        self.microphone_combo.clear()
        default_index = 0
        for index, device in enumerate(devices):
            suffix = "（默认）" if device["is_default"] else ""
            self.microphone_combo.addItem(
                device["name"] + suffix,
                device["id"],
            )
            if device["is_default"]:
                default_index = index
        if devices:
            self.microphone_combo.setCurrentIndex(default_index)
            self.microphone_combo.setEnabled(True)
            self.microphone_start_check.setEnabled(True)
        else:
            self.microphone_combo.addItem("未检测到麦克风", None)
            self.microphone_start_check.setChecked(False)
            self.microphone_start_check.setEnabled(False)

    def _on_microphone_device_error(self, message: str) -> None:
        self.microphone_combo.clear()
        self.microphone_combo.addItem("麦克风检测失败", None)
        self.microphone_combo.setEnabled(False)
        self.microphone_start_check.setChecked(False)
        self.microphone_start_check.setEnabled(False)
        self.microphone_combo.setToolTip(message)

    def _device_thread_finished(self) -> None:
        self._device_thread = None
        self._device_worker = None

    def stop_recording(self) -> None:
        if self._worker is None:
            return
        self.stop_button.setEnabled(False)
        self._worker.request_stop()

    def toggle_subtitle_overlay(self) -> None:
        if (
            self._subtitle_overlay is not None
            and self._subtitle_overlay.isVisible()
        ):
            self._subtitle_overlay.close()
            return
        overlay = SubtitleOverlay()
        overlay.closed.connect(self._on_subtitle_overlay_closed)
        self._subtitle_overlay = overlay
        overlay.show()
        overlay.move_to_default_position()
        overlay.raise_()
        self.subtitle_toggle_button.setText("关闭悬浮字幕")

    def _on_subtitle_overlay_closed(self) -> None:
        overlay = self.sender()
        if overlay is self._subtitle_overlay:
            self._subtitle_overlay.deleteLater()
            self._subtitle_overlay = None
        self.subtitle_toggle_button.setText("开启悬浮字幕")

    def toggle_microphone(self) -> None:
        if self._worker is None:
            return
        requested = not self._microphone_enabled
        self._microphone_requested = requested
        self.microphone_toggle_button.setEnabled(False)
        self.microphone_toggle_button.setText(
            "正在开启麦克风…" if requested else "正在关闭麦克风…"
        )
        self.microphone_state_label.setText(
            "本人麦克风正在开启…" if requested else "本人麦克风正在关闭…"
        )
        self._worker.set_microphone_enabled(requested)

    def _close_subtitle_overlay(self) -> None:
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.close()

    def _on_partial(self, text: str) -> None:
        if self._partial_row is None:
            self._partial_row = self.transcript_list.add_row(
                "识别中",
                self._format_offset(self._elapsed_seconds),
                partial=True,
            )
        self._partial_row.set_text(text)
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.update_partial(text)
        self.transcript_list.scroll_to_bottom()

    def _on_final(self, text: str, start: float, end: float) -> None:
        timestamp = self._format_offset(start)
        if self._partial_row is None:
            self._partial_row = self.transcript_list.add_row(
                "识别中",
                timestamp,
                partial=True,
            )
        self._partial_row.finalize(text, timestamp)
        self._partial_row = None
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.update_final(text)
        self.transcript_list.scroll_to_bottom()

    def _on_microphone_partial(self, text: str) -> None:
        if self._microphone_partial_row is None:
            self._microphone_partial_row = self.transcript_list.add_row(
                "本人",
                self._format_offset(self._elapsed_seconds),
                partial=True,
            )
        self._microphone_partial_row.set_text(text)
        self.transcript_list.scroll_to_bottom()

    def _on_microphone_final(
        self,
        text: str,
        start: float,
        end: float,
    ) -> None:
        timestamp = self._format_offset(start)
        if self._microphone_partial_row is None:
            self._microphone_partial_row = self.transcript_list.add_row(
                "本人",
                timestamp,
                partial=True,
            )
        self._microphone_partial_row.finalize(text, timestamp)
        self._microphone_partial_row = None
        self.transcript_list.scroll_to_bottom()

    def _on_microphone_status(self, enabled: bool, message: str) -> None:
        self._microphone_enabled = bool(enabled)
        self._microphone_requested = bool(enabled)
        self.microphone_state_label.setText(message)
        self.microphone_toggle_button.setText(
            "关闭本人麦克风" if enabled else "开启本人麦克风"
        )
        self.microphone_toggle_button.setEnabled(
            self._thread is not None
            and self.microphone_combo.currentData() is not None
        )

    def _on_microphone_error(self, message: str) -> None:
        self._microphone_enabled = False
        self._microphone_requested = False
        self.microphone_state_label.setText("本人麦克风不可用")
        self.microphone_toggle_button.setText("重试开启麦克风")
        self.microphone_toggle_button.setEnabled(
            self._thread is not None
            and self.microphone_combo.currentData() is not None
        )
        QMessageBox.warning(
            self,
            "麦克风通道已关闭",
            "麦克风发生错误，但系统音频纪要仍在继续。\n\n" + message,
        )

    def _on_status(self, status: str) -> None:
        active = status.startswith("录制中")
        prefix = "●  " if active else ""
        self.recording_status.setText(prefix + status)

    def _on_completed(self, meeting_id: str) -> None:
        self.elapsed_timer.stop()
        self.stop_button.setEnabled(False)
        self.microphone_toggle_button.setEnabled(False)
        self._close_subtitle_overlay()
        self.refresh_history()
        QTimer.singleShot(250, lambda: self.show_meeting(meeting_id))

    def _on_error(self, message: str) -> None:
        self.elapsed_timer.stop()
        self.stop_button.setEnabled(False)
        self.microphone_toggle_button.setEnabled(False)
        self._close_subtitle_overlay()
        self.recording_status.setText("发生错误")
        QMessageBox.critical(
            self,
            "会议纪要未完成",
            "录制流程发生错误，已尝试释放音频和模型资源。\n\n" + message,
        )
        self.refresh_history()

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._microphone_enabled = False
        self._microphone_requested = False
        self.microphone_toggle_button.setEnabled(False)
        self.current_meeting_button.setVisible(False)
        self.elapsed_timer.stop()
        if self._close_after_finish:
            self._close_after_finish = False
            self.close()

    def refresh_history(self) -> None:
        self.history_tree.clear()
        grouped: dict[str, list[dict]] = defaultdict(list)
        for meeting in self.store.list_meetings():
            try:
                started = datetime.fromisoformat(meeting["start_time"])
                key = started.strftime("%Y年%m月%d日")
            except (TypeError, ValueError):
                key = "日期未知"
            grouped[key].append(meeting)

        for date_label, meetings in grouped.items():
            group = QTreeWidgetItem([date_label])
            group.setFlags(
                group.flags() & ~Qt.ItemFlag.ItemIsSelectable
            )
            self.history_tree.addTopLevelItem(group)
            for meeting in meetings:
                child = QTreeWidgetItem([""])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    meeting["meeting_id"],
                )
                group.addChild(child)
                row = HistoryItemWidget(
                    str(meeting["meeting_id"]),
                    str(meeting.get("title") or "未命名会议"),
                )
                row.selected.connect(
                    lambda selected_id, tree_item=child: (
                        self._open_history_item(selected_id, tree_item)
                    )
                )
                row.rename_requested.connect(self.rename_history_meeting)
                row.delete_requested.connect(self.delete_history_meeting)
                child.setSizeHint(0, QSize(0, 42))
                self.history_tree.setItemWidget(child, 0, row)
                if meeting["meeting_id"] == self._current_meeting_id:
                    self.history_tree.setCurrentItem(child)
            group.setExpanded(True)

    def _open_history_item(
        self,
        meeting_id: str,
        item: QTreeWidgetItem,
    ) -> None:
        self.history_tree.setCurrentItem(item)
        self.show_meeting(meeting_id)

    def _history_clicked(self, item: QTreeWidgetItem) -> None:
        meeting_id = item.data(0, Qt.ItemDataRole.UserRole)
        if meeting_id:
            self.show_meeting(str(meeting_id))

    def _meeting_has_background_job(self, meeting_id: str) -> bool:
        return bool(
            (
                self._summary_thread is not None
                and self._summary_meeting_id == meeting_id
            )
            or (
                self._correction_thread is not None
                and self._correction_meeting_id == meeting_id
            )
        )

    def rename_history_meeting(self, meeting_id: str) -> None:
        meeting = self.store.get_meeting(meeting_id)
        if meeting is None:
            return
        if self._meeting_has_background_job(meeting_id):
            QMessageBox.information(
                self,
                "会议正在处理中",
                "请等待 AI 处理完成后再重命名。",
            )
            return
        title, accepted = QInputDialog.getText(
            self,
            "重命名会议",
            "会议名称",
            text=str(meeting.get("title") or ""),
        )
        if not accepted:
            return
        try:
            self.store.rename_meeting(meeting_id, title)
        except (KeyError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "无法重命名会议", str(exc))
            return
        self.refresh_history()
        if self._current_meeting_id == meeting_id:
            self.show_meeting(meeting_id)

    def delete_history_meeting(self, meeting_id: str) -> None:
        meeting = self.store.get_meeting(meeting_id)
        if meeting is None:
            return
        if self._meeting_has_background_job(meeting_id):
            QMessageBox.information(
                self,
                "会议正在处理中",
                "请等待 AI 处理完成后再删除。",
            )
            return
        title = str(meeting.get("title") or "未命名会议")
        answer = QMessageBox.question(
            self,
            "确认删除会议？",
            f"确定要永久删除“{title}”吗？\n\n"
            "数据库记录、识别片段、AI 摘要、说话人命名、JSON 和 "
            "Markdown 文件都会被删除。此操作无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.store.delete_meeting(meeting_id)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "无法删除会议", str(exc))
            return
        if not deleted:
            return
        if self._current_meeting_id == meeting_id:
            self._current_meeting_id = None
            self.pages.setCurrentWidget(self.home_page)
        self.refresh_history()

    def show_meeting(self, meeting_id: str) -> None:
        meeting = self.store.get_meeting(meeting_id)
        if not meeting:
            return
        self._current_meeting_id = meeting_id
        speaker_labels = sorted({
            segment["speaker"]
            for segment in meeting.get("segments", [])
            if segment.get("speaker")
            and segment.get("source") != "microphone"
        })
        self.speaker_names_button.setVisible(bool(speaker_labels))
        self.export_markdown_button.setVisible(True)
        self.summary_button.setVisible(True)
        self.summary_button.setEnabled(
            self._summary_thread is None
            and self._correction_thread is None
        )
        self.summary_button.setText(
            "摘要生成中…"
            if self._summary_thread is not None
            else (
                "重新生成摘要"
                if meeting.get("summary")
                else "生成 AI 摘要"
            )
        )
        self.detail_title.setText(meeting.get("title") or "会议纪要")
        meta = [self._format_meeting_datetime(meeting.get("start_time"))]
        duration = meeting.get("duration_seconds")
        if duration is not None:
            meta.append(self._format_offset(float(duration)))
        correction_status = meeting.get("correction_status")
        retryable_correction = (
            (
                correction_status in {"fallback", "partial"}
                or meeting.get("status") == "interrupted"
            )
            and bool(meeting.get("segments"))
        )
        self.retry_correction_button.setVisible(retryable_correction)
        self.retry_correction_button.setEnabled(
            self._correction_thread is None
            and self._summary_thread is None
        )
        self.retry_correction_button.setText(
            "正在重新校对…"
            if self._correction_meeting_id == meeting_id
            else (
                "恢复并 AI 校对"
                if meeting.get("status") == "interrupted"
                else "重新 AI 校对"
            )
        )
        correction_error = str(
            meeting.get("correction_error") or ""
        ).strip()
        self.retry_correction_button.setToolTip(
            ("上次失败原因：" + correction_error)
            if correction_error
            else "重新使用当前设置中的 API 与模型校对原始转写"
        )
        if correction_status == "success":
            meta.append("AI 已校对")
        elif correction_status == "partial":
            meta.append("AI 部分校对，其余保留原文")
        elif correction_status == "fallback":
            meta.append("AI 校对失败，已保留原文")
        elif meeting.get("status") == "interrupted":
            meta.append("会后处理曾中断，可恢复校对")
        speaker_status = meeting.get("speaker_status")
        if speaker_status in {"fallback", "recovered_single_speaker"}:
            meta.append("说话人区分失败，已按单人保存")
        if meeting.get("summary"):
            meta.append("AI 已摘要")
        self.detail_meta.setText("  ·  ".join(item for item in meta if item))

        self.detail_transcript.begin_batch_update()
        try:
            self._show_summary(meeting)
            self.detail_transcript.clear_rows()
            segments = meeting.get("segments", [])
            corrected_starts = {
                round(float(segment.get("start_time") or 0))
                for segment in segments
                if str(segment.get("corrected_text") or "").strip()
                and str(segment.get("corrected_text") or "").strip()
                != str(segment.get("raw_text") or "").strip()
            }
            markdown_rows = self._parse_markdown_rows(
                self._read_meeting_markdown(meeting)
            )
            if not markdown_rows:
                markdown_rows = [
                    (
                        self._format_offset(
                            float(segment.get("start_time") or 0)
                        ),
                        segment.get("display_speaker")
                        or segment.get("speaker")
                        or "Speaker Pending",
                        str(segment.get("corrected_text") or "").strip()
                        or str(segment.get("raw_text") or "").strip(),
                    )
                    for segment in segments
                ]
            if not markdown_rows:
                self.detail_transcript.set_empty_message(
                    "这场会议没有可展示的转写内容。"
                )
            for index, (timestamp, speaker, text) in enumerate(markdown_rows):
                next_timestamp = (
                    markdown_rows[index + 1][0]
                    if index + 1 < len(markdown_rows)
                    else None
                )
                self.detail_transcript.add_row(
                    speaker,
                    timestamp,
                    text,
                    corrected=self._row_contains_correction(
                        timestamp,
                        next_timestamp,
                        corrected_starts,
                    ),
                )
        finally:
            self.detail_transcript.end_batch_update()
        self.detail_transcript.scroll_to_top()
        self.pages.setCurrentWidget(self.detail_page)

    def _show_summary(self, meeting: dict) -> None:
        payload = meeting.get("summary")
        if not payload:
            self.summary_card.setVisible(False)
            self.summary_text.clear()
            self.summary_meta.clear()
            self.detail_transcript.refresh_layout()
            return
        try:
            summary = self._summary_from_payload(payload)
        except Exception:
            self.summary_card.setVisible(False)
            self.detail_transcript.refresh_layout()
            return
        self.summary_text.setText(summary.to_plain_text())
        generated = self._format_meeting_datetime(
            meeting.get("summary_generated_at")
        )
        model = str(meeting.get("summary_model") or "").strip()
        self.summary_meta.setText(
            " · ".join(item for item in (model, generated) if item)
        )
        self.summary_card.setVisible(True)
        self.detail_transcript.refresh_layout()

    @staticmethod
    def _summary_from_payload(payload: dict) -> MeetingSummary:
        from meeting.summary_service import OpenAICompatibleSummaryService

        return OpenAICompatibleSummaryService.parse_payload(payload)

    def generate_current_summary(self) -> None:
        if (
            self._summary_thread is not None
            or self._correction_thread is not None
            or not self._current_meeting_id
        ):
            return
        if not has_api_key():
            QMessageBox.warning(
                self,
                "需要 API Key",
                "请先在设置中配置 API Key，再生成 AI 摘要。",
            )
            return
        meeting = self.store.get_meeting(self._current_meeting_id)
        if meeting is None:
            return
        if not meeting.get("segments"):
            QMessageBox.information(
                self,
                "没有可摘要内容",
                "这场会议没有可供摘要的识别文本。",
            )
            return

        thread = QThread(self)
        worker = SummaryWorker(
            meeting,
            self.store.db_path,
            base_url=self.runtime_settings.base_url,
            model=self.runtime_settings.model,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_summary_completed)
        worker.error.connect(self._on_summary_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._summary_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._summary_thread = thread
        self._summary_worker = worker
        self._summary_meeting_id = self._current_meeting_id
        self.summary_button.setEnabled(False)
        self.summary_button.setText("摘要生成中…")
        if not meeting.get("summary"):
            self.summary_text.setText("正在根据完整会议内容生成摘要…")
            self.summary_meta.clear()
            self.summary_card.setVisible(True)
            self.detail_transcript.refresh_layout()
        thread.start()

    def _on_summary_completed(self, meeting_id: str, payload: object) -> None:
        if self._current_meeting_id == meeting_id:
            self.show_meeting(meeting_id)

    def _on_summary_error(self, message: str) -> None:
        if self._current_meeting_id == self._summary_meeting_id:
            meeting = self.store.get_meeting(self._current_meeting_id)
            if meeting is not None:
                self._show_summary(meeting)
            QMessageBox.critical(
                self,
                "AI 摘要生成失败",
                "原始会议记录未受影响。\n\n" + message,
            )

    def _summary_thread_finished(self) -> None:
        self._summary_thread = None
        self._summary_worker = None
        self._summary_meeting_id = None
        if self._current_meeting_id:
            meeting = self.store.get_meeting(self._current_meeting_id)
            self.summary_button.setEnabled(True)
            self.summary_button.setText(
                "重新生成摘要"
                if meeting and meeting.get("summary")
                else "生成 AI 摘要"
            )

    def retry_current_correction(self) -> None:
        if (
            self._correction_thread is not None
            or self._summary_thread is not None
            or not self._current_meeting_id
        ):
            return
        if not has_api_key():
            QMessageBox.warning(
                self,
                "需要 API Key",
                "请先在设置中配置 API Key，再重新进行 AI 校对。",
            )
            return
        meeting = self.store.get_meeting(self._current_meeting_id)
        if meeting is None or not meeting.get("segments"):
            QMessageBox.information(
                self,
                "没有可校对内容",
                "这场会议没有可供重新校对的识别文本。",
            )
            return

        thread = QThread(self)
        worker = HistoricalCorrectionWorker(
            meeting,
            self.store.db_path,
            base_url=self.runtime_settings.base_url,
            model=self.runtime_settings.model,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_correction_completed)
        worker.error.connect(self._on_correction_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._correction_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._correction_thread = thread
        self._correction_worker = worker
        self._correction_meeting_id = self._current_meeting_id
        self.retry_correction_button.setEnabled(False)
        self.retry_correction_button.setText("正在重新校对…")
        self.summary_button.setEnabled(False)
        thread.start()

    def _on_correction_completed(
        self,
        meeting_id: str,
        status: str,
        reason: str,
    ) -> None:
        if self._current_meeting_id == meeting_id:
            self.show_meeting(meeting_id)
        if status == "success":
            QMessageBox.information(
                self,
                "AI 校对完成",
                "会议正文已经重新校对并保存。",
            )
        elif status == "partial":
            QMessageBox.warning(
                self,
                "AI 校对部分完成",
                "部分批次校对失败，失败部分保留原文。"
                + (("\n\n" + reason) if reason else ""),
            )
        else:
            QMessageBox.warning(
                self,
                "AI 校对仍未成功",
                "本次仍未获得有效校对结果，已继续保留原文。"
                + (("\n\n" + reason) if reason else ""),
            )

    def _on_correction_error(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "重新校对失败",
            "原始会议记录未受影响。\n\n" + message,
        )

    def _correction_thread_finished(self) -> None:
        meeting_id = self._correction_meeting_id
        self._correction_thread = None
        self._correction_worker = None
        self._correction_meeting_id = None
        if meeting_id and self._current_meeting_id == meeting_id:
            self.show_meeting(meeting_id)

    def edit_speaker_names(self) -> None:
        if not self._current_meeting_id:
            return
        meeting = self.store.get_meeting(self._current_meeting_id)
        if meeting is None:
            return
        labels = sorted({
            segment["speaker"]
            for segment in meeting.get("segments", [])
            if segment.get("speaker")
            and segment.get("source") != "microphone"
        })
        if not labels:
            QMessageBox.information(
                self,
                "暂无说话人",
                "当前会议没有可命名的说话人标签。",
            )
            return
        dialog = SpeakerNamesDialog(
            labels,
            meeting.get("speaker_names") or {},
            self,
        )
        if not dialog.exec():
            return
        try:
            self.store.update_speaker_names(
                self._current_meeting_id,
                dialog.names(),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            QMessageBox.critical(
                self,
                "无法更新说话人名称",
                str(exc),
            )
            return
        self.show_meeting(self._current_meeting_id)

    def export_current_markdown(self) -> None:
        if not self._current_meeting_id:
            return
        meeting = self.store.get_meeting(self._current_meeting_id)
        if meeting is None:
            return
        title = str(meeting.get("title") or "会议纪要").strip()
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title).rstrip(". ")
        suggested_path = str(Path.home() / f"{safe_title or '会议纪要'}.md")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Markdown",
            suggested_path,
            "Markdown 文件 (*.md)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".md":
            destination = destination.with_suffix(".md")
        try:
            destination.write_text(
                self._build_export_markdown(meeting),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "导出失败",
                f"无法保存 Markdown 文件：\n{exc}",
            )
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"Markdown 已保存到：\n{destination}",
        )

    def _build_export_markdown(self, meeting: dict) -> str:
        markdown = self._read_meeting_markdown(meeting)
        payload = meeting.get("summary")
        if not payload:
            return markdown
        summary_markdown = self._summary_from_payload(payload).to_markdown()
        for marker in ("## 会议正文", "## Transcript"):
            position = markdown.find(marker)
            if position >= 0:
                return (
                    markdown[:position].rstrip()
                    + "\n\n"
                    + summary_markdown
                    + "\n"
                    + markdown[position:].lstrip()
                )
        return markdown.rstrip() + "\n\n" + summary_markdown

    @staticmethod
    def _split_meeting_markdown(markdown: str) -> tuple[str, str]:
        for marker in ("## 会议正文", "## Transcript"):
            position = markdown.find(marker)
            if position >= 0:
                header = markdown[:position].rstrip()
                if header.endswith("---"):
                    header = header[:-3].rstrip()
                body = markdown[position:]
                if marker == "## Transcript":
                    body = body.replace(
                        "## Transcript",
                        "## 会议正文",
                        1,
                    )
                return header + "\n", body.lstrip()
        return "# 会议纪要\n", markdown

    def _read_meeting_markdown(self, meeting: dict) -> str:
        markdown_path = meeting.get("markdown_path")
        if markdown_path:
            path = Path(str(markdown_path))
            try:
                if path.is_file():
                    return path.read_text(encoding="utf-8")
            except OSError:
                pass

        started = str(meeting.get("start_time") or "").replace("T", " ")
        ended = str(meeting.get("end_time") or "").replace("T", " ")
        lines = ["# 会议纪要", "", f"**开始时间：** {started}"]
        if ended:
            lines.append(f"**结束时间：** {ended}")
        lines.extend(["", "---", "", "## 会议正文", ""])
        for segment in meeting.get("segments", []):
            start = self._format_offset(
                float(segment.get("start_time") or 0)
            )
            speaker = (
                segment.get("display_speaker")
                or segment.get("speaker")
                or "Speaker Pending"
            ).replace("_", " ")
            text = (
                str(segment.get("corrected_text") or "").strip()
                or str(segment.get("raw_text") or "").strip()
            )
            source = (
                "麦克风"
                if segment.get("source") == "microphone"
                else "系统音频"
            )
            lines.extend([
                f"### {start} · {speaker} · {source}",
                "",
                "",
                text,
                "",
                "",
            ])
        if not meeting.get("segments"):
            lines.append("暂无识别内容。")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _parse_markdown_rows(markdown: str) -> list[tuple[str, str, str]]:
        """Turn the saved Markdown headings into the native two-column view."""
        rows: list[tuple[str, str, str]] = []
        timestamp = ""
        speaker = ""
        body: list[str] = []

        def append_current() -> None:
            text = "\n".join(body).strip()
            if timestamp and text:
                rows.append((timestamp, speaker or "Speaker Pending", text))

        body = markdown
        for marker in ("## 会议正文", "## Transcript"):
            position = markdown.find(marker)
            if position >= 0:
                body = markdown[position + len(marker):]
                break
        for line in body.splitlines():
            if line.startswith("### "):
                append_current()
                heading = line[4:].strip()
                parts = [part.strip() for part in heading.split("·")]
                timestamp = parts[0]
                speaker = parts[1] if len(parts) > 1 else "Speaker Pending"
                body = []
            elif timestamp:
                body.append(line)
        append_current()
        return rows

    @staticmethod
    def _timestamp_seconds(timestamp: str) -> int:
        try:
            parts = [int(part) for part in timestamp.split(":")]
        except ValueError:
            return -1
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return -1

    @classmethod
    def _row_contains_correction(
        cls,
        timestamp: str,
        next_timestamp: str | None,
        corrected_starts: set[int],
    ) -> bool:
        """Include corrections from segments merged into one Markdown row."""
        start = cls._timestamp_seconds(timestamp)
        if start < 0:
            return False
        end = (
            cls._timestamp_seconds(next_timestamp)
            if next_timestamp is not None
            else None
        )
        if end is None:
            return any(value >= start for value in corrected_starts)
        if end > start:
            return any(start <= value < end for value in corrected_starts)
        return start in corrected_starts

    def _tick_elapsed(self) -> None:
        self._elapsed_seconds += 1
        self._update_elapsed()

    def _update_elapsed(self) -> None:
        hours, remainder = divmod(self._elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    @staticmethod
    def _format_meeting_datetime(value: object) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(str(value)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            return str(value).replace("T", " ")

    @staticmethod
    def _format_offset(seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, second = divmod(total, 60)
        hours, minute = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minute:02d}:{second:02d}"
        return f"{minute:02d}:{second:02d}"

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._correction_thread is not None:
            QMessageBox.information(
                self,
                "AI 校对正在进行",
                "请等待重新校对完成后再关闭窗口。",
            )
            event.ignore()
            return
        if self._summary_thread is not None:
            QMessageBox.information(
                self,
                "AI 摘要正在生成",
                "请等待摘要生成完成后再关闭窗口。",
            )
            event.ignore()
            return
        if self._thread is None:
            self._close_subtitle_overlay()
            if self._device_thread is not None:
                self._device_thread.quit()
                self._device_thread.wait(1000)
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "结束并保存会议？",
            "会议仍在录制或处理中。是否结束纪要、保存记录后退出？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._close_after_finish = True
            self.stop_recording()
        event.ignore()

