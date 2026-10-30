from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher

from .config import CorrectionConfig


class CorrectionServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class CorrectionResult:
    segment_id: int
    corrected_text: str
    reason: str = "上下文校对"


class TranscriptCorrectionService(ABC):
    @abstractmethod
    def correct(self, segments) -> list[CorrectionResult]: ...


SYSTEM_PROMPT = """你是会议语音转写校对器。输入来自中文会议ASR，可能夹杂英文技术名词。
你的任务仅是校对，不是总结或改写。

必须遵守：
1. 修复有充分上下文依据的同音字、漏字、重复词、英文技术名词和标点。
2. 保持原意、事实、数字、时间、人名、说话人和片段顺序。
3. 不添加原文没有的信息；无法确定时保留原文。
4. 每个输入片段必须返回一次，id必须完全一致。
5. 只返回JSON对象，不要Markdown或解释。

返回格式：
{"segments":[{"id":0,"corrected_text":"校对后的文本","reason":"简短理由"}]}
"""


class OpenAICompatibleCorrectionService(TranscriptCorrectionService):
    def __init__(self, config: CorrectionConfig, api_key: str | None = None):
        self.config = config
        self._api_key = api_key
        self.failed_batches = 0
        self.total_batches = 0
        self.last_error_type: str | None = None

    def _resolve_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        value = os.getenv(self.config.api_key_env, "").strip()
        if not value:
            raise CorrectionServiceError(
                "未提供运行时 API Key，且环境变量 "
                f"{self.config.api_key_env} 未设置"
            )
        return value

    def _create_client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise CorrectionServiceError("缺少openai依赖") from exc
        return OpenAI(
            api_key=self._resolve_api_key(),
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

    @staticmethod
    def _parse_payload(content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise CorrectionServiceError("校对服务未返回合法JSON") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("segments"), list
        ):
            raise CorrectionServiceError("校对服务返回结构不正确")
        return payload

    def _validate_batch(self, source, payload: dict) -> list[CorrectionResult]:
        returned = payload["segments"]
        expected_ids = [item["id"] for item in source]
        returned_ids = [item.get("id") for item in returned]
        if returned_ids != expected_ids:
            raise CorrectionServiceError("校对结果的片段ID或顺序发生变化")

        results = []
        for original, item in zip(source, returned):
            corrected = item.get("corrected_text")
            if not isinstance(corrected, str) or not corrected.strip():
                raise CorrectionServiceError("校对结果包含空文本")
            corrected = corrected.strip()
            source_text = original["text"].strip()
            similarity = SequenceMatcher(None, source_text, corrected).ratio()
            length_ratio = len(corrected) / max(1, len(source_text))
            if similarity < self.config.minimum_similarity or not (
                0.5 <= length_ratio <= 1.6
            ):
                corrected = source_text
                reason = "修改幅度过大，已回退原文"
            else:
                reason = str(item.get("reason") or "上下文校对")
            results.append(CorrectionResult(
                segment_id=original["id"],
                corrected_text=corrected,
                reason=reason,
            ))
        return results

    def _batches(self, segments):
        batch = []
        char_count = 0
        for index, segment in enumerate(segments):
            item = {
                "id": index,
                "speaker": segment.speaker or "Speaker Pending",
                "start": round(segment.start_time, 3),
                "text": segment.text,
            }
            item_chars = len(segment.text)
            if batch and (
                len(batch) >= self.config.max_segments_per_request
                or char_count + item_chars > self.config.max_chars_per_request
            ):
                yield batch
                batch = []
                char_count = 0
            batch.append(item)
            char_count += item_chars
        if batch:
            yield batch

    def correct(self, segments) -> list[CorrectionResult]:
        if not segments:
            return []
        client = self._create_client()
        self.failed_batches = 0
        self.total_batches = 0
        self.last_error_type = None
        results = []
        previous_context = ""
        for batch in self._batches(segments):
            self.total_batches += 1
            request_payload = {
                "previous_context": previous_context,
                "segments": batch,
            }
            batch_results = None
            last_error = None
            for _attempt in range(2):
                try:
                    response = client.chat.completions.create(
                        model=self.config.model,
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    request_payload,
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                    )
                    content = response.choices[0].message.content or ""
                    batch_results = self._validate_batch(
                        batch,
                        self._parse_payload(content),
                    )
                    break
                except Exception as exc:
                    last_error = exc
            if batch_results is None:
                self.failed_batches += 1
                self.last_error_type = type(last_error).__name__
                batch_results = [
                    CorrectionResult(
                        segment_id=item["id"],
                        corrected_text=item["text"].strip(),
                        reason="AI 校对失败，已保留原文",
                    )
                    for item in batch
                ]
            results.extend(batch_results)
            previous_context = "".join(
                item.corrected_text for item in batch_results[-3:]
            )[-self.config.context_chars:]
        return results


def create_correction_service(
    config: CorrectionConfig,
    *,
    api_key: str | None = None,
) -> TranscriptCorrectionService:
    if config.backend == "openai_compatible":
        return OpenAICompatibleCorrectionService(config, api_key=api_key)
    raise CorrectionServiceError(f"不支持的校对后端：{config.backend}")
