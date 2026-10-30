from __future__ import annotations

import threading
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from desktop.main_window import MainWindow
from desktop.recorder_worker import (
    DeviceDiscoveryWorker,
    RecorderOptions,
    RecorderWorker,
)
from meeting.audio_capture import AudioDevice, WasapiLoopbackCapture
from meeting.windows_com import (
    RPC_E_CHANGED_MODE,
    S_FALSE,
    S_OK,
    WindowsComApartment,
)


class FakeOle32:
    def __init__(self, result: int) -> None:
        self.result = result
        self.initialize_threads: list[int] = []
        self.uninitialize_threads: list[int] = []

    def CoInitializeEx(self, _reserved, _mode):
        self.initialize_threads.append(threading.get_ident())
        return self.result

    def CoUninitialize(self) -> None:
        self.uninitialize_threads.append(threading.get_ident())


class TrackingApartment:
    active = False
    events: list[str] = []

    def __enter__(self):
        type(self).active = True
        type(self).events.append("com_enter")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        type(self).events.append("com_exit")
        type(self).active = False


class SlowDeviceDiscoveryWorker(QObject):
    devices_ready = Signal(object)
    error = Signal(str)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        time.sleep(0.2)
        self.devices_ready.emit([])
        self.finished.emit()


class FakeService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def stop(self) -> None:
        if not TrackingApartment.active:
            raise AssertionError("service stopped after COM was released")
        self.events.append("service_stop")


class FakeRecorder:
    def __init__(self, events: list[str]) -> None:
        self.audio_capture = FakeService(events)
        self.asr = FakeService(events)
        self.speaker = FakeService(events)

    def request_stop(self) -> None:
        self.audio_capture.events.append("request_stop")


class WindowsComTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_s_ok_initializes_and_uninitializes_on_same_thread(self) -> None:
        ole32 = FakeOle32(S_OK)
        with WindowsComApartment(
            ole32=ole32,
            platform_name="win32",
        ):
            self.assertEqual(ole32.initialize_threads, [threading.get_ident()])
        self.assertEqual(ole32.uninitialize_threads, [threading.get_ident()])

    def test_s_false_is_success_and_is_balanced(self) -> None:
        ole32 = FakeOle32(S_FALSE)
        with WindowsComApartment(
            ole32=ole32,
            platform_name="win32",
        ):
            pass
        self.assertEqual(len(ole32.uninitialize_threads), 1)

    def test_changed_mode_does_not_uninitialize_foreign_apartment(self) -> None:
        ole32 = FakeOle32(RPC_E_CHANGED_MODE)
        with WindowsComApartment(
            ole32=ole32,
            platform_name="win32",
        ):
            pass
        self.assertFalse(ole32.uninitialize_threads)

    def test_device_discovery_uses_com_without_real_soundcard(self) -> None:
        TrackingApartment.events = []
        devices = []
        errors = []
        worker = DeviceDiscoveryWorker()
        worker.devices_ready.connect(devices.extend)
        worker.error.connect(errors.append)
        fake_device = AudioDevice("device-1", "Fake Output", True)
        with (
            patch(
                "desktop.recorder_worker.WindowsComApartment",
                TrackingApartment,
            ),
            patch.object(
                WasapiLoopbackCapture,
                "list_devices",
                return_value=[fake_device],
            ),
        ):
            worker.run()
        self.assertFalse(errors)
        self.assertEqual(devices[0]["id"], "device-1")
        self.assertEqual(
            TrackingApartment.events,
            ["com_enter", "com_exit"],
        )

    def test_recorder_cleanup_happens_before_com_release(self) -> None:
        TrackingApartment.events = []
        events: list[str] = []
        options = RecorderOptions(
            device_id="device-1",
            device_name="Fake Output",
            expected_speakers=-1,
            correction_enabled=False,
            base_url="",
            model="",
            simulation=False,
            models_enabled=True,
        )
        worker = RecorderWorker(options, ".")

        def fake_run_real():
            self.assertTrue(TrackingApartment.active)
            worker._recorder = FakeRecorder(events)
            return "meeting-1"

        worker._run_real_recorder = fake_run_real
        completed = []
        errors = []
        worker.completed.connect(completed.append)
        worker.error.connect(errors.append)
        with patch(
            "desktop.recorder_worker.WindowsComApartment",
            TrackingApartment,
        ):
            worker.run()
        self.assertFalse(errors)
        self.assertEqual(completed, ["meeting-1"])
        self.assertEqual(events.count("service_stop"), 3)
        self.assertLess(
            TrackingApartment.events.index("com_enter"),
            TrackingApartment.events.index("com_exit"),
        )

    def test_start_failure_still_cleans_up_before_com_release(self) -> None:
        TrackingApartment.events = []
        events: list[str] = []
        options = RecorderOptions(
            device_id="device-1",
            device_name="Fake Output",
            expected_speakers=-1,
            correction_enabled=False,
            base_url="",
            model="",
            simulation=False,
            models_enabled=True,
        )
        worker = RecorderWorker(options, ".")

        def failing_run_real():
            worker._recorder = FakeRecorder(events)
            raise RuntimeError("start failed")

        worker._run_real_recorder = failing_run_real
        errors = []
        worker.error.connect(errors.append)
        with (
            patch(
                "desktop.recorder_worker.WindowsComApartment",
                TrackingApartment,
            ),
            patch.object(worker, "_mark_failed"),
        ):
            worker.run()
        self.assertTrue(errors)
        self.assertEqual(events.count("service_stop"), 3)
        self.assertEqual(
            TrackingApartment.events,
            ["com_enter", "com_exit"],
        )

    def test_device_discovery_does_not_block_gui_thread(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with (
                patch.dict(
                    os.environ,
                    {"DEEPSEEK_API_KEY": "test-key-not-real"},
                ),
                patch(
                    "desktop.main_window.DeviceDiscoveryWorker",
                    SlowDeviceDiscoveryWorker,
                ),
            ):
                window = MainWindow(folder, simulation_mode=True)
                loop = QEventLoop()
                timer_delays: list[float] = []
                started = time.perf_counter()
                QTimer.singleShot(
                    20,
                    lambda: timer_delays.append(
                        time.perf_counter() - started
                    ),
                )
                QTimer.singleShot(350, loop.quit)
                loop.exec()
                self.assertTrue(timer_delays)
                self.assertLess(timer_delays[0], 0.1)
                self.assertIsNone(window._device_thread)
                window.close()


if __name__ == "__main__":
    unittest.main()
