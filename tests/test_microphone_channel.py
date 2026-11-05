from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from desktop.recorder_worker import RecorderOptions, RecorderWorker
from meeting.audio_utils import AudioChunk
from meeting.config import MeetingConfig
from meeting.microphone_channel import MicrophoneChannel
from meeting.vad import VADDecision


class FakeApartment:
    entered_thread: int | None = None
    exited_thread: int | None = None

    def __enter__(self):
        type(self).entered_thread = threading.get_ident()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        type(self).exited_thread = threading.get_ident()


class FakeVad:
    def reset(self) -> None:
        return None

    def accept(self, _chunk: AudioChunk) -> VADDecision:
        return VADDecision(False)


class FakeAsr:
    def __init__(self) -> None:
        self.stopped = False

    def start(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def feed_audio(self, _samples, _start, _end):
        return []

    def finalize_utterance(self, _end):
        return None

    def stop(self) -> None:
        self.stopped = True


class ToggleCapture:
    instances: list["ToggleCapture"] = []

    def __init__(self, **_kwargs) -> None:
        self.started = False
        self.stopped = False
        self.index = 0
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def read_chunk(self) -> AudioChunk:
        time.sleep(0.005)
        start = self.index * 0.01
        self.index += 1
        return AudioChunk(
            np.zeros(160, dtype=np.float32),
            16000,
            start,
            start + 0.01,
        )

    def stop(self) -> None:
        self.stopped = True


class FailingCapture(ToggleCapture):
    def read_chunk(self) -> AudioChunk:
        raise RuntimeError("microphone disconnected")


class MicrophoneChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeApartment.entered_thread = None
        FakeApartment.exited_thread = None
        ToggleCapture.instances = []

    def test_channel_is_off_by_default_and_can_toggle_during_meeting(self) -> None:
        statuses: list[tuple[bool, str]] = []
        active = threading.Event()

        def status(enabled: bool, message: str) -> None:
            statuses.append((enabled, message))
            if enabled:
                active.set()

        fake_asr = FakeAsr()
        channel = MicrophoneChannel(
            MeetingConfig(),
            "mic-1",
            timeline_origin=time.monotonic(),
            result_handler=lambda _result: None,
            status_handler=status,
            error_handler=self.fail,
        )
        with (
            patch(
                "meeting.microphone_channel.WindowsComApartment",
                FakeApartment,
            ),
            patch(
                "meeting.microphone_channel.WasapiMicrophoneCapture",
                ToggleCapture,
            ),
            patch(
                "meeting.microphone_channel.create_vad",
                return_value=FakeVad(),
            ),
            patch(
                "meeting.microphone_channel.create_asr_service",
                return_value=fake_asr,
            ),
        ):
            channel.start(enabled=False)
            time.sleep(0.03)
            self.assertFalse(ToggleCapture.instances)
            channel.set_enabled(True)
            self.assertTrue(active.wait(1.0))
            channel.set_enabled(False)
            deadline = time.monotonic() + 1.0
            while statuses[-1][0] and time.monotonic() < deadline:
                time.sleep(0.01)
            channel.stop()

        self.assertEqual(statuses[0], (True, "本人麦克风已开启"))
        self.assertEqual(statuses[-1], (False, "本人麦克风已关闭"))
        self.assertTrue(ToggleCapture.instances[0].stopped)
        self.assertTrue(fake_asr.stopped)
        self.assertEqual(
            FakeApartment.entered_thread,
            FakeApartment.exited_thread,
        )

    def test_capture_failure_is_reported_and_resources_are_released(self) -> None:
        errors: list[str] = []
        failed = threading.Event()

        def report_error(message: str) -> None:
            errors.append(message)
            failed.set()

        channel = MicrophoneChannel(
            MeetingConfig(),
            "mic-1",
            timeline_origin=time.monotonic(),
            result_handler=lambda _result: None,
            status_handler=lambda _enabled, _message: None,
            error_handler=report_error,
        )
        with (
            patch(
                "meeting.microphone_channel.WindowsComApartment",
                FakeApartment,
            ),
            patch(
                "meeting.microphone_channel.WasapiMicrophoneCapture",
                FailingCapture,
            ),
            patch(
                "meeting.microphone_channel.create_vad",
                return_value=FakeVad(),
            ),
            patch(
                "meeting.microphone_channel.create_asr_service",
                return_value=FakeAsr(),
            ),
        ):
            channel.start(enabled=True)
            self.assertTrue(failed.wait(1.0))
            channel.stop()

        self.assertIn("microphone disconnected", errors[0])
        self.assertTrue(ToggleCapture.instances[0].stopped)

    def test_worker_contains_toggle_failure_without_stopping_system(self) -> None:
        class BrokenChannel:
            @staticmethod
            def set_enabled(_enabled: bool) -> None:
                raise RuntimeError("mic control failed")

        options = RecorderOptions(
            device_id="output-1",
            device_name="Output",
            expected_speakers=-1,
            correction_enabled=False,
            base_url="",
            model="",
            simulation=False,
            models_enabled=True,
            microphone_device_id="mic-1",
        )
        worker = RecorderWorker(options, ".", ".")
        worker._microphone_channel = BrokenChannel()
        errors: list[str] = []
        worker.microphone_error.connect(errors.append)

        worker.set_microphone_enabled(True)

        self.assertIn("mic control failed", errors[0])
        self.assertFalse(worker._stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
