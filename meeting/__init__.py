"""Independent local-first core for Meeting Recorder Desktop."""

from .config import MeetingConfig
from .recorder import MeetingRecorder, RecorderEvent
from .transcript import MeetingTranscript, TranscriptSegment

__all__ = [
    "MeetingConfig",
    "MeetingRecorder",
    "RecorderEvent",
    "MeetingTranscript",
    "TranscriptSegment",
]
