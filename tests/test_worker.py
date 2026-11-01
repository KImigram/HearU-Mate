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
        worker = RecorderWorker(
            options,
            Path.cwd() / "test-data",
            Path.cwd() / "test-models",
        )
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
            worker = RecorderWorker(
                options,
                root / "data",
                root / "models",
            )
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
                root / "data" / "meeting_history.db"
            ).get_meeting(completed[0])
            self.assertEqual(meeting["status"], "completed")
            self.assertEqual(len(meeting["segments"]), 2)

    def test_installed_paths_are_applied_to_models_and_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            data_dir = root / "local-data"
            models_root = root / "installed-models"
            options = RecorderOptions(
                device_id=None,
                device_name="测试设备",
                expected_speakers=1,
                correction_enabled=False,
                base_url="https://api.deepseek.com",
                model="deepseek-flash",
                simulation=True,
                models_enabled=False,
            )
            worker = RecorderWorker(
                options,
                data_dir,
                models_root,
            )
            config = worker._new_config()
            self.assertEqual(Path(config.output.root_dir), data_dir)
            self.assertEqual(
                Path(config.asr.model_dir),
                models_root / "paraformer-streaming-int8",
            )
            self.assertEqual(
                Path(config.vad.model),
                models_root / "silero-vad" / "silero_vad.onnx",
            )
            self.assertEqual(
                worker._store().db_path,
                (data_dir / "meeting_history.db").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
