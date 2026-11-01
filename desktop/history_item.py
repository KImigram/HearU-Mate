from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QWidget,
)


class HistoryItemWidget(QWidget):
    selected = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(
        self,
        meeting_id: str,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.meeting_id = meeting_id
        self._title = title
        self.setObjectName("historyItemWidget")
        self.setFixedHeight(40)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("historyItemTitle")
        self.title_label.setToolTip(title)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        self.menu_button = QToolButton()
        self.menu_button.setObjectName("historyItemMenuButton")
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip("会议操作")
        self.menu_button.setAccessibleName("会议操作")
        self.menu_button.setFixedSize(30, 28)
        self.menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )

        menu = QMenu(self.menu_button)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除会议")
        rename_action.triggered.connect(
            lambda: self.rename_requested.emit(self.meeting_id)
        )
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.meeting_id)
        )
        self.menu_button.setMenu(menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 3, 2)
        layout.setSpacing(4)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.menu_button)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = max(20, self.title_label.width())
        self.title_label.setText(
            self.title_label.fontMetrics().elidedText(
                self._title,
                Qt.TextElideMode.ElideRight,
                width,
            )
        )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.meeting_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)
