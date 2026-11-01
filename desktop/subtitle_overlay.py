from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .transcript_view import transcript_font


class SubtitleOverlay(QWidget):
    """Small always-on-top window that mirrors the current ASR sentence."""

    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HearU Mate 实时字幕")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(560, 118)
        self.resize(760, 128)
        self._drag_offset: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        self.card = QFrame()
        self.card.setObjectName("subtitleOverlayCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(22, 12, 14, 16)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("HearU Mate · 实时字幕")
        self.caption.setObjectName("subtitleOverlayCaption")
        self.caption.setFont(transcript_font(9.5))
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("subtitleOverlayCloseButton")
        self.close_button.setFont(transcript_font(15))
        self.close_button.setToolTip("关闭悬浮字幕")
        self.close_button.setFixedSize(30, 26)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.caption)
        header.addStretch(1)
        header.addWidget(self.close_button)

        self.subtitle_label = QLabel("等待语音…")
        self.subtitle_label.setObjectName("subtitleOverlayText")
        self.subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        self.subtitle_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMinimumHeight(48)

        card_layout.addLayout(header)
        card_layout.addWidget(self.subtitle_label, 1)
        outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 55))
        self.card.setGraphicsEffect(shadow)

        for widget in (self.card, self.caption, self.subtitle_label):
            widget.installEventFilter(self)

    @property
    def text(self) -> str:
        return self.subtitle_label.text()

    def reset(self) -> None:
        self.caption.setText("HearU Mate · 实时字幕")
        self.subtitle_label.setText("等待语音…")
        self._fit_text()

    def update_partial(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        self.caption.setText("HearU Mate · 识别中")
        self.subtitle_label.setText(clean)
        self._fit_text()

    def update_final(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        self.caption.setText("HearU Mate · 实时字幕")
        self.subtitle_label.setText(clean)
        self._fit_text()

    def move_to_default_position(self) -> None:
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.x() + (available.width() - self.width()) // 2
        y = available.y() + available.height() - self.height() - 72
        self.move(max(available.x(), x), max(available.y(), y))

    def _fit_text(self) -> None:
        length = len(self.subtitle_label.text())
        point_size = 19 if length <= 38 else 17 if length <= 76 else 14
        self.subtitle_label.setFont(transcript_font(point_size))

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if (
                isinstance(mouse_event, QMouseEvent)
                and mouse_event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag_offset = (
                    mouse_event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
        elif event.type() == QEvent.Type.MouseMove:
            mouse_event = event
            if (
                isinstance(mouse_event, QMouseEvent)
                and self._drag_offset is not None
                and mouse_event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(
                    mouse_event.globalPosition().toPoint()
                    - self._drag_offset
                )
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_offset = None
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)
