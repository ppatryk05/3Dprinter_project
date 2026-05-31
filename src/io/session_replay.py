from __future__ import annotations

import json
import cv2
import numpy as np
from pathlib import Path
from typing import Iterable, List, Sequence

from PyQt6.QtGui import QImage

from src.core.types import MotionState
from src.sim.simulator import SimulationFrame


def export_frames(path: str | Path, frames: Iterable[SimulationFrame]) -> None:
    data = [
        {
            "t": frame.state.t,
            "x": frame.state.x,
            "y": frame.state.y,
            "z": frame.state.z,
            "e": frame.state.e,
            "feed_rate": frame.state.feed_rate,
            "nozzle_temp": frame.state.nozzle_temp,
            "bed_temp": frame.state.bed_temp,
            "issues": frame.issues,
            "path_kind": frame.path_kind,
        }
        for frame in frames
    ]
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def import_frames(path: str | Path) -> List[SimulationFrame]:
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    frames: List[SimulationFrame] = []
    for item in source:
        state = MotionState(
            t=item["t"],
            x=item["x"],
            y=item["y"],
            z=item["z"],
            e=item["e"],
            feed_rate=item["feed_rate"],
            nozzle_temp=item["nozzle_temp"],
            bed_temp=item["bed_temp"],
            alarms=[],
        )
        frames.append(SimulationFrame(
            state=state,
            issues=item.get("issues", []),
            path_kind=item.get("path_kind", "model"),
        ))
    return frames


class VideoRenderManager:
    """
    Renders a sequence of SimulationFrames into an MP4 file by replaying them
    through the scene widget and capturing OpenGL screenshots.

    Accepts either:
    - a pre-loaded list of SimulationFrame objects  (for exporting current session)
    - a Path / str to a JSON session file           (legacy, JSON→MP4 workflow)

    Parameters
    ----------
    scene_widget   : Scene3DWidget instance
    frames_or_path : list[SimulationFrame] **or** path to a JSON session file
    output_mp4_path: destination .mp4 file
    fps            : frames per second of the output video
    step           : capture one video frame every `step` simulation frames
                     (lower = smoother video, but larger file and slower export)
    """

    def __init__(
        self,
        scene_widget,
        frames_or_path: Sequence[SimulationFrame] | str | Path,
        output_mp4_path: str | Path,
        fps: int = 60,
        step: int = 10,
    ) -> None:
        self.scene_widget = scene_widget
        self.output_path  = Path(output_mp4_path)
        self.fps          = fps
        self.step         = step

        if isinstance(frames_or_path, (str, Path)):
            self.frames = import_frames(frames_or_path)
        else:
            self.frames = list(frames_or_path)

        self.total_frames  = len(self.frames)
        self.current_idx   = 0
        self.previous_frame: SimulationFrame | None = None
        self.video_writer: cv2.VideoWriter | None = None

        if self.total_frames > 0:
            self.scene_widget.reset_scene()

    # ------------------------------------------------------------------
    def is_finished(self) -> bool:
        return self.current_idx >= self.total_frames

    def render_next_step(self) -> tuple[int, int]:
        if self.is_finished():
            return self.current_idx, self.total_frames

        current_frame = self.frames[self.current_idx]
        self.scene_widget.update_frame(self.previous_frame, current_frame)

        capture = (
            self.current_idx % self.step == 0
            or self.current_idx == self.total_frames - 1
        )
        if capture:
            self.scene_widget.repaint()
            pixmap  = self.scene_widget.grab()
            qimage  = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)

            w = qimage.width()  - (qimage.width()  % 2)
            h = qimage.height() - (qimage.height() % 2)

            if self.video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self.video_writer = cv2.VideoWriter(
                    str(self.output_path), fourcc, self.fps, (w, h)
                )

            ptr = qimage.bits()
            ptr.setsize(qimage.sizeInBytes())
            arr       = np.array(ptr).reshape(qimage.height(), qimage.width(), 4)
            frame_bgr = cv2.cvtColor(arr[:h, :w], cv2.COLOR_RGBA2BGR)
            self.video_writer.write(frame_bgr)

        self.previous_frame  = current_frame
        self.current_idx    += 1
        return self.current_idx, self.total_frames

    def close(self) -> None:
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
        self.scene_widget.reset_scene()
