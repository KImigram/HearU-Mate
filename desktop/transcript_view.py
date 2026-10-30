from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def transcript_font(
    point_size: float,
    weight: QFont.Weight = QFont.Weight.Normal,
) -> QFont:
    """Use scalable point sizes and stable glyph rasterization on Windows."""
    font = QFont("Microsoft YaHei UI")
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias
        | QFont.StyleStrategy.PreferQuality
    )
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


class TranscriptRow(QWidget):
    """A native Qt version of the two-column transcript row used by DocAgent."""

    geometry_changed = Signal()

    def __init__(
        self,
        speaker: str,
        timestamp: str,
        text: str = "",
        *,
        corrected: bool = False,
        partial: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._partial = partial
        self.setObjectName("transcriptRow")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QHBoxLayout()
        content.setContentsMargins(0, 15, 0, 15)
        content.setSpacing(24)

        label_column = QVBoxLayout()
        label_column.setContentsMargins(0, 0, 0, 0)
        label_column.setSpacing(3)
        self.speaker_label = QLabel(speaker.replace("_", " "))
        self.speaker_label.setObjectName("segmentSpeaker")
        self.speaker_label.setTextFormat(Qt.TextFormat.PlainText)
        self.speaker_label.setFont(
            transcript_font(9.5, QFont.Weight.DemiBold)
        )
        self.time_label = QLabel(timestamp)
        self.time_label.setObjectName("segmentTime")
        self.time_label.setTextFormat(Qt.TextFormat.PlainText)
        self.time_label.setFont(transcript_font(9.0))
        label_column.addWidget(self.speaker_label)
        label_column.addWidget(self.time_label)
        label_column.addStretch(1)

        label_host = QWidget()
        label_host.setObjectName("segmentLabelColumn")
        label_host.setFixedWidth(118)
        label_host.setLayout(label_column)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(5)
        self.text_label = QLabel()
        self.text_label.setObjectName("segmentText")
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setFont(transcript_font(11.0))
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.text_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self.corrected_note = QLabel("AI 已根据完整上下文校对")
        self.corrected_note.setObjectName("correctedNote")
        self.corrected_note.setTextFormat(Qt.TextFormat.PlainText)
        self.corrected_note.setFont(transcript_font(8.5))
        self.corrected_note.setVisible(corrected)
        text_column.addWidget(self.text_label)
        text_column.addWidget(self.corrected_note)

        content.addWidget(label_host, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(text_column, 1)
        root.addLayout(content)

        divider = QFrame()
        divider.setObjectName("segmentDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        root.addWidget(divider)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        cursor = "  ▎" if self._partial and text else ""
        self.text_label.setText(text + cursor)
        self.updateGeometry()
        self.geometry_changed.emit()

    def set_timestamp(self, timestamp: str) -> None:
        self.time_label.setText(timestamp)

    def set_speaker(self, speaker: str) -> None:
        self.speaker_label.setText(speaker.replace("_", " "))

    def finalize(self, text: str, timestamp: str | None = None) -> None:
        self._partial = False
        if timestamp is not None:
            self.set_timestamp(timestamp)
        self.set_text(text)


class TranscriptList(QScrollArea):
    """Flat, scrollable transcript surface containing native row widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptList")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._content = QWidget()
        self._content.setObjectName("transcriptContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 10, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self.setWidget(self._content)
        self._empty_label: QLabel | None = None
        self._top_widgets: list[QWidget] = []
        self._scroll_to_bottom_pending = False
        self._layout_refresh_pending = False
        self._batch_depth = 0

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self) -> None:
        if self._layout_refresh_pending or self._batch_depth:
            return
        self._layout_refresh_pending = True
        QTimer.singleShot(0, self._apply_layout_refresh)

    def refresh_layout(self) -> None:
        """Recalculate height after a top card changes visibility or text."""
        self._schedule_layout_refresh()

    def _sync_content_height(self) -> None:
        self._layout.invalidate()
        width = max(1, self.viewport().width())
        natural_height = (
            self._layout.heightForWidth(width)
            if self._layout.hasHeightForWidth()
            else self._layout.sizeHint().height()
        )
        target = max(self.viewport().height(), natural_height)
        self._content.setFixedHeight(target)
        self._layout.activate()

    def _apply_layout_refresh(self) -> None:
        self._layout_refresh_pending = False
        self._sync_content_height()
        if self._scroll_to_bottom_pending:
            # The scroll range is recalculated after the content resize. Apply
            # the final position on the next event-loop turn so Partial growth
            # cannot leave the viewport one layout pass behind.
            QTimer.singleShot(0, self._finish_scroll_to_bottom)

    def _finish_scroll_to_bottom(self) -> None:
        self._sync_content_height()
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._scroll_to_bottom_pending = False

    def begin_batch_update(self) -> None:
        """Pause layout and painting while many transcript rows are rebuilt."""
        self._batch_depth += 1
        if self._batch_depth != 1:
            return
        self.setUpdatesEnabled(False)
        self.viewport().setUpdatesEnabled(False)
        self._layout.setEnabled(False)

    def end_batch_update(self) -> None:
        if self._batch_depth == 0:
            return
        self._batch_depth -= 1
        if self._batch_depth != 0:
            return
        self._layout.setEnabled(True)
        self._sync_content_height()
        self._content.updateGeometry()
        self.viewport().setUpdatesEnabled(True)
        self.setUpdatesEnabled(True)
        self.viewport().update()

    def add_top_widget(self, widget: QWidget) -> None:
        """Keep a detail widget above transcript rows in the same scroll area."""
        if widget in self._top_widgets:
            return
        self._layout.insertWidget(len(self._top_widgets), widget)
        self._top_widgets.append(widget)
        self._schedule_layout_refresh()

    def clear_rows(self) -> None:
        first_row = len(self._top_widgets)
        while self._layout.count() > first_row + 1:
            item = self._layout.takeAt(first_row)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._empty_label = None
        self._schedule_layout_refresh()

    def set_empty_message(self, message: str) -> None:
        self.clear_rows()
        label = QLabel(message)
        label.setObjectName("transcriptEmpty")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(150)
        self._layout.insertWidget(len(self._top_widgets), label)
        self._empty_label = label
        self._schedule_layout_refresh()

    def add_row(
        self,
        speaker: str,
        timestamp: str,
        text: str = "",
        *,
        corrected: bool = False,
        partial: bool = False,
    ) -> TranscriptRow:
        if self._empty_label is not None:
            self._layout.removeWidget(self._empty_label)
            self._empty_label.deleteLater()
            self._empty_label = None
        row = TranscriptRow(
            speaker,
            timestamp,
            text,
            corrected=corrected,
            partial=partial,
            parent=self._content,
        )
        row.geometry_changed.connect(self._schedule_layout_refresh)
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._schedule_layout_refresh()
        return row

    def scroll_to_bottom(self) -> None:
        self._scroll_to_bottom_pending = True
        self._schedule_layout_refresh()

    def is_near_bottom(self, threshold: int = 36) -> bool:
        bar = self.verticalScrollBar()
        return bar.maximum() - bar.value() <= threshold

    def scroll_to_top(self) -> None:
        self._schedule_layout_refresh()
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))
