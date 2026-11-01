from __future__ import annotations

import argparse
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_frame(source: QImage, size: int) -> bytes:
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Unable to open the in-memory PNG buffer")
    if not scaled.save(buffer, "PNG"):
        raise RuntimeError(f"Unable to encode the {size}px icon frame")
    buffer.close()
    return bytes(payload)


def build_ico(source_path: Path, destination_path: Path) -> None:
    source = QImage(str(source_path))
    if source.isNull():
        raise ValueError(f"Unable to read icon source: {source_path}")
    if source.width() != source.height():
        raise ValueError("The icon source must be square")

    frames = [(size, png_frame(source, size)) for size in ICON_SIZES]
    header_size = 6 + (16 * len(frames))
    offset = header_size
    entries: list[bytes] = []
    payloads: list[bytes] = []
    for size, payload in frames:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.append(payload)
        offset += len(payload)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(
        struct.pack("<HHH", 0, 1, len(frames))
        + b"".join(entries)
        + b"".join(payloads)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the HearU Mate ICO")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build_ico(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
