from __future__ import annotations

import ctypes
import sys
import threading


S_OK = 0x00000000
S_FALSE = 0x00000001
RPC_E_CHANGED_MODE = 0x80010106
COINIT_MULTITHREADED = 0x0


class ComInitializationError(RuntimeError):
    pass


class WindowsComApartment:
    """Thread-scoped COM initialization for SoundCard/WASAPI calls."""

    def __init__(
        self,
        *,
        ole32=None,
        platform_name: str | None = None,
    ) -> None:
        self._ole32 = ole32
        self._platform_name = platform_name or sys.platform
        self._thread_id: int | None = None
        self._must_uninitialize = False
        self.result_code: int | None = None

    @staticmethod
    def _unsigned_hresult(result: int) -> int:
        return int(result) & 0xFFFFFFFF

    def _load_ole32(self):
        if self._ole32 is not None:
            return self._ole32
        library = ctypes.OleDLL("ole32")
        library.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        library.CoInitializeEx.restype = ctypes.c_long
        library.CoUninitialize.argtypes = []
        library.CoUninitialize.restype = None
        self._ole32 = library
        return library

    def __enter__(self) -> "WindowsComApartment":
        self._thread_id = threading.get_ident()
        if self._platform_name != "win32":
            return self

        ole32 = self._load_ole32()
        result = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        code = self._unsigned_hresult(result)
        self.result_code = code
        if code in {S_OK, S_FALSE}:
            # Both successful results increment the per-thread COM count and
            # therefore both require a matching CoUninitialize.
            self._must_uninitialize = True
        elif code == RPC_E_CHANGED_MODE:
            # The thread already owns a different apartment. COM is available,
            # but this scope did not initialize it and must not uninitialize it.
            self._must_uninitialize = False
        else:
            raise ComInitializationError(
                f"CoInitializeEx 失败：0x{code:08x}"
            )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._must_uninitialize:
            return
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("CoUninitialize 必须在初始化 COM 的同一线程执行")
        self._load_ole32().CoUninitialize()
        self._must_uninitialize = False


def preload_soundcard() -> None:
    """Import SoundCard on the long-lived main thread before worker COM init."""
    if sys.platform != "win32":
        return
    try:
        import soundcard  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("meeting_onnx 环境中缺少 SoundCard") from exc

