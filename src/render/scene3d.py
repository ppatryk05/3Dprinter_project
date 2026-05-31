from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.MeshData import MeshData

from src.core.types import PrinterConfig
from src.sim.simulator import SimulationFrame

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
C_BED_GLASS  = (0.07, 0.09, 0.14, 1.0)
C_BED_FRAME  = (0.40, 0.42, 0.48, 1.0)
C_BED_UNDER  = (0.30, 0.31, 0.36, 1.0)
C_GRID       = (0.30, 0.34, 0.50, 0.80)
C_FRAME_COL  = (0.28, 0.30, 0.35, 1.0)
C_FRAME_BEAM = (0.25, 0.27, 0.32, 1.0)
C_BUILD_VOL  = (0.20, 0.50, 0.95, 0.50)
C_XRAIL      = (0.58, 0.60, 0.68, 1.0)   # X-axis rail beams
C_ZCAR       = (0.50, 0.52, 0.60, 1.0)   # Z-axis carriage blocks
C_TOOLHEAD   = (0.93, 0.94, 0.96, 1.0)
C_FAN        = (0.06, 0.06, 0.09, 1.0)
C_HEATSINK   = (0.50, 0.53, 0.60, 1.0)
C_HEAT_BREAK = (0.35, 0.35, 0.42, 1.0)
C_HEATER_BLK = (0.82, 0.36, 0.04, 1.0)
C_NOZZLE     = (0.75, 0.60, 0.10, 1.0)
C_NOZZLE_TIP = (1.00, 0.72, 0.15, 1.0)
C_FILAMENT   = (1.00, 0.45, 0.02, 1.0)
C_TRAVEL     = (0.20, 0.55, 1.00, 0.55)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _box_mesh(w: float, d: float, h: float) -> MeshData:
    hw, hd, hh = w / 2, d / 2, h / 2
    v = np.array([
        [-hw,-hd,-hh],[ hw,-hd,-hh],[ hw, hd,-hh],[-hw, hd,-hh],
        [-hw,-hd, hh],[ hw,-hd, hh],[ hw, hd, hh],[-hw, hd, hh],
    ], dtype=float)
    f = np.array([
        [0,2,1],[0,3,2],[4,5,6],[4,6,7],
        [0,1,5],[0,5,4],[2,3,7],[2,7,6],
        [1,2,6],[1,6,5],[3,0,4],[3,4,7],
    ])
    return MeshData(vertexes=v, faces=f)


def _rect_mesh(x0, y0, z, x1, y1) -> MeshData:
    v = np.array([[x0,y0,z],[x1,y0,z],[x1,y1,z],[x0,y1,z]], dtype=float)
    return MeshData(vertexes=v, faces=np.array([[0,1,2],[0,2,3]]))


def _line_pairs(pairs: list) -> np.ndarray:
    out: list = []
    for a, b in pairs:
        out.append(a); out.append(b)
    return np.array(out, dtype=float)


def _mesh(w, d, h, color, edges=False, ec=(0, 0, 0, 0.55)) -> gl.GLMeshItem:
    item = gl.GLMeshItem(
        meshdata=_box_mesh(w, d, h), smooth=False, color=color,
        shader='shaded', drawEdges=edges, edgeColor=ec,
    )
    item.setGLOptions('opaque')
    return item


def _flat(x0, y0, z, x1, y1, color) -> gl.GLMeshItem:
    item = gl.GLMeshItem(
        meshdata=_rect_mesh(x0, y0, z, x1, y1), smooth=False,
        color=color, shader='shaded',
    )
    item.setGLOptions('opaque')
    return item


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class Scene3DWidget(gl.GLViewWidget):
    """
    3D printer viewport.

    Gantry: two thick GLLinePlotItem rods (front + back) spanning the full
    X width, connected at each end by a short end-connector line, with
    bracket arms descending to the toolhead carriage.  All rods move with
    Y and Z.  The toolhead assembly hangs from the brackets.

    Hotend stack (no mesh overlaps, z = nozzle-tip Z):
      z+ 0..z+ 3   nozzle lo  (6×6×3,  brass)
      z+ 3..z+ 8   nozzle hi (10×10×5, brass)
      z+ 8..z+20   heater block (16×16×12, copper)
      z+20..z+30   heat break  ( 5× 5×10, steel)
      z+30..z+44   5 heatsink fins (22×22×2, 1 mm gaps)
      z+44..z+74   toolhead carriage (44×44×30, white)
      z+63         rod centre passes through carriage
    """

    ROD_Y_OFFSET = 18.0
    ROD_Z_OFFSET = 63.0
    MARGIN       = 18.0
    COL_SIZE     = 14.0

    def __init__(self, config: PrinterConfig | None = None, parent=None) -> None:
        cfg = config or PrinterConfig()
        self.BX: float = cfg.build_x
        self.BY: float = cfg.build_y
        self.BZ: float = cfg.build_z
        self._dep_pts:    list[list[float]] = []
        self._travel_pts: list[list[float]] = []

        super().__init__(parent=parent)
        self.setBackgroundColor((210, 212, 218, 255))
        self.setCameraPosition(distance=660, elevation=24, azimuth=225)
        self.pan(self.BX / 2, self.BY / 2, 40)

        self._build_static()
        self._build_dynamic()
        self._update_moving_parts(self.BX / 2, self.BY / 2, 5.0, extruding=False)

    # ------------------------------------------------------------------
    # Static geometry
    # ------------------------------------------------------------------
    def _build_static(self) -> None:
        bx, by, bz = self.BX, self.BY, self.BZ
        cx, cy = bx / 2, by / 2
        M  = self.MARGIN
        CS = self.COL_SIZE
        BED_T  = 5.0
        POST_H = 45.0
        FLOOR_Z = -BED_T - POST_H
        COL_H   = bz + 40 - FLOOR_Z

        # Bed
        self.addItem(_flat(0, 0, 0, bx, by, C_BED_GLASS))
        for x0, y0, x1, y1 in [
            (-M,-M, bx+M,  0), (-M, by, bx+M, by+M),
            (-M, 0,   0,  by), (bx,  0, bx+M, by  ),
        ]:
            self.addItem(_flat(x0, y0, -BED_T, x1, y1, C_BED_FRAME))
        self.addItem(_flat(-M, -M, -BED_T, bx+M, by+M, C_BED_UNDER))

        bed_grid = gl.GLGridItem()
        bed_grid.scale(bx / 20, by / 20, 1)
        bed_grid.translate(cx, cy, 0.5)
        bed_grid.setColor(C_GRID)
        self.addItem(bed_grid)

        # Floor
        FSIZE = 600.0
        fg = gl.GLGridItem()
        fg.scale(FSIZE / 10, FSIZE / 10, 1)
        fg.translate(cx, cy, FLOOR_Z)
        fg.setColor((0.45, 0.47, 0.52, 0.55))
        self.addItem(fg)
        self.addItem(_flat(cx-FSIZE/2, cy-FSIZE/2, FLOOR_Z-0.5,
                           cx+FSIZE/2, cy+FSIZE/2, (0.76,0.77,0.80,1.0)))

        # 4 corner columns
        for px, py in [(-M,-M),(bx+M,-M),(bx+M,by+M),(-M,by+M)]:
            col = _mesh(CS, CS, COL_H, C_FRAME_COL, edges=True, ec=(0,0,0,0.35))
            col.translate(px, py, FLOOR_Z + COL_H / 2)
            self.addItem(col)

        # Top beams
        top_z = bz + 40
        BH, BD = 12.0, 12.0
        for ry in (-M, by+M):
            b = _mesh(bx+2*M+CS, BD, BH, C_FRAME_BEAM, edges=True, ec=(0,0,0,0.30))
            b.translate(cx, ry, top_z + BH/2)
            self.addItem(b)
        for rx in (-M, bx+M):
            b = _mesh(BD, by+2*M+CS, BH, C_FRAME_BEAM, edges=True, ec=(0,0,0,0.30))
            b.translate(rx, cy, top_z + BH/2)
            self.addItem(b)

        # Build-volume wireframe
        c8 = [(0,0,0),(bx,0,0),(bx,by,0),(0,by,0),
              (0,0,bz),(bx,0,bz),(bx,by,bz),(0,by,bz)]
        ev  = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
               (0,4),(1,5),(2,6),(3,7)]
        self.addItem(gl.GLLinePlotItem(
            pos=_line_pairs([(c8[a], c8[b]) for a, b in ev]),
            color=C_BUILD_VOL, width=1.5, mode='lines', antialias=True,
        ))

    # ------------------------------------------------------------------
    # Dynamic geometry
    # ------------------------------------------------------------------
    def _build_dynamic(self) -> None:
        bx, M = self.BX, self.MARGIN
        by = self.BY
        RY = self.ROD_Y_OFFSET

        # ── Gantry: two X-rail profiles + two Z-carriage blocks ──────────
        #  X-rails span the full width (column-to-column), depth 14 mm, height 12 mm
        #  Z-carriages sit at each end column, depth spans both rails + gap
        XRAIL_LEN = bx + 2 * M          # e.g. 256 mm  (column centre to centre)
        YRAIL_LEN = by + 2 * M
        XRAIL_D   = 14.0
        XRAIL_H   = 12.0
        YRAIL_D   = 14.0
        YRAIL_H   = 12.0
        ZCAR_W    = 24.0
        ZCAR_D    = RY * 2 + XRAIL_D    # 50 mm – spans both rails
        ZCAR_H    = 22.0
        YCAR_H = 22.0
        YCAR_W = 20.0
        YCAR_D = 20.0

        self._xrail_f = _mesh(XRAIL_LEN, XRAIL_D, XRAIL_H, C_XRAIL,
                              edges=True, ec=(0, 0, 0, 0.22))
        self._xrail_b = _mesh(XRAIL_LEN, XRAIL_D, XRAIL_H, C_XRAIL,
                              edges=True, ec=(0, 0, 0, 0.22))
        self._yrail_l = _mesh(YRAIL_D, YRAIL_LEN, YRAIL_H, C_XRAIL,
                              edges=True, ec=(0, 0, 0, 0.22))
        self._yrail_r = _mesh(YRAIL_D, YRAIL_LEN, YRAIL_H, C_XRAIL,
                              edges=True, ec=(0, 0, 0, 0.22))
        self._zcar_l  = _mesh(ZCAR_W, ZCAR_D, ZCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))
        self._zcar_r  = _mesh(ZCAR_W, ZCAR_D, ZCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))
        self._ycar_fl  = _mesh(YCAR_W, YCAR_D, YCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))
        self._ycar_fr  = _mesh(YCAR_W, YCAR_D, YCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))
        self._ycar_bl  = _mesh(YCAR_W, YCAR_D, YCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))
        self._ycar_br  = _mesh(YCAR_W, YCAR_D, YCAR_H, C_ZCAR,
                              edges=True, ec=(0, 0, 0, 0.28))

        # ── Toolhead carriage ────────────────────────────────────────────
        self._toolhead = _mesh(44, 44, 30, C_TOOLHEAD, edges=True, ec=(0,0,0,0.50))
        self._fan_body = _mesh(26,  6, 26, C_FAN)

        # ── Heatsink fins (5 × 22×22×2) ─────────────────────────────────
        self._fins: list[gl.GLMeshItem] = [
            _mesh(22, 22, 2, C_HEATSINK, edges=True, ec=(0,0,0,0.22))
            for _ in range(5)
        ]

        # ── Heat break ───────────────────────────────────────────────────
        self._heat_break = _mesh(5, 5, 10, C_HEAT_BREAK)

        # ── Heater block (copper) ────────────────────────────────────────
        self._heater_blk = _mesh(16, 16, 12, C_HEATER_BLK,
                                 edges=True, ec=(0,0,0,0.28))

        # ── Nozzle (brass stepped) ───────────────────────────────────────
        self._nozzle_hi = _mesh(10, 10, 5, C_NOZZLE)
        self._nozzle_lo = _mesh( 6,  6, 3, C_NOZZLE)

        # ── Nozzle tip glow ──────────────────────────────────────────────
        self._nozzle_tip = gl.GLScatterPlotItem(
            pos=np.array([[0.,0.,0.]]), size=16,
            color=C_NOZZLE_TIP, pxMode=True,
        )

        # ── Filament strand ──────────────────────────────────────────────
        self._fil_strand = gl.GLLinePlotItem(
            pos=np.zeros((2,3)), color=C_FILAMENT, width=4, antialias=True,
        )
        self._fil_strand.setGLOptions('opaque')
        self._fil_strand.setVisible(False)

        # ── Print paths (opaque so meshes occlude them correctly) ─────────
        self._deposition = gl.GLLinePlotItem(
            pos=np.empty((0,3)), color=C_FILAMENT, width=11,
            mode='lines', antialias=True,
        )
        self._deposition.setGLOptions('opaque')

        self._travel_lines = gl.GLLinePlotItem(
            pos=np.empty((0,3)), color=C_TRAVEL, width=1.5,
            mode='lines', antialias=True,
        )
        self._travel_lines.setGLOptions('opaque')
        self._travel_lines.setVisible(True)

        # Add paths first so meshes render on top of them
        for item in [
            self._deposition, self._travel_lines,
            self._xrail_f, self._xrail_b,
            self._yrail_l, self._yrail_r,
            self._zcar_l, self._zcar_r,
            self._ycar_fl, self._ycar_bl,
            self._ycar_fr, self._ycar_br,
            self._toolhead, self._fan_body,
            *self._fins,
            self._heat_break, self._heater_blk,
            self._nozzle_hi, self._nozzle_lo,
            self._nozzle_tip, self._fil_strand,
        ]:
            self.addItem(item)

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------
    def _update_moving_parts(self, x: float, y: float, z: float,
                              extruding: bool) -> None:
        bx, M = self.BX, self.MARGIN
        by = self.BY
        cx  = bx / 2
        cy = by / 2
        RY  = self.ROD_Y_OFFSET
        RZ  = z + self.ROD_Z_OFFSET
        yf  = y - RY
        yb  = y + RY

        # X-rail beams (front + back), centred in X, moving with Y and Z
        self._xrail_f.resetTransform(); self._xrail_f.translate(cx, yf, RZ)
        self._xrail_b.resetTransform(); self._xrail_b.translate(cx, yb, RZ)

        # Y-rail beams (front + back), centred in Y and X, moving with Z
        self._yrail_l.resetTransform(); self._yrail_l.translate(-M, cy, RZ)
        self._yrail_r.resetTransform(); self._yrail_r.translate(bx+M, cy, RZ)

        # Z-carriages at column positions (left=-M, right=BX+M), moving with Y and Z
        self._zcar_l.resetTransform();  self._zcar_l.translate(-M,   y, RZ)
        self._zcar_r.resetTransform();  self._zcar_r.translate(bx+M, y, RZ)

        # Y-carriages at column positions (left=-M, right=BX+M), moving with Z
        self._ycar_fl.resetTransform();  self._ycar_fl.translate(-M, -M, RZ)
        self._ycar_bl.resetTransform();  self._ycar_bl.translate(-M, by + M, RZ)

        # Y-carriages at column positions (left=-M, right=BX+M), moving with Z
        self._ycar_fr.resetTransform();  self._ycar_fr.translate(bx+M, -M, RZ)
        self._ycar_br.resetTransform();  self._ycar_br.translate(bx+M, by + M, RZ)

        # Toolhead carriage — z+44..z+74, rods at z+63 pass through it
        th_cz = z + 59
        self._toolhead.resetTransform(); self._toolhead.translate(x, y, th_cz)
        self._fan_body.resetTransform(); self._fan_body.translate(x, y - 25, th_cz)

        # Heatsink fins: z+31..z+43 (step 3 mm, no overlap with carriage at z+44)
        for i, fin in enumerate(self._fins):
            fin.resetTransform(); fin.translate(x, y, z + 31 + i * 3)

        # Heat break: z+20..z+30
        self._heat_break.resetTransform(); self._heat_break.translate(x, y, z + 25)

        # Heater block: z+8..z+20
        self._heater_blk.resetTransform(); self._heater_blk.translate(x, y, z + 14)

        # Nozzle: hi z+3..z+8, lo z+0..z+3
        self._nozzle_hi.resetTransform(); self._nozzle_hi.translate(x, y, z + 5.5)
        self._nozzle_lo.resetTransform(); self._nozzle_lo.translate(x, y, z + 1.5)
        self._nozzle_tip.setData(pos=np.array([[x, y, z]]))

        if extruding and z > 0.05:
            self._fil_strand.setData(
                pos=np.array([[x,y,z],[x,y,0.0]], dtype=float))
            self._fil_strand.setVisible(True)
        else:
            self._fil_strand.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_show_travel(self, visible: bool) -> None:
        self._travel_lines.setVisible(visible)

    def reset_scene(self) -> None:
        self._dep_pts    = []
        self._travel_pts = []
        self._deposition.setData(pos=np.empty((0, 3)))
        self._travel_lines.setData(pos=np.empty((0, 3)))
        self._update_moving_parts(self.BX / 2, self.BY / 2, 5.0, extruding=False)

    # Minimum XY+Z displacement (mm) to record a path segment.
    # Filters interpolation micro-steps that create a "dashed" appearance.
    _MIN_SEG_MM = 0.25

    def update_frame(self, previous: SimulationFrame | None,
                     frame: SimulationFrame) -> None:
        sx, sy, sz = frame.state.x, frame.state.y, frame.state.z
        extruding = previous is not None and frame.state.e > previous.state.e
        self._update_moving_parts(sx, sy, sz, extruding=extruding)

        if previous is not None:
            px, py, pz = previous.state.x, previous.state.y, previous.state.z
            seg_len_sq = (sx-px)**2 + (sy-py)**2 + (sz-pz)**2
            if seg_len_sq < self._MIN_SEG_MM ** 2:
                return  # skip sub-threshold micro-segments
            seg = [[px, py, pz], [sx, sy, sz]]
            if extruding:
                self._dep_pts.extend(seg)
                self._deposition.setData(pos=np.array(self._dep_pts))
            else:
                self._travel_pts.extend(seg)
                self._travel_lines.setData(pos=np.array(self._travel_pts))
