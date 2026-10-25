"""Bounded, ephemeral media. Client clocks are never freshness authorities."""

import base64
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Frame:
    id: str
    received_at: float
    jpeg: bytes


class FrameBuffer:
    def __init__(self) -> None:
        self.frames: deque[Frame] = deque(maxlen=50)
        self.lock = threading.RLock()

    def add(self, frame_id: str, encoded: str) -> Frame:
        if len(encoded) > 400_000:
            raise ValueError("frame_too_large")
        jpeg = base64.b64decode(encoded, validate=True)
        if jpeg_size(jpeg) not in ((640, 480), (480, 640)):
            raise ValueError("expected_640x480_jpeg")
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.shape[:2] not in ((480, 640), (640, 480)):
            raise ValueError("expected_640x480_frame")
        with self.lock:
            if any(f.id == frame_id for f in self.frames):
                raise ValueError("duplicate_frame_id")
            frame = Frame(frame_id, time.monotonic(), jpeg)
            self.frames.append(frame)
            self.prune()
        return frame

    def prune(self) -> None:
        with self.lock:
            while self.frames and time.monotonic() - self.frames[0].received_at > 10:
                self.frames.popleft()

    def get(self, frame_id: str) -> Frame:
        with self.lock:
            self.prune()
            for frame in self.frames:
                if frame.id == frame_id:
                    return frame
        raise ValueError("keyframe_missing_or_expired")

    def samples(self) -> list[Frame]:
        with self.lock:
            self.prune()
            frames = list(self.frames)
        return [frames[i] for i in sorted({0, len(frames) // 2, len(frames) - 1})] if frames else []


def jpeg_size(data: bytes) -> tuple[int, int]:
    """Check dimensions before allocating a decoded image."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("jpeg_required")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise ValueError("invalid_jpeg_marker")
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if length < 2 or offset + 2 + length > len(data):
            raise ValueError("invalid_jpeg_segment")
        if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            return width, height
        offset += 2 + length
    raise ValueError("jpeg_dimensions_missing")
