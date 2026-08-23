"""Frame sampling from a video using OpenCV (headless build, no system ffmpeg)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2

from app import config

# Long edge cap for each sampled frame. Raised from an initial 1024px after
# testing showed jersey numbers were too blurry to read at the smaller size.
MAX_FRAME_LONG_EDGE = 1568
JPEG_QUALITY = 90


class VideoReadError(Exception):
    """Raised when a video can't be opened or yields no readable frames."""


@dataclass
class FrameSample:
    path: Path
    timestamp_sec: float

    @property
    def timestamp_label(self) -> str:
        total = int(round(self.timestamp_sec))
        minutes, seconds = divmod(total, 60)
        return f"{minutes:02d}:{seconds:02d}"


def _resize_long_edge(frame, max_long_edge: int):
    height, width = frame.shape[:2]
    long_edge = max(height, width)
    if long_edge <= max_long_edge:
        return frame
    scale = max_long_edge / float(long_edge)
    new_size = (int(round(width * scale)), int(round(height * scale)))
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def extract_frames(video_path: Path, frames_dir: Path) -> list[FrameSample]:
    """Sample frames from ``video_path`` into ``frames_dir``.

    One frame is sampled every ``SAMPLE_INTERVAL_SEC`` seconds, widening the
    interval automatically so the total never exceeds ``MAX_FRAMES`` regardless
    of clip length. Each frame is resized so its long edge is at most
    ``MAX_FRAME_LONG_EDGE`` px and JPEG-encoded at ``JPEG_QUALITY``.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise VideoReadError(
            "Could not open the video file. It may be corrupt or in an "
            "unsupported format."
        )

    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0

    if fps <= 0:
        # Some containers don't report fps; fall back to a sane default so we
        # can still compute an interval.
        fps = 30.0

    duration_sec = (frame_count / fps) if frame_count > 0 else 0.0

    # Decide the sampling interval (seconds). Widen it if a 1s cadence would
    # exceed MAX_FRAMES.
    interval_sec = config.SAMPLE_INTERVAL_SEC
    if duration_sec > 0:
        estimated = duration_sec / interval_sec
        if estimated > config.MAX_FRAMES:
            interval_sec = duration_sec / config.MAX_FRAMES

    frame_interval = max(1, int(round(fps * interval_sec)))

    samples: list[FrameSample] = []
    index = 0
    next_capture = 0

    while len(samples) < config.MAX_FRAMES:
        grabbed, frame = capture.read()
        if not grabbed:
            break

        if index >= next_capture:
            timestamp_sec = index / fps
            resized = _resize_long_edge(frame, MAX_FRAME_LONG_EDGE)
            out_path = frames_dir / f"frame_{len(samples):03d}.jpg"
            ok = cv2.imwrite(
                str(out_path),
                resized,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
            )
            if ok:
                samples.append(FrameSample(path=out_path, timestamp_sec=timestamp_sec))
            next_capture += frame_interval

        index += 1

    capture.release()

    if not samples:
        raise VideoReadError(
            "No frames could be extracted from the video. It may be empty or "
            "corrupt."
        )

    return samples
