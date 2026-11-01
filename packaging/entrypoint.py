from __future__ import annotations

from pathlib import Path
import sys
import traceback


def _diagnostic_path() -> Path:
    return Path(sys.executable).resolve().with_name("self-check-error.log")


try:
    from desktop.app import main

    raise SystemExit(main())
except SystemExit:
    raise
except BaseException:
    if "--self-check" in sys.argv:
        _diagnostic_path().write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        raise SystemExit(3)
    raise
