from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .env_store import has_api_key, save_project_api_key


@dataclass(slots=True)
class RuntimeSettings:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    correction_enabled: bool = True


class SettingsDialog(QDialog):
    """Edits non-secret preferences and keeps the API key in memory only."""

    def __init__(
        self,
        current: RuntimeSettings,
        project_root,
        *,
        require_api_key: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(480)
        self.project_root = project_root
        self.require_api_key = require_api_key
        self._had_api_key = has_api_key()

        self.base_url_edit = QLineEdit(current.base_url)
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com")
        self.model_edit = QLineEdit(current.model)
        self.model_edit.setPlaceholderText("deepseek-flash")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(
            "已配置；输入新值才替换"
            if self._had_api_key
            else "首次使用需要填写"
        )
        self.enabled_check = QCheckBox("启用会后 AI 文本校对")
        self.enabled_check.setChecked(current.correction_enabled)

        form = QFormLayout()
        form.setSpacing(14)
        form.addRow("API 地址", self.base_url_edit)
        form.addRow("模型名称", self.model_edit)
        form.addRow("API Key", self.api_key_edit)

        note = QLabel(
            "API Key 保存到本项目的 .env，并加载为进程环境变量。"
            "它不会写入源码或数据库，且已被 Git 忽略。"
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        layout.addWidget(self.enabled_check)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def values(self) -> RuntimeSettings:
        return RuntimeSettings(
            base_url=self.base_url_edit.text().strip()
            or "https://api.deepseek.com",
            model=self.model_edit.text().strip() or "deepseek-flash",
            correction_enabled=self.enabled_check.isChecked(),
        )

    def _save_and_accept(self) -> None:
        entered_key = self.api_key_edit.text().strip()
        if entered_key:
            try:
                save_project_api_key(self.project_root, entered_key)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "无法保存 API Key", str(exc))
                return
        if (
            self.enabled_check.isChecked()
            and not has_api_key()
        ):
            QMessageBox.warning(
                self,
                "需要 API Key",
                "启用 AI 会后校对前必须先填写 API Key。",
            )
            return
        self.accept()

    @staticmethod
    def load() -> RuntimeSettings:
        settings = QSettings("MeetingRecorderDesktop", "MeetingRecorderDesktop")
        return RuntimeSettings(
            base_url=settings.value(
                "correction/base_url",
                "https://api.deepseek.com",
                type=str,
            ),
            model=settings.value(
                "correction/model",
                "deepseek-flash",
                type=str,
            ),
            correction_enabled=settings.value(
                "correction/enabled",
                True,
                type=bool,
            ),
        )

    @staticmethod
    def save_non_secret(values: RuntimeSettings) -> None:
        settings = QSettings("MeetingRecorderDesktop", "MeetingRecorderDesktop")
        settings.setValue("correction/base_url", values.base_url)
        settings.setValue("correction/model", values.model)
        settings.setValue("correction/enabled", values.correction_enabled)

