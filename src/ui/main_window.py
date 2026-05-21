from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.gcode_parser import parse_gcode_file
from src.core.types import PrinterConfig
from src.io.session_replay import export_frames , VideoRenderManager
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

        export_btn = QPushButton("Zapisz sesję (JSON)")
        export_btn.clicked.connect(self.export_replay)
        sidebar_layout.addWidget(export_btn)


        self.record_btn = QPushButton("Konwertuj sesję (JSON --> MP4)")
        self.record_btn.clicked.connect(self.on_click_render)
        sidebar_layout.addWidget(self.record_btn)

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
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play()
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
                break
            previous = self.frames[self.frame_idx - 1] if self.frame_idx > 0 else None
            frame    = self.frames[self.frame_idx]
            self.scene.update_frame(previous, frame)

            s    = frame.state
            info = (
                f"t={s.t:.1f}s  "
                f"X={s.x:.1f}  Y={s.y:.1f}  Z={s.z:.2f}  "
                f"E={s.e:.2f}  "
                f"Dysza={s.nozzle_temp:.0f}°C  Stół={s.bed_temp:.0f}°C"
            )
            if frame.issues:
                info = "⚠ " + " | ".join(frame.issues) + "  |  " + info
            self.status_label.setText(info)
            self.frame_idx += 1

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

    def on_click_render(self) -> None:
        # Jeśli renderowanie już trwa, kliknięcie oznacza akcję "Anuluj"
        if hasattr(self, '_render_timer') and self._render_timer.isActive():
            self._render_timer.stop()
            if hasattr(self, '_render_manager') and self._render_manager:
                self._render_manager.close()
            self.status_label.setText("Renderowanie zostało przerwane przez użytkownika.")
            self._cleanup_render_ui()
            return

        json_file, _ = QFileDialog.getOpenFileName(self, "Wybierz plik sesji JSON", "", "JSON (*.json)")
        if not json_file: return

        mp4_file, _ = QFileDialog.getSaveFileName(self, "Zapisz wideo jako...", "render.mp4", "Wideo MP4 (*.mp4)")
        if not mp4_file: return

        try:
            self._render_manager = VideoRenderManager(self.scene, json_file, mp4_file, fps=60, step=10)
        except Exception as e:
            self.status_label.setText(f"Błąd inicjalizacji managera: {str(e)}")
            return

        if self._render_manager.total_frames == 0:
            self.status_label.setText("Błąd: Wybrany plik JSON nie zawiera klatek.")
            return

        # Zmiana wyglądu okna (UI) na czas pracy
        self.load_btn.setEnabled(False)
        self.record_btn.setText("Anuluj renderowanie")
        self.status_label.setText("Rozpoczynam renderowanie klatek...")

        # Uruchomienie cyklicznego timera okna
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_render_timer_tick)
        self._render_timer.start(0)

    def _on_render_timer_tick(self) -> None:
        current, total = self._render_manager.render_next_step()

        if current % 5 == 0 or current == total:
            percentage = (current / total) * 100
            self.status_label.setText(f"Renderowanie MP4: {current}/{total} klatek ({percentage:.1f}%)")

        if self._render_manager.is_finished():
            self._render_timer.stop()
            self._render_manager.close()
            self.status_label.setText("Sukces! Wideo zostało pomyślnie zapisane.")
            self._cleanup_render_ui()

    def _cleanup_render_ui(self) -> None:
        self.load_btn.setEnabled(True)
        self.record_btn.setText("Konwertuj sesję (JSON --> MP4)")
        self._render_manager = None