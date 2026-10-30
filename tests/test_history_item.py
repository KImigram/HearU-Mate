from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop.history_item import HistoryItemWidget


class HistoryItemWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_three_dot_menu_emits_rename_and_delete_requests(self) -> None:
        widget = HistoryItemWidget("meeting-1", "产品周会")
        renamed = []
        deleted = []
        widget.rename_requested.connect(renamed.append)
        widget.delete_requested.connect(deleted.append)

        actions = widget.menu_button.menu().actions()
        self.assertEqual(
            [action.text() for action in actions],
            ["重命名", "删除会议"],
        )
        actions[0].trigger()
        actions[1].trigger()

        self.assertEqual(renamed, ["meeting-1"])
        self.assertEqual(deleted, ["meeting-1"])


if __name__ == "__main__":
    unittest.main()
