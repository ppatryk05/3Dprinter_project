from __future__ import annotations

import datetime
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import cv2
import numpy as np

from src.core.gcode_parser import parse_gcode_file
from src.core.types import PrinterConfig
from src.io.session_replay import export_frames, import_frames, VideoRenderManager
from src.render.scene3d import Scene3DWidget
from src.sim.simulator import PrinterSimulator, SimulationFrame



# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _LoadWorker(QThread):
    finished = pyqtSignal(list, str)   # frames, label text
    error    = pyqtSignal(str)

    def __init__(self, path: Path, config: PrinterConfig) -> None:
        super().__init__()
        self.path   = path
        self.config = config

    def run(self) -> None:
        try:
            commands = parse_gcode_file(self.path)
            sim      = PrinterSimulator(self.config)
            frames   = sim.run(commands)
            label    = f"Załadowano: {self.path.name}  ({len(frames)} kroków)"
            self.finished.emit(frames, label)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Loading overlay dialog
# ---------------------------------------------------------------------------

class _LoadingDialog(QDialog):
    def __init__(self, parent: QWidget, filename: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ładowanie…")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )
        self.setModal(True)
        self.setFixedSize(340, 90)

        layout = QVBoxLayout(self)
        self._label = QLabel(f"Przetwarzanie: {filename}")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._dots_label = QLabel("●  ○  ○  ○  ○")
        self._dots_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dots_label.setStyleSheet("font-size: 18px; letter-spacing: 4px; color: #4a7adc;")
        layout.addWidget(self._dots_label)

        self._tick = 0
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(180)

    def _step(self) -> None:
        self._tick = (self._tick + 1) % 5
        dots = ["●" if i == self._tick else "○" for i in range(5)]
        self._dots_label.setText("  ".join(dots))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

# Folder where all recordings and exports are saved automatically
_RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"


def _auto_path(prefix: str, ext: str) -> Path:
    """Return recordings/<prefix>_YYYYMMDD_HHMMSS.<ext>, creating folder if needed."""
    _RECORDINGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _RECORDINGS_DIR / f"{prefix}_{stamp}.{ext}"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3D Printer Simulator")
        self.resize(1400, 900)

        self.config  = PrinterConfig()
        self.frames: list[SimulationFrame] = []
        self.frame_idx = 0
        self.playing   = False
        self.last_file = Path("examples/sample.gcode")
        self._worker: _LoadWorker | None = None
        self._loading_dlg: _LoadingDialog | None = None

        # Live recording state
        self._recording      = False
        self._rec_writer: cv2.VideoWriter | None = None
        self._rec_path       = ""
        self._rec_frame_cnt  = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        self.scene = Scene3DWidget(config=self.config)
        layout.addWidget(self.scene, stretch=3)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        layout.addWidget(sidebar, stretch=2)

        self.status_label = QLabel("Załaduj plik G-code aby zacząć")
        self.status_label.setWordWrap(True)
        sidebar_layout.addWidget(self.status_label)

        self.load_btn = QPushButton("Załaduj G-code")
        self.load_btn.clicked.connect(self.load_gcode)
        sidebar_layout.addWidget(self.load_btn)

        play_btn = QPushButton("Play / Pauza  [Spacja]")
        play_btn.clicked.connect(self.toggle_play)
        sidebar_layout.addWidget(play_btn)

        restart_btn = QPushButton("Restart")
        restart_btn.clicked.connect(self.restart)
        sidebar_layout.addWidget(restart_btn)

        # ── Session group ─────────────────────────────────────────────
        session_box = QGroupBox("Sesja / Nagranie")
        session_layout = QVBoxLayout(session_box)
        session_layout.setSpacing(4)

        self._save_btn = QPushButton("Zapisz sesję (JSON)")
        self._save_btn.setToolTip("Zapisuje wszystkie klatki symulacji do pliku JSON")
        self._save_btn.clicked.connect(self.export_replay)
        session_layout.addWidget(self._save_btn)

        self._load_btn = QPushButton("Wczytaj i odtwórz sesję (JSON)")
        self._load_btn.setToolTip("Wczytuje sesję z pliku JSON i automatycznie rozpoczyna odtwarzanie")
        self._load_btn.clicked.connect(self.import_replay)
        session_layout.addWidget(self._load_btn)

        self._rec_btn = QPushButton("Nagraj od teraz")
        self._rec_btn.setToolTip(
            "Rozpoczyna nagrywanie na żywo od bieżącej klatki.\n"
            "Naciśnij ponownie aby zatrzymać i zapisać wideo MP4."
        )
        self._rec_btn.setStyleSheet("QPushButton { color: #ff4444; font-weight: bold; }")
        self._rec_btn.clicked.connect(self.toggle_live_record)
        session_layout.addWidget(self._rec_btn)

        self._mp4_btn = QPushButton("Eksportuj całą sesję do MP4")
        self._mp4_btn.setToolTip(
            "Renderuje WSZYSTKIE klatki bieżącej sesji do pliku wideo MP4.\n"
            "Nie wymaga osobnego pliku JSON – działa na bieżących danych w pamięci."
        )
        self._mp4_btn.clicked.connect(self.on_click_render)
        session_layout.addWidget(self._mp4_btn)

        # Progress bar shown only during MP4 export
        self._render_progress = QProgressBar()
        self._render_progress.setRange(0, 100)
        self._render_progress.setValue(0)
        self._render_progress.setTextVisible(True)
        self._render_progress.setFormat("Renderowanie: %p%")
        self._render_progress.setVisible(False)
        session_layout.addWidget(self._render_progress)

        sidebar_layout.addWidget(session_box)

        self._speed_label = QLabel("Prędkość: 5×")
        sidebar_layout.addWidget(self._speed_label)
        self.speed = QSlider()
        self.speed.setOrientation(Qt.Orientation.Horizontal)
        self.speed.setRange(1, 50)
        self.speed.setValue(5)
        self.speed.valueChanged.connect(
            lambda v: self._speed_label.setText(f"Prędkość: {v}×")
        )
        sidebar_layout.addWidget(self.speed)

        self._travel_cb = QCheckBox("Pokaż ruchy jałowe")
        self._travel_cb.setChecked(True)
        self._travel_cb.toggled.connect(self.scene.set_show_travel)
        sidebar_layout.addWidget(self._travel_cb)

        self._support_cb = QCheckBox("Pokaż podpory (niebieskie)")
        self._support_cb.setChecked(True)
        self._support_cb.toggled.connect(self.scene.set_show_support)
        sidebar_layout.addWidget(self._support_cb)

        self._shadow_cb = QCheckBox("Pokaż cień na stole")
        self._shadow_cb.setChecked(True)
        self._shadow_cb.toggled.connect(self.scene.set_show_shadow)
        sidebar_layout.addWidget(self._shadow_cb)

        # ── Statistics panel ──────────────────────────────────────────────
        sidebar_layout.addWidget(QLabel("Statystyki:"))
        self._stat_progress = QLabel("Postęp:  0.0 %")
        self._stat_time     = QLabel("Czas:    0:00")
        self._stat_layer    = QLabel("Warstwa: Z = 0.00 mm")
        self._stat_filament = QLabel("Filament: 0.0 mm  (0.00 g)")
        for lbl in (self._stat_progress, self._stat_time,
                    self._stat_layer, self._stat_filament):
            lbl.setStyleSheet("font-family: monospace; font-size: 11px;")
            sidebar_layout.addWidget(lbl)

        sidebar_layout.addWidget(QLabel("Temperatura [°C]:"))
        self.temp_plot = pg.PlotWidget()
        self.temp_plot.setMaximumHeight(200)
        self.temp_plot.setBackground((28, 30, 38))
        self.temp_plot.getAxis("left").setPen(pg.mkPen((140, 145, 165)))
        self.temp_plot.getAxis("bottom").setPen(pg.mkPen((140, 145, 165)))
        self.temp_plot.getAxis("left").setTextPen(pg.mkPen((190, 192, 205)))
        self.temp_plot.getAxis("bottom").setTextPen(pg.mkPen((190, 192, 205)))
        self.temp_plot.addLegend(labelTextColor=(200, 202, 215))
        self.temp_plot.setLabel("left", "°C", color="#c8cadc")
        self.nozzle_curve = self.temp_plot.plot([], [], pen=pg.mkPen((240, 80, 60), width=2), name="Dysza")
        self.bed_curve    = self.temp_plot.plot([], [], pen=pg.mkPen((255, 195, 40), width=2), name="Stół")
        sidebar_layout.addWidget(self.temp_plot)

        sidebar_layout.addWidget(QLabel("Ekstruzja (E):"))
        self.progress_plot = pg.PlotWidget()
        self.progress_plot.setMaximumHeight(160)
        self.progress_plot.setBackground((28, 30, 38))
        self.progress_plot.getAxis("left").setPen(pg.mkPen((140, 145, 165)))
        self.progress_plot.getAxis("bottom").setPen(pg.mkPen((140, 145, 165)))
        self.progress_plot.getAxis("left").setTextPen(pg.mkPen((190, 192, 205)))
        self.progress_plot.getAxis("bottom").setTextPen(pg.mkPen((190, 192, 205)))
        self.progress_plot.setLabel("left", "mm", color="#c8cadc")
        self.extrusion_curve = self.progress_plot.plot([], [], pen=pg.mkPen((255, 115, 30), width=2))
        sidebar_layout.addWidget(self.progress_plot)

        sidebar_layout.addStretch(1)

        if self.last_file.exists():
            self._start_load(self.last_file)

    # ------------------------------------------------------------------
    # Loading (background thread)
    # ------------------------------------------------------------------
    def _start_load(self, path: Path) -> None:
        self.playing = False
        self.load_btn.setEnabled(False)
        self.status_label.setText(f"Ładowanie: {path.name}…")

        self._loading_dlg = _LoadingDialog(self, path.name)
        self._loading_dlg.show()

        self._worker = _LoadWorker(path, self.config)
        self._worker.finished.connect(self._on_load_done)
        self._worker.error.connect(self._on_load_error)
        self._worker.start()

    def _on_load_done(self, frames: list[SimulationFrame], label: str) -> None:
        self.frames    = frames
        self.frame_idx = 0
        self.playing   = False
        self.scene.reset_scene()
        self._refresh_charts()
        self.status_label.setText(label)
        self.load_btn.setEnabled(True)
        if self._loading_dlg:
            self._loading_dlg.accept()
            self._loading_dlg = None

    def _on_load_error(self, msg: str) -> None:
        self.status_label.setText(f"Błąd ładowania: {msg}")
        self.load_btn.setEnabled(True)
        if self._loading_dlg:
            self._loading_dlg.reject()
            self._loading_dlg = None

    def load_gcode(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Otwórz G-code", str(self.last_file.parent),
            "G-code (*.gcode *.gc *.txt);;Wszystkie pliki (*)",
        )
        if filename:
            self.last_file = Path(filename)
            self._start_load(self.last_file)

    # ------------------------------------------------------------------
    def toggle_play(self) -> None:
        if not self.frames:
            self.status_label.setText("Brak danych – załaduj G-code")
            return
        self.playing = not self.playing

    def restart(self) -> None:
        self.frame_idx = 0
        self.playing   = False
        self.scene.reset_scene()
        self.status_label.setText("Restart – naciśnij Play aby zacząć od nowa")

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_R:
            self.restart()
        elif key == Qt.Key.Key_Left:
            # Step back (pause first)
            self.playing = False
            steps = self.speed.value()
            self.frame_idx = max(0, self.frame_idx - steps)
            if self.frames:
                previous = self.frames[self.frame_idx - 1] if self.frame_idx > 0 else None
                self.scene.update_frame(previous, self.frames[self.frame_idx])
        elif key == Qt.Key.Key_Right:
            # Step forward (pause first)
            self.playing = False
            steps = self.speed.value()
            self.frame_idx = min(len(self.frames) - 1, self.frame_idx + steps)
            if self.frames:
                previous = self.frames[self.frame_idx - 1] if self.frame_idx > 0 else None
                self.scene.update_frame(previous, self.frames[self.frame_idx])
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.speed.setValue(min(50, self.speed.value() + 5))
        elif key == Qt.Key.Key_Minus:
            self.speed.setValue(max(1, self.speed.value() - 5))
        else:
            super().keyPressEvent(event)

    def _tick(self) -> None:
        if not self.playing or not self.frames:
            return
        steps = self.speed.value()
        for _ in range(steps):
            if self.frame_idx >= len(self.frames):
                self.playing = False
                self.status_label.setText("Druk zakończony")
                if self._recording:
                    self._stop_live_record()
                break
            previous = self.frames[self.frame_idx - 1] if self.frame_idx > 0 else None
            frame    = self.frames[self.frame_idx]
            self.scene.update_frame(previous, frame)

            s    = frame.state
            rec_tag = f"  [REC {self._rec_frame_cnt}]" if self._recording else ""
            info = (
                f"t={s.t:.1f}s  "
                f"X={s.x:.1f}  Y={s.y:.1f}  Z={s.z:.2f}  "
                f"E={s.e:.2f}  "
                f"Dysza={s.nozzle_temp:.0f}°C  Stół={s.bed_temp:.0f}°C"
                f"{rec_tag}"
            )
            if frame.issues:
                info = "⚠ " + " | ".join(frame.issues) + "  |  " + info
            self.status_label.setText(info)
            self._update_stats(frame)
            self.frame_idx += 1

        # Capture one video frame per timer tick (not per simulation step)
        # This gives smooth ~30fps video regardless of playback speed setting
        if self._recording and self.playing:
            self._capture_live_frame()

    # ------------------------------------------------------------------
    # Live recording
    # ------------------------------------------------------------------
    def toggle_live_record(self) -> None:
        if self._recording:
            self._stop_live_record()
        else:
            self._start_live_record()

    def _start_live_record(self) -> None:
        if not self.frames:
            self.status_label.setText("Brak sesji – załaduj G-code aby móc nagrywać.")
            return

        mp4_path = _auto_path("nagranie", "mp4")

        self._rec_path      = str(mp4_path)
        self._rec_frame_cnt = 0
        self._rec_writer    = None   # writer created on first frame (need widget size)
        self._recording     = True

        if not self.playing:
            self.playing = True

        self._rec_btn.setText("Zatrzymaj nagrywanie")
        self._rec_btn.setStyleSheet(
            "QPushButton { background-color: #8b0000; color: white; font-weight: bold; }"
        )
        self.status_label.setText(f"[REC] Nagrywanie → recordings/{mp4_path.name}")

    def _capture_live_frame(self) -> None:
        """Grab the current OpenGL viewport and write it to the video file."""
        self.scene.repaint()
        pixmap  = self.scene.grab()
        qimage  = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)

        w = qimage.width()  - (qimage.width()  % 2)
        h = qimage.height() - (qimage.height() % 2)

        if self._rec_writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._rec_writer = cv2.VideoWriter(
                self._rec_path, fourcc, 30, (w, h)
            )

        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        arr = np.array(ptr).reshape(qimage.height(), qimage.width(), 4)
        self._rec_writer.write(cv2.cvtColor(arr[:h, :w], cv2.COLOR_RGBA2BGR))
        self._rec_frame_cnt += 1

    def _stop_live_record(self) -> None:
        self._recording = False
        if self._rec_writer is not None:
            self._rec_writer.release()
            self._rec_writer = None
        self._rec_btn.setText("Nagraj od teraz")
        self._rec_btn.setStyleSheet(
            "QPushButton { color: #ff4444; font-weight: bold; }"
        )
        self.status_label.setText(
            f"Nagranie zapisane: {Path(self._rec_path).name}  "
            f"({self._rec_frame_cnt} klatek)"
        )

    # ------------------------------------------------------------------
    def _update_stats(self, frame: SimulationFrame) -> None:
        s = frame.state
        total = max(1, len(self.frames))
        pct   = self.frame_idx / total * 100
        mins  = int(s.t) // 60
        secs  = int(s.t) % 60
        # Rough PLA mass: π*(1.75/2)²*1.24 g/cm³ ≈ 0.00292 g/mm of filament
        grams = s.e * 0.00292
        self._stat_progress.setText(f"Postęp:  {pct:.1f} %  ({self.frame_idx}/{total})")
        self._stat_time.setText(    f"Czas:    {mins}:{secs:02d}")
        self._stat_layer.setText(   f"Warstwa: Z = {s.z:.2f} mm")
        self._stat_filament.setText(f"Filament: {s.e:.1f} mm  ({grams:.2f} g)")

    def _refresh_charts(self) -> None:
        t = [f.state.t for f in self.frames]
        self.nozzle_curve.setData(t, [f.state.nozzle_temp for f in self.frames])
        self.bed_curve.setData(t,    [f.state.bed_temp    for f in self.frames])
        self.extrusion_curve.setData(t, [f.state.e        for f in self.frames])

    def export_replay(self) -> None:
        if not self.frames:
            self.status_label.setText("Brak danych do zapisania")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Zapisz sesję", "sesja.json", "JSON (*.json)",
        )
        if filename:
            export_frames(filename, self.frames)
            self.status_label.setText(f"Sesja zapisana: {Path(filename).name}")

    def import_replay(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj sesję", "", "JSON (*.json)",
        )
        if not filename:
            return
        try:
            frames = import_frames(filename)
        except Exception as exc:
            self.status_label.setText(f"Błąd wczytywania sesji: {exc}")
            return
        self.frames    = frames
        self.frame_idx = 0
        self.playing   = False
        self.scene.reset_scene()
        self._refresh_charts()
        self.status_label.setText(
            f"Sesja wczytana: {Path(filename).name}  ({len(frames)} kroków) – odtwarzanie…"
        )
        # Auto-start playback so loading a session feels like pressing Play
        self.playing = True

    # ------------------------------------------------------------------
    # MP4 export (works on the frames currently in memory)
    # ------------------------------------------------------------------
    def on_click_render(self) -> None:
        # If rendering is already in progress, cancel it
        if hasattr(self, "_render_timer") and self._render_timer.isActive():
            self._render_timer.stop()
            if getattr(self, "_render_manager", None):
                self._render_manager.close()
            self.status_label.setText("Renderowanie przerwane.")
            self._cleanup_render_ui()
            return

        if not self.frames:
            self.status_label.setText("Brak sesji do eksportu – załaduj G-code lub sesję JSON.")
            return

        mp4_path = _auto_path("export", "mp4")

        try:
            self._render_manager = VideoRenderManager(
                self.scene, self.frames, mp4_path, fps=60, step=10
            )
        except Exception as exc:
            self.status_label.setText(f"Błąd inicjalizacji renderowania: {exc}")
            return

        # Freeze simulation and update UI
        self.playing = False
        self.load_btn.setEnabled(False)
        self._mp4_btn.setText("Anuluj renderowanie")
        self._render_progress.setValue(0)
        self._render_progress.setVisible(True)
        self.status_label.setText("Renderowanie MP4…")

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_render_timer_tick)
        self._render_timer.start(0)

    def _on_render_timer_tick(self) -> None:
        current, total = self._render_manager.render_next_step()

        pct = int(current / max(total, 1) * 100)
        self._render_progress.setValue(pct)

        if current % 20 == 0 or current == total:
            self.status_label.setText(
                f"Renderowanie MP4: {current}/{total} klatek ({pct}%)"
            )

        if self._render_manager.is_finished():
            self._render_timer.stop()
            saved = Path(self._render_manager.output_path).name
            self._render_manager.close()
            self.status_label.setText(
                f"Eksport gotowy → recordings/{saved}  ({total} klatek)"
            )
            self._cleanup_render_ui()

    def _cleanup_render_ui(self) -> None:
        self.load_btn.setEnabled(True)
        self._mp4_btn.setText("Eksportuj całą sesję do MP4")
        self._render_progress.setVisible(False)
        self._render_manager = None