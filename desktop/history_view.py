from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTextBrowser, QWidget

from meeting.summary_service import MeetingSummary


@dataclass(slots=True)
class HistoryRow:
    speaker: str
    timestamp: str
    text: str
    corrected: bool = False


class HistoryTranscriptView(QTextBrowser):
    """Single-document renderer for long historical meeting transcripts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyTranscriptView")
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        font = QFont("Microsoft YaHei UI")
        font.setPointSizeF(11.0)
        font.setWeight(QFont.Weight.Normal)
        font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias
            | QFont.StyleStrategy.PreferQuality
        )
        self.document().setDefaultFont(font)

    @staticmethod
    def _text(value: object) -> str:
        return escape(str(value or "")).replace("\n", "<br>")

    @classmethod
    def _bullet_list(cls, items: list[str]) -> str:
        values = items or ["未明确"]
        return "<ul>" + "".join(
            f"<li>{cls._text(item)}</li>" for item in values
        ) + "</ul>"

    @classmethod
    def _summary_html(
        cls,
        summary: MeetingSummary,
        meta: str,
    ) -> str:
        actions = [
            f"{item.task}（负责人：{item.owner}；截止时间：{item.deadline}）"
            for item in summary.action_items
        ]
        keywords = "、".join(summary.keywords) if summary.keywords else "未明确"
        return f"""
        <table class="summary" width="100%" cellspacing="0" cellpadding="0">
          <tr><td>
            <table width="100%" cellspacing="0" cellpadding="0">
              <tr>
                <td class="summary-title">AI 会议摘要</td>
                <td class="summary-meta" align="right">{cls._text(meta)}</td>
              </tr>
            </table>
            <div class="section-title">会议概览</div>
            <div>{cls._text(summary.overview)}</div>
            <div class="section-title">核心要点</div>
            {cls._bullet_list(summary.key_points)}
            <div class="section-title">关键决定</div>
            {cls._bullet_list(summary.decisions)}
            <div class="section-title">待办事项</div>
            {cls._bullet_list(actions)}
            <div class="section-title">风险与待确认</div>
            {cls._bullet_list(summary.open_questions)}
            <div class="section-title">关键词</div>
            <div>{cls._text(keywords)}</div>
          </td></tr>
        </table>
        <div class="summary-gap"></div>
        """

    @classmethod
    def _rows_html(cls, rows: list[HistoryRow]) -> str:
        if not rows:
            return '<div class="empty">这场会议没有可展示的转写内容。</div>'
        rendered = []
        for row in rows:
            note = (
                '<div class="corrected">AI 已根据完整上下文校对</div>'
                if row.corrected else ""
            )
            rendered.append(f"""
              <tr>
                <td class="meta" width="128">
                  <div class="speaker">{cls._text(row.speaker)}</div>
                  <div class="time">{cls._text(row.timestamp)}</div>
                </td>
                <td class="body">
                  <div class="utterance">{cls._text(row.text)}</div>
                  {note}
                </td>
              </tr>
            """)
        return (
            '<table class="transcript" width="100%" '
            'cellspacing="0" cellpadding="0">'
            + "".join(rendered)
            + "</table>"
        )

    def set_meeting_content(
        self,
        rows: list[HistoryRow],
        *,
        summary: MeetingSummary | None = None,
        summary_meta: str = "",
    ) -> None:
        summary_html = (
            self._summary_html(summary, summary_meta)
            if summary is not None else ""
        )
        body = summary_html + self._rows_html(rows)
        self.setHtml(f"""
        <html><head><style>
          body {{
            font-family: "Microsoft YaHei UI";
            font-size: 11pt;
            font-weight: 400;
            color: #2f2f2f;
            background: #ffffff;
            margin: 10px 2px 20px 2px;
          }}
          table {{ border-collapse: collapse; }}
          table.summary {{
            background-color: #f7f7f8;
            border: 1px solid #e5e5e8;
          }}
          table.summary > tbody > tr > td {{ padding: 18px 22px; }}
          .summary-title {{ font-size: 16px; font-weight: 600; }}
          .summary-meta {{ font-size: 10px; color: #929292; }}
          .section-title {{ margin-top: 13px; font-weight: 600; }}
          ul {{ margin-top: 4px; margin-bottom: 5px; padding-left: 22px; }}
          li {{ margin-bottom: 3px; }}
          .summary-gap {{ height: 12px; }}
          table.transcript td {{
            border-bottom: 1px solid #eeeeef;
            vertical-align: top;
            padding-top: 15px;
            padding-bottom: 15px;
          }}
          td.meta {{ padding-right: 22px; color: #8b8b8b; }}
          .speaker {{ font-size: 10px; font-weight: 600; color: #555555; }}
          .time {{ margin-top: 4px; font-size: 9px; color: #8b8b8b; }}
          td.body {{ line-height: 1.65; }}
          .utterance {{ font-size: 11pt; color: #2f2f2f; }}
          .corrected {{ margin-top: 6px; font-size: 9px; color: #999999; }}
          .empty {{ padding: 70px 20px; text-align: center; color: #aaaaaa; }}
        </style></head><body>{body}</body></html>
        """)
        self.scroll_to_top()

    def scroll_to_top(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(0),
        )
