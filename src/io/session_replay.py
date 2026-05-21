from __future__ import annotations

import json
import cv2
import numpy as np
from pathlib import Path
from typing import Iterable, List

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
        frames.append(SimulationFrame(state=state, issues=item.get("issues", [])))
    return frames

class VideoRenderManager:
    def __init__(self, scene_widget, json_path: str | Path, output_mp4_path: str | Path, fps: int = 60 , step: int = 20):
        self.scene_widget = scene_widget
        self.output_path = output_mp4_path
        self.fps = fps
        self.step = step
        
        # Wczytanie klatek przy starcie managera
        self.frames = import_frames(json_path)
        self.total_frames = len(self.frames)
        
        self.current_idx = 0
        self.previous_frame = None
        self.video_writer = None
        
        if self.total_frames > 0:
            self.scene_widget.reset_scene()

    def is_finished(self) -> bool:
        """Zwraca True, jeśli przetworzono już wszystkie klatki."""
        return self.current_idx >= self.total_frames

    def render_next_step(self) -> tuple[int, int]:
        if self.is_finished():
            return self.current_idx, self.total_frames

        current_frame = self.frames[self.current_idx]

        self.scene_widget.update_frame(self.previous_frame, current_frame) 

        if self.current_idx % self.step == 0 or self.current_idx == self.total_frames - 1:
            
            
            self.scene_widget.repaint()

            pixmap = self.scene_widget.grab()
            qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)

            img_width = qimage.width()
            img_height = qimage.height()
            img_width = img_width if img_width % 2 == 0 else img_width - 1
            img_height = img_height if img_height % 2 == 0 else img_height - 1

            if self.video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                self.video_writer = cv2.VideoWriter(
                    str(self.output_path), fourcc, self.fps, (img_width, img_height)
                )

            ptr = qimage.bits()
            ptr.setsize(qimage.sizeInBytes())
            arr = np.array(ptr).reshape(qimage.height(), qimage.width(), 4)
            arr = arr[:img_height, :img_width]
            frame_bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            
            self.video_writer.write(frame_bgr)
        
        self.previous_frame = current_frame
        self.current_idx += 1

        return self.current_idx, self.total_frames

    def close(self):
        """Zwalnia plik wideo i czyści scenę."""
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
        self.scene_widget.reset_scene()