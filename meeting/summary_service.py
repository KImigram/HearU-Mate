from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .config import CorrectionConfig


class SummaryServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class ActionItem:
    task: str
    owner: str = "未明确"
    deadline: str = "未明确"


@dataclass(slots=True)
class MeetingSummary:
    overview: str
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def _section(title: str, items: list[str]) -> list[str]:
        values = items or ["未明确"]
        return [title, *[f"• {item}" for item in values]]

    def to_plain_text(self) -> str:
        lines = ["会议概览", self.overview or "未生成概览", ""]
        lines.extend(self._section("核心要点", self.key_points))
        lines.extend(["", *self._section("关键决定", self.decisions)])
        action_lines = [
            f"{item.task}（负责人：{item.owner}；截止时间：{item.deadline}）"
            for item in self.action_items
        ]
        lines.extend(["", *self._section("待办事项", action_lines)])
        lines.extend([
            "",
            *self._section("风险与待确认", self.open_questions),
        ])
        if self.keywords:
            lines.extend(["", "关键词", "、".join(self.keywords)])
        return "\n".join(lines).strip()

    def to_markdown(self) -> str:
        lines = ["## AI 摘要", "", "### 会议概览", "", self.overview]
        sections = [
            ("核心要点", self.key_points),
            ("关键决定", self.decisions),
        ]
        for title, items in sections:
            lines.extend(["", f"### {title}", ""])
            lines.extend(f"- {item}" for item in (items or ["未明确"]))
        lines.extend(["", "### 待办事项", ""])
        if self.action_items:
            for item in self.action_items:
                lines.append(
                    f"- {item.task}（负责人：{item.owner}；"
                    f"截止时间：{item.deadline}）"
                )
        else:
            lines.append("- 未明确")
        lines.extend(["", "### 风险与待确认", ""])
        lines.extend(
            f"- {item}" for item in (self.open_questions or ["未明确"])
        )
        if self.keywords:
            lines.extend(["", "### 关键词", "", "、".join(self.keywords)])
        return "\n".join(lines).strip() + "\n"


SYSTEM_PROMPT = """你是严谨的会议摘要助手。请只根据输入的会议转写生成摘要。

必须遵守：
1. 不得补充原文中没有出现的事实、决定、负责人或截止时间。
2. 无法确定负责人或截止时间时必须写“未明确”。
3. 区分讨论意见与已经形成的决定，不要把建议写成决定。
4. 保留重要数字、版本号、专有名词和风险。
5. 输出简体中文JSON对象，不要Markdown或额外解释。

返回格式：
{
  "overview":"2到4句会议概览",
  "key_points":["核心要点，最多6项"],
  "decisions":["已明确决定，最多5项"],
  "action_items":[
    {"task":"待办内容","owner":"负责人或未明确","deadline":"时间或未明确"}
  ],
  "open_questions":["风险、争议或待确认事项，最多5项"],
  "keywords":["关键词，最多8个"]
}
"""


class OpenAICompatibleSummaryService:
    def __init__(
        self,
        config: CorrectionConfig,
        *,
        api_key: str | None = None,
        max_chars_per_request: int = 8000,
    ) -> None:
        self.config = config
        self._api_key = api_key
        self.max_chars_per_request = max(1000, max_chars_per_request)

    def _resolve_api_key(self) -> str:
        value = (self._api_key or os.getenv(
            self.config.api_key_env,
            "",
        )).strip()
        if not value:
            raise SummaryServiceError("未配置 API Key")
        return value

    def _create_client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SummaryServiceError("缺少 openai 依赖") from exc
        return OpenAI(
            api_key=self._resolve_api_key(),
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

    @staticmethod
    def _clean_string(value: object, fallback: str = "") -> str:
        return str(value).strip() if value is not None else fallback

    @classmethod
    def _string_list(cls, value: object, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            text = cls._clean_string(item)
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    @classmethod
    def parse_payload(cls, content: str | dict) -> MeetingSummary:
        if isinstance(content, str):
            text = content.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1]).strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SummaryServiceError("摘要服务未返回合法JSON") from exc
        else:
            payload = content
        if not isinstance(payload, dict):
            raise SummaryServiceError("摘要服务返回结构不正确")
        overview = cls._clean_string(payload.get("overview"))
        if not overview:
            raise SummaryServiceError("摘要缺少会议概览")
        action_items = []
        raw_actions = payload.get("action_items")
        if isinstance(raw_actions, list):
            for item in raw_actions[:8]:
                if not isinstance(item, dict):
                    continue
                task = cls._clean_string(item.get("task"))
                if not task:
                    continue
                action_items.append(ActionItem(
                    task=task,
                    owner=cls._clean_string(
                        item.get("owner"),
                        "未明确",
                    ) or "未明确",
                    deadline=cls._clean_string(
                        item.get("deadline"),
                        "未明确",
                    ) or "未明确",
                ))
        return MeetingSummary(
            overview=overview,
            key_points=cls._string_list(payload.get("key_points"), 6),
            decisions=cls._string_list(payload.get("decisions"), 5),
            action_items=action_items,
            open_questions=cls._string_list(
                payload.get("open_questions"),
                5,
            ),
            keywords=cls._string_list(payload.get("keywords"), 8),
        )

    def _request(self, client, payload: dict) -> MeetingSummary:
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        )
        content = response.choices[0].message.content or ""
        return self.parse_payload(content)

    def _chunks(self, meeting: dict) -> list[list[dict]]:
        chunks: list[list[dict]] = []
        current: list[dict] = []
        char_count = 0
        for segment in meeting.get("segments", []):
            text = (
                self._clean_string(segment.get("corrected_text"))
                or self._clean_string(segment.get("raw_text"))
            )
            if not text:
                continue
            item = {
                "time": round(float(segment.get("start_time") or 0), 1),
                "speaker": (
                    segment.get("display_speaker")
                    or segment.get("speaker")
                    or "Speaker Pending"
                ),
                "text": text,
            }
            if current and char_count + len(text) > self.max_chars_per_request:
                chunks.append(current)
                current = []
                char_count = 0
            current.append(item)
            char_count += len(text)
        if current:
            chunks.append(current)
        return chunks

    def summarize(self, meeting: dict) -> MeetingSummary:
        chunks = self._chunks(meeting)
        if not chunks:
            raise SummaryServiceError("这场会议没有可供摘要的文本")
        client = self._create_client()
        partials = [
            self._request(client, {
                "mode": "summarize_transcript_chunk",
                "meeting_title": meeting.get("title") or "会议纪要",
                "transcript": chunk,
            })
            for chunk in chunks
        ]
        if len(partials) == 1:
            return partials[0]
        return self._request(client, {
            "mode": "consolidate_partial_summaries",
            "meeting_title": meeting.get("title") or "会议纪要",
            "partial_summaries": [item.to_dict() for item in partials],
        })


def create_summary_service(
    config: CorrectionConfig,
    *,
    api_key: str | None = None,
) -> OpenAICompatibleSummaryService:
    if config.backend != "openai_compatible":
        raise SummaryServiceError(f"不支持的摘要后端：{config.backend}")
    return OpenAICompatibleSummaryService(config, api_key=api_key)
