from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "meetings" / "meeting_history.db"


class MeetingStore:
    """SQLite index for meeting history and finalized transcript segments."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._import_existing_transcripts()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    meeting_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_seconds REAL,
                    device_name TEXT,
                    speaker_count INTEGER,
                    speaker_status TEXT,
                    speaker_error TEXT,
                    correction_status TEXT,
                    correction_error TEXT,
                    json_path TEXT,
                    markdown_path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS meeting_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    speaker TEXT,
                    raw_text TEXT NOT NULL,
                    corrected_text TEXT,
                    corrections_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (meeting_id)
                        REFERENCES meetings(meeting_id)
                        ON DELETE CASCADE,
                    UNIQUE(meeting_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS meeting_speaker_names (
                    meeting_id TEXT NOT NULL,
                    speaker_label TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    PRIMARY KEY (meeting_id, speaker_label),
                    FOREIGN KEY (meeting_id)
                        REFERENCES meetings(meeting_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS meeting_summaries (
                    meeting_id TEXT PRIMARY KEY,
                    summary_json TEXT NOT NULL,
                    model TEXT,
                    generated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id)
                        REFERENCES meetings(meeting_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_meetings_start_time
                ON meetings(start_time DESC);

                CREATE INDEX IF NOT EXISTS idx_meeting_segments_meeting
                ON meeting_segments(meeting_id, sequence);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(meetings)")
            }
            if "correction_error" not in columns:
                connection.execute(
                    "ALTER TABLE meetings ADD COLUMN correction_error TEXT"
                )
            if "speaker_status" not in columns:
                connection.execute(
                    "ALTER TABLE meetings ADD COLUMN speaker_status TEXT"
                )
            if "speaker_error" not in columns:
                connection.execute(
                    "ALTER TABLE meetings ADD COLUMN speaker_error TEXT"
                )
            connection.execute(
                """
                UPDATE meetings
                SET status = 'interrupted',
                    error_message = COALESCE(
                        error_message,
                        '会议服务上次退出时仍在录制'
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('starting', 'recording', 'stopping', 'processing')
                """
            )

    @staticmethod
    def _row_to_dict(row):
        return dict(row) if row is not None else None

    def create_meeting(
        self,
        meeting_id: str,
        start_time: datetime,
        *,
        device_name: str | None = None,
    ) -> None:
        title = f"会议纪要 {start_time:%m-%d %H:%M}"
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO meetings(
                    meeting_id, title, status, start_time, device_name
                ) VALUES (?, ?, 'starting', ?, ?)
                """,
                (
                    meeting_id,
                    title,
                    start_time.isoformat(timespec="seconds"),
                    device_name,
                ),
            )

    def update_status(
        self,
        meeting_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE meetings
                SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE meeting_id = ?
                """,
                (status, error_message, meeting_id),
            )

    def save_live_segment(
        self,
        meeting_id: str,
        sequence: int,
        start_time: float,
        end_time: float,
        raw_text: str,
    ) -> None:
        """Checkpoint one finalized ASR segment during recording.

        Final persistence replaces these provisional rows after speaker
        alignment and AI correction. If the process exits early, the rows
        remain available for an interrupted-meeting recovery view.
        """
        text = str(raw_text).strip()
        if not text:
            return
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO meeting_segments(
                    meeting_id, sequence, start_time, end_time, speaker,
                    raw_text, corrected_text, corrections_json
                ) VALUES (?, ?, ?, ?, NULL, ?, NULL, '[]')
                ON CONFLICT(meeting_id, sequence) DO UPDATE SET
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    raw_text = excluded.raw_text
                """,
                (
                    meeting_id,
                    int(sequence),
                    float(start_time),
                    float(end_time),
                    text,
                ),
            )

    def save_transcript(self, transcript, output_dir: str | Path) -> None:
        output_dir = Path(output_dir).resolve()
        segments = transcript.segments
        title = f"会议纪要 {transcript.start_time:%m-%d %H:%M}"
        end_time = transcript.end_time or datetime.now()
        duration = max(
            0.0,
            (end_time - transcript.start_time).total_seconds(),
        )
        speakers = {
            segment.speaker for segment in segments if segment.speaker
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO meetings(
                    meeting_id, title, status, start_time
                ) VALUES (?, ?, 'processing', ?)
                """,
                (
                    transcript.meeting_id,
                    title,
                    transcript.start_time.isoformat(timespec="seconds"),
                ),
            )
            stored_title = connection.execute(
                "SELECT title FROM meetings WHERE meeting_id = ?",
                (transcript.meeting_id,),
            ).fetchone()["title"]
            connection.execute(
                """
                UPDATE meetings
                SET title = ?, status = 'completed', end_time = ?,
                    duration_seconds = ?, speaker_count = ?,
                    speaker_status = ?, speaker_error = ?,
                    correction_status = ?, correction_error = ?,
                    json_path = ?, markdown_path = ?,
                    error_message = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE meeting_id = ?
                """,
                (
                    stored_title,
                    end_time.isoformat(timespec="seconds"),
                    duration,
                    len(speakers),
                    transcript.metadata.get("speaker_status"),
                    transcript.metadata.get("speaker_error_message")
                    or transcript.metadata.get("speaker_error"),
                    transcript.metadata.get("correction_status"),
                    transcript.metadata.get("correction_error_message")
                    or transcript.metadata.get("correction_error"),
                    str(output_dir / "transcript.json"),
                    str(output_dir / "transcript.md"),
                    transcript.meeting_id,
                ),
            )
            connection.execute(
                "DELETE FROM meeting_segments WHERE meeting_id = ?",
                (transcript.meeting_id,),
            )
            connection.executemany(
                """
                INSERT INTO meeting_segments(
                    meeting_id, sequence, start_time, end_time, speaker,
                    raw_text, corrected_text, corrections_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        transcript.meeting_id,
                        index,
                        segment.start_time,
                        segment.end_time,
                        segment.speaker,
                        segment.text,
                        segment.corrected_text,
                        json.dumps(segment.corrections, ensure_ascii=False),
                    )
                    for index, segment in enumerate(segments)
                ],
            )

    def _import_existing_transcripts(self) -> None:
        """Index JSON transcripts created by the earlier CLI implementation."""
        from .transcript import MeetingTranscript, TranscriptSegment

        for json_path in self.db_path.parent.glob("*/transcript.json"):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                meeting_id = str(payload["meeting_id"])
                if self.get_meeting(meeting_id) is not None:
                    continue
                transcript = MeetingTranscript(
                    meeting_id=meeting_id,
                    start_time=datetime.fromisoformat(payload["start_time"]),
                    end_time=(
                        datetime.fromisoformat(payload["end_time"])
                        if payload.get("end_time") else None
                    ),
                    metadata=payload.get("metadata") or {},
                    segments=[
                        TranscriptSegment(
                            start_time=float(item["start"]),
                            end_time=float(item["end"]),
                            text=str(item.get("text") or ""),
                            speaker=item.get("speaker"),
                            is_final=bool(item.get("is_final", True)),
                            corrected_text=item.get("corrected_text"),
                            corrections=item.get("corrections") or [],
                        )
                        for item in payload.get("segments", [])
                    ],
                )
                self.save_transcript(transcript, json_path.parent)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

    def list_meetings(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT meeting_id, title, status, start_time, end_time,
                       duration_seconds, speaker_count, speaker_status,
                       speaker_error, correction_status, error_message
                FROM meetings
                ORDER BY start_time DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_meeting(self, meeting_id: str) -> dict | None:
        with self._connection() as connection:
            meeting = connection.execute(
                "SELECT * FROM meetings WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchone()
            if meeting is None:
                return None
            segments = connection.execute(
                """
                SELECT sequence, start_time, end_time, speaker,
                       raw_text, corrected_text, corrections_json
                FROM meeting_segments
                WHERE meeting_id = ?
                ORDER BY sequence
                """,
                (meeting_id,),
            ).fetchall()
            speaker_names = connection.execute(
                """
                SELECT speaker_label, display_name
                FROM meeting_speaker_names
                WHERE meeting_id = ?
                ORDER BY speaker_label
                """,
                (meeting_id,),
            ).fetchall()
            summary = connection.execute(
                """
                SELECT summary_json, model, generated_at
                FROM meeting_summaries
                WHERE meeting_id = ?
                """,
                (meeting_id,),
            ).fetchone()
        payload = dict(meeting)
        payload["speaker_names"] = {
            row["speaker_label"]: row["display_name"]
            for row in speaker_names
        }
        payload["summary"] = (
            json.loads(summary["summary_json"])
            if summary is not None else None
        )
        payload["summary_model"] = (
            summary["model"] if summary is not None else None
        )
        payload["summary_generated_at"] = (
            summary["generated_at"] if summary is not None else None
        )
        payload["segments"] = [
            {
                **dict(row),
                "corrections": json.loads(row["corrections_json"] or "[]"),
            }
            for row in segments
        ]
        for segment in payload["segments"]:
            segment.pop("corrections_json", None)
            label = segment.get("speaker")
            segment["display_speaker"] = (
                payload["speaker_names"].get(label, label)
                if label else None
            )
        return payload

    def save_summary(
        self,
        meeting_id: str,
        summary: dict,
        *,
        model: str | None = None,
        generated_at: datetime | None = None,
    ) -> None:
        if self.get_meeting(meeting_id) is None:
            raise KeyError(f"会议不存在：{meeting_id}")
        timestamp = (generated_at or datetime.now()).isoformat(
            timespec="seconds"
        )
        payload = json.dumps(summary, ensure_ascii=False)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO meeting_summaries(
                    meeting_id, summary_json, model, generated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(meeting_id) DO UPDATE SET
                    summary_json = excluded.summary_json,
                    model = excluded.model,
                    generated_at = excluded.generated_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (meeting_id, payload, model, timestamp),
            )

    def update_speaker_names(
        self,
        meeting_id: str,
        speaker_names: dict[str, str],
    ) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            raise KeyError(f"会议不存在：{meeting_id}")
        valid_labels = {
            segment["speaker"]
            for segment in meeting["segments"]
            if segment.get("speaker")
        }
        cleaned = {
            label: name.strip()
            for label, name in speaker_names.items()
            if label in valid_labels and name.strip()
        }
        if any(len(name) > 60 for name in cleaned.values()):
            raise ValueError("说话人名称不能超过 60 个字符")

        with self._connection() as connection:
            connection.execute(
                "DELETE FROM meeting_speaker_names WHERE meeting_id = ?",
                (meeting_id,),
            )
            connection.executemany(
                """
                INSERT INTO meeting_speaker_names(
                    meeting_id, speaker_label, display_name
                ) VALUES (?, ?, ?)
                """,
                [
                    (meeting_id, label, name)
                    for label, name in sorted(cleaned.items())
                ],
            )
        self._rewrite_exports_with_speaker_names(meeting_id)

    def _rewrite_exports_with_speaker_names(self, meeting_id: str) -> None:
        from .transcript import MeetingTranscript, TranscriptSegment

        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            raise KeyError(f"会议不存在：{meeting_id}")
        mapping = meeting["speaker_names"]
        json_path = (
            Path(meeting["json_path"])
            if meeting.get("json_path") else None
        )
        markdown_path = (
            Path(meeting["markdown_path"])
            if meeting.get("markdown_path") else None
        )

        metadata = {}
        json_payload = None
        if json_path and json_path.is_file():
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            metadata = dict(json_payload.get("metadata") or {})
        metadata["speaker_names"] = mapping

        transcript = MeetingTranscript(
            meeting_id=meeting_id,
            start_time=datetime.fromisoformat(meeting["start_time"]),
            end_time=(
                datetime.fromisoformat(meeting["end_time"])
                if meeting.get("end_time") else None
            ),
            metadata=metadata,
            segments=[
                TranscriptSegment(
                    start_time=float(segment["start_time"]),
                    end_time=float(segment["end_time"]),
                    text=str(segment.get("raw_text") or ""),
                    speaker=(
                        mapping.get(
                            segment.get("speaker"),
                            segment.get("speaker"),
                        )
                    ),
                    corrected_text=segment.get("corrected_text"),
                    corrections=segment.get("corrections") or [],
                )
                for segment in meeting["segments"]
            ],
        )
        if markdown_path:
            MeetingTranscript._atomic_write(
                markdown_path,
                transcript.to_markdown(
                    readable=True,
                    merge_gap_seconds=1.8,
                    internal_punctuation_min_chars=36,
                    max_paragraph_chars=90,
                ),
            )

        if json_path and json_payload is not None:
            json_payload["metadata"] = metadata
            for segment in json_payload.get("segments", []):
                label = segment.get("speaker")
                display_name = mapping.get(label)
                if display_name:
                    segment["speaker_name"] = display_name
                else:
                    segment.pop("speaker_name", None)
            MeetingTranscript._atomic_write(
                json_path,
                json.dumps(
                    json_payload,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
            )

    def rename_meeting(self, meeting_id: str, title: str) -> None:
        cleaned = str(title).strip()
        if not cleaned:
            raise ValueError("会议名称不能为空")
        if len(cleaned) > 100:
            raise ValueError("会议名称不能超过 100 个字符")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE meetings
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE meeting_id = ?
                """,
                (cleaned, meeting_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"会议不存在：{meeting_id}")

    def delete_meeting(self, meeting_id: str) -> bool:
        """Delete one meeting and its complete export directory.

        The export directory is first moved to an app-owned tombstone inside
        the meetings root. If the database transaction fails, it is restored.
        This prevents a corrupted path in SQLite from deleting arbitrary files.
        """
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return False

        root = self.db_path.parent.resolve()
        export_path = meeting.get("json_path") or meeting.get("markdown_path")
        directory = (
            Path(str(export_path)).resolve().parent
            if export_path
            else (root / meeting_id).resolve()
        )
        if directory == root or directory.parent != root:
            raise ValueError("会议文件目录不在应用数据目录内，已拒绝删除")

        staged = root / f".deleting-{uuid.uuid4().hex}"
        directory_staged = False
        if directory.exists():
            directory.replace(staged)
            directory_staged = True
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM meetings WHERE meeting_id = ?",
                    (meeting_id,),
                )
                deleted = cursor.rowcount > 0
        except Exception:
            if directory_staged and staged.exists():
                staged.replace(directory)
            raise

        if directory_staged and staged.exists():
            try:
                shutil.rmtree(staged)
            except OSError as exc:
                raise OSError(
                    "数据库记录已删除，但会议文件清理失败："
                    f"{staged}"
                ) from exc
        return deleted
