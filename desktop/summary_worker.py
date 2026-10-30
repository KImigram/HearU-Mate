from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from meeting.config import CorrectionConfig
from meeting.store import MeetingStore
from meeting.summary_service import create_summary_service


class SummaryWorker(QObject):
    completed = Signal(str, object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        meeting: dict,
        db_path: str | Path,
        *,
        base_url: str,
        model: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.meeting = meeting
        self.db_path = Path(db_path)
        self.base_url = base_url
        self.model = model

    @Slot()
    def run(self) -> None:
        try:
            config = CorrectionConfig(
                enabled=True,
                base_url=self.base_url,
                model=self.model,
            )
            summary = create_summary_service(config).summarize(self.meeting)
            payload = summary.to_dict()
            MeetingStore(self.db_path).save_summary(
                self.meeting["meeting_id"],
                payload,
                model=self.model,
            )
            self.completed.emit(self.meeting["meeting_id"], payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
