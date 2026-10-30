from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .readability import build_readable_paragraphs


def format_timestamp(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass(slots=True)
class TranscriptSegment:
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None
    is_final: bool = True
    corrected_text: str | None = None
    corrections: list[dict] = field(default_factory=list)

    def to_dict(self):
        payload = {
            "start": round(self.start_time, 3),
            "end": round(self.end_time, 3),
            "speaker": self.speaker,
            "text": self.text,
            "is_final": self.is_final,
        }
        if self.corrected_text is not None:
            payload["corrected_text"] = self.corrected_text
            payload["corrections"] = self.corrections
        return payload


@dataclass(slots=True)
class MeetingTranscript:
    meeting_id: str
    start_time: datetime
    end_time: datetime | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        metadata: dict | None = None,
        meeting_id: str | None = None,
    ) -> "MeetingTranscript":
        now = datetime.now()
        return cls(
            meeting_id=meeting_id or now.strftime("%Y%m%d_%H%M%S"),
            start_time=now,
            metadata=metadata or {},
        )

    def add_segment(self, segment: TranscriptSegment) -> None:
        if not segment.is_final:
            return
        text = segment.text.strip()
        if not text:
            return
        segment.text = text
        self.segments.append(segment)

    def update_segment(self, index: int, **changes) -> None:
        segment = self.segments[index]
        for key, value in changes.items():
            if not hasattr(segment, key):
                raise AttributeError(f"TranscriptSegment 没有字段：{key}")
            setattr(segment, key, value)

    def finish(self) -> None:
        self.end_time = datetime.now()

    def to_dict(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "start_time": self.start_time.isoformat(timespec="seconds"),
            "end_time": (
                self.end_time.isoformat(timespec="seconds")
                if self.end_time else None
            ),
            "metadata": self.metadata,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    def to_markdown(
        self,
        *,
        readable: bool = True,
        merge_gap_seconds: float = 1.8,
        internal_punctuation_min_chars: int = 36,
        max_paragraph_chars: int = 140,
    ) -> str:
        lines = [
            "# 会议纪要",
            "",
            f"**开始时间：** {self.start_time:%Y-%m-%d %H:%M:%S}",
        ]
        if self.end_time:
            lines.append(
                f"**结束时间：** {self.end_time:%Y-%m-%d %H:%M:%S}"
            )
        lines.extend(["", "---", "", "## 会议正文", ""])
        rendered_segments = (
            build_readable_paragraphs(
                self.segments,
                merge_gap_seconds=merge_gap_seconds,
                internal_punctuation_min_chars=internal_punctuation_min_chars,
                max_paragraph_chars=max_paragraph_chars,
            )
            if readable else self.segments
        )
        for segment in rendered_segments:
            speaker = (segment.speaker or "Speaker Pending").replace("_", " ")
            lines.extend([
                f"### {format_timestamp(segment.start_time)} · {speaker}",
                "",
                "",
                segment.text,
                "",
                "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def save(
        self,
        root_dir: str | Path,
        *,
        readable: bool = True,
        merge_gap_seconds: float = 1.8,
        internal_punctuation_min_chars: int = 36,
        max_paragraph_chars: int = 140,
    ) -> Path:
        meeting_dir = Path(root_dir).expanduser().resolve() / self.meeting_id
        self._atomic_write(
            meeting_dir / "transcript.json",
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        self._atomic_write(
            meeting_dir / "transcript.md",
            self.to_markdown(
                readable=readable,
                merge_gap_seconds=merge_gap_seconds,
                internal_punctuation_min_chars=internal_punctuation_min_chars,
                max_paragraph_chars=max_paragraph_chars,
            ),
        )
        return meeting_dir
