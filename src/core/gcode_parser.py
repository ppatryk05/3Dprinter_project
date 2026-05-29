from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from .types import MotionCommand


def _strip_comments(line: str) -> str:
    if ";" in line:
        line = line.split(";", maxsplit=1)[0]
    return line.strip()


def _parse_params(parts: list[str]) -> dict[str, float]:
    """Parse G-code parameter tokens like X12.5 → {'X': 12.5}."""
    params: dict[str, float] = {}
    for token in parts[1:]:
        if len(token) < 2:
            continue
        letter = token[0].upper()
        try:
            params[letter] = float(token[1:])
        except ValueError:
            continue
    return params


def parse_gcode_lines(lines: Iterable[str]) -> List[MotionCommand]:
    commands: List[MotionCommand] = []
    current_path_kind = "model"  # updated by ;TYPE: slicer annotations

    for raw_line in lines:
        raw = raw_line.rstrip("\n")

        # ── Slicer path-type annotations (before comment stripping) ──────
        # PrusaSlicer / Cura / Bambu: ;TYPE:SUPPORT  ;TYPE:PERIMETER  etc.
        stripped = raw.strip()
        if stripped.startswith(";TYPE:"):
            kind_tag = stripped[6:].strip().upper()
            current_path_kind = "support" if "SUPPORT" in kind_tag else "model"
            continue

        clean = _strip_comments(raw)
        if not clean:
            continue
        parts = clean.split()
        if not parts:
            continue

        name = parts[0].upper()
        p = _parse_params(parts)

        # ── Motion commands ───────────────────────────────────────────────
        if name in {"G0", "G1"}:
            commands.append(MotionCommand(
                kind=name,
                x=p.get("X"), y=p.get("Y"), z=p.get("Z"),
                e=p.get("E"), f=p.get("F"),
                path_kind=current_path_kind,
            ))

        elif name in {"G2", "G3"}:
            # Arc move (clockwise G2, counter-clockwise G3).
            # I/J are offsets from current position to arc centre.
            commands.append(MotionCommand(
                kind=name,
                x=p.get("X"), y=p.get("Y"), z=p.get("Z"),
                e=p.get("E"), f=p.get("F"),
                i=p.get("I", 0.0), j=p.get("J", 0.0),
                path_kind=current_path_kind,
            ))

        # ── Homing ───────────────────────────────────────────────────────
        elif name == "G28":
            # Optional axis letters: G28 X  G28 Y  G28 Z  G28 (all)
            commands.append(MotionCommand(
                kind="G28",
                x=0.0 if "X" in p or len(p) == 0 else None,
                y=0.0 if "Y" in p or len(p) == 0 else None,
                z=0.0 if "Z" in p or len(p) == 0 else None,
            ))

        # ── Positioning mode ─────────────────────────────────────────────
        elif name == "G90":
            commands.append(MotionCommand(kind="G90"))
        elif name == "G91":
            commands.append(MotionCommand(kind="G91"))

        # ── Set position (coordinate reset) ──────────────────────────────
        elif name == "G92":
            commands.append(MotionCommand(
                kind="G92",
                x=p.get("X"), y=p.get("Y"), z=p.get("Z"), e=p.get("E"),
            ))

        # ── Park head ────────────────────────────────────────────────────
        elif name == "G27":
            # Park: raise Z to safe height (treat as rapid Z move)
            commands.append(MotionCommand(kind="G27"))

        # ── Temperature ──────────────────────────────────────────────────
        elif name in {"M104", "M109"}:
            commands.append(MotionCommand(kind=name, nozzle_temp=p.get("S")))
        elif name in {"M140", "M190"}:
            commands.append(MotionCommand(kind=name, bed_temp=p.get("S")))

        # ── E-axis mode ───────────────────────────────────────────────────
        elif name == "M82":
            commands.append(MotionCommand(kind="M82"))   # absolute E
        elif name == "M83":
            commands.append(MotionCommand(kind="M83"))   # relative E

        # ── Fan ───────────────────────────────────────────────────────────
        elif name == "M106":
            # Fan on — acknowledged but not visualised
            commands.append(MotionCommand(kind="M106"))
        elif name == "M107":
            commands.append(MotionCommand(kind="M107"))  # fan off

        # All other commands (M201, M204, M220, M221, M600, etc.) are
        # silently ignored — no error raised, simulation continues.

    return commands


def parse_gcode_file(path: str | Path) -> List[MotionCommand]:
    source = Path(path)
    return parse_gcode_lines(source.read_text(encoding="utf-8").splitlines())
