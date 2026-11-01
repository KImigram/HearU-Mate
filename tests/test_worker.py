from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from desktop.recorder_worker import RecorderOptions, RecorderWorker
from meeting.store import MeetingStore


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_worker_applies_selected_speaker_embedding_profile(self) -> None:
        options = RecorderOptions(
            device_id=None,
            device_name="测试设备",
            expected_speakers=2,
            correction_enabled=False,
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            simulation=True,
            models_enabled=False,
            speaker_embedding_profile="wespeaker_cnceleb_resnet34_lm",
        )
        worker = RecorderWorker(options, Path.cwd())
        config = worker._new_config()
        self.assertEqual(
            config.speaker.embedding_profile,
            "wespeaker_cnceleb_resnet34_lm",
        )
        self.assertTrue(
            config.speaker.embedding_model.endswith(
                "wespeaker-cnceleb-resnet34-LM-sherpa.onnx"
            )
        )
        self.assertEqual(config.speaker.num_speakers, 2)

    def test_simulation_emits_signal_chain_and_saves_history(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            options = RecorderOptions(
                device_id=None,
                device_name="测试设备",
                expected_speakers=-1,
                correction_enabled=True,
                base_url="https://api.deepseek.com",
                model="deepseek-flash",
                simulation=True,
                models_enabled=False,
                simulation_delay=0.0,
            )
            worker = RecorderWorker(options, root)
            partials: list[str] = []
            finals: list[str] = []
            statuses: list[str] = []
            completed: list[str] = []
            errors: list[str] = []
            worker.partial.connect(partials.append)
            worker.final.connect(lambda text, _start, _end: finals.append(text))
            worker.status.connect(statuses.append)
            worker.completed.connect(completed.append)
            worker.error.connect(errors.append)
            worker.run()
            self.assertFalse(errors)
            self.assertTrue(partials)
            self.assertEqual(len(finals), 2)
            self.assertEqual(statuses[-1], "已完成")
            self.assertEqual(len(completed), 1)
            meeting = MeetingStore(
                root / "data" / "meetings" / "meeting_history.db"
            ).get_meeting(completed[0])
            self.assertEqual(meeting["status"], "completed")
            self.assertEqual(len(meeting["segments"]), 2)


if __name__ == "__main__":
    unittest.main()
