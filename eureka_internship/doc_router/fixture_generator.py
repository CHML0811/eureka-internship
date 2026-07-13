"""Small, deterministic synthetic document images used by tests and demos."""

from __future__ import annotations

import struct
import zlib


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _png(pixels: list[list[int]]) -> bytes:
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _canvas(width: int, height: int) -> list[list[int]]:
    return [[255] * width for _ in range(height)]


def _rect(
    pixels: list[list[int]], left: int, top: int, right: int, bottom: int
) -> None:
    for y in range(max(0, top), min(len(pixels), bottom)):
        for x in range(max(0, left), min(len(pixels[0]), right)):
            pixels[y][x] = 0


def _line(
    pixels: list[list[int]], x1: int, y1: int, x2: int, y2: int
) -> None:
    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(steps + 1):
        x = round(x1 + (x2 - x1) * step / steps)
        y = round(y1 + (y2 - y1) * step / steps)
        if 0 <= y < len(pixels) and 0 <= x < len(pixels[0]):
            pixels[y][x] = 0


def generate_fixture(name: str) -> bytes:
    """Generate one of ten visual fixtures without storing binary files."""
    variant = 2 if name.endswith("_2") else 1
    if name.startswith("id_document"):
        pixels = _canvas(180, 105)
        _rect(pixels, 8, 8, 172, 10)
        _rect(pixels, 8, 95, 172, 97)
        _rect(pixels, 15, 20, 55, 80)
        for y in range(22, 82, 12 - variant):
            _rect(pixels, 68, y, 155, y + 2)
        return _png(pixels)

    if name.startswith("form_like"):
        pixels = _canvas(100, 145)
        for y in range(15, 130, 15 - variant):
            _rect(pixels, 8, y, 92, y + 2)
        return _png(pixels)

    if name.startswith("hybrid_report"):
        pixels = _canvas(110, 155)
        for y in range(10, 65, 12 - variant):
            _rect(pixels, 8, y, 102, y + 2)
        for index, height in enumerate((30, 55, 40, 65)):
            _rect(pixels, 12 + index * 24, 145 - height, 28 + index * 24, 145)
        return _png(pixels)

    if name.startswith("chart_like"):
        pixels = _canvas(130, 120)
        for index, height in enumerate((35, 70, 50, 85)):
            _rect(pixels, 10 + index * 28, 110 - height, 30 + index * 28, 110)
        if variant == 2:
            _rect(pixels, 100, 12, 115, 27)
        return _png(pixels)

    if name.startswith("hand_drawn"):
        pixels = _canvas(130, 125)
        upper_node = (115, 20 + variant * 3)
        _line(pixels, 10, 15, 65, 55)
        _line(pixels, 65, 55, *upper_node)
        _line(pixels, 65, 55, 25, 105)
        _line(pixels, 65, 55, 110, 105)
        for x, y in ((10, 15), upper_node, (25, 105), (110, 105)):
            _rect(pixels, x - 3, y - 3, x + 4, y + 4)
        return _png(pixels)

    if name == "uncertain":
        return _png(_canvas(100, 100))
    raise ValueError(f"Unknown synthetic fixture: {name}")
