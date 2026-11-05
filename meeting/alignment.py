from __future__ import annotations

from collections import defaultdict

from .speaker_service import SpeakerSegment
from .transcript import TranscriptSegment


def overlap_duration(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def align_speaker(
    transcript: TranscriptSegment,
    speaker_segments: list[SpeakerSegment],
) -> str | None:
    """Choose one speaker by accumulated overlap with an ASR segment.

    Diarization windows may overlap. Treating every near-tie combination as a
    new label (for example ``Speaker_01+Speaker_02``) makes the naming UI show
    artificial speakers. A transcript utterance needs one stable display
    label, so ties are resolved deterministically by the label.
    """
    overlaps: dict[str, float] = defaultdict(float)
    for segment in speaker_segments:
        duration = overlap_duration(
            transcript.start_time,
            transcript.end_time,
            segment.start_time,
            segment.end_time,
        )
        if duration > 0:
            overlaps[segment.speaker] += duration
    if not overlaps:
        return None
    return max(
        sorted(overlaps),
        key=lambda speaker: overlaps[speaker],
    )


def align_transcript(
    transcript_segments: list[TranscriptSegment],
    speaker_segments: list[SpeakerSegment],
) -> list[TranscriptSegment]:
    for segment in transcript_segments:
        if segment.source == "microphone":
            continue
        speaker = align_speaker(segment, speaker_segments)
        if speaker:
            segment.speaker = speaker
    return transcript_segments
