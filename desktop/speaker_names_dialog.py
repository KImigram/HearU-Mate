from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class SpeakerNamesDialog(QDialog):
    def __init__(
        self,
        labels: list[str],
        current_names: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("命名说话人")
        self.setMinimumWidth(430)
        self._edits: dict[str, QLineEdit] = {}

        note = QLabel(
            "为识别出的说话人填写姓名或称呼。留空会继续显示原始 "
            "Speaker 标签。保存后 JSON 和 Markdown 会同步更新。"
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")

        form = QFormLayout()
        form.setSpacing(14)
        for label in labels:
            edit = QLineEdit(current_names.get(label, ""))
            edit.setPlaceholderText("例如：张三、产品经理、客户")
            edit.setMaxLength(60)
            self._edits[label] = edit
            form.addRow(label.replace("_", " "), edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def names(self) -> dict[str, str]:
        return {
            label: edit.text().strip()
            for label, edit in self._edits.items()
        }
