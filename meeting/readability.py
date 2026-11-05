from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transcript import TranscriptSegment


TERMINAL_PUNCTUATION = ("。", "！", "？", ".", "!", "?")
CLAUSE_PUNCTUATION = TERMINAL_PUNCTUATION + ("，", "；", "：", ",", ";", ":")
DISCOURSE_MARKERS = (
    "然后",
    "首先",
    "其次",
    "最后",
    "所以",
    "但是",
    "另外",
    "接下来",
    "同时",
    "之后",
    "此外",
)


@dataclass(slots=True)
class ReadableParagraph:
    start_time: float
    end_time: float
    speaker: str | None
    text: str
    source: str = "system"


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)


def _add_internal_punctuation(text: str, minimum_length: int) -> str:
    """Add conservative punctuation before clear discourse markers.

    This is intentionally rule based. It improves reading without claiming to
    correct ASR semantics or replace a punctuation-restoration model.
    """
    if len(text) < minimum_length:
        return text
    for marker in DISCOURSE_MARKERS:
        text = re.sub(
            rf"(?<![，。！？；：,.!?;:])(?<!^){re.escape(marker)}",
            f"，{marker}",
            text,
        )
    return text


def _finish_sentence(text: str) -> str:
    text = text.rstrip("，,；;：:")
    if text and not text.endswith(TERMINAL_PUNCTUATION):
        text += "。"
    return text


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left.endswith(CLAUSE_PUNCTUATION):
        return left + right
    return left + "，" + right


def build_readable_paragraphs(
    segments: list[TranscriptSegment],
    *,
    merge_gap_seconds: float = 1.8,
    internal_punctuation_min_chars: int = 36,
    max_paragraph_chars: int = 140,
) -> list[ReadableParagraph]:
    """Merge raw ASR/VAD segments into conservative reading paragraphs."""
    paragraphs: list[ReadableParagraph] = []
    for segment in segments:
        text = _normalize_text(segment.corrected_text or segment.text)
        if not text:
            continue
        text = _add_internal_punctuation(
            text,
            internal_punctuation_min_chars,
        )
        if paragraphs:
            previous = paragraphs[-1]
            gap = max(0.0, segment.start_time - previous.end_time)
            if (
                segment.speaker == previous.speaker
                and segment.source == previous.source
                and gap <= merge_gap_seconds
                and len(previous.text) + len(text) + 1 <= max_paragraph_chars
            ):
                previous.text = _join_text(previous.text, text)
                previous.end_time = max(previous.end_time, segment.end_time)
                continue
        paragraphs.append(ReadableParagraph(
            start_time=segment.start_time,
            end_time=segment.end_time,
            speaker=segment.speaker,
            text=text,
            source=segment.source,
        ))

    for paragraph in paragraphs:
        paragraph.text = _finish_sentence(paragraph.text)
    return paragraphs
